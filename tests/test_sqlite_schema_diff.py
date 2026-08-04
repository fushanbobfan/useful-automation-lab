import hashlib
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import useful_automation_lab
from useful_automation_lab.sqlite_schema_diff import compare_sqlite_schemas, main


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_reference(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE events ("
            "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, "
            "FOREIGN KEY (user_id) REFERENCES users(id))"
        )
        connection.execute("CREATE INDEX events_user ON events(user_id)")
        connection.execute("CREATE TABLE legacy (id INTEGER PRIMARY KEY)")
        connection.commit()


def _create_candidate(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE users ("
            "id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, "
            "status TEXT DEFAULT 'active')"
        )
        connection.execute(
            "CREATE TABLE events ("
            "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, "
            "FOREIGN KEY (user_id) REFERENCES users(id))"
        )
        connection.execute("CREATE UNIQUE INDEX events_user ON events(user_id)")
        connection.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY)")
        connection.commit()


class SqliteSchemaDiffTests(unittest.TestCase):
    def test_reports_stable_table_column_and_index_changes_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.sqlite"
            candidate = Path(directory) / "candidate.sqlite"
            _create_reference(reference)
            _create_candidate(candidate)
            before = (_digest(reference), _digest(candidate))

            report = compare_sqlite_schemas(
                reference,
                candidate,
                max_changes=10,
            )

            self.assertTrue(report["passed"])
            self.assertIs(
                useful_automation_lab.compare_sqlite_schemas,
                compare_sqlite_schemas,
            )
            self.assertEqual(report["summary"]["reference_table_count"], 3)
            self.assertEqual(report["summary"]["candidate_table_count"], 3)
            self.assertEqual(report["summary"]["changed_table_count"], 4)
            self.assertEqual(report["summary"]["change_count"], 6)
            self.assertEqual(
                [change["kind"] for change in report["changes"]],
                [
                    "table_removed",
                    "table_added",
                    "index_changed",
                    "column_removed",
                    "column_added",
                    "column_added",
                ],
            )
            self.assertEqual((_digest(reference), _digest(candidate)), before)

    def test_identical_schemas_pass_a_zero_change_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.sqlite"
            candidate = Path(directory) / "candidate.sqlite"
            _create_reference(reference)
            _create_reference(candidate)

            report = compare_sqlite_schemas(reference, candidate)

            self.assertTrue(report["passed"])
            self.assertEqual(report["summary"]["change_count"], 0)
            self.assertEqual(report["changes"], [])

    def test_details_are_bounded_but_total_counts_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.sqlite"
            candidate = Path(directory) / "candidate.sqlite"
            _create_reference(reference)
            _create_candidate(candidate)

            report = compare_sqlite_schemas(
                reference,
                candidate,
                max_changes=0,
                max_details=2,
            )

            self.assertFalse(report["passed"])
            self.assertEqual(report["summary"]["change_count"], 6)
            self.assertEqual(report["summary"]["reported_changes"], 2)
            self.assertEqual(report["summary"]["truncated_changes"], 4)
            self.assertEqual(len(report["changes"]), 2)

    def test_foreign_key_targets_are_compared_structurally(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.sqlite"
            candidate = Path(directory) / "candidate.sqlite"
            for database, target in (
                (reference, "parent_a"),
                (candidate, "parent_b"),
            ):
                with closing(sqlite3.connect(database)) as connection:
                    connection.execute("CREATE TABLE parent_a (id INTEGER PRIMARY KEY)")
                    connection.execute("CREATE TABLE parent_b (id INTEGER PRIMARY KEY)")
                    connection.execute(
                        "CREATE TABLE child ("
                        "parent_id INTEGER, "
                        f"FOREIGN KEY (parent_id) REFERENCES {target}(id))"
                    )
                    connection.commit()

            report = compare_sqlite_schemas(
                reference,
                candidate,
                max_changes=2,
            )

            self.assertTrue(report["passed"])
            self.assertEqual(report["summary"]["change_count"], 2)
            self.assertEqual(
                [change["kind"] for change in report["changes"]],
                ["foreign_key_removed", "foreign_key_added"],
            )
            self.assertEqual(
                report["changes"][1]["foreign_key"]["referenced_table"],
                "parent_b",
            )

    def test_invalid_paths_and_configuration_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.sqlite"
            _create_reference(reference)
            with self.assertRaises(FileNotFoundError):
                compare_sqlite_schemas(reference, Path(directory) / "missing.sqlite")
            with self.assertRaisesRegex(ValueError, "regular file"):
                compare_sqlite_schemas(reference, Path(directory))
            for option in (True, -1, 1.5):
                with self.subTest(option=option):
                    with self.assertRaisesRegex(ValueError, "non-negative integer"):
                        compare_sqlite_schemas(
                            reference,
                            reference,
                            max_details=option,
                        )

    def test_cli_writes_a_failed_report_and_accepts_a_change_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.sqlite"
            candidate = Path(directory) / "candidate.sqlite"
            output = Path(directory) / "diff.json"
            _create_reference(reference)
            _create_candidate(candidate)

            failed_exit = main(
                [str(reference), str(candidate), "--output", str(output)]
            )
            report = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(failed_exit, 1)
            self.assertFalse(report["passed"])
            with contextlib.redirect_stdout(io.StringIO()):
                passed_exit = main(
                    [str(reference), str(candidate), "--max-changes", "6"]
                )
            self.assertEqual(passed_exit, 0)

    def test_cli_rejects_invalid_database_and_output_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.sqlite"
            candidate = Path(directory) / "candidate.sqlite"
            _create_reference(reference)
            _create_candidate(candidate)

            before = _digest(reference)
            with contextlib.redirect_stderr(io.StringIO()):
                alias_exit = main(
                    [
                        str(reference),
                        str(candidate),
                        "--output",
                        str(reference),
                    ]
                )
            self.assertEqual(alias_exit, 2)
            self.assertEqual(_digest(reference), before)

            invalid = Path(directory) / "invalid.sqlite"
            invalid.write_text("not a database", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                invalid_exit = main([str(reference), str(invalid)])
            self.assertEqual(invalid_exit, 2)


if __name__ == "__main__":
    unittest.main()
