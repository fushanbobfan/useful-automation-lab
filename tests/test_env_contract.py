import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from useful_automation_lab.env_contract import (
    InvalidEnvContractError,
    audit_env_contract,
    load_env_contract,
    main,
    normalize_env_contract,
    parse_env_file,
)


def contract(**overrides):
    value = {
        "version": 1,
        "required_keys": ["SERVICE_URL", "LOG_LEVEL"],
        "optional_keys": ["CACHE_URL"],
        "non_empty_keys": ["SERVICE_URL", "LOG_LEVEL"],
        "allowed_prefixes": ["FEATURE_"],
    }
    value.update(overrides)
    return value


class EnvContractTests(unittest.TestCase):
    def test_passes_without_copying_environment_values(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = Path(directory) / ".env"
            environment.write_text(
                "SERVICE_URL=https://service.invalid\n"
                "LOG_LEVEL=super-secret-value\n"
                "CACHE_URL=\n"
                "FEATURE_FAST=true\n",
                encoding="utf-8",
            )
            entries = parse_env_file(environment)

        report = audit_env_contract(contract(), entries)
        rendered = json.dumps(report)

        self.assertTrue(report["passed"])
        self.assertEqual(report["summary"]["allowed_prefix_key_count"], 1)
        self.assertNotIn("https://service.invalid", rendered)
        self.assertNotIn("super-secret-value", rendered)

    def test_reports_missing_blank_and_extra_keys_with_bounded_details(self):
        entries = {
            "LOG_LEVEL": {"line": 1, "blank": True},
            "UNDECLARED_A": {"line": 2, "blank": False},
            "UNDECLARED_B": {"line": 3, "blank": False},
        }

        report = audit_env_contract(contract(), entries, max_details=2)

        self.assertFalse(report["passed"])
        self.assertEqual(report["summary"]["missing_required_key_count"], 1)
        self.assertEqual(report["summary"]["blank_non_empty_key_count"], 1)
        self.assertEqual(report["summary"]["extra_key_count"], 2)
        self.assertEqual(report["summary"]["violation_count"], 4)
        self.assertEqual(len(report["violations"]), 2)
        self.assertTrue(report["details_truncated"])

    def test_extra_key_budget_can_pass_without_hiding_count(self):
        entries = {
            "SERVICE_URL": {"line": 1, "blank": False},
            "LOG_LEVEL": {"line": 2, "blank": False},
            "LOCAL_OVERRIDE": {"line": 3, "blank": False},
        }

        report = audit_env_contract(contract(), entries, max_extra_keys=1)

        self.assertTrue(report["passed"])
        self.assertEqual(report["summary"]["extra_key_count"], 1)

    def test_contract_validation_rejects_ambiguous_schemas(self):
        invalid = [
            {"version": 2},
            {"version": 1, "unknown": []},
            contract(optional_keys=["SERVICE_URL"]),
            contract(non_empty_keys=["NOT_DECLARED"]),
            contract(required_keys=["BAD-NAME"]),
            contract(required_keys=[{}]),
        ]

        for value in invalid:
            with self.subTest(value=value), self.assertRaises(
                InvalidEnvContractError
            ):
                normalize_env_contract(value)

    def test_parser_rejects_duplicate_and_malformed_assignments(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = Path(directory) / ".env"
            for contents in (
                "KEY=one\nKEY=two\n",
                "NOT_AN_ASSIGNMENT\n",
                "BAD KEY=value\n",
            ):
                environment.write_text(contents, encoding="utf-8")
                with self.subTest(contents=contents), self.assertRaises(ValueError):
                    parse_env_file(environment)

    def test_loader_enforces_bounded_valid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract()), encoding="utf-8")
            self.assertEqual(load_env_contract(path)["version"], 1)

            with self.assertRaisesRegex(ValueError, "exceeds"):
                load_env_contract(path, max_file_bytes=4)
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(InvalidEnvContractError):
                load_env_contract(path)

    def test_cli_returns_zero_or_one_with_key_only_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = root / "contract.json"
            environment = root / ".env"
            contract_path.write_text(json.dumps(contract()), encoding="utf-8")
            environment.write_text(
                "SERVICE_URL=https://service.invalid\nLOG_LEVEL=info\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = main([str(contract_path), str(environment)])
            self.assertEqual(exit_code, 0)
            self.assertNotIn("https://service.invalid", stdout.getvalue())

            environment.write_text("LOG_LEVEL=\nEXTRA=value\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = main([str(contract_path), str(environment)])
            self.assertEqual(exit_code, 1)

    def test_cli_refuses_to_overwrite_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = root / "contract.json"
            environment = root / ".env"
            contract_contents = json.dumps(contract())
            environment_contents = "SERVICE_URL=url\nLOG_LEVEL=info\n"
            contract_path.write_text(contract_contents, encoding="utf-8")
            environment.write_text(environment_contents, encoding="utf-8")

            for output in (contract_path, environment):
                with self.subTest(output=output), contextlib.redirect_stderr(
                    io.StringIO()
                ):
                    exit_code = main(
                        [str(contract_path), str(environment), "--output", str(output)]
                    )
                self.assertEqual(exit_code, 2)
            self.assertEqual(
                contract_path.read_text(encoding="utf-8"), contract_contents
            )
            self.assertEqual(
                environment.read_text(encoding="utf-8"), environment_contents
            )


if __name__ == "__main__":
    unittest.main()
