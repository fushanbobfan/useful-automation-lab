"""Audit JSONL event ordering without changing source records."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .jsonl_structure import load_jsonl_records


def _validate_field(name: str, value: str | None, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _validate_maximum(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _canonical_scalar(value: Any, *, location: str) -> tuple[str, str]:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{location} must be a string or integer")
    if isinstance(value, str):
        if not value:
            raise ValueError(f"{location} must not be empty")
        return ("string", value)
    return ("integer", str(value))


def _parse_timestamp(value: Any, *, location: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{location} must be an RFC3339 timestamp string")
    if "T" not in value or not (value.endswith("Z") or value[-6:-5] in ("+", "-")):
        raise ValueError(f"{location} must include a timezone offset")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"{location} must be an RFC3339 timestamp string") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{location} must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def audit_jsonl_event_order(
    records: Sequence[Mapping[str, Any]],
    *,
    id_field: str = "event_id",
    timestamp_field: str = "timestamp",
    group_field: str | None = None,
    sequence_field: str | None = None,
    max_duplicate_event_ids: int = 0,
    max_timestamp_regressions: int = 0,
    max_sequence_violations: int = 0,
    max_details: int = 50,
) -> dict[str, Any]:
    """Report ID duplicates and per-scope timestamp or sequence regressions."""

    if not records:
        raise ValueError("records must contain at least one event")
    event_id_field = _validate_field("id_field", id_field)
    event_timestamp_field = _validate_field("timestamp_field", timestamp_field)
    event_group_field = _validate_field("group_field", group_field, optional=True)
    event_sequence_field = _validate_field(
        "sequence_field", sequence_field, optional=True
    )
    fields = [event_id_field, event_timestamp_field]
    fields.extend(
        field for field in (event_group_field, event_sequence_field) if field is not None
    )
    if len(set(fields)) != len(fields):
        raise ValueError("configured field names must be distinct")
    thresholds = {
        "duplicate_event_ids": _validate_maximum(
            "max_duplicate_event_ids", max_duplicate_event_ids
        ),
        "timestamp_regressions": _validate_maximum(
            "max_timestamp_regressions", max_timestamp_regressions
        ),
        "sequence_violations": _validate_maximum(
            "max_sequence_violations", max_sequence_violations
        ),
    }
    maximum_details = _validate_maximum("max_details", max_details)

    global_scope = ("global", "")
    seen_ids: dict[tuple[str, str], int] = {}
    last_timestamp: dict[tuple[str, str], tuple[datetime, int]] = {}
    last_sequence: dict[tuple[str, str], tuple[int, int]] = {}
    groups: set[tuple[str, str]] = set()
    details: list[dict[str, Any]] = []
    counts = {
        "duplicate_event_ids": 0,
        "timestamp_regressions": 0,
        "sequence_regressions": 0,
        "duplicate_sequences": 0,
        "sequence_gap_transitions": 0,
        "missing_sequence_values": 0,
    }

    def add_detail(detail: dict[str, Any]) -> None:
        if len(details) < maximum_details:
            details.append(detail)

    for index, record in enumerate(records):
        line = index + 1
        if not isinstance(record, Mapping):
            raise ValueError(f"record {index} must be an object")
        for field in fields:
            if field not in record:
                raise ValueError(f"record {index} is missing {field}")

        canonical_id = _canonical_scalar(
            record[event_id_field], location=f"record {index} {event_id_field}"
        )
        parsed_timestamp = _parse_timestamp(
            record[event_timestamp_field],
            location=f"record {index} {event_timestamp_field}",
        )
        scope = (
            _canonical_scalar(
                record[event_group_field],
                location=f"record {index} {event_group_field}",
            )
            if event_group_field is not None
            else global_scope
        )
        groups.add(scope)

        if canonical_id in seen_ids:
            counts["duplicate_event_ids"] += 1
            add_detail(
                {
                    "line": line,
                    "code": "duplicate_event_id",
                    "first_line": seen_ids[canonical_id],
                }
            )
        else:
            seen_ids[canonical_id] = line

        previous_timestamp = last_timestamp.get(scope)
        if previous_timestamp is not None and parsed_timestamp < previous_timestamp[0]:
            counts["timestamp_regressions"] += 1
            add_detail(
                {
                    "line": line,
                    "code": "timestamp_regression",
                    "previous_line": previous_timestamp[1],
                }
            )
        last_timestamp[scope] = (parsed_timestamp, line)

        if event_sequence_field is not None:
            sequence = record[event_sequence_field]
            if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
                raise ValueError(
                    f"record {index} {event_sequence_field} must be a non-negative integer"
                )
            previous_sequence = last_sequence.get(scope)
            if previous_sequence is not None:
                previous_value, previous_line = previous_sequence
                if sequence < previous_value:
                    counts["sequence_regressions"] += 1
                    add_detail(
                        {
                            "line": line,
                            "code": "sequence_regression",
                            "previous_line": previous_line,
                        }
                    )
                elif sequence == previous_value:
                    counts["duplicate_sequences"] += 1
                    add_detail(
                        {
                            "line": line,
                            "code": "duplicate_sequence",
                            "previous_line": previous_line,
                        }
                    )
                elif sequence > previous_value + 1:
                    missing = sequence - previous_value - 1
                    counts["sequence_gap_transitions"] += 1
                    counts["missing_sequence_values"] += missing
                    add_detail(
                        {
                            "line": line,
                            "code": "sequence_gap",
                            "previous_line": previous_line,
                            "missing_values": missing,
                        }
                    )
            last_sequence[scope] = (sequence, line)

    sequence_violations = (
        counts["sequence_regressions"]
        + counts["duplicate_sequences"]
        + counts["sequence_gap_transitions"]
    )
    observed = {
        "duplicate_event_ids": counts["duplicate_event_ids"],
        "timestamp_regressions": counts["timestamp_regressions"],
        "sequence_violations": sequence_violations,
    }
    failures = []
    for metric in (
        "duplicate_event_ids",
        "timestamp_regressions",
        "sequence_violations",
    ):
        actual = observed[metric]
        maximum = thresholds[metric]
        if actual > maximum:
            failures.append(
                {
                    "metric": metric,
                    "actual": actual,
                    "maximum": maximum,
                    "excess": actual - maximum,
                }
            )

    total_violations = (
        counts["duplicate_event_ids"]
        + counts["timestamp_regressions"]
        + sequence_violations
    )
    return {
        "passed": not failures,
        "summary": {
            "record_count": len(records),
            "group_count": len(groups),
            **counts,
            "sequence_violations": sequence_violations,
            "violation_count": total_violations,
            "reported_details": len(details),
            "truncated_details": total_violations - len(details),
        },
        "thresholds": thresholds,
        "failures": failures,
        "details": details,
        "settings": {
            "id_field": event_id_field,
            "timestamp_field": event_timestamp_field,
            "group_field": event_group_field,
            "sequence_field": event_sequence_field,
            "timestamp_scope": "group" if event_group_field is not None else "global",
            "record_values_reported": False,
            "max_details": maximum_details,
        },
    }


def _paths_alias(source: Path, output: Path) -> bool:
    if source.resolve() == output.resolve():
        return True
    try:
        return source.samefile(output)
    except (FileNotFoundError, OSError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--id-field", default="event_id")
    parser.add_argument("--timestamp-field", default="timestamp")
    parser.add_argument("--group-field")
    parser.add_argument("--sequence-field")
    parser.add_argument("--max-duplicate-event-ids", type=int, default=0)
    parser.add_argument("--max-timestamp-regressions", type=int, default=0)
    parser.add_argument("--max-sequence-violations", type=int, default=0)
    parser.add_argument("--max-details", type=int, default=50)
    parser.add_argument("--max-file-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.output is not None and _paths_alias(args.dataset, args.output):
            raise ValueError("output must not alias the source dataset")
        report = audit_jsonl_event_order(
            load_jsonl_records(
                args.dataset,
                max_file_bytes=args.max_file_bytes,
            ),
            id_field=args.id_field,
            timestamp_field=args.timestamp_field,
            group_field=args.group_field,
            sequence_field=args.sequence_field,
            max_duplicate_event_ids=args.max_duplicate_event_ids,
            max_timestamp_regressions=args.max_timestamp_regressions,
            max_sequence_violations=args.max_sequence_violations,
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
