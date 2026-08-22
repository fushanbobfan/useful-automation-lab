"""Compare strict CSV snapshots by composite key without reporting values."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
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


def _key_fingerprint(key: tuple[str, ...]) -> str:
    canonical = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _validate_header(
    rows: Sequence[Mapping[str, Any]], *, dataset_name: str
) -> tuple[str, ...]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise ValueError(f"{dataset_name}_rows must be a sequence")
    if not rows:
        raise ValueError(f"{dataset_name}_rows must contain at least one row")
    first = rows[0]
    if not isinstance(first, Mapping):
        raise ValueError(f"{dataset_name} row 2 must be an object")
    header = tuple(first)
    if (
        not header
        or any(not isinstance(column, str) or not column for column in header)
        or len(set(header)) != len(header)
    ):
        raise ValueError(f"{dataset_name} header must contain unique non-empty strings")
    return header


def _index_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    dataset_name: str,
    header: tuple[str, ...],
    key_columns: tuple[str, ...],
    ignored: set[str],
) -> dict[tuple[str, ...], dict[str, Any]]:
    indexed = {}
    compared_columns = tuple(column for column in header if column not in ignored)
    for index, row in enumerate(rows, start=2):
        if not isinstance(row, Mapping):
            raise ValueError(f"{dataset_name} row {index} must be an object")
        if tuple(row) != header:
            raise ValueError(
                f"{dataset_name} row {index} must use the same ordered columns"
            )
        for column, value in row.items():
            if not isinstance(value, str):
                raise ValueError(
                    f"{dataset_name} row {index} column {column!r} must be a string"
                )
        key = tuple(row[column] for column in key_columns)
        if any(component == "" for component in key):
            raise ValueError(f"{dataset_name} row {index} key fields must be non-empty")
        if key in indexed:
            raise ValueError(
                f"{dataset_name} row {index} has a duplicate composite key"
            )
        indexed[key] = {
            "row_number": index,
            "values": tuple(row[column] for column in compared_columns),
            "row": row,
        }
    return indexed


def compare_csv_records(
    reference_rows: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
    *,
    key_columns: Sequence[str] = ("id",),
    ignore_columns: Sequence[str] = (),
    max_added: int = 0,
    max_removed: int = 0,
    max_modified: int = 0,
    max_details: int = 50,
) -> dict[str, Any]:
    """Return deterministic composite-key additions, removals, and modifications."""
    keys = _columns("key_columns", key_columns)
    if isinstance(ignore_columns, (str, bytes)) or not isinstance(
        ignore_columns, Sequence
    ):
        raise ValueError("ignore_columns must be a sequence of column names")
    ignored_list = list(ignore_columns)
    if any(not isinstance(column, str) or not column for column in ignored_list):
        raise ValueError("ignore_columns must contain non-empty strings")
    if len(set(ignored_list)) != len(ignored_list):
        raise ValueError("ignore_columns must not contain duplicates")
    if set(keys) & set(ignored_list):
        raise ValueError("key columns cannot be ignored")
    thresholds = {
        "added_record_count": _non_negative_integer("max_added", max_added),
        "removed_record_count": _non_negative_integer("max_removed", max_removed),
        "modified_record_count": _non_negative_integer("max_modified", max_modified),
    }
    maximum_details = _non_negative_integer("max_details", max_details)

    reference_header = _validate_header(reference_rows, dataset_name="reference")
    candidate_header = _validate_header(candidate_rows, dataset_name="candidate")
    if candidate_header != reference_header:
        raise ValueError("reference and candidate CSV headers must match exactly")
    missing_keys = [column for column in keys if column not in reference_header]
    if missing_keys:
        raise ValueError(f"CSV header is missing key columns {missing_keys}")
    missing_ignored = [
        column for column in ignored_list if column not in reference_header
    ]
    if missing_ignored:
        raise ValueError(f"CSV header is missing ignored columns {missing_ignored}")
    ignored = set(ignored_list)

    reference = _index_rows(
        reference_rows,
        dataset_name="reference",
        header=reference_header,
        key_columns=keys,
        ignored=ignored,
    )
    candidate = _index_rows(
        candidate_rows,
        dataset_name="candidate",
        header=candidate_header,
        key_columns=keys,
        ignored=ignored,
    )
    reference_keys = set(reference)
    candidate_keys = set(candidate)
    added_keys = sorted(candidate_keys - reference_keys, key=_key_fingerprint)
    removed_keys = sorted(reference_keys - candidate_keys, key=_key_fingerprint)
    shared_keys = sorted(reference_keys & candidate_keys, key=_key_fingerprint)

    added_records = [
        {
            "key_fingerprint": _key_fingerprint(key),
            "candidate_row_number": candidate[key]["row_number"],
        }
        for key in added_keys
    ]
    removed_records = [
        {
            "key_fingerprint": _key_fingerprint(key),
            "reference_row_number": reference[key]["row_number"],
        }
        for key in removed_keys
    ]
    modified_records = []
    unchanged_count = 0
    compared_columns = [
        column for column in reference_header if column not in ignored
    ]
    for key in shared_keys:
        before = reference[key]
        after = candidate[key]
        if before["values"] == after["values"]:
            unchanged_count += 1
            continue
        changed_columns = sorted(
            column
            for column in compared_columns
            if column not in keys and before["row"][column] != after["row"][column]
        )
        modified_records.append(
            {
                "key_fingerprint": _key_fingerprint(key),
                "reference_row_number": before["row_number"],
                "candidate_row_number": after["row_number"],
                "changed_columns": changed_columns,
            }
        )

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
            "key_columns": list(keys),
            "ignored_columns": sorted(ignored),
            "max_details": maximum_details,
            "comparison": "exact_decoded_csv_strings_after_ignored_columns",
            "raw_key_values_reported": False,
            "scalar_values_reported": False,
            "key_fingerprint_algorithm": "sha256-prefix-16",
        },
    }
