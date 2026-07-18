"""Audit JSON Lines data without changing the source file."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any


class _DuplicateKeyError(ValueError):
    pass


class _InvalidConstantError(ValueError):
    pass


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKeyError(key)
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise _InvalidConstantError(value)


def _required_fields(fields: Sequence[str]) -> tuple[str, ...]:
    if isinstance(fields, (str, bytes)):
        raise ValueError("required_fields must be a sequence of field names")
    validated = []
    for field in fields:
        if not isinstance(field, str) or not field:
            raise ValueError("required_fields must contain non-empty strings")
        if field in validated:
            raise ValueError("required_fields must not contain duplicates")
        validated.append(field)
    return tuple(validated)


def _optional_positive_integer(name: str, value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def audit_jsonl(
    lines: Iterable[str],
    *,
    required_fields: Sequence[str] = (),
    unique_field: str | None = None,
    allow_blank_lines: bool = False,
    max_line_bytes: int | None = None,
    max_errors: int = 100,
) -> dict[str, Any]:
    """Return a bounded, deterministic data-quality report for JSON Lines text."""

    required = _required_fields(required_fields)
    if unique_field is not None and (
        not isinstance(unique_field, str) or not unique_field
    ):
        raise ValueError("unique_field must be a non-empty string")
    if not isinstance(allow_blank_lines, bool):
        raise ValueError("allow_blank_lines must be a boolean")
    maximum_bytes = _optional_positive_integer("max_line_bytes", max_line_bytes)
    maximum_errors = _optional_positive_integer("max_errors", max_errors)
    assert maximum_errors is not None

    errors = []
    error_count = 0
    total_lines = 0
    blank_lines = 0
    object_records = 0
    valid_records = 0
    invalid_lines = 0
    duplicate_records = 0
    seen_unique_values: dict[str, int] = {}

    def add_error(error: dict[str, Any]) -> None:
        nonlocal error_count
        error_count += 1
        if len(errors) < maximum_errors:
            errors.append(error)

    for line_number, line in enumerate(lines, start=1):
        total_lines += 1
        if not isinstance(line, str):
            raise ValueError(f"line {line_number} must be a string")
        content = line.rstrip("\r\n")
        if not content.strip():
            blank_lines += 1
            if not allow_blank_lines:
                invalid_lines += 1
                add_error({"line": line_number, "code": "blank_line"})
            continue

        line_has_error = False
        line_bytes = len(content.encode("utf-8"))
        if maximum_bytes is not None and line_bytes > maximum_bytes:
            line_has_error = True
            add_error(
                {
                    "line": line_number,
                    "code": "line_too_large",
                    "actual_bytes": line_bytes,
                    "maximum_bytes": maximum_bytes,
                }
            )

        try:
            record = json.loads(
                content,
                object_pairs_hook=_object_without_duplicate_keys,
                parse_constant=_reject_constant,
            )
        except _DuplicateKeyError as error:
            invalid_lines += 1
            add_error(
                {
                    "line": line_number,
                    "code": "duplicate_json_key",
                    "key": str(error),
                }
            )
            continue
        except _InvalidConstantError as error:
            invalid_lines += 1
            add_error(
                {
                    "line": line_number,
                    "code": "invalid_json_constant",
                    "constant": str(error),
                }
            )
            continue
        except json.JSONDecodeError as error:
            invalid_lines += 1
            add_error(
                {
                    "line": line_number,
                    "code": "invalid_json",
                    "column": error.colno,
                }
            )
            continue

        if not isinstance(record, dict):
            invalid_lines += 1
            add_error({"line": line_number, "code": "non_object_record"})
            continue
        object_records += 1

        missing = [field for field in required if field not in record]
        if missing:
            line_has_error = True
            add_error(
                {
                    "line": line_number,
                    "code": "missing_required_fields",
                    "fields": missing,
                }
            )

        if unique_field is not None:
            if unique_field not in record:
                line_has_error = True
                add_error(
                    {
                        "line": line_number,
                        "code": "missing_unique_field",
                        "field": unique_field,
                    }
                )
            else:
                canonical = json.dumps(
                    record[unique_field],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                )
                if canonical in seen_unique_values:
                    line_has_error = True
                    duplicate_records += 1
                    add_error(
                        {
                            "line": line_number,
                            "code": "duplicate_unique_value",
                            "field": unique_field,
                            "first_line": seen_unique_values[canonical],
                        }
                    )
                else:
                    seen_unique_values[canonical] = line_number

        if line_has_error:
            invalid_lines += 1
        else:
            valid_records += 1

    return {
        "passed": error_count == 0,
        "summary": {
            "total_lines": total_lines,
            "blank_lines": blank_lines,
            "object_records": object_records,
            "valid_records": valid_records,
            "invalid_lines": invalid_lines,
            "duplicate_records": duplicate_records,
            "error_count": error_count,
            "reported_errors": len(errors),
            "truncated_errors": error_count - len(errors),
        },
        "configuration": {
            "required_fields": list(required),
            "unique_field": unique_field,
            "allow_blank_lines": allow_blank_lines,
            "max_line_bytes": maximum_bytes,
            "max_errors": maximum_errors,
        },
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        dest="required_fields",
        metavar="FIELD",
    )
    parser.add_argument("--unique-field")
    parser.add_argument("--allow-blank-lines", action="store_true")
    parser.add_argument("--max-line-bytes", type=int)
    parser.add_argument("--max-errors", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        with args.dataset.open(encoding="utf-8-sig") as handle:
            report = audit_jsonl(
                handle,
                required_fields=args.required_fields,
                unique_field=args.unique_field,
                allow_blank_lines=args.allow_blank_lines,
                max_line_bytes=args.max_line_bytes,
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
