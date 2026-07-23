"""Audit SQLite health and schema metadata through a read-only connection."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _pragma_scalar(connection: sqlite3.Connection, name: str) -> Any:
    row = connection.execute(f"PRAGMA {name}").fetchone()
    if row is None:
        raise ValueError(f"PRAGMA {name} returned no value")
    return row[0]


def audit_sqlite(database: Path, *, max_errors: int = 100) -> dict[str, Any]:
    """Return bounded integrity, foreign-key, and schema diagnostics."""

    if isinstance(max_errors, bool) or not isinstance(max_errors, int) or max_errors <= 0:
        raise ValueError("max_errors must be a positive integer")
    database_path = Path(database)
    resolved = database_path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("database must be a regular file")

    issues = []
    issue_count = 0
    issue_codes: Counter[str] = Counter()

    def add_issue(code: str, **details: Any) -> None:
        nonlocal issue_count
        issue_count += 1
        issue_codes[code] += 1
        if len(issues) < max_errors:
            issues.append({"code": code, **details})

    connection = sqlite3.connect(
        f"{resolved.as_uri()}?mode=ro",
        uri=True,
        timeout=5.0,
    )
    try:
        connection.enable_load_extension(False)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA trusted_schema = OFF")

        quick_check_rows = [
            str(row[0])
            for row in connection.execute(f"PRAGMA quick_check({max_errors + 1})")
        ]
        quick_check_ok = quick_check_rows == ["ok"]
        if not quick_check_ok:
            for message in quick_check_rows:
                add_issue("quick_check_failed", message=message)

        schema_rows = connection.execute(
            "SELECT type, name, tbl_name FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        object_type_counts = Counter(str(row[0]) for row in schema_rows)
        table_names = [str(row[1]) for row in schema_rows if row[0] == "table"]
        tables = []
        for table_name in table_names:
            columns = connection.execute(
                "SELECT * FROM pragma_table_xinfo(?) ORDER BY cid",
                (table_name,),
            ).fetchall()
            foreign_keys = connection.execute(
                "SELECT * FROM pragma_foreign_key_list(?)",
                (table_name,),
            ).fetchall()
            index_count = connection.execute(
                "SELECT COUNT(*) FROM pragma_index_list(?)",
                (table_name,),
            ).fetchone()[0]
            tables.append(
                {
                    "name": table_name,
                    "column_count": len(columns),
                    "hidden_column_count": sum(
                        int(column[6] != 0) for column in columns
                    ),
                    "not_null_column_count": sum(
                        int(column[3] != 0) for column in columns
                    ),
                    "primary_key_column_count": sum(
                        int(column[5] != 0) for column in columns
                    ),
                    "foreign_key_count": len(foreign_keys),
                    "index_count": int(index_count),
                }
            )

        for table, row_id, parent, constraint_index in connection.execute(
            "PRAGMA foreign_key_check"
        ):
            add_issue(
                "foreign_key_violation",
                table=str(table),
                row_id=row_id,
                parent_table=str(parent),
                constraint_index=int(constraint_index),
            )

        page_count = int(_pragma_scalar(connection, "page_count"))
        freelist_count = int(_pragma_scalar(connection, "freelist_count"))
        summary = {
            "file_size_bytes": resolved.stat().st_size,
            "page_size_bytes": int(_pragma_scalar(connection, "page_size")),
            "page_count": page_count,
            "freelist_count": freelist_count,
            "freelist_ratio": (
                freelist_count / page_count if page_count else 0.0
            ),
            "user_version": int(_pragma_scalar(connection, "user_version")),
            "application_id": int(_pragma_scalar(connection, "application_id")),
            "encoding": str(_pragma_scalar(connection, "encoding")),
            "object_count": len(schema_rows),
            "object_type_counts": dict(sorted(object_type_counts.items())),
            "table_count": len(table_names),
            "quick_check_ok": quick_check_ok,
            "issue_count": issue_count,
            "reported_issues": len(issues),
            "truncated_issues": issue_count - len(issues),
            "issue_codes": dict(sorted(issue_codes.items())),
        }
    finally:
        connection.close()

    return {
        "passed": issue_count == 0,
        "summary": summary,
        "configuration": {"max_errors": max_errors},
        "tables": tables,
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--max-errors", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.output is not None:
            same_path = args.output.resolve() == args.database.resolve()
            same_file = (
                args.output.exists() and args.output.samefile(args.database)
            )
            if same_path or same_file:
                raise ValueError("output must differ from the source database")
        report = audit_sqlite(args.database, max_errors=args.max_errors)
        rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
    except (sqlite3.DatabaseError, OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
