import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import useful_automation_lab
from useful_automation_lab.jsonl_structure import (
    compare_jsonl_structures,
    load_jsonl_records,
    main,
)


class JsonlStructureTests(unittest.TestCase):
    def setUp(self):
        self.reference = [
            {"id": "a", "score": 1, "tag": None},
            {"id": "b", "score": 2, "tag": "x"},
        ]
        self.candidate = [
            {"id": "c", "score": "1", "tag": "x", "region": "west"},
            {"id": "d", "score": "2"},
        ]

    def test_report_contains_profiles_and_deterministic_changes(self):
        report = compare_jsonl_structures(
            self.reference,
            self.candidate,
            max_presence_rate_delta=0.2,
            max_null_rate_delta=0.2,
            max_changes=4,
        )

        self.assertIs(
            useful_automation_lab.compare_jsonl_structures,
            compare_jsonl_structures,
        )
        self.assertTrue(report["passed"])
        self.assertEqual(report["summary"]["change_count"], 4)
        self.assertEqual(
            [(item["field"], item["code"]) for item in report["changes"]],
            [
                ("region", "field_added"),
                ("score", "type_set_changed"),
                ("tag", "presence_rate_changed"),
                ("tag", "null_rate_changed"),
            ],
        )
        tag = next(
            item
            for item in report["reference_profile"]["fields"]
            if item["field"] == "tag"
        )
        self.assertEqual(tag["null_count"], 1)
        self.assertEqual(tag["non_null_types"], ["string"])

    def test_report_never_copies_scalar_values(self):
        report = compare_jsonl_structures(
            [{"payload": "REFERENCE_SECRET_42"}],
            [{"payload": "CANDIDATE_SECRET_99"}],
        )
        rendered = json.dumps(report)

        self.assertNotIn("REFERENCE_SECRET_42", rendered)
        self.assertNotIn("CANDIDATE_SECRET_99", rendered)
        self.assertTrue(report["settings"]["scalar_values_reported"] is False)

    def test_gate_and_detail_bound_preserve_full_counts(self):
        report = compare_jsonl_structures(
            self.reference,
            self.candidate,
            max_presence_rate_delta=0.2,
            max_null_rate_delta=0.2,
            max_changes=1,
            max_details=2,
        )

        self.assertFalse(report["passed"])
        self.assertEqual(report["summary"]["change_count"], 4)
        self.assertEqual(report["summary"]["reported_change_count"], 2)
        self.assertEqual(report["summary"]["truncated_change_count"], 2)
        self.assertTrue(report["details_truncated"])
        self.assertEqual(report["failures"][0]["excess"], 3)

    def test_invalid_records_and_configuration_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            compare_jsonl_structures([], self.candidate)
        with self.assertRaisesRegex(ValueError, "must be an object"):
            compare_jsonl_structures(["not-object"], self.candidate)
        with self.assertRaisesRegex(ValueError, "field names"):
            compare_jsonl_structures([{1: "value"}], self.candidate)
        for value in (True, -0.1, 1.1, float("inf")):
            with self.subTest(rate=value):
                with self.assertRaisesRegex(ValueError, "between 0 and 1"):
                    compare_jsonl_structures(
                        self.reference,
                        self.candidate,
                        max_null_rate_delta=value,
                    )
        for value in (True, -1, 1.2):
            with self.subTest(max_changes=value):
                with self.assertRaisesRegex(ValueError, "max_changes"):
                    compare_jsonl_structures(
                        self.reference, self.candidate, max_changes=value
                    )

    def test_loader_rejects_duplicate_keys_constants_blanks_and_large_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            cases = (
                ('{"id":1,"id":2}\n', "duplicate"),
                ('{"score":NaN}\n', "non-standard"),
                ('{"id":1}\n\n{"id":2}\n', "blank"),
                ('[1,2]\n', "JSON object"),
            )
            for contents, message in cases:
                with self.subTest(contents=contents):
                    path.write_text(contents, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        load_jsonl_records(path)
            path.write_text('{"id":1}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "max_file_bytes"):
                load_jsonl_records(path, max_file_bytes=4)

    def test_cli_writes_report_and_uses_zero_one_two_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.jsonl"
            candidate = root / "candidate.jsonl"
            output = root / "report.json"
            reference.write_text(
                "".join(json.dumps(item) + "\n" for item in self.reference),
                encoding="utf-8",
            )
            candidate.write_text(
                "".join(json.dumps(item) + "\n" for item in self.candidate),
                encoding="utf-8",
            )

            self.assertEqual(
                main(
                    [
                        str(reference),
                        str(candidate),
                        "--max-presence-rate-delta",
                        "0.2",
                        "--max-null-rate-delta",
                        "0.2",
                        "--max-changes",
                        "4",
                        "--output",
                        str(output),
                    ]
                ),
                0,
            )
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["passed"])

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(reference), str(candidate)]), 1)
            original = reference.read_text(encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
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
            self.assertEqual(reference.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
