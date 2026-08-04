"""Create two small SQLite databases for the schema-diff example."""

from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    reference = args.output_directory / "schema-reference.sqlite"
    candidate = args.output_directory / "schema-candidate.sqlite"
    if reference.exists() or candidate.exists():
        raise SystemExit("refusing to overwrite an existing demo database")

    with closing(sqlite3.connect(reference)) as connection:
        connection.execute(
            "CREATE TABLE jobs (id INTEGER PRIMARY KEY, state TEXT NOT NULL)"
        )
        connection.execute("CREATE INDEX jobs_state ON jobs(state)")
        connection.commit()

    with closing(sqlite3.connect(candidate)) as connection:
        connection.execute(
            "CREATE TABLE jobs ("
            "id INTEGER PRIMARY KEY, state TEXT NOT NULL, attempts INTEGER DEFAULT 0)"
        )
        connection.execute("CREATE INDEX jobs_state ON jobs(state)")
        connection.commit()

    print(reference)
    print(candidate)


if __name__ == "__main__":
    main()
