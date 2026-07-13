import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import useful_automation_lab
from useful_automation_lab.compare import (
    InvalidInventoryError,
    compare_inventories,
    load_inventory,
    main,
)


def entry(path: str, marker: str, size: int = 1) -> dict[str, str | int]:
    return {"path": path, "size": size, "sha256": marker * 64}


class CompareTests(unittest.TestCase):
    def test_comparison_api_is_available_from_package(self):
        self.assertIs(useful_automation_lab.compare_inventories, compare_inventories)

    def test_report_categorizes_changes_and_sorts_paths(self):
        before = [
            entry("same.txt", "a"),
            entry("removed.txt", "b"),
            entry("changed.txt", "c", size=2),
        ]
        after = [
            entry("new.txt", "d"),
            entry("changed.txt", "e", size=3),
            entry("same.txt", "a"),
        ]

        report = compare_inventories(before, after)

        self.assertEqual(
            report["summary"],
            {"added": 1, "removed": 1, "modified": 1, "unchanged": 1},
        )
        self.assertEqual([item["path"] for item in report["added"]], ["new.txt"])
        self.assertEqual(
            [item["path"] for item in report["removed"]], ["removed.txt"]
        )
        self.assertEqual(report["modified"][0]["path"], "changed.txt")
        self.assertEqual(report["modified"][0]["before"]["size"], 2)
        self.assertEqual(report["modified"][0]["after"]["size"], 3)

    def test_duplicate_paths_are_rejected(self):
        duplicate = [entry("same.txt", "a"), entry("same.txt", "b")]

        with self.assertRaisesRegex(InvalidInventoryError, "duplicate path"):
            compare_inventories(duplicate, [])

    def test_noncanonical_paths_are_rejected(self):
        invalid_paths = ["../secret.txt", "/absolute.txt", "nested\\file.txt"]

        for path in invalid_paths:
            with self.subTest(path=path):
                with self.assertRaisesRegex(InvalidInventoryError, "normalized relative"):
                    compare_inventories([entry(path, "a")], [])

    def test_invalid_fields_are_rejected(self):
        invalid = {"path": "file.txt", "size": -1, "sha256": "not-a-digest"}

        with self.assertRaisesRegex(InvalidInventoryError, "invalid size"):
            compare_inventories([invalid], [])

    def test_cli_returns_zero_for_identical_inventories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            output = root / "diff.json"
            snapshot.write_text(json.dumps([entry("same.txt", "a")]), encoding="utf-8")

            exit_code = main([str(snapshot), str(snapshot), "--output", str(output)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.read_text())["summary"]["unchanged"], 1)

    def test_cli_returns_one_and_prints_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = root / "before.json"
            after = root / "after.json"
            before.write_text("[]", encoding="utf-8")
            after.write_text(json.dumps([entry("new.txt", "a")]), encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = main([str(before), str(after)])

            self.assertEqual(exit_code, 1)
            self.assertEqual(json.loads(stdout.getvalue())["summary"]["added"], 1)

    def test_cli_returns_two_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "invalid.json"
            valid = root / "valid.json"
            invalid.write_text("{", encoding="utf-8")
            valid.write_text("[]", encoding="utf-8")
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                exit_code = main([str(invalid), str(valid)])

            self.assertEqual(exit_code, 2)
            self.assertIn("invalid JSON", stderr.getvalue())

    def test_cli_returns_two_for_non_utf8_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "invalid.json"
            valid = root / "valid.json"
            invalid.write_bytes(b"\xff")
            valid.write_text("[]", encoding="utf-8")

            with contextlib.redirect_stderr(io.StringIO()):
                exit_code = main([str(invalid), str(valid)])

            self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
