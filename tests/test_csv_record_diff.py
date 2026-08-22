import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import useful_automation_lab
from useful_automation_lab.csv_record_diff import compare_csv_records, main


class CsvRecordDiffTests(unittest.TestCase):
    def setUp(self):
        self.reference = [
            {
                "tenant": "west",
                "record_id": "a",
                "status": "open",
                "updated_at": "2026-01-01",
            },
            {
                "tenant": "east",
                "record_id": "b",
                "status": "open",
                "updated_at": "2026-01-01",
            },
            {
                "tenant": "west",
                "record_id": "c",
                "status": "closed",
                "updated_at": "2026-01-01",
            },
        ]
        self.candidate = [
            {
                "tenant": "west",
                "record_id": "a",
                "status": "closed",
                "updated_at": "2026-02-01",
            },
            {
                "tenant": "west",
                "record_id": "c",
                "status": "closed",
                "updated_at": "2026-01-01",
            },
            {
                "tenant": "north",
                "record_id": "d",
                "status": "open",
                "updated_at": "2026-02-01",
            },
        ]

    def compare(self, **kwargs):
        return compare_csv_records(
            self.reference,
            self.candidate,
            key_columns=("tenant", "record_id"),
            **kwargs,
        )

    def test_reports_composite_key_changes(self):
        report = self.compare(
            ignore_columns=("updated_at",),
            max_added=1,
            max_removed=1,
            max_modified=1,
        )

        self.assertIs(useful_automation_lab.compare_csv_records, compare_csv_records)
        self.assertTrue(report["passed"])
        self.assertEqual(
            report["summary"],
            {
                "reference_record_count": 3,
                "candidate_record_count": 3,
                "added_record_count": 1,
                "removed_record_count": 1,
                "modified_record_count": 1,
                "unchanged_record_count": 1,
                "changed_record_count": 3,
            },
        )
        self.assertEqual(report["modified_records"][0]["changed_columns"], ["status"])

    def test_default_zero_budgets_report_all_failures(self):
        report = self.compare()

        self.assertFalse(report["passed"])
        self.assertEqual(
            [failure["metric"] for failure in report["failures"]],
            ["added_record_count", "removed_record_count", "modified_record_count"],
        )

    def test_ignored_columns_remove_expected_volatile_changes(self):
        without_ignore = self.compare(max_added=1, max_removed=1, max_modified=1)
        with_ignore = self.compare(
            ignore_columns=("updated_at",),
            max_added=1,
            max_removed=1,
            max_modified=1,
        )

        self.assertEqual(
            without_ignore["modified_records"][0]["changed_columns"],
            ["status", "updated_at"],
        )
        self.assertEqual(
            with_ignore["modified_records"][0]["changed_columns"], ["status"]
        )

    def test_details_are_bounded_and_values_are_not_reported(self):
        report = self.compare(ignore_columns=("updated_at",), max_details=0)
        rendered = json.dumps(report)

        self.assertEqual(report["added_records"], [])
        self.assertEqual(report["removed_records"], [])
        self.assertEqual(report["modified_records"], [])
        self.assertEqual(
            report["details_truncated"],
            {"added_records": True, "removed_records": True, "modified_records": True},
        )
        for private_value in ("west", "east", "north", "open", "closed"):
            self.assertNotIn(private_value, rendered)
        self.assertFalse(report["settings"]["raw_key_values_reported"])

    def test_fingerprints_are_stable_and_do_not_collapse_composite_keys(self):
        report = compare_csv_records(
            [{"left": "ab", "right": "c", "value": "old"}],
            [{"left": "a", "right": "bc", "value": "new"}],
            key_columns=("left", "right"),
            max_added=1,
            max_removed=1,
        )

        self.assertNotEqual(
            report["added_records"][0]["key_fingerprint"],
            report["removed_records"][0]["key_fingerprint"],
        )
        self.assertEqual(len(report["added_records"][0]["key_fingerprint"]), 16)

    def test_invalid_rows_and_configuration_are_rejected(self):
        invalid_calls = [
            ([], self.candidate, {}, "reference_rows"),
            (self.reference, self.candidate, {"key_columns": ()}, "at least one"),
            (
                self.reference,
                self.candidate,
                {"key_columns": ("tenant",), "ignore_columns": ("tenant",)},
                "cannot be ignored",
            ),
            (self.reference, self.candidate, {"max_added": -1}, "non-negative"),
            (self.reference, self.candidate, {"max_details": True}, "non-negative"),
        ]
        for reference, candidate, kwargs, message in invalid_calls:
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, message):
                    compare_csv_records(reference, candidate, **kwargs)

        with self.assertRaisesRegex(ValueError, "headers must match"):
            compare_csv_records(
                [{"id": "a", "value": "x"}],
                [{"id": "a", "other": "x"}],
            )
        with self.assertRaisesRegex(ValueError, "duplicate composite key"):
            compare_csv_records(
                [{"id": "a"}, {"id": "a"}],
                [{"id": "a"}],
            )
        with self.assertRaisesRegex(ValueError, "must be a string"):
            compare_csv_records([{"id": 1}], [{"id": "1"}])
        with self.assertRaisesRegex(ValueError, "non-empty"):
            compare_csv_records([{"id": ""}], [{"id": ""}])

    def test_cli_writes_a_report_and_uses_strict_default_budgets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.csv"
            candidate = root / "candidate.csv"
            output = root / "report.json"
            reference.write_text(
                "tenant,id,status,updated_at\nwest,a,open,2026-01-01\n",
                encoding="utf-8",
            )
            candidate.write_text(
                "tenant,id,status,updated_at\nwest,a,closed,2026-02-01\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    str(reference),
                    str(candidate),
                    "--key-column",
                    "tenant",
                    "--key-column",
                    "id",
                    "--ignore-column",
                    "updated_at",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(exit_code, 1)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["modified_record_count"], 1)

    def test_cli_prints_a_passing_budgeted_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.csv"
            candidate = root / "candidate.csv"
            reference.write_text("id,status\na,open\n", encoding="utf-8")
            candidate.write_text("id,status\na,closed\n", encoding="utf-8")

            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                exit_code = main(
                    [str(reference), str(candidate), "--max-modified", "1"]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(json.loads(stdout.getvalue())["passed"])

    def test_cli_rejects_input_alias_output_alias_and_oversized_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.csv"
            candidate = root / "candidate.csv"
            reference.write_text("id,status\na,open\n", encoding="utf-8")
            candidate.write_text("id,status\na,closed\n", encoding="utf-8")

            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(reference), str(reference)]), 2)
                self.assertEqual(
                    main(
                        [
                            str(reference),
                            str(candidate),
                            "--output",
                            str(reference),
                        ]
                    ),
                    2,
                )
                self.assertEqual(
                    main(
                        [
                            str(reference),
                            str(candidate),
                            "--max-file-bytes",
                            "2",
                        ]
                    ),
                    2,
                )


if __name__ == "__main__":
    unittest.main()
