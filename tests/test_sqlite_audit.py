import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import useful_automation_lab
from useful_automation_lab.sqlite_audit import audit_sqlite


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SqliteAuditTests(unittest.TestCase):
    def test_sqlite_api_is_available_from_package(self):
        self.assertIs(useful_automation_lab.audit_sqlite, audit_sqlite)

    def test_valid_database_reports_schema_without_changing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "valid.sqlite"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("PRAGMA user_version = 7")
                connection.execute(
                    "CREATE TABLE parent (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE child ("
                    "id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL, "
                    "FOREIGN KEY (parent_id) REFERENCES parent(id))"
                )
                connection.execute("CREATE INDEX child_parent ON child(parent_id)")
                connection.execute("INSERT INTO parent VALUES (1, 'example')")
                connection.execute("INSERT INTO child VALUES (1, 1)")
                connection.commit()
            before = _digest(database)

            report = audit_sqlite(database)

            self.assertTrue(report["passed"])
            self.assertEqual(report["summary"]["user_version"], 7)
            self.assertEqual(report["summary"]["table_count"], 2)
            self.assertEqual(report["summary"]["object_type_counts"]["index"], 1)
            self.assertTrue(report["summary"]["quick_check_ok"])
            child = next(item for item in report["tables"] if item["name"] == "child")
            self.assertEqual(child["column_count"], 2)
            self.assertEqual(child["foreign_key_count"], 1)
            self.assertEqual(child["index_count"], 1)
            self.assertEqual(_digest(database), before)

    def test_foreign_key_violations_are_counted_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "violations.sqlite"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
                connection.execute(
                    "CREATE TABLE child ("
                    "id INTEGER PRIMARY KEY, parent_id INTEGER, "
                    "FOREIGN KEY (parent_id) REFERENCES parent(id))"
                )
                connection.executemany(
                    "INSERT INTO child VALUES (?, ?)",
                    [(1, 10), (2, 20), (3, 30)],
                )
                connection.commit()

            report = audit_sqlite(database, max_errors=2)

            self.assertFalse(report["passed"])
            self.assertEqual(report["summary"]["issue_count"], 3)
            self.assertEqual(report["summary"]["reported_issues"], 2)
            self.assertEqual(report["summary"]["truncated_issues"], 1)
            self.assertEqual(
                report["summary"]["issue_codes"],
                {"foreign_key_violation": 3},
            )
            self.assertEqual(
                [issue["row_id"] for issue in report["issues"]],
                [1, 2],
            )

    def test_invalid_paths_and_configuration_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            with self.assertRaisesRegex(ValueError, "regular file"):
                audit_sqlite(directory_path)
            with self.assertRaises(FileNotFoundError):
                audit_sqlite(directory_path / "missing.sqlite")
            database = directory_path / "empty.sqlite"
            sqlite3.connect(database).close()
            with self.assertRaisesRegex(ValueError, "positive integer"):
                audit_sqlite(database, max_errors=0)


if __name__ == "__main__":
    unittest.main()
