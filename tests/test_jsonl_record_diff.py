import contextlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

import useful_automation_lab
from useful_automation_lab.jsonl_record_diff import compare_jsonl_records, main


class JsonlRecordDiffTests(unittest.TestCase):
    def setUp(self):
        self.reference = [
            {
                "id": "a",
                "name": "alpha",
                "status": "open",
                "updated_at": "2026-01-01",
            },
            {"id": "b", "name": "beta", "status": "open"},
            {"id": "c", "name": "gamma", "status": "closed"},
        ]
        self.candidate = [
            {
                "id": "a",
                "name": "alpha",
                "status": "closed",
                "updated_at": "2026-02-01",
            },
            {"id": "c", "name": "gamma", "status": "closed"},
            {"id": "d", "name": "delta", "status": "open"},
        ]

    def test_public_api_and_keyed_change_counts(self):
        self.assertIs(
            useful_automation_lab.compare_jsonl_records,
            compare_jsonl_records,
        )

        report = compare_jsonl_records(
            self.reference,
            self.candidate,
            ignore_fields=["updated_at"],
            max_added=1,
            max_removed=1,
            max_modified=1,
        )

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
        self.assertEqual(report["added_records"], [{"id": "d"}])
        self.assertEqual(report["removed_records"], [{"id": "b"}])
        self.assertEqual(
            report["modified_records"],
            [{"id": "a", "changed_fields": ["status"]}],
        )

    def test_default_zero_budgets_report_all_failures(self):
        report = compare_jsonl_records(self.reference, self.candidate)

        self.assertFalse(report["passed"])
        self.assertEqual(
            [failure["metric"] for failure in report["failures"]],
            [
                "added_record_count",
                "removed_record_count",
                "modified_record_count",
            ],
        )

    def test_ignore_fields_exclude_expected_volatile_changes(self):
        without_ignore = compare_jsonl_records(
            self.reference,
            self.candidate,
            max_added=1,
            max_removed=1,
            max_modified=1,
        )
        with_ignore = compare_jsonl_records(
            self.reference,
            self.candidate,
            ignore_fields=["updated_at"],
            max_added=1,
            max_removed=1,
            max_modified=1,
        )

        self.assertEqual(
            without_ignore["modified_records"][0]["changed_fields"],
            ["status", "updated_at"],
        )
        self.assertEqual(
            with_ignore["modified_records"][0]["changed_fields"],
            ["status"],
        )

    def test_details_are_bounded_without_reporting_values(self):
        report = compare_jsonl_records(
            self.reference,
            self.candidate,
            ignore_fields=["updated_at"],
            max_details=0,
        )

        self.assertEqual(report["added_records"], [])
        self.assertEqual(report["removed_records"], [])
        self.assertEqual(report["modified_records"], [])
        self.assertEqual(
            report["details_truncated"],
            {"added_records": True, "removed_records": True, "modified_records": True},
        )
        self.assertFalse(report["settings"]["scalar_values_reported_beyond_ids"])
        self.assertNotIn("alpha", json.dumps(report))

    def test_key_types_are_kept_distinct(self):
        report = compare_jsonl_records(
            [{"id": 1, "value": "before"}],
            [{"id": "1", "value": "after"}],
            max_added=1,
            max_removed=1,
        )

        self.assertEqual(report["summary"]["added_record_count"], 1)
        self.assertEqual(report["summary"]["removed_record_count"], 1)
        self.assertEqual(report["summary"]["modified_record_count"], 0)

    def test_invalid_inputs_are_rejected(self):
        invalid_calls = [
            ([], self.candidate, {}),
            (self.reference, self.candidate, {"key_field": ""}),
            (self.reference, self.candidate, {"ignore_fields": ["id"]}),
            (self.reference, self.candidate, {"ignore_fields": ["x", "x"]}),
            (self.reference, self.candidate, {"max_added": -1}),
            (self.reference, self.candidate, {"max_removed": True}),
            (self.reference, self.candidate, {"max_details": -1}),
        ]
        for reference, candidate, kwargs in invalid_calls:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                compare_jsonl_records(reference, candidate, **kwargs)

        duplicate = [self.reference[0], dict(self.reference[0])]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            compare_jsonl_records(duplicate, self.candidate)
        with self.assertRaisesRegex(ValueError, "string or integer"):
            compare_jsonl_records([{"id": True}], [{"id": "a"}])
        with self.assertRaisesRegex(ValueError, "JSON-compatible"):
            compare_jsonl_records(
                [{"id": "a", "value": math.nan}],
                [{"id": "a", "value": 1.0}],
            )

    def test_cli_writes_report_and_uses_strict_default_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            reference_path = Path(directory) / "reference.jsonl"
            candidate_path = Path(directory) / "candidate.jsonl"
            output_path = Path(directory) / "report.json"
            self._write_jsonl(reference_path, self.reference)
            self._write_jsonl(candidate_path, self.candidate)

            exit_code = main(
                [
                    str(reference_path),
                    str(candidate_path),
                    "--ignore-field",
                    "updated_at",
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(exit_code, 1)
            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8"))["summary"][
                    "changed_record_count"
                ],
                3,
            )

    def test_cli_rejects_output_alias_and_oversized_input(self):
        with tempfile.TemporaryDirectory() as directory:
            reference_path = Path(directory) / "reference.jsonl"
            candidate_path = Path(directory) / "candidate.jsonl"
            self._write_jsonl(reference_path, self.reference)
            self._write_jsonl(candidate_path, self.candidate)

            with contextlib.redirect_stderr(io.StringIO()):
                alias_exit = main(
                    [
                        str(reference_path),
                        str(candidate_path),
                        "--output",
                        str(reference_path),
                    ]
                )
                size_exit = main(
                    [
                        str(reference_path),
                        str(candidate_path),
                        "--max-file-bytes",
                        "4",
                    ]
                )

        self.assertEqual(alias_exit, 2)
        self.assertEqual(size_exit, 2)

    @staticmethod
    def _write_jsonl(path, records):
        path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
