import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import useful_automation_lab
from useful_automation_lab.compare import InvalidInventoryError
from useful_automation_lab.duplicates import find_duplicates, main


def entry(path: str, marker: str, size: int) -> dict[str, str | int]:
    return {"path": path, "size": size, "sha256": marker * 64}


class DuplicateDetectionTests(unittest.TestCase):
    def test_duplicate_api_is_available_from_package(self):
        self.assertIs(useful_automation_lab.find_duplicates, find_duplicates)

    def test_groups_duplicates_and_reports_reclaimable_bytes(self):
        report = find_duplicates(
            [
                entry("z-copy.bin", "a", 10),
                entry("unique.txt", "b", 3),
                entry("a-original.bin", "a", 10),
                entry("third.bin", "a", 10),
            ]
        )

        self.assertEqual(
            report["summary"],
            {
                "scanned_files": 4,
                "eligible_files": 4,
                "duplicate_groups": 1,
                "duplicate_files": 3,
                "reclaimable_bytes": 20,
            },
        )
        self.assertEqual(
            report["groups"][0]["paths"],
            ["a-original.bin", "third.bin", "z-copy.bin"],
        )

    def test_groups_are_sorted_by_reclaimable_bytes_then_identity(self):
        report = find_duplicates(
            [
                entry("small-a", "c", 4),
                entry("small-b", "c", 4),
                entry("large-a", "b", 8),
                entry("large-b", "b", 8),
            ]
        )

        self.assertEqual([group["size"] for group in report["groups"]], [8, 4])

    def test_minimum_size_filters_entries_before_grouping(self):
        report = find_duplicates(
            [entry("empty-a", "a", 0), entry("empty-b", "a", 0)],
            min_size=1,
        )

        self.assertEqual(report["summary"]["eligible_files"], 0)
        self.assertEqual(report["groups"], [])

    def test_digest_and_size_must_both_match(self):
        report = find_duplicates(
            [entry("short.bin", "a", 1), entry("long.bin", "a", 2)]
        )

        self.assertEqual(report["groups"], [])

    def test_invalid_minimum_and_inventory_are_rejected(self):
        for minimum in (-1, 1.5, True):
            with self.subTest(minimum=minimum):
                with self.assertRaisesRegex(ValueError, "min_size"):
                    find_duplicates([], min_size=minimum)
        with self.assertRaises(InvalidInventoryError):
            find_duplicates([{"path": "missing-fields"}])

    def test_cli_prints_report_and_can_fail_when_duplicates_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "inventory.json"
            inventory.write_text(
                json.dumps([entry("a.bin", "a", 10), entry("b.bin", "a", 10)]),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = main([str(inventory), "--fail-on-duplicates"])

            self.assertEqual(exit_code, 1)
            self.assertEqual(
                json.loads(stdout.getvalue())["summary"]["reclaimable_bytes"],
                10,
            )

    def test_cli_writes_a_filtered_report(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "inventory.json"
            output = Path(directory) / "duplicates.json"
            inventory.write_text(
                json.dumps([entry("a.bin", "a", 1), entry("b.bin", "a", 1)]),
                encoding="utf-8",
            )

            exit_code = main(
                [str(inventory), "--min-size", "2", "--output", str(output)]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.read_text())["groups"], [])

    def test_cli_returns_two_for_invalid_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "inventory.json"
            inventory.write_text("{", encoding="utf-8")

            with contextlib.redirect_stderr(io.StringIO()):
                exit_code = main([str(inventory)])

            self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
