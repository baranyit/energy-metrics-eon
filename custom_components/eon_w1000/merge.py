"""Merging of new meter data into stored data (no Home Assistant imports)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def merge_hourly(
    existing: dict[datetime, tuple[float, float]],
    new: dict[datetime, float],
) -> list[dict]:
    """Return the statistic rows to (re)write.

    existing: hour start -> (state, sum) already stored.
    new: hour start -> kWh in that hour from a freshly parsed file.

    A new value replaces the stored value of the same hour; it is never added
    to it, so importing the same data again changes nothing. The running
    total (`sum`) is recomputed from the first new hour onward, which keeps it
    consistent when an earlier period is imported later or a value is
    corrected.
    """
    if not new:
        return []

    first = min(new)
    earlier = [start for start in existing if start < first]
    running = existing[max(earlier)][1] if earlier else 0.0

    states = {start: state for start, (state, _sum) in existing.items()}
    states.update(new)

    rows = []
    for start in sorted(s for s in states if s >= first):
        running = round(running + states[start], 6)
        rows.append({"start": start, "state": states[start], "sum": running})
    return rows


# --------------------------------------------------------------------------
# Interval (e.g. 15 minute) store
#
# The raw interval values are kept per kind and per UTC day:
#     {"2026-11-04": {"step": 15, "v": [0.325, 0.113, ..., None, ...]}}
# A slot holds the kWh of the interval starting at midnight UTC + i * step.
# Hourly values are always recomputed from these slots, so a file that lacks
# some intervals can never overwrite data that arrived earlier.

def _day_key(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).date().isoformat()


def _day_start(key: str) -> datetime:
    return datetime.fromisoformat(key).replace(tzinfo=timezone.utc)


def merge_intervals(
    days: dict[str, dict],
    intervals: dict[datetime, float],
    step: timedelta,
) -> set[datetime]:
    """Merge interval values into `days` (modified in place).

    A new value replaces the stored value of the same interval; intervals the
    new data does not mention keep their stored value. Returns the UTC hour
    starts whose value may have changed.
    """
    minutes = int(step.total_seconds() // 60)
    if minutes <= 0 or 1440 % minutes or minutes > 60:
        raise ValueError(f"Unsupported interval length: {step}")
    slots = 1440 // minutes

    touched: set[datetime] = set()
    for start, kwh in intervals.items():
        start = start.astimezone(timezone.utc)
        key = _day_key(start)
        day = days.get(key)
        if day is None or day.get("step") != minutes:
            # New day, or the resolution changed: start the day afresh.
            day = days[key] = {"step": minutes, "v": [None] * slots}
            touched.update(_day_start(key) + timedelta(hours=i) for i in range(24))
        index = int((start - _day_start(key)).total_seconds() // 60) // minutes
        day["v"][index] = round(float(kwh), 6)
        touched.add(start.replace(minute=0, second=0, microsecond=0))
    return touched


def hourly_from_intervals(
    days: dict[str, dict], hours: set[datetime]
) -> dict[datetime, float]:
    """Sum the stored intervals of the given hours (hours with no data are left out)."""
    result: dict[datetime, float] = {}
    for hour in hours:
        hour = hour.astimezone(timezone.utc)
        day = days.get(_day_key(hour))
        if day is None:
            continue
        per_hour = 60 // day["step"]
        first = hour.hour * per_hour
        values = [v for v in day["v"][first : first + per_hour] if v is not None]
        if values:
            result[hour] = round(sum(values), 6)
    return result

