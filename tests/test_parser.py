"""Standalone tests for the export parser (no Home Assistant needed).

Run: python3 -m unittest discover -s tests -v
"""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import unittest

_PATH = Path(__file__).parents[1] / "custom_components" / "energy_metrics_eon" / "parser.py"
_spec = importlib.util.spec_from_file_location("energy_metrics_eon_parser", _PATH)
parser = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = parser
_spec.loader.exec_module(parser)

COLS = {"import": "+A", "export": "-A"}


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def quarter_rows(day: datetime, count: int, fmt="%Y.%m.%d. %H:%M"):
    return [(day + timedelta(minutes=15 * i)).strftime(fmt) for i in range(count)]


class ParserTest(unittest.TestCase):
    def test_portal_csv(self):
        """Layout of the portal's own CSV download: comma separated, summary rows."""
        lines = ["Dátum/Idő,+A,-A", "MAXIMUM ÉRTÉK,0.5,0.25", "ÖSSZEG,48,24"]
        lines += [f"{ts},0.5,0.25" for ts in quarter_rows(datetime(2026, 11, 9), 96)]
        result = parser.parse_export(("﻿" + "\n".join(lines)).encode(), COLS)

        self.assertEqual(result.step, timedelta(minutes=15))
        self.assertEqual(len(result.series["import"]), 24)
        # 2026-11-09 00:00 CET == 2026-11-08 23:00 UTC
        self.assertEqual(result.series["import"][utc(2026, 11, 8, 23)], 2.0)
        self.assertEqual(result.series["export"][utc(2026, 11, 9, 22)], 1.0)

    def test_semicolon_decimal_comma_with_units_and_preamble(self):
        lines = ["POD;HU000000000000000000000000000000", "", "Időbélyeg;+A [kWh];-A [kWh];+Ri"]
        lines += [
            f"{ts};0,125;0,000;9"
            for ts in quarter_rows(datetime(2026, 7, 1), 8, "%Y-%m-%d %H:%M:%S")
        ]
        result = parser.parse_export("\n".join(lines).encode("cp1250"), COLS)
        # July is CEST (UTC+2)
        self.assertEqual(result.series["import"], {utc(2026, 6, 30, 22): 0.5, utc(2026, 6, 30, 23): 0.5})
        self.assertEqual(result.series["export"][utc(2026, 6, 30, 22)], 0.0)

    def test_interval_end(self):
        lines = ["Dátum/Idő,+A"]
        lines += [f"{ts},1" for ts in quarter_rows(datetime(2026, 11, 9, 0, 15), 8)]
        result = parser.parse_export("\n".join(lines).encode(), {"import": "+A"}, interval_end=True)
        self.assertEqual(result.series["import"], {utc(2026, 11, 8, 23): 4.0, utc(2026, 11, 9, 0): 4.0})

    def test_trailing_partial_hour_dropped(self):
        lines = ["Dátum/Idő,+A"]
        lines += [f"{ts},1" for ts in quarter_rows(datetime(2026, 11, 9), 6)]
        result = parser.parse_export("\n".join(lines).encode(), {"import": "+A"})
        self.assertEqual(list(result.series["import"]), [utc(2026, 11, 8, 23)])

    def test_autumn_dst_day_has_25_hours(self):
        # 2026-10-25: 02:00-02:45 local time occurs twice.
        stamps = []
        t = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)  # 00:00 CEST
        for _ in range(100):
            stamps.append(t.astimezone(parser.LOCAL_TZ).strftime("%Y.%m.%d. %H:%M"))
            t += timedelta(minutes=15)
        lines = ["Dátum/Idő,+A"] + [f"{s},1" for s in stamps]
        result = parser.parse_export("\n".join(lines).encode(), {"import": "+A"})
        self.assertEqual(len(result.series["import"]), 25)
        self.assertTrue(all(v == 4.0 for v in result.series["import"].values()))

    def test_missing_columns_lists_headers(self):
        data = "Dátum/Idő,X,Y\n2026.11.09. 00:00,1,2\n".encode()
        with self.assertRaises(parser.ParseError) as ctx:
            parser.parse_export(data, COLS)
        self.assertIn("'X'", str(ctx.exception))

    def test_daily_export_rejected(self):
        data = "Dátum,+A\n2026.11.09.,1\n2026.11.10.,2\n".encode()
        with self.assertRaises(parser.ParseError):
            parser.parse_export(data, COLS)

    def test_only_export_column_configured_missing_is_ok(self):
        lines = ["Dátum/Idő,+A"] + [f"{ts},1" for ts in quarter_rows(datetime(2026, 11, 9), 4)]
        result = parser.parse_export("\n".join(lines).encode(), COLS)
        self.assertEqual(set(result.series), {"import"})

    def test_real_export_layout(self):
        """Layout of a real MertErtekek_*.xlsx: text timestamps, summary rows,
        empty value cells for the part of the day not yet read out."""
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl not installed")
        import io

        wb = Workbook()
        ws = wb.active
        ws.append(["Dátum/Idő", "+A", "-A"])
        ws.append(["MAXIMUM ÉRTÉK", 2.455, 1.463])
        ws.append(["ÖSSZEG", 347.394, 106.96])
        stamps = quarter_rows(datetime(2026, 11, 10), 96)
        for i, ts in enumerate(stamps):
            # values until 17:15 inclusive, then blanks
            ws.append([ts, 0.25, 0] if i < 70 else [ts, None, None])
        buf = io.BytesIO()
        wb.save(buf)
        result = parser.parse_export(buf.getvalue(), COLS)
        hours = result.series["import"]
        # 17 complete hours (00..16 local); the half-filled 17:00 hour is left out
        self.assertEqual(len(hours), 17)
        self.assertEqual(max(hours), utc(2026, 11, 10, 15))
        self.assertTrue(all(v == 1.0 for v in hours.values()))
        self.assertEqual(sum(result.series["export"].values()), 0)

    def _long_xlsx(self, sheets):
        """sheets: {title: [(pod, datetime, [(var, value, unit), ...]), ...]}"""
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl not installed")
        import io

        wb = Workbook()
        wb.remove(wb.active)
        for title, rows in sheets.items():
            ws = wb.create_sheet(title)
            width = max(len(r[2]) for r in rows)
            ws.append(["Pod", "Időbélyeg"] + ["Változó", "Érték", "Mértékegység"] * width)
            for pod, ts, groups in rows:
                ws.append([pod, ts] + [c for g in groups for c in g])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_email_export_layout(self):
        """Layout of the scheduled e-mail export (adatok.xlsx)."""
        rows = [
            ("HU-TEST-POD-1", datetime(2026, 11, 4) + timedelta(minutes=15 * i),
             [("+A", 0.25, "kWh"), ("-A", 0.5 if i >= 40 else 0.0, "kWh")])
            for i in range(96)
        ]
        result = parser.parse_export(self._long_xlsx({"POD_1": rows}), COLS)
        self.assertEqual(result.layout, "long")
        self.assertEqual(result.pod, "HU-TEST-POD-1")
        self.assertEqual(result.variables, ["+A", "-A"])
        self.assertEqual(result.step, timedelta(minutes=15))
        self.assertEqual(len(result.series["import"]), 24)
        self.assertEqual(result.series["import"][utc(2026, 11, 3, 23)], 1.0)
        # 10:00 local (index 40) onwards feeds in 0.5 per quarter
        self.assertEqual(result.series["export"][utc(2026, 11, 4, 8)], 0.0)
        self.assertEqual(result.series["export"][utc(2026, 11, 4, 9)], 2.0)

    def test_email_export_wh_and_variable_order(self):
        rows = [
            ("P", datetime(2026, 11, 4, 0, 15 * i),
             [("-A", 100, "Wh"), ("+Ri", 9, "kvarh"), ("+A", 250, "Wh")])
            for i in range(4)
        ]
        result = parser.parse_export(self._long_xlsx({"POD_1": rows}), COLS)
        self.assertEqual(result.series["import"], {utc(2026, 11, 3, 23): 1.0})
        self.assertEqual(result.series["export"], {utc(2026, 11, 3, 23): 0.4})

    def test_email_export_unknown_unit_for_wanted_variable(self):
        rows = [("P", datetime(2026, 11, 4, 0, 15 * i), [("+A", 1, "kVAh")]) for i in range(4)]
        with self.assertRaises(parser.ParseError):
            parser.parse_export(self._long_xlsx({"POD_1": rows}), COLS)

    def test_email_export_several_pods(self):
        def rows(pod, value):
            return [(pod, datetime(2026, 11, 4, 0, 15 * i), [("+A", value, "kWh")]) for i in range(4)]

        data = self._long_xlsx({"POD_1": rows("POD-A", 1), "POD_2": rows("POD-B", 2)})
        with self.assertRaises(parser.ParseError) as ctx:
            parser.parse_export(data, COLS)
        self.assertIn("POD-B", str(ctx.exception))
        result = parser.parse_export(data, COLS, pod="POD-B")
        self.assertEqual(result.pods, ["POD-A", "POD-B"])
        self.assertEqual(result.series["import"], {utc(2026, 11, 3, 23): 8.0})
        with self.assertRaises(parser.ParseError):
            parser.parse_export(data, COLS, pod="POD-C")

    def test_email_export_missing_variables_listed(self):
        rows = [("P", datetime(2026, 11, 4, 0, 15 * i), [("+Ri", 1, "kvarh")]) for i in range(4)]
        with self.assertRaises(parser.ParseError) as ctx:
            parser.parse_export(self._long_xlsx({"POD_1": rows}), COLS)
        self.assertIn("+Ri", str(ctx.exception))

    def _pod_file(self, pod, variables=("+A",), value=1):
        rows = [
            (pod, datetime(2026, 11, 4, 0, 15 * i),
             [(var, value, "kvarh" if var == "+Ri" else "kWh") for var in variables])
            for i in range(4)
        ]
        return self._long_xlsx({"POD_1": rows})

    def test_attachments_import_and_export_in_separate_files(self):
        files = [("a.xlsx", self._pod_file("P", ("+A",))), ("b.xlsx", self._pod_file("P", ("-A",), 2))]
        result = parser.parse_attachments(files, COLS)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].series["import"], {utc(2026, 11, 3, 23): 4.0})
        self.assertEqual(result[1].series["export"], {utc(2026, 11, 3, 23): 8.0})

    def test_attachments_other_pod_skipped(self):
        files = [("a.xlsx", self._pod_file("POD-A")), ("b.xlsx", self._pod_file("POD-B", value=2))]
        result = parser.parse_attachments(files, COLS, pod="POD-B")
        self.assertEqual([r.pod for r in result], ["POD-B"])
        # an e-mail only about another metering point is not an error
        self.assertEqual(parser.parse_attachments(files[:1], COLS, pod="POD-B"), [])

    def test_attachments_file_without_variables_skipped_if_another_has_data(self):
        files = [("reactive.xlsx", self._pod_file("P", ("+Ri",))), ("a.xlsx", self._pod_file("P"))]
        self.assertEqual(len(parser.parse_attachments(files, COLS)), 1)
        with self.assertRaises(parser.ParseError) as ctx:
            parser.parse_attachments(files[:1], COLS)
        self.assertIn("reactive.xlsx", str(ctx.exception))
        self.assertIn("+Ri", str(ctx.exception))

    def test_attachments_unreadable_file_is_an_error(self):
        files = [("a.xlsx", self._pod_file("P")), ("broken.csv", b"not an export")]
        with self.assertRaises(parser.ParseError) as ctx:
            parser.parse_attachments(files, COLS)
        self.assertIn("broken.csv", str(ctx.exception))

    def test_attachments_several_pods_without_configured_pod(self):
        files = [("a.xlsx", self._pod_file("POD-A")), ("b.xlsx", self._pod_file("POD-B"))]
        with self.assertRaises(parser.ParseError) as ctx:
            parser.parse_attachments(files, COLS)
        self.assertIn("POD-A", str(ctx.exception))
        self.assertIn("POD-B", str(ctx.exception))
        # also across e-mails: POD-A was imported earlier
        with self.assertRaises(parser.ParseError):
            parser.parse_attachments(files[1:], COLS, known_pod="POD-A")
        self.assertEqual(len(parser.parse_attachments(files[:1], COLS, known_pod="POD-A")), 1)
        self.assertEqual(parser.parse_attachments([], COLS), [])

    def test_leading_partial_hour_dropped(self):
        lines = ["Dátum/Idő,+A"]
        lines += [f"{ts},1" for ts in quarter_rows(datetime(2026, 11, 9, 0, 30), 6)]
        result = parser.parse_export("\n".join(lines).encode(), {"import": "+A"})
        self.assertEqual(list(result.series["import"]), [utc(2026, 11, 9, 0)])

    def test_xlsx(self):
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl not installed")
        import io

        wb = Workbook()
        ws = wb.active
        ws.append(["Dátum/Idő", "+A", "-A"])
        for i in range(4):
            ws.append([datetime(2026, 11, 9, 0, 15 * i), 0.25, 0.5])
        buf = io.BytesIO()
        wb.save(buf)
        result = parser.parse_export(buf.getvalue(), COLS)
        self.assertEqual(result.series["import"], {utc(2026, 11, 8, 23): 1.0})
        self.assertEqual(result.series["export"], {utc(2026, 11, 8, 23): 2.0})


if __name__ == "__main__":
    unittest.main()
