import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from useful_automation_lab.csv_references import (
    audit_csv_references,
    load_csv_rows,
    main,
)


class CsvReferenceTests(unittest.TestCase):
    def setUp(self):
        self.parents = [
            {"account_id": "a", "region": "west", "private": "parent-a"},
            {"account_id": "b", "region": "east", "private": "parent-b"},
        ]
        self.children = [
            {"owner_id": "a", "owner_region": "west", "private": "child-1"},
            {"owner_id": "a", "owner_region": "west", "private": "child-2"},
            {"owner_id": "missing", "owner_region": "north", "private": "child-3"},
        ]

    def audit(self, **kwargs):
        return audit_csv_references(
            self.parents,
            self.children,
            parent_key_columns=("account_id", "region"),
            child_key_columns=("owner_id", "owner_region"),
            **kwargs,
        )

    def test_reports_composite_reference_integrity(self):
        report = self.audit(max_orphan_rate=1 / 3)

        self.assertTrue(report["passed"])
        self.assertEqual(report["summary"]["parent_key_count"], 2)
        self.assertEqual(report["summary"]["referenced_parent_key_count"], 1)
        self.assertEqual(report["summary"]["matched_child_row_count"], 2)
        self.assertEqual(report["summary"]["orphan_child_row_count"], 1)
        self.assertAlmostEqual(report["summary"]["orphan_child_rate"], 1 / 3)

    def test_duplicate_and_orphan_failures_have_stable_order(self):
        parents = self.parents + [dict(self.parents[0])]
        report = audit_csv_references(
            parents,
            self.children,
            parent_key_columns=("account_id", "region"),
            child_key_columns=("owner_id", "owner_region"),
        )

        self.assertFalse(report["passed"])
        self.assertEqual(
            [failure["metric"] for failure in report["failures"]],
            ["duplicate_parent_key_count", "orphan_child_rate"],
        )
        self.assertEqual(report["duplicate_parent_keys"][0]["row_numbers"], [2, 4])

    def test_report_uses_fingerprints_instead_of_key_values(self):
        rendered = json.dumps(self.audit(max_orphan_rate=1.0))

        self.assertNotIn("missing", rendered)
        self.assertNotIn("north", rendered)
        self.assertNotIn("parent-a", rendered)
        self.assertNotIn("child-3", rendered)
        self.assertFalse(self.audit(max_orphan_rate=1.0)["settings"]["raw_key_values_reported"])
        self.assertEqual(len(self.audit(max_orphan_rate=1.0)["orphan_child_keys"][0]["key_fingerprint"]), 16)

    def test_optional_all_empty_child_keys_can_be_skipped(self):
        report = audit_csv_references(
            [{"id": "a"}],
            [{"owner": ""}, {"owner": "a"}],
            child_key_columns=("owner",),
            allow_empty_child_keys=True,
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["summary"]["optional_empty_child_row_count"], 1)
        self.assertEqual(report["summary"]["checked_child_row_count"], 1)

    def test_details_are_bounded(self):
        children = [
            {"parent_id": "missing-a"},
            {"parent_id": "missing-b"},
        ]
        report = audit_csv_references(
            [{"id": "parent"}], children, max_orphan_rate=1.0, max_details=1
        )

        self.assertEqual(len(report["orphan_child_keys"]), 1)
        self.assertTrue(report["details_truncated"]["orphan_child_keys"])

    def test_invalid_rows_and_configuration_are_rejected(self):
        invalid_calls = [
            ([], self.children, {}, "parent_rows"),
            (self.parents, [], {}, "child_rows"),
            (self.parents, self.children, {"parent_key_columns": ()}, "at least one"),
            (self.parents, self.children, {"max_orphan_rate": 2}, "between 0 and 1"),
            (self.parents, self.children, {"max_duplicate_parent_keys": -1}, "non-negative"),
            (self.parents, self.children, {"max_details": -1}, "max_details"),
        ]
        for parents, children, kwargs, message in invalid_calls:
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, message):
                    audit_csv_references(parents, children, **kwargs)

        with self.assertRaisesRegex(ValueError, "same length"):
            audit_csv_references(
                [{"id": "a"}],
                [{"a": "a", "b": "b"}],
                child_key_columns=("a", "b"),
            )
        with self.assertRaisesRegex(ValueError, "non-empty"):
            audit_csv_references([{"id": ""}], [{"parent_id": ""}])

    def test_loader_rejects_duplicate_headers_and_bad_width(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("id,id\na,b\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "header"):
                load_csv_rows(path)
            path.write_text("id,name\na\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "width"):
                load_csv_rows(path)

    def test_cli_writes_report_and_uses_gate_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parents = root / "parents.csv"
            children = root / "children.csv"
            output = root / "report.json"
            parents.write_text("id,name\np1,Parent\n", encoding="utf-8")
            children.write_text("id,parent_id\nc1,missing\n", encoding="utf-8")

            exit_code = main([str(parents), str(children), "--output", str(output)])

            self.assertEqual(exit_code, 1)
            self.assertFalse(json.loads(output.read_text(encoding="utf-8"))["passed"])

    def test_cli_rejects_input_alias_output_alias_and_oversized_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parents = root / "parents.csv"
            children = root / "children.csv"
            parents.write_text("id\np1\n", encoding="utf-8")
            children.write_text("parent_id\np1\n", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(parents), str(parents)]), 2)
                self.assertEqual(
                    main([str(parents), str(children), "--output", str(children)]),
                    2,
                )
                self.assertEqual(
                    main([str(parents), str(children), "--max-file-bytes", "2"]),
                    2,
                )


if __name__ == "__main__":
    unittest.main()
