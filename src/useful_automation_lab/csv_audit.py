"""Audit CSV structure and column rules without changing the source file."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any


SUPPORTED_TYPES = ("boolean", "date", "integer", "number")


def _column_names(name: str, values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a sequence of column names")
    validated = []
    for value in values:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must contain non-empty strings")
        if value in validated:
            raise ValueError(f"{name} must not contain duplicates")
        validated.append(value)
    return tuple(validated)


def _positive_integer(name: str, value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _column_type_rules(value: Mapping[str, str] | None) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("column_types must be a mapping")
    rules = {}
    for column, type_name in value.items():
        if not isinstance(column, str) or not column:
            raise ValueError("column_types keys must be non-empty strings")
        if type_name not in SUPPORTED_TYPES:
            raise ValueError(
                "column_types values must be boolean, date, integer, or number"
            )
        rules[column] = type_name
    return rules


def _matches_type(value: str, type_name: str) -> bool:
    if type_name == "integer":
        return re.fullmatch(r"[+-]?[0-9]+", value) is not None
    if type_name == "number":
        try:
            number = float(value)
        except ValueError:
            return False
        return math.isfinite(number)
    if type_name == "boolean":
        return value in {"true", "false"}
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def audit_csv(
    lines: Iterable[str],
    *,
    required_columns: Sequence[str] = (),
    not_empty_columns: Sequence[str] = (),
    unique_column: str | None = None,
    column_types: Mapping[str, str] | None = None,
    max_field_bytes: int | None = None,
    max_errors: int = 100,
) -> dict[str, Any]:
    """Return a bounded report for one RFC 4180-style CSV stream."""

    required = _column_names("required_columns", required_columns)
    not_empty = _column_names("not_empty_columns", not_empty_columns)
    if unique_column is not None and (
        not isinstance(unique_column, str) or not unique_column
    ):
        raise ValueError("unique_column must be a non-empty string")
    types = _column_type_rules(column_types)
    maximum_field_bytes = _positive_integer("max_field_bytes", max_field_bytes)
    maximum_errors = _positive_integer("max_errors", max_errors)
    assert maximum_errors is not None

    issues = []
    issue_count = 0
    issue_codes: Counter[str] = Counter()
    header: list[str] = []
    header_valid = False
    data_rows = 0
    valid_rows = 0
    invalid_rows = 0
    blank_rows = 0
    duplicate_rows = 0
    maximum_observed_field_bytes = 0
    stopped_early = False

    def add_issue(code: str, **details: Any) -> None:
        nonlocal issue_count
        issue_count += 1
        issue_codes[code] += 1
        if len(issues) < maximum_errors:
            issues.append({"code": code, **details})

    reader = csv.reader(lines, strict=True)
    try:
        header = next(reader)
    except StopIteration:
        add_issue("missing_header")
    except (csv.Error, TypeError) as error:
        add_issue("csv_parse_error", line=reader.line_num or 1, message=str(error))
        stopped_early = True

    if header:
        empty_columns = [index for index, value in enumerate(header, start=1) if not value]
        if empty_columns:
            add_issue("empty_header_columns", columns=empty_columns)
        duplicates = []
        seen_columns = set()
        for value in header:
            if value in seen_columns and value not in duplicates:
                duplicates.append(value)
            seen_columns.add(value)
        if duplicates:
            add_issue("duplicate_header_columns", columns=duplicates)
        missing_required = [column for column in required if column not in header]
        if missing_required:
            add_issue("missing_required_columns", columns=missing_required)
        configured_columns = list(not_empty) + list(types)
        if unique_column is not None:
            configured_columns.append(unique_column)
        missing_rules = []
        for column in configured_columns:
            if column not in header and column not in missing_rules:
                missing_rules.append(column)
        if missing_rules:
            add_issue("missing_rule_columns", columns=missing_rules)
        header_valid = issue_count == 0
    elif not stopped_early and issue_count == 0:
        add_issue("missing_header")

    indexes = {column: header.index(column) for column in set(header)}
    seen_unique_values: dict[str, int] = {}
    if header and not stopped_early:
        while True:
            try:
                row = next(reader)
            except StopIteration:
                break
            except (csv.Error, TypeError) as error:
                add_issue(
                    "csv_parse_error",
                    line=reader.line_num,
                    message=str(error),
                )
                stopped_early = True
                break

            data_rows += 1
            line = reader.line_num
            if not row:
                blank_rows += 1
                invalid_rows += 1
                add_issue("blank_row", line=line)
                continue
            if len(row) != len(header):
                invalid_rows += 1
                add_issue(
                    "row_width",
                    line=line,
                    expected_fields=len(header),
                    actual_fields=len(row),
                )
                continue

            row_has_issue = False
            for index, value in enumerate(row):
                field_bytes = len(value.encode("utf-8"))
                maximum_observed_field_bytes = max(
                    maximum_observed_field_bytes, field_bytes
                )
                if (
                    maximum_field_bytes is not None
                    and field_bytes > maximum_field_bytes
                ):
                    row_has_issue = True
                    add_issue(
                        "field_too_large",
                        line=line,
                        column=header[index],
                        actual_bytes=field_bytes,
                        maximum_bytes=maximum_field_bytes,
                    )

            empty_required_values = [
                column for column in not_empty if column in indexes and not row[indexes[column]]
            ]
            if empty_required_values:
                row_has_issue = True
                add_issue(
                    "empty_required_values",
                    line=line,
                    columns=empty_required_values,
                )

            if unique_column is not None and unique_column in indexes:
                value = row[indexes[unique_column]]
                if value in seen_unique_values:
                    row_has_issue = True
                    duplicate_rows += 1
                    add_issue(
                        "duplicate_unique_value",
                        line=line,
                        column=unique_column,
                        first_line=seen_unique_values[value],
                    )
                else:
                    seen_unique_values[value] = line

            for column, type_name in sorted(types.items()):
                if column not in indexes:
                    continue
                value = row[indexes[column]]
                if value and not _matches_type(value, type_name):
                    row_has_issue = True
                    add_issue(
                        "invalid_type",
                        line=line,
                        column=column,
                        expected_type=type_name,
                    )

            if row_has_issue:
                invalid_rows += 1
            else:
                valid_rows += 1

    return {
        "passed": issue_count == 0,
        "header": header,
        "summary": {
            "header_valid": header_valid,
            "physical_lines_read": reader.line_num,
            "data_rows": data_rows,
            "valid_rows": valid_rows,
            "invalid_rows": invalid_rows,
            "blank_rows": blank_rows,
            "duplicate_rows": duplicate_rows,
            "maximum_field_bytes": maximum_observed_field_bytes,
            "stopped_early": stopped_early,
            "issue_count": issue_count,
            "reported_issues": len(issues),
            "truncated_issues": issue_count - len(issues),
            "issue_codes": dict(sorted(issue_codes.items())),
        },
        "configuration": {
            "required_columns": list(required),
            "not_empty_columns": list(not_empty),
            "unique_column": unique_column,
            "column_types": dict(sorted(types.items())),
            "max_field_bytes": maximum_field_bytes,
            "max_errors": maximum_errors,
        },
        "issues": issues,
    }


def _parse_type_rules(values: Sequence[str]) -> dict[str, str]:
    rules = {}
    for value in values:
        column, separator, type_name = value.partition("=")
        if not separator or not column or type_name not in SUPPORTED_TYPES:
            raise ValueError(
                "type rules must use COLUMN=boolean|date|integer|number"
            )
        if column in rules:
            raise ValueError("type rules must not repeat a column")
        rules[column] = type_name
    return rules


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--require", action="append", default=[])
    parser.add_argument("--not-empty", action="append", default=[])
    parser.add_argument("--unique-column")
    parser.add_argument(
        "--type",
        action="append",
        default=[],
        dest="type_rules",
        metavar="COLUMN=TYPE",
    )
    parser.add_argument("--max-field-bytes", type=int)
    parser.add_argument("--max-errors", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        with args.dataset.open(newline="", encoding="utf-8-sig") as handle:
            report = audit_csv(
                handle,
                required_columns=args.require,
                not_empty_columns=args.not_empty,
                unique_column=args.unique_column,
                column_types=_parse_type_rules(args.type_rules),
                max_field_bytes=args.max_field_bytes,
                max_errors=args.max_errors,
            )
        rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
    except (OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
