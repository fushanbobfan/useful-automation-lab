"""Compare top-level JSONL structure without reporting scalar values."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    raise ValueError(f"unsupported JSON value type: {type(value).__name__}")


def _profile_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise ValueError("each dataset must contain at least one record")

    fields: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"record {index} must be an object")
        for field, value in record.items():
            if not isinstance(field, str):
                raise ValueError(f"record {index} field names must be strings")
            value_type = _json_type(value)
            profile = fields.setdefault(
                field,
                {"present_count": 0, "null_count": 0, "type_counts": Counter()},
            )
            profile["present_count"] += 1
            if value_type == "null":
                profile["null_count"] += 1
            else:
                profile["type_counts"][value_type] += 1

    count = len(records)
    field_profiles = []
    for field in sorted(fields):
        profile = fields[field]
        present_count = profile["present_count"]
        type_counts = dict(sorted(profile["type_counts"].items()))
        field_profiles.append(
            {
                "field": field,
                "present_count": present_count,
                "missing_count": count - present_count,
                "presence_rate": present_count / count,
                "required": present_count == count,
                "null_count": profile["null_count"],
                "null_rate_when_present": profile["null_count"] / present_count,
                "non_null_types": list(type_counts),
                "non_null_type_counts": type_counts,
            }
        )
    return {
        "record_count": count,
        "field_count": len(field_profiles),
        "fields": field_profiles,
    }


def _validate_rate(name: str, value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.0 <= value <= 1.0
    ):
        raise ValueError(f"{name} must be between 0 and 1")
    return float(value)


def compare_jsonl_structures(
    reference_records: Sequence[Mapping[str, Any]],
    candidate_records: Sequence[Mapping[str, Any]],
    *,
    max_presence_rate_delta: float = 0.0,
    max_null_rate_delta: float = 0.0,
    max_changes: int = 0,
    max_details: int = 50,
) -> dict[str, Any]:
    """Return deterministic top-level field and type drift diagnostics."""

    presence_limit = _validate_rate(
        "max_presence_rate_delta", max_presence_rate_delta
    )
    null_limit = _validate_rate("max_null_rate_delta", max_null_rate_delta)
    for name, value in (("max_changes", max_changes), ("max_details", max_details)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")

    reference = _profile_records(reference_records)
    candidate = _profile_records(candidate_records)
    reference_fields = {item["field"]: item for item in reference["fields"]}
    candidate_fields = {item["field"]: item for item in candidate["fields"]}

    changes = []
    for field in sorted(set(reference_fields) | set(candidate_fields)):
        before = reference_fields.get(field)
        after = candidate_fields.get(field)
        if before is None:
            changes.append(
                {
                    "code": "field_added",
                    "field": field,
                    "candidate_presence_rate": after["presence_rate"],
                    "candidate_non_null_types": after["non_null_types"],
                }
            )
            continue
        if after is None:
            changes.append(
                {
                    "code": "field_removed",
                    "field": field,
                    "reference_presence_rate": before["presence_rate"],
                    "reference_non_null_types": before["non_null_types"],
                }
            )
            continue

        if before["non_null_types"] != after["non_null_types"]:
            changes.append(
                {
                    "code": "type_set_changed",
                    "field": field,
                    "reference_non_null_types": before["non_null_types"],
                    "candidate_non_null_types": after["non_null_types"],
                }
            )
        presence_delta = abs(after["presence_rate"] - before["presence_rate"])
        if presence_delta > presence_limit:
            changes.append(
                {
                    "code": "presence_rate_changed",
                    "field": field,
                    "reference_rate": before["presence_rate"],
                    "candidate_rate": after["presence_rate"],
                    "absolute_delta": presence_delta,
                }
            )
        null_delta = abs(
            after["null_rate_when_present"] - before["null_rate_when_present"]
        )
        if null_delta > null_limit:
            changes.append(
                {
                    "code": "null_rate_changed",
                    "field": field,
                    "reference_rate": before["null_rate_when_present"],
                    "candidate_rate": after["null_rate_when_present"],
                    "absolute_delta": null_delta,
                }
            )

    kind_counts = Counter(change["code"] for change in changes)
    change_count = len(changes)
    failures = []
    if change_count > max_changes:
        failures.append(
            {
                "metric": "change_count",
                "actual": change_count,
                "maximum": max_changes,
                "excess": change_count - max_changes,
            }
        )

    return {
        "passed": not failures,
        "summary": {
            "reference_record_count": reference["record_count"],
            "candidate_record_count": candidate["record_count"],
            "reference_field_count": reference["field_count"],
            "candidate_field_count": candidate["field_count"],
            "change_count": change_count,
            "reported_change_count": min(change_count, max_details),
            "truncated_change_count": max(0, change_count - max_details),
            "change_kind_counts": dict(sorted(kind_counts.items())),
        },
        "thresholds": {
            "max_presence_rate_delta": presence_limit,
            "max_null_rate_delta": null_limit,
            "max_changes": max_changes,
        },
        "failures": failures,
        "changes": changes[:max_details],
        "details_truncated": change_count > max_details,
        "reference_profile": reference,
        "candidate_profile": candidate,
        "settings": {
            "scope": "top_level_fields",
            "scalar_values_reported": False,
            "max_details": max_details,
        },
    }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant {value}")


def load_jsonl_records(
    path: Path, *, max_file_bytes: int = 10 * 1024 * 1024
) -> list[Mapping[str, Any]]:
    """Load a bounded strict JSONL object stream."""

    if (
        isinstance(max_file_bytes, bool)
        or not isinstance(max_file_bytes, int)
        or max_file_bytes <= 0
    ):
        raise ValueError("max_file_bytes must be a positive integer")
    with path.open("rb") as handle:
        data = handle.read(max_file_bytes + 1)
    if len(data) > max_file_bytes:
        raise ValueError(f"input exceeds max_file_bytes ({max_file_bytes})")
    text = data.decode("utf-8-sig")
    records = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"line {line_number} must not be blank")
        try:
            value = json.loads(
                line,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_constant,
            )
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON on line {line_number}") from error
        except ValueError as error:
            raise ValueError(f"line {line_number}: {error}") from error
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number} must contain a JSON object")
        records.append(value)
    if not records:
        raise ValueError("input must contain at least one JSON object")
    return records


def _paths_alias(source: Path, output: Path) -> bool:
    if source.resolve() == output.resolve():
        return True
    try:
        return source.samefile(output)
    except (FileNotFoundError, OSError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--max-presence-rate-delta", type=float, default=0.0)
    parser.add_argument("--max-null-rate-delta", type=float, default=0.0)
    parser.add_argument("--max-changes", type=int, default=0)
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
        report = compare_jsonl_structures(
            load_jsonl_records(
                args.reference, max_file_bytes=args.max_file_bytes
            ),
            load_jsonl_records(
                args.candidate, max_file_bytes=args.max_file_bytes
            ),
            max_presence_rate_delta=args.max_presence_rate_delta,
            max_null_rate_delta=args.max_null_rate_delta,
            max_changes=args.max_changes,
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
