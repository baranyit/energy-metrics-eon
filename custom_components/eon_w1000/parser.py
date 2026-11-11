"""Parser for E.ON W1000 interval exports (XLSX / CSV).

Deliberately free of Home Assistant imports so it can be tested standalone.

Two layouts are understood:

* "long" - the scheduled e-mail export (e.g. adatok.xlsx). One sheet per
  metering point (POD_1, POD_2, ...), one row per interval, and a repeating
  Változó / Érték / Mértékegység group per meter variable:

      Pod | Időbélyeg | Változó | Érték | Mértékegység | Változó | Érték | Mértékegység
      HU… | 2026-11-04 00:00 | +A | 0.325 | kWh | -A | 0 | kWh

* "wide" - the portal's own download (MertErtekek_*.xlsx / CSV). A timestamp
  column and one column per meter variable, with ÖSSZEG / MAXIMUM ÉRTÉK
  summary rows above the data:

      Dátum/Idő | +A | -A
      2026.11.01. 00:00 | 0.095 | 0

Timestamps are Hungarian local time and mark the start of the interval.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import io
import re
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Budapest")
DEFAULT_STEP = timedelta(minutes=15)

UNIT_FACTORS = {"kwh": 1.0, "wh": 0.001, "mwh": 1000.0}

_DT_RE = re.compile(
    r"^\s*(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})\.?"
    r"(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?\s*$"
)

# Header names of the long layout, compared case-insensitively.
_H_POD = "pod"
_H_TIME = ("időbélyeg", "dátum/idő", "datum/ido", "timestamp")
_H_VAR = "változó"
_H_VALUE = "érték"
_H_UNIT = "mértékegység"


class ParseError(Exception):
    """The file could not be interpreted as a W1000 interval export."""


@dataclass
class ParsedExport:
    """Result of parsing one export file."""

    layout: str  # "long" or "wide"
    variables: list[str]  # meter variables present in the file
    step: timedelta
    pod: str | None  # metering point the series belong to, if known
    # kind ("import"/"export") -> hour start (UTC, aware) -> kWh in that hour,
    # complete hours only
    series: dict[str, dict[datetime, float]]
    pods: list[str] = field(default_factory=list)  # all PODs in the file
    # kind -> interval start (UTC, aware) -> kWh in that interval
    intervals: dict[str, dict[datetime, float]] = field(default_factory=dict)


# --------------------------------------------------------------------------
# cell helpers


def _text(cell) -> str:
    return "" if cell is None else str(cell).strip()


def _parse_dt(cell) -> tuple[datetime, bool] | None:
    """Return (naive local datetime, has_time_part) or None."""
    if isinstance(cell, datetime):
        return cell.replace(tzinfo=None, microsecond=0), True
    if not isinstance(cell, str):
        return None
    m = _DT_RE.match(cell)
    if not m:
        return None
    year, month, day, hour, minute, second = m.groups()
    try:
        if hour is None:
            return datetime(int(year), int(month), int(day)), False
        extra_day = 0
        h = int(hour)
        if h == 24:  # "24:00" = midnight of the next day
            h, extra_day = 0, 1
        return (
            datetime(int(year), int(month), int(day), h, int(minute), int(second or 0))
            + timedelta(days=extra_day),
            True,
        )
    except ValueError:
        return None


def _parse_number(cell) -> float | None:
    if cell is None or isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    text = str(cell).strip().replace(" ", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _unit_factor(cell) -> float:
    unit = _text(cell).lower()
    if not unit:
        return 1.0  # no unit given: assume kWh
    if unit not in UNIT_FACTORS:
        raise ParseError(f"Unsupported unit '{_text(cell)}'; expected kWh, Wh or MWh")
    return UNIT_FACTORS[unit]


def _variable_matches(name: str, wanted: str) -> bool:
    """'+A' matches '+A', '+A [kWh]', '+A (kWh)' but not '+Ri'."""
    n = name.strip().lower()
    w = wanted.strip().lower()
    if not w:
        return False
    return n == w or any(n.startswith(w + sep) for sep in (" ", "[", "(", "\t"))


def _kind_for(name: str, columns: dict[str, str]) -> str | None:
    for kind, wanted in columns.items():
        if _variable_matches(name, wanted):
            return kind
    return None


# --------------------------------------------------------------------------
# reading


def _read_tables(data: bytes) -> list[tuple[str, list[list]]]:
    """Return (sheet name, rows) for every sheet / the single CSV table."""
    if data[:2] == b"PK":
        try:
            from openpyxl import load_workbook  # noqa: PLC0415
        except ImportError as err:  # pragma: no cover
            raise ParseError("XLSX export needs the openpyxl package") from err
        import warnings  # noqa: PLC0415

        with warnings.catch_warnings():
            # The e-mailed workbook has no default style; openpyxl warns about it.
            warnings.simplefilter("ignore", UserWarning)
            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            return [
                (sheet.title, [list(row) for row in sheet.iter_rows(values_only=True)])
                for sheet in workbook.worksheets
            ]
        finally:
            workbook.close()

    for encoding in ("utf-8-sig", "cp1250"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1250 decodes nearly anything
        raise ParseError("Unknown text encoding")

    sample = "\n".join(text.splitlines()[:30])
    delimiter = max((";", "\t", ","), key=lambda d: (sample.count(d), d == ";"))
    return [("csv", list(csv.reader(io.StringIO(text), delimiter=delimiter)))]


# Points in file order: (naive local start, {kind: kWh}).
Points = list[tuple[datetime, dict[str, float]]]


def _find_long_header(rows: list[list]) -> int | None:
    for i, row in enumerate(rows[:30]):
        lowered = [_text(c).lower() for c in row]
        if _H_VAR in lowered and _H_VALUE in lowered:
            return i
    return None


def _parse_long(
    rows: list[list], header_idx: int, columns: dict[str, str], variables: set[str]
) -> dict[str, Points]:
    """Long layout -> {pod: points}."""
    header = [_text(c).lower() for c in rows[header_idx]]

    pod_col = header.index(_H_POD) if _H_POD in header else None
    time_col = next((i for i, h in enumerate(header) if h in _H_TIME), None)
    groups = []  # (variable col, value col, unit col or None)
    for i, h in enumerate(header):
        if h == _H_VAR and i + 1 < len(header) and header[i + 1] == _H_VALUE:
            unit_col = i + 2 if i + 2 < len(header) and header[i + 2] == _H_UNIT else None
            groups.append((i, i + 1, unit_col))
    if not groups:
        raise ParseError("The Változó / Érték columns are not next to each other")

    result: dict[str, Points] = {}
    for row in rows[header_idx + 1 :]:
        if time_col is None:
            # no recognised header: take the first cell that is a timestamp
            parsed = next((p for c in row if (p := _parse_dt(c)) and p[1]), None)
        else:
            parsed = _parse_dt(row[time_col]) if time_col < len(row) else None
        if not parsed or not parsed[1]:
            continue
        pod = _text(row[pod_col]) if pod_col is not None and pod_col < len(row) else ""

        values: dict[str, float] = {}
        for var_col, value_col, unit_col in groups:
            if value_col >= len(row):
                continue
            name = _text(row[var_col])
            if not name:
                continue
            variables.add(name)
            kind = _kind_for(name, columns)
            number = _parse_number(row[value_col])
            if kind is None or number is None:
                continue
            factor = _unit_factor(row[unit_col]) if unit_col is not None and unit_col < len(row) else 1.0
            values[kind] = values.get(kind, 0.0) + number * factor
        if values:
            result.setdefault(pod, []).append((parsed[0], values))
    return result


def _parse_wide(rows: list[list], columns: dict[str, str], variables: set[str]) -> Points:
    """Wide layout (portal download) -> points."""
    first_row = date_col = None
    for i, row in enumerate(rows):
        for c, cell in enumerate(row):
            parsed = _parse_dt(cell)
            if parsed and parsed[1]:
                first_row, date_col = i, c
                break
        if first_row is not None:
            break
    if first_row is None:
        raise ParseError(
            "No rows with a date and time found; is this an intraday (15 min) export?"
        )

    # The header is the nearest row above the data that names a configured
    # variable; summary rows (ÖSSZEG, MAXIMUM ÉRTÉK) may sit in between.
    col_for: dict[str, int] = {}
    fallback: list[str] = []
    for row in reversed(rows[:first_row]):
        cells = [_text(c) for c in row]
        if not any(cell for idx, cell in enumerate(cells) if idx != date_col):
            continue
        found = {}
        for idx, cell in enumerate(cells):
            if idx == date_col or not cell:
                continue
            kind = _kind_for(cell, columns)
            if kind is not None and kind not in found:
                found[kind] = idx
        if found:
            col_for = found
            variables.update(c for i, c in enumerate(cells) if c and i != date_col)
            break
        if not fallback and all(_parse_number(c) is None for c in cells if c):
            fallback = [c for i, c in enumerate(cells) if c and i != date_col]
    if not col_for:
        variables.update(fallback)
        return []

    points: Points = []
    for row in rows[first_row:]:
        if date_col >= len(row):
            continue
        parsed = _parse_dt(row[date_col])
        if not parsed or not parsed[1]:
            continue
        values = {}
        for kind, idx in col_for.items():
            if idx < len(row):
                number = _parse_number(row[idx])
                if number is not None:
                    values[kind] = number
        if values:
            points.append((parsed[0], values))
    return points


# --------------------------------------------------------------------------
# aggregation


def _is_ambiguous(naive: datetime) -> bool:
    return (
        naive.replace(tzinfo=LOCAL_TZ, fold=0).utcoffset()
        != naive.replace(tzinfo=LOCAL_TZ, fold=1).utcoffset()
    )


def _to_hourly(
    points: Points, interval_end: bool
) -> tuple[
    timedelta, dict[str, dict[datetime, float]], dict[str, dict[datetime, float]]
]:
    unique = sorted({p[0] for p in points})
    diffs = [b - a for a, b in zip(unique, unique[1:]) if b > a]
    step = min(diffs) if diffs else DEFAULT_STEP
    if step > timedelta(hours=1):
        raise ParseError(
            f"Data resolution is {step}; an hourly or finer export is needed"
        )
    per_hour = max(1, int(timedelta(hours=1) / step))

    # Interval start (UTC) -> value. The repeated hour at the autumn DST change
    # is told apart by its second occurrence in the file.
    intervals: dict[str, dict[datetime, float]] = {}
    seen: set[datetime] = set()
    for naive, values in points:
        fold = 1 if naive in seen and _is_ambiguous(naive) else 0
        seen.add(naive)
        start = naive.replace(tzinfo=LOCAL_TZ, fold=fold).astimezone(timezone.utc)
        if interval_end:
            start -= step
        for kind, number in values.items():
            intervals.setdefault(kind, {})[start] = number

    series: dict[str, dict[datetime, float]] = {}
    for kind, by_start in intervals.items():
        hourly: dict[datetime, float] = {}
        counts: dict[datetime, int] = {}
        for start, number in by_start.items():
            hour = start.replace(minute=0, second=0, microsecond=0)
            hourly[hour] = hourly.get(hour, 0.0) + number
            counts[hour] = counts.get(hour, 0) + 1
        # Drop incomplete hours at either end (export started / cut off mid-hour).
        for edge in (min, max):
            if hourly:
                hour = edge(hourly)
                if counts[hour] < per_hour:
                    del hourly[hour]
        if hourly:
            series[kind] = {h: round(v, 6) for h, v in sorted(hourly.items())}
    return step, series, intervals


# --------------------------------------------------------------------------
# entry point


def parse_export(
    data: bytes,
    columns: dict[str, str],
    *,
    interval_end: bool = False,
    pod: str | None = None,
) -> ParsedExport:
    """Parse an export file into hourly kWh sums.

    columns: kind -> meter variable, e.g. {"import": "+A", "export": "-A"}.
    interval_end: True if a timestamp marks the end of its interval.
    pod: metering point to use when the file contains several.
    """
    columns = {kind: name for kind, name in columns.items() if name and name.strip()}
    if not columns:
        raise ParseError("No meter variables configured")

    variables: set[str] = set()
    by_pod: dict[str, Points] = {}
    layout = "wide"
    for _sheet, rows in _read_tables(data):
        header_idx = _find_long_header(rows)
        if header_idx is not None:
            layout = "long"
            for pod_id, points in _parse_long(rows, header_idx, columns, variables).items():
                by_pod.setdefault(pod_id, []).extend(points)
        elif layout == "wide" and not by_pod:
            try:
                points = _parse_wide(rows, columns, variables)
            except ParseError:
                continue  # e.g. an unrelated extra sheet
            if points:
                by_pod[""] = points

    pods = sorted(p for p in by_pod if p)
    if not by_pod:
        if variables:
            raise ParseError(
                f"None of the configured variables {sorted(columns.values())} were "
                f"found; variables in the file: {sorted(variables)}"
            )
        raise ParseError("No interval data found in the file")

    wanted_pod = (pod or "").strip()
    if wanted_pod:
        if wanted_pod not in by_pod:
            raise ParseError(f"POD '{wanted_pod}' is not in the file; PODs found: {pods}")
        chosen = wanted_pod
    elif len(by_pod) == 1:
        chosen = next(iter(by_pod))
    else:
        raise ParseError(
            f"The file contains several metering points {pods}; "
            "set the POD in the integration options"
        )

    step, series, intervals = _to_hourly(by_pod[chosen], interval_end)
    if not intervals:
        raise ParseError("The file does not contain any interval data")
    return ParsedExport(
        layout=layout,
        variables=sorted(variables),
        step=step,
        pod=chosen or None,
        series=series,
        pods=pods,
        intervals=intervals,
    )
