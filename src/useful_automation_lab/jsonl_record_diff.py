"""Compare JSONL snapshots by stable record key without reporting values."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .jsonl_structure import load_jsonl_records


def _non_negative_integer(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _validate_json(value: Any, *, location: str) -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{location} must contain JSON-compatible values")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json(item, location=f"{location}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{location} must contain JSON-compatible values")
            _validate_json(item, location=f"{location}.{key}")
        return
    raise ValueError(f"{location} must contain JSON-compatible values")


def _canonical_key(value: Any, *, location: str) -> tuple[str, str]:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{location} must be a string or integer")
    if isinstance(value, str):
        if not value:
            raise ValueError(f"{location} must be a non-empty string or integer")
        return ("string", value)
    return ("integer", str(value))


def _index_records(
    records: Sequence[Mapping[str, Any]],
    *,
    dataset_name: str,
    key_field: str,
    ignored: set[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    if not records:
        raise ValueError(f"{dataset_name} must contain at least one record")
    indexed = {}
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"{dataset_name} record {index} must be an object")
        if any(not isinstance(field, str) for field in record):
            raise ValueError(f"{dataset_name} record {index} field names must be strings")
        _validate_json(record, location=f"{dataset_name} record {index}")
        if key_field not in record:
            raise ValueError(
                f"{dataset_name} record {index} is missing key field {key_field}"
            )
        raw_key = record[key_field]
        canonical_key = _canonical_key(
            raw_key,
            location=f"{dataset_name} record {index} {key_field}",
        )
        if canonical_key in indexed:
            raise ValueError(
                f"{dataset_name} record {index} has duplicate key {raw_key!r}"
            )
        compared_record = {
            field: value for field, value in record.items() if field not in ignored
        }
        fingerprint = json.dumps(
            compared_record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        indexed[canonical_key] = {
            "id": raw_key,
            "record": compared_record,
            "fingerprint": fingerprint,
        }
    return indexed


def compare_jsonl_records(
    reference_records: Sequence[Mapping[str, Any]],
    candidate_records: Sequence[Mapping[str, Any]],
    *,
    key_field: str = "id",
    ignore_fields: Sequence[str] = (),
    max_added: int = 0,
    max_removed: int = 0,
    max_modified: int = 0,
    max_details: int = 50,
) -> dict[str, Any]:
    """Return deterministic key-level additions, removals, and modifications."""

    if not isinstance(key_field, str) or not key_field:
        raise ValueError("key_field must be a non-empty string")
    if isinstance(ignore_fields, str) or not isinstance(ignore_fields, Sequence):
        raise ValueError("ignore_fields must be a sequence of field names")
    ignored_list = list(ignore_fields)
    if any(not isinstance(field, str) or not field for field in ignored_list):
        raise ValueError("ignore_fields must contain non-empty strings")
    if len(set(ignored_list)) != len(ignored_list):
        raise ValueError("ignore_fields must not contain duplicates")
    if key_field in ignored_list:
        raise ValueError("key_field cannot be ignored")
    thresholds = {
        "added_record_count": _non_negative_integer("max_added", max_added),
        "removed_record_count": _non_negative_integer("max_removed", max_removed),
        "modified_record_count": _non_negative_integer("max_modified", max_modified),
    }
    maximum_details = _non_negative_integer("max_details", max_details)
    ignored = set(ignored_list)

    reference = _index_records(
        reference_records,
        dataset_name="reference",
        key_field=key_field,
        ignored=ignored,
    )
    candidate = _index_records(
        candidate_records,
        dataset_name="candidate",
        key_field=key_field,
        ignored=ignored,
    )
    reference_keys = set(reference)
    candidate_keys = set(candidate)
    added_keys = sorted(candidate_keys - reference_keys)
    removed_keys = sorted(reference_keys - candidate_keys)
    shared_keys = sorted(reference_keys & candidate_keys)

    modified_records = []
    unchanged_count = 0
    missing = object()
    for key in shared_keys:
        before = reference[key]
        after = candidate[key]
        if before["fingerprint"] == after["fingerprint"]:
            unchanged_count += 1
            continue
        fields = sorted(set(before["record"]) | set(after["record"]))
        changed_fields = [
            field
            for field in fields
            if field != key_field
            and before["record"].get(field, missing)
            != after["record"].get(field, missing)
        ]
        modified_records.append(
            {"id": after["id"], "changed_fields": changed_fields}
        )

    added_records = [{"id": candidate[key]["id"]} for key in added_keys]
    removed_records = [{"id": reference[key]["id"]} for key in removed_keys]
    summary = {
        "reference_record_count": len(reference),
        "candidate_record_count": len(candidate),
        "added_record_count": len(added_records),
        "removed_record_count": len(removed_records),
        "modified_record_count": len(modified_records),
        "unchanged_record_count": unchanged_count,
        "changed_record_count": (
            len(added_records) + len(removed_records) + len(modified_records)
        ),
    }
    failures = []
    for metric, maximum in thresholds.items():
        actual = summary[metric]
        if actual > maximum:
            failures.append(
                {
                    "metric": metric,
                    "actual": actual,
                    "maximum": maximum,
                    "excess": actual - maximum,
                }
            )

    return {
        "passed": not failures,
        "summary": summary,
        "thresholds": thresholds,
        "failures": failures,
        "added_records": added_records[:maximum_details],
        "removed_records": removed_records[:maximum_details],
        "modified_records": modified_records[:maximum_details],
        "details_truncated": {
            "added_records": len(added_records) > maximum_details,
            "removed_records": len(removed_records) > maximum_details,
            "modified_records": len(modified_records) > maximum_details,
        },
        "settings": {
            "key_field": key_field,
            "ignored_fields": sorted(ignored),
            "max_details": maximum_details,
            "comparison": "canonical_json_after_ignored_fields",
            "scalar_values_reported_beyond_ids": False,
        },
    }


def _paths_alias(first: Path, second: Path) -> bool:
    if first.resolve() == second.resolve():
        return True
    try:
        return first.samefile(second)
    except (FileNotFoundError, OSError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--key-field", default="id")
    parser.add_argument("--ignore-field", action="append", default=[])
    parser.add_argument("--max-added", type=int, default=0)
    parser.add_argument("--max-removed", type=int, default=0)
    parser.add_argument("--max-modified", type=int, default=0)
    parser.add_argument("--max-details", type=int, default=50)
    parser.add_argument("--max-file-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.output is not None and (
            _paths_alias(args.reference, args.output)
            or _paths_alias(args.candidate, args.output)
        ):
            raise ValueError("output must not alias an input file")
        report = compare_jsonl_records(
            load_jsonl_records(
                args.reference, max_file_bytes=args.max_file_bytes
            ),
            load_jsonl_records(
                args.candidate, max_file_bytes=args.max_file_bytes
            ),
            key_field=args.key_field,
            ignore_fields=args.ignore_field,
            max_added=args.max_added,
            max_removed=args.max_removed,
            max_modified=args.max_modified,
            max_details=args.max_details,
        )
        rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
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
