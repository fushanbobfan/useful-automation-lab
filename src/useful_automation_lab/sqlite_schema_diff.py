"""Compare two SQLite schemas without reading application rows."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any


def _open_read_only(database: Path) -> sqlite3.Connection:
    resolved = Path(database).resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("database must be a regular file")
    connection = sqlite3.connect(
        f"{resolved.as_uri()}?mode=ro",
        uri=True,
        timeout=5.0,
    )
    connection.enable_load_extension(False)
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA trusted_schema = OFF")
    return connection


def _foreign_keys(
    connection: sqlite3.Connection,
    table_name: str,
) -> list[dict[str, Any]]:
    grouped: dict[int, list[tuple[Any, ...]]] = defaultdict(list)
    for row in connection.execute(
        "SELECT id, seq, \"table\", \"from\", \"to\", on_update, on_delete, "
        "match FROM pragma_foreign_key_list(?) ORDER BY id, seq",
        (table_name,),
    ):
        grouped[int(row[0])].append(row)

    constraints = []
    for rows in grouped.values():
        first = rows[0]
        constraints.append(
            {
                "referenced_table": str(first[2]),
                "columns": [
                    {"from": str(row[3]), "to": str(row[4])} for row in rows
                ],
                "on_update": str(first[5]),
                "on_delete": str(first[6]),
                "match": str(first[7]),
            }
        )
    return sorted(
        constraints,
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
    )


def _indexes(
    connection: sqlite3.Connection,
    table_name: str,
) -> list[dict[str, Any]]:
    indexes = []
    for _, index_name, unique, origin, partial in connection.execute(
        "SELECT seq, name, \"unique\", origin, partial "
        "FROM pragma_index_list(?) ORDER BY name",
        (table_name,),
    ):
        columns = []
        for _, cid, column_name, descending, collation, key_column in connection.execute(
            "SELECT seqno, cid, name, \"desc\", coll, key "
            "FROM pragma_index_xinfo(?) ORDER BY seqno",
            (index_name,),
        ):
            columns.append(
                {
                    "column": column_name,
                    "column_id": int(cid),
                    "descending": bool(descending),
                    "collation": collation,
                    "key": bool(key_column),
                }
            )
        indexes.append(
            {
                "name": str(index_name),
                "unique": bool(unique),
                "origin": str(origin),
                "partial": bool(partial),
                "columns": columns,
            }
        )
    return indexes


def _snapshot_schema(database: Path) -> dict[str, dict[str, Any]]:
    connection = _open_read_only(database)
    try:
        options = {
            str(name): {"without_rowid": bool(without_rowid), "strict": bool(strict)}
            for name, without_rowid, strict in connection.execute(
                "SELECT name, wr, strict FROM pragma_table_list "
                "WHERE schema = 'main' AND type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        }
        tables: dict[str, dict[str, Any]] = {}
        for table_name in sorted(options):
            columns = [
                {
                    "name": str(name),
                    "type": str(column_type),
                    "not_null": bool(not_null),
                    "default_value": default_value,
                    "primary_key_position": int(primary_key_position),
                    "hidden": int(hidden),
                }
                for _, name, column_type, not_null, default_value, primary_key_position, hidden
                in connection.execute(
                    "SELECT cid, name, type, \"notnull\", dflt_value, pk, hidden "
                    "FROM pragma_table_xinfo(?) ORDER BY cid",
                    (table_name,),
                )
            ]
            tables[table_name] = {
                "options": options[table_name],
                "columns": columns,
                "indexes": _indexes(connection, table_name),
                "foreign_keys": _foreign_keys(connection, table_name),
            }
        return tables
    finally:
        connection.close()


def _by_name(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["name"]): item for item in items}


def compare_sqlite_schemas(
    reference: Path,
    candidate: Path,
    *,
    max_changes: int = 0,
    max_details: int = 100,
) -> dict[str, Any]:
    """Return a deterministic, bounded structural diff for two databases."""

    for name, value in {"max_changes": max_changes, "max_details": max_details}.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")

    reference_schema = _snapshot_schema(reference)
    candidate_schema = _snapshot_schema(candidate)
    reference_tables = set(reference_schema)
    candidate_tables = set(candidate_schema)
    changes: list[dict[str, Any]] = []
    changed_tables: set[str] = set()
    category_counts: dict[str, int] = defaultdict(int)

    def add_change(kind: str, table: str, **details: Any) -> None:
        category_counts[kind] += 1
        changed_tables.add(table)
        changes.append({"kind": kind, "table": table, **details})

    for table in sorted(reference_tables - candidate_tables):
        add_change("table_removed", table, schema=reference_schema[table])
    for table in sorted(candidate_tables - reference_tables):
        add_change("table_added", table, schema=candidate_schema[table])

    for table in sorted(reference_tables & candidate_tables):
        before = reference_schema[table]
        after = candidate_schema[table]
        if before["options"] != after["options"]:
            add_change(
                "table_options_changed",
                table,
                before=before["options"],
                after=after["options"],
            )

        before_columns = _by_name(before["columns"])
        after_columns = _by_name(after["columns"])
        for column in sorted(before_columns.keys() - after_columns.keys()):
            add_change("column_removed", table, column=before_columns[column])
        for column in sorted(after_columns.keys() - before_columns.keys()):
            add_change("column_added", table, column=after_columns[column])
        for column in sorted(before_columns.keys() & after_columns.keys()):
            if before_columns[column] != after_columns[column]:
                add_change(
                    "column_changed",
                    table,
                    column=column,
                    before=before_columns[column],
                    after=after_columns[column],
                )
        before_order = [item["name"] for item in before["columns"]]
        after_order = [item["name"] for item in after["columns"]]
        if set(before_order) == set(after_order) and before_order != after_order:
            add_change(
                "column_order_changed",
                table,
                before=before_order,
                after=after_order,
            )

        before_indexes = _by_name(before["indexes"])
        after_indexes = _by_name(after["indexes"])
        for index in sorted(before_indexes.keys() - after_indexes.keys()):
            add_change("index_removed", table, index=before_indexes[index])
        for index in sorted(after_indexes.keys() - before_indexes.keys()):
            add_change("index_added", table, index=after_indexes[index])
        for index in sorted(before_indexes.keys() & after_indexes.keys()):
            if before_indexes[index] != after_indexes[index]:
                add_change(
                    "index_changed",
                    table,
                    index=index,
                    before=before_indexes[index],
                    after=after_indexes[index],
                )

        before_foreign_keys = {
            json.dumps(item, sort_keys=True, separators=(",", ":")): item
            for item in before["foreign_keys"]
        }
        after_foreign_keys = {
            json.dumps(item, sort_keys=True, separators=(",", ":")): item
            for item in after["foreign_keys"]
        }
        for key in sorted(before_foreign_keys.keys() - after_foreign_keys.keys()):
            add_change(
                "foreign_key_removed",
                table,
                foreign_key=before_foreign_keys[key],
            )
        for key in sorted(after_foreign_keys.keys() - before_foreign_keys.keys()):
            add_change(
                "foreign_key_added",
                table,
                foreign_key=after_foreign_keys[key],
            )

    change_count = len(changes)
    return {
        "passed": change_count <= max_changes,
        "summary": {
            "reference_table_count": len(reference_schema),
            "candidate_table_count": len(candidate_schema),
            "changed_table_count": len(changed_tables),
            "change_count": change_count,
            "reported_changes": min(change_count, max_details),
            "truncated_changes": max(0, change_count - max_details),
            "change_kinds": dict(sorted(category_counts.items())),
        },
        "thresholds": {"max_changes": max_changes},
        "changes": changes[:max_details],
        "configuration": {"max_details": max_details},
    }
