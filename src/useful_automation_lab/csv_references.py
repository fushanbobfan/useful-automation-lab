"""Audit composite references between parent and child CSV files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _columns(name: str, values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a sequence of column names")
    normalized = []
    for value in values:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must contain non-empty strings")
        if value in normalized:
            raise ValueError(f"{name} must not contain duplicates")
        normalized.append(value)
    if not normalized:
        raise ValueError(f"{name} must contain at least one column")
    return tuple(normalized)


def _non_negative_integer(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _rate(name: str, value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    return float(value)


def _key(
    record: Mapping[str, Any],
    columns: Sequence[str],
    *,
    location: str,
) -> tuple[str, ...]:
    missing = [column for column in columns if column not in record]
    if missing:
        raise ValueError(f"{location} is missing key columns {missing}")
    values = []
    for column in columns:
        value = record[column]
        if not isinstance(value, str):
            raise ValueError(f"{location} column {column!r} must be a string")
        values.append(value)
    return tuple(values)


def _fingerprint(key: tuple[str, ...]) -> str:
    canonical = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _bounded_rows(rows: Sequence[int], *, limit: int = 5) -> dict[str, Any]:
    return {
        "row_numbers": list(rows[:limit]),
        "row_numbers_truncated": len(rows) > limit,
        "omitted_row_number_count": max(0, len(rows) - limit),
    }


def audit_csv_references(
    parent_rows: Sequence[Mapping[str, Any]],
    child_rows: Sequence[Mapping[str, Any]],
    *,
    parent_key_columns: Sequence[str] = ("id",),
    child_key_columns: Sequence[str] = ("parent_id",),
    allow_empty_child_keys: bool = False,
    max_duplicate_parent_keys: int = 0,
    max_orphan_rate: float = 0.0,
    max_details: int = 50,
) -> dict[str, Any]:
    """Return privacy-minimizing CSV referential-integrity diagnostics."""
    if not parent_rows:
        raise ValueError("parent_rows must contain at least one row")
    if not child_rows:
        raise ValueError("child_rows must contain at least one row")
    parent_columns = _columns("parent_key_columns", parent_key_columns)
    child_columns = _columns("child_key_columns", child_key_columns)
    if len(parent_columns) != len(child_columns):
        raise ValueError("parent and child key columns must have the same length")
    if not isinstance(allow_empty_child_keys, bool):
        raise ValueError("allow_empty_child_keys must be a boolean")
    maximum_duplicates = _non_negative_integer(
        "max_duplicate_parent_keys", max_duplicate_parent_keys
    )
    maximum_orphan_rate = _rate("max_orphan_rate", max_orphan_rate)
    maximum_details = _non_negative_integer("max_details", max_details)

    parent_lines_by_key: dict[tuple[str, ...], list[int]] = {}
    for index, record in enumerate(parent_rows):
        if not isinstance(record, Mapping):
            raise ValueError(f"parent row {index + 2} must be an object")
        key = _key(record, parent_columns, location=f"parent row {index + 2}")
        if any(component == "" for component in key):
            raise ValueError(f"parent row {index + 2} key fields must be non-empty")
        parent_lines_by_key.setdefault(key, []).append(index + 2)

    child_lines_by_key: dict[tuple[str, ...], list[int]] = {}
    optional_empty_child_rows = 0
    for index, record in enumerate(child_rows):
        if not isinstance(record, Mapping):
            raise ValueError(f"child row {index + 2} must be an object")
        key = _key(record, child_columns, location=f"child row {index + 2}")
        if allow_empty_child_keys and all(component == "" for component in key):
            optional_empty_child_rows += 1
            continue
        child_lines_by_key.setdefault(key, []).append(index + 2)

    duplicate_groups = [
        (key, rows) for key, rows in parent_lines_by_key.items() if len(rows) > 1
    ]
    duplicate_groups.sort(key=lambda item: (-len(item[1]), _fingerprint(item[0])))
    orphan_groups = [
        (key, rows) for key, rows in child_lines_by_key.items() if key not in parent_lines_by_key
    ]
    orphan_groups.sort(key=lambda item: (-len(item[1]), _fingerprint(item[0])))

    checked_child_rows = sum(len(rows) for rows in child_lines_by_key.values())
    orphan_child_rows = sum(len(rows) for _, rows in orphan_groups)
    matched_child_rows = checked_child_rows - orphan_child_rows
    orphan_rate = orphan_child_rows / checked_child_rows if checked_child_rows else 0.0
    referenced_parent_keys = sum(
        key in child_lines_by_key for key in parent_lines_by_key
    )

    failures = []
    if len(duplicate_groups) > maximum_duplicates:
        failures.append(
            {
                "metric": "duplicate_parent_key_count",
                "actual": len(duplicate_groups),
                "maximum": maximum_duplicates,
                "excess": len(duplicate_groups) - maximum_duplicates,
            }
        )
    if orphan_rate > maximum_orphan_rate:
        failures.append(
            {
                "metric": "orphan_child_rate",
                "actual": orphan_rate,
                "maximum": maximum_orphan_rate,
                "excess": orphan_rate - maximum_orphan_rate,
                "orphan_child_row_count": orphan_child_rows,
            }
        )

    duplicate_details = [
        {
            "key_fingerprint": _fingerprint(key),
            "occurrence_count": len(rows),
            **_bounded_rows(rows),
        }
        for key, rows in duplicate_groups
    ]
    orphan_details = [
        {
            "key_fingerprint": _fingerprint(key),
            "child_row_count": len(rows),
            **_bounded_rows(rows),
        }
        for key, rows in orphan_groups
    ]
    return {
        "passed": not failures,
        "summary": {
            "parent_row_count": len(parent_rows),
            "child_row_count": len(child_rows),
            "parent_key_count": len(parent_lines_by_key),
            "duplicate_parent_key_count": len(duplicate_groups),
            "referenced_parent_key_count": referenced_parent_keys,
            "checked_child_row_count": checked_child_rows,
            "matched_child_row_count": matched_child_rows,
            "orphan_child_row_count": orphan_child_rows,
            "distinct_orphan_key_count": len(orphan_groups),
            "orphan_child_rate": orphan_rate,
            "optional_empty_child_row_count": optional_empty_child_rows,
        },
        "thresholds": {
            "max_duplicate_parent_keys": maximum_duplicates,
            "max_orphan_rate": maximum_orphan_rate,
        },
        "failures": failures,
        "duplicate_parent_keys": duplicate_details[:maximum_details],
        "orphan_child_keys": orphan_details[:maximum_details],
        "details_truncated": {
            "duplicate_parent_keys": len(duplicate_details) > maximum_details,
            "orphan_child_keys": len(orphan_details) > maximum_details,
        },
        "settings": {
            "parent_key_columns": list(parent_columns),
            "child_key_columns": list(child_columns),
            "allow_empty_child_keys": allow_empty_child_keys,
            "max_details": maximum_details,
            "raw_key_values_reported": False,
            "key_fingerprint_algorithm": "sha256-prefix-16",
        },
    }


def load_csv_rows(
    path: Path, *, max_file_bytes: int = 10 * 1024 * 1024
) -> list[dict[str, str]]:
    """Load a bounded, strict CSV as string-valued row mappings."""
    if (
        isinstance(max_file_bytes, bool)
        or not isinstance(max_file_bytes, int)
        or max_file_bytes <= 0
    ):
        raise ValueError("max_file_bytes must be a positive integer")
    with path.open("rb") as handle:
        data = handle.read(max_file_bytes + 1)
    if len(data) > max_file_bytes:
        raise ValueError(f"CSV exceeds max_file_bytes ({max_file_bytes})")

    reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
    try:
        header = next(reader)
    except StopIteration as error:
        raise ValueError("CSV must contain a header") from error
    if (
        not header
        or any(not column or column.strip() != column for column in header)
        or len(set(header)) != len(header)
    ):
        raise ValueError("CSV header columns must be unique, non-empty, and trimmed")

    rows = []
    try:
        for row in reader:
            if len(row) != len(header):
                raise ValueError(f"CSV row {reader.line_num} must match the header width")
            rows.append(dict(zip(header, row)))
    except csv.Error as error:
        raise ValueError(f"invalid CSV near row {reader.line_num}") from error
    if not rows:
        raise ValueError("CSV must contain at least one data row")
    return rows


def _paths_alias(first: Path, second: Path) -> bool:
    if first.resolve() == second.resolve():
        return True
    try:
        return first.samefile(second)
    except (FileNotFoundError, OSError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parents", type=Path)
    parser.add_argument("children", type=Path)
    parser.add_argument("--parent-key", action="append", dest="parent_keys")
    parser.add_argument("--child-key", action="append", dest="child_keys")
    parser.add_argument("--allow-empty-child-keys", action="store_true")
    parser.add_argument("--max-duplicate-parent-keys", type=int, default=0)
    parser.add_argument("--max-orphan-rate", type=float, default=0.0)
    parser.add_argument("--max-details", type=int, default=50)
    parser.add_argument("--max-file-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        if _paths_alias(args.parents, args.children):
            raise ValueError("parent and child inputs must be different files")
        if args.output is not None and (
            _paths_alias(args.parents, args.output)
            or _paths_alias(args.children, args.output)
        ):
            raise ValueError("output must not alias an input file")
        report = audit_csv_references(
            load_csv_rows(args.parents, max_file_bytes=args.max_file_bytes),
            load_csv_rows(args.children, max_file_bytes=args.max_file_bytes),
            parent_key_columns=args.parent_keys or ("id",),
            child_key_columns=args.child_keys or ("parent_id",),
            allow_empty_child_keys=args.allow_empty_child_keys,
            max_duplicate_parent_keys=args.max_duplicate_parent_keys,
            max_orphan_rate=args.max_orphan_rate,
            max_details=args.max_details,
        )
        rendered = json.dumps(report, indent=2) + "\n"
        if args.output is None:
            print(rendered, end="")
        else:
            args.output.write_text(rendered, encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
