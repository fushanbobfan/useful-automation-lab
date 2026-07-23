"""Create a small synthetic SQLite database for the audit example."""

from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    if args.output.exists():
        parser.error("output already exists")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(args.output)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "CREATE TABLE runs ("
            "id INTEGER PRIMARY KEY, started_on TEXT NOT NULL UNIQUE)"
        )
        connection.execute(
            "CREATE TABLE checks ("
            "id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, "
            "name TEXT NOT NULL, passed INTEGER NOT NULL, "
            "FOREIGN KEY (run_id) REFERENCES runs(id))"
        )
        connection.execute("CREATE INDEX checks_run_id ON checks(run_id)")
        connection.execute("INSERT INTO runs VALUES (1, '2026-01-01')")
        connection.executemany(
            "INSERT INTO checks VALUES (?, 1, ?, ?)",
            [(1, "schema", 1), (2, "sample", 1)],
        )
        connection.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
