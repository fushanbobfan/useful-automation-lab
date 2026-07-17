import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import useful_automation_lab
from useful_automation_lab.compare import InvalidInventoryError
from useful_automation_lab.policy import (
    InvalidPolicyError,
    audit_inventory_policy,
    main,
)


def entry(path: str, size: int, marker: str = "a") -> dict[str, str | int]:
    return {"path": path, "size": size, "sha256": marker * 64}


class ManifestPolicyTests(unittest.TestCase):
    inventory = [
        entry("README.md", 5),
        entry("data/large.bin", 200, "b"),
        entry("secrets/token.txt", 10, "c"),
    ]

    def test_policy_api_is_available_from_package(self):
        self.assertIs(
            useful_automation_lab.audit_inventory_policy, audit_inventory_policy
        )
        self.assertIs(useful_automation_lab.InvalidPolicyError, InvalidPolicyError)

    def test_passing_policy_reports_inventory_totals(self):
        report = audit_inventory_policy(
            self.inventory,
            {
                "version": 1,
                "max_files": 3,
                "max_total_bytes": 215,
                "max_file_bytes": 200,
                "required_paths": ["README.md"],
                "forbidden_patterns": ["*.tmp"],
            },
        )

        self.assertTrue(report["passed"])
        self.assertEqual(
            report["summary"],
            {
                "files": 3,
                "total_bytes": 215,
                "largest_file_bytes": 200,
                "violations": 0,
            },
        )

    def test_all_violations_are_reported_in_deterministic_order(self):
        report = audit_inventory_policy(
            self.inventory,
            {
                "version": 1,
                "max_files": 2,
                "max_total_bytes": 100,
                "max_file_bytes": 50,
                "required_paths": ["LICENSE", "README.md"],
                "forbidden_patterns": ["secrets", "*.bin"],
            },
        )

        self.assertFalse(report["passed"])
        self.assertEqual(
            [violation["rule"] for violation in report["violations"]],
            [
                "max_files",
                "max_total_bytes",
                "max_file_bytes",
                "required_path",
                "forbidden_pattern",
                "forbidden_pattern",
            ],
        )
        self.assertEqual(
            report["violations"][2]["offending_files"],
            [{"path": "data/large.bin", "size": 200}],
        )
        self.assertEqual(report["violations"][3]["path"], "LICENSE")
        self.assertEqual(report["violations"][4]["path"], "data/large.bin")
        self.assertEqual(report["violations"][5]["path"], "secrets/token.txt")

    def test_invalid_policy_schema_is_rejected(self):
        invalid = [
            [],
            {},
            {"version": 2},
            {"version": 1, "max_files": -1},
            {"version": 1, "unknown": 1},
            {"version": 1, "required_paths": ["*.txt"]},
            {"version": 1, "required_paths": ["../outside"]},
            {"version": 1, "forbidden_patterns": ["../outside"]},
            {"version": 1, "forbidden_patterns": ["*.tmp", "*.tmp"]},
        ]
        for policy in invalid:
            with self.subTest(policy=policy):
                with self.assertRaises(InvalidPolicyError):
                    audit_inventory_policy(self.inventory, policy)

    def test_invalid_inventory_is_rejected_before_policy_audit(self):
        with self.assertRaises(InvalidInventoryError):
            audit_inventory_policy([{"path": "missing-fields"}], {"version": 1})

    def test_cli_writes_a_passing_policy_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory.json"
            policy = root / "policy.json"
            output = root / "report.json"
            inventory.write_text(json.dumps(self.inventory), encoding="utf-8")
            policy.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "max_files": 3,
                        "required_paths": ["README.md"],
                    }
                ),
                encoding="utf-8",
            )

            exit_code = main([str(inventory), str(policy), "--output", str(output)])

            self.assertEqual(exit_code, 0)
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["passed"])

    def test_cli_returns_one_and_prints_policy_violations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory.json"
            policy = root / "policy.json"
            inventory.write_text(json.dumps(self.inventory), encoding="utf-8")
            policy.write_text(
                json.dumps({"version": 1, "max_files": 1}), encoding="utf-8"
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = main([str(inventory), str(policy)])

            self.assertEqual(exit_code, 1)
            self.assertEqual(
                json.loads(stdout.getvalue())["violations"][0]["rule"], "max_files"
            )

    def test_cli_returns_two_for_invalid_policy_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory.json"
            policy = root / "policy.json"
            inventory.write_text(json.dumps(self.inventory), encoding="utf-8")
            policy.write_text("{", encoding="utf-8")

            with contextlib.redirect_stderr(io.StringIO()):
                exit_code = main([str(inventory), str(policy)])

            self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
