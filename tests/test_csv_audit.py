import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import useful_automation_lab
from useful_automation_lab.csv_audit import audit_csv, main


class CsvAuditTests(unittest.TestCase):
    def test_csv_audit_api_is_available_from_package(self):
        self.assertIs(useful_automation_lab.audit_csv, audit_csv)

    def test_valid_typed_rows_and_quoted_fields_pass(self):
        report = audit_csv(
            [
                "id,date,amount,active,note\n",
                '1,2026-01-01,12.5,true,"hello, world"\n',
                "2,2026-01-02,,false,\n",
            ],
            required_columns=["id", "date", "amount", "active"],
            not_empty_columns=["id", "date", "active"],
            unique_column="id",
            column_types={
                "id": "integer",
                "date": "date",
                "amount": "number",
                "active": "boolean",
            },
            max_field_bytes=20,
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["summary"]["data_rows"], 2)
        self.assertEqual(report["summary"]["valid_rows"], 2)
        self.assertEqual(report["summary"]["maximum_field_bytes"], 12)
        self.assertEqual(report["configuration"]["column_types"]["date"], "date")

    def test_data_issues_are_reported_in_stable_row_order(self):
        report = audit_csv(
            [
                "id,event,amount\n",
                "1,start,1.5\n",
                "\n",
                "2,finish\n",
                "1,,NaN\n",
            ],
            not_empty_columns=["event"],
            unique_column="id",
            column_types={"amount": "number", "id": "integer"},
        )

        self.assertFalse(report["passed"])
        self.assertEqual(
            [issue["code"] for issue in report["issues"]],
            [
                "blank_row",
                "row_width",
                "empty_required_values",
                "duplicate_unique_value",
                "invalid_type",
            ],
        )
        self.assertEqual(report["summary"]["valid_rows"], 1)
        self.assertEqual(report["summary"]["invalid_rows"], 3)
        self.assertEqual(report["summary"]["duplicate_rows"], 1)
        self.assertEqual(report["issues"][3]["first_line"], 2)

    def test_header_schema_issues_are_audit_failures(self):
        report = audit_csv(
            ["id,id,,value\n", "1,2,x,3\n"],
            required_columns=["missing"],
            not_empty_columns=["unknown"],
        )

        self.assertFalse(report["summary"]["header_valid"])
        self.assertEqual(
            [issue["code"] for issue in report["issues"][:4]],
            [
                "empty_header_columns",
                "duplicate_header_columns",
                "missing_required_columns",
                "missing_rule_columns",
            ],
        )

    def test_field_size_uses_utf8_bytes(self):
        report = audit_csv(
            ["id,value\n", "1,ééé\n"],
            max_field_bytes=5,
        )

        self.assertEqual(report["issues"][0]["code"], "field_too_large")
        self.assertEqual(report["issues"][0]["actual_bytes"], 6)
        self.assertEqual(report["summary"]["maximum_field_bytes"], 6)

    def test_detailed_issues_are_bounded_without_hiding_totals(self):
        report = audit_csv(
            ["id,value\n", "1,abcdef\n", "1,abcdef\n"],
            unique_column="id",
            max_field_bytes=3,
            max_errors=2,
        )

        self.assertEqual(report["summary"]["issue_count"], 3)
        self.assertEqual(report["summary"]["reported_issues"], 2)
        self.assertEqual(report["summary"]["truncated_issues"], 1)

    def test_fatal_csv_parse_error_is_explicit(self):
        report = audit_csv(["id,name\n", '1,"unterminated\n'])

        self.assertFalse(report["passed"])
        self.assertTrue(report["summary"]["stopped_early"])
        self.assertEqual(report["issues"][0]["code"], "csv_parse_error")

    def test_invalid_configuration_is_rejected(self):
        cases = [
            ({"required_columns": "id"}, "required_columns"),
            ({"not_empty_columns": ["id", "id"]}, "duplicates"),
            ({"unique_column": ""}, "unique_column"),
            ({"column_types": {"id": "uuid"}}, "column_types"),
            ({"max_field_bytes": 0}, "max_field_bytes"),
            ({"max_errors": True}, "max_errors"),
        ]
        for kwargs, message in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, message):
                    audit_csv(["id\n"], **kwargs)

    def test_cli_writes_a_passing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "events.csv"
            output = Path(directory) / "report.json"
            dataset.write_text(
                "id,event,amount\n1,start,1.5\n2,finish,2\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    str(dataset),
                    "--require",
                    "id",
                    "--not-empty",
                    "event",
                    "--unique-column",
                    "id",
                    "--type",
                    "id=integer",
                    "--type",
                    "amount=number",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["passed"])

    def test_cli_returns_one_for_data_issues_and_two_for_bad_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "events.csv"
            dataset.write_text("id\n1\n1\n", encoding="utf-8")

            with contextlib.redirect_stdout(io.StringIO()):
                data_exit = main([str(dataset), "--unique-column", "id"])
            with contextlib.redirect_stderr(io.StringIO()):
                config_exit = main([str(dataset), "--type", "id=uuid"])

            self.assertEqual(data_exit, 1)
            self.assertEqual(config_exit, 2)


if __name__ == "__main__":
    unittest.main()
