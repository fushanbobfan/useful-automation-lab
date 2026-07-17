import unittest

from useful_automation_lab.compare import InvalidInventoryError
from useful_automation_lab.policy import InvalidPolicyError, audit_inventory_policy


def entry(path: str, size: int, marker: str = "a") -> dict[str, str | int]:
    return {"path": path, "size": size, "sha256": marker * 64}


class ManifestPolicyTests(unittest.TestCase):
    inventory = [
        entry("README.md", 5),
        entry("data/large.bin", 200, "b"),
        entry("secrets/token.txt", 10, "c"),
    ]

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


if __name__ == "__main__":
    unittest.main()
