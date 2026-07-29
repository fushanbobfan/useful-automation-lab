import contextlib
import io
import json
import tempfile
import unittest
import unicodedata
from pathlib import Path

import useful_automation_lab
from useful_automation_lab.compare import InvalidInventoryError
from useful_automation_lab.portability import audit_path_portability, main


def entry(path: str, marker: str = "a") -> dict[str, str | int]:
    return {"path": path, "size": 1, "sha256": marker * 64}


class PathPortabilityTests(unittest.TestCase):
    def test_safe_paths_pass_with_empty_issue_counts(self):
        report = audit_path_portability(
            [
                entry("README.md"),
                entry("src/package/module.py", "b"),
            ]
        )

        self.assertIs(
            useful_automation_lab.audit_path_portability,
            audit_path_portability,
        )
        self.assertTrue(report["passed"])
        self.assertEqual(
            report["summary"],
            {
                "files": 2,
                "issue_count": 0,
                "affected_path_count": 0,
                "issue_codes": {},
            },
        )

    def test_windows_component_hazards_are_reported_in_stable_order(self):
        report = audit_path_portability(
            [
                entry("aux.txt"),
                entry("logs/bad?.txt", "b"),
                entry("notes/trailing. ", "c"),
                entry("raw/control\u0001.txt", "d"),
            ]
        )

        self.assertFalse(report["passed"])
        self.assertEqual(
            [issue["code"] for issue in report["issues"]],
            [
                "windows_reserved_name",
                "windows_forbidden_character",
                "windows_trailing_space_or_dot",
                "control_character",
            ],
        )
        self.assertEqual(
            report["summary"]["issue_codes"],
            {
                "control_character": 1,
                "windows_forbidden_character": 1,
                "windows_reserved_name": 1,
                "windows_trailing_space_or_dot": 1,
            },
        )

    def test_case_collisions_include_both_affected_paths(self):
        report = audit_path_portability(
            [
                entry("Data/Model.JSON"),
                entry("data/model.json", "b"),
            ]
        )

        self.assertEqual(report["issues"][0]["code"], "case_collision")
        self.assertEqual(report["issues"][0]["first_path"], "Data/Model.JSON")
        self.assertEqual(report["issues"][0]["path"], "data/model.json")
        self.assertEqual(report["summary"]["affected_path_count"], 2)

    def test_unicode_normalization_collisions_are_distinguished(self):
        composed = "caf\u00e9.txt"
        decomposed = unicodedata.normalize("NFD", composed)

        report = audit_path_portability(
            [entry(composed), entry(decomposed, "b")]
        )

        self.assertEqual(
            report["issues"][0]["code"],
            "unicode_normalization_collision",
        )

    def test_combined_case_and_normalization_collision_is_explicit(self):
        report = audit_path_portability(
            [
                entry("\u00c9cole.txt"),
                entry("e\u0301COLE.txt", "b"),
            ]
        )

        self.assertEqual(report["issues"][0]["code"], "case_unicode_collision")

    def test_invalid_inventory_is_rejected_before_the_audit(self):
        with self.assertRaises(InvalidInventoryError):
            audit_path_portability([{"path": "missing-fields"}])

    def test_cli_prints_a_failed_audit_and_returns_one(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "inventory.json"
            inventory.write_text(
                json.dumps([entry("CON.txt")]),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = main([str(inventory)])

            report = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 1)
            self.assertFalse(report["passed"])
            self.assertEqual(report["issues"][0]["code"], "windows_reserved_name")

    def test_cli_writes_a_passing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory.json"
            output = root / "report.json"
            inventory.write_text(
                json.dumps([entry("src/module.py")]),
                encoding="utf-8",
            )

            exit_code = main(
                [str(inventory), "--output", str(output)]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["passed"])

    def test_cli_returns_two_for_invalid_inventory_json(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "inventory.json"
            inventory.write_text("{", encoding="utf-8")

            with contextlib.redirect_stderr(io.StringIO()):
                exit_code = main([str(inventory)])

            self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
