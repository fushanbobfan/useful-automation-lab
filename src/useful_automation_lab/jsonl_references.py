"""Audit references between parent and child JSONL object streams."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any


def _validate_field(name: str, value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _validate_optional_count(name: str, value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _canonical_id(value: Any, *, location: str) -> tuple[str, Any]:
    if isinstance(value, (Mapping, list)) or value is None or isinstance(value, bool):
        raise ValueError(f"{location} must be a string or number")
    if not isinstance(value, (str, int, float)):
        raise ValueError(f"{location} must be a string or number")
    if isinstance(value, float) and (value != value or abs(value) == float("inf")):
        raise ValueError(f"{location} must be finite")
    if isinstance(value, str) and not value:
        raise ValueError(f"{location} must not be empty")
    canonical = json.dumps(value, ensure_ascii=False, allow_nan=False)
    return canonical, value


def audit_jsonl_references(
    parent_records: Sequence[Mapping[str, Any]],
    child_records: Sequence[Mapping[str, Any]],
    *,
    parent_id_field: str = "id",
    child_reference_field: str = "parent_id",
    max_orphan_references: int | None = 0,
    max_unreferenced_parents: int | None = None,
    max_children_per_parent: int | None = None,
    max_details: int = 50,
) -> dict[str, Any]:
    """Return deterministic cardinality and referential-integrity diagnostics."""

    if not parent_records:
        raise ValueError("parent_records must contain at least one record")
    if not child_records:
        raise ValueError("child_records must contain at least one record")
    parent_field = _validate_field("parent_id_field", parent_id_field)
    child_field = _validate_field("child_reference_field", child_reference_field)
    maximum_orphans = _validate_optional_count(
        "max_orphan_references", max_orphan_references
    )
    maximum_unreferenced = _validate_optional_count(
        "max_unreferenced_parents", max_unreferenced_parents
    )
    maximum_children = _validate_optional_count(
        "max_children_per_parent", max_children_per_parent
    )
    if isinstance(max_details, bool) or not isinstance(max_details, int) or max_details < 0:
        raise ValueError("max_details must be a non-negative integer")

    parents: dict[str, Any] = {}
    for index, record in enumerate(parent_records):
        if not isinstance(record, Mapping):
            raise ValueError(f"parent record {index} must be an object")
        if parent_field not in record:
            raise ValueError(f"parent record {index} is missing {parent_field}")
        canonical, value = _canonical_id(
            record[parent_field], location=f"parent record {index} {parent_field}"
        )
        if canonical in parents:
            raise ValueError(f"parent record {index} has a duplicate ID")
        parents[canonical] = value

    child_counts: Counter[str] = Counter()
    child_values: dict[str, Any] = {}
    for index, record in enumerate(child_records):
        if not isinstance(record, Mapping):
            raise ValueError(f"child record {index} must be an object")
        if child_field not in record:
            raise ValueError(f"child record {index} is missing {child_field}")
        canonical, value = _canonical_id(
            record[child_field], location=f"child record {index} {child_field}"
        )
        child_counts[canonical] += 1
        child_values[canonical] = value

    orphan_groups = [
        {"id": child_values[key], "child_count": child_counts[key]}
        for key in child_counts
        if key not in parents
    ]
    orphan_groups.sort(key=lambda item: (-item["child_count"], json.dumps(item["id"])))
    orphan_reference_count = sum(item["child_count"] for item in orphan_groups)

    unreferenced = [
        {"id": parents[key]}
        for key in parents
        if child_counts[key] == 0
    ]
    unreferenced.sort(key=lambda item: json.dumps(item["id"]))
    parent_cardinality = [
        {"id": parents[key], "child_count": child_counts[key]}
        for key in parents
    ]
    parent_cardinality.sort(
        key=lambda item: (-item["child_count"], json.dumps(item["id"]))
    )
    maximum_observed_children = parent_cardinality[0]["child_count"]
    fanout_violations = (
        [
            item
            for item in parent_cardinality
            if item["child_count"] > maximum_children
        ]
        if maximum_children is not None
        else []
    )

    failures = []
    if maximum_orphans is not None and orphan_reference_count > maximum_orphans:
        failures.append(
            {
                "metric": "orphan_reference_count",
                "actual": orphan_reference_count,
                "maximum": maximum_orphans,
                "excess": orphan_reference_count - maximum_orphans,
            }
        )
    if maximum_unreferenced is not None and len(unreferenced) > maximum_unreferenced:
        failures.append(
            {
                "metric": "unreferenced_parent_count",
                "actual": len(unreferenced),
                "maximum": maximum_unreferenced,
                "excess": len(unreferenced) - maximum_unreferenced,
            }
        )
    if maximum_children is not None and maximum_observed_children > maximum_children:
        failures.append(
            {
                "metric": "maximum_children_per_parent",
                "actual": maximum_observed_children,
                "maximum": maximum_children,
                "excess": maximum_observed_children - maximum_children,
                "violating_parent_count": len(fanout_violations),
            }
        )

    return {
        "passed": not failures,
        "summary": {
            "parent_record_count": len(parent_records),
            "child_record_count": len(child_records),
            "referenced_parent_count": len(parents) - len(unreferenced),
            "unreferenced_parent_count": len(unreferenced),
            "orphan_reference_count": orphan_reference_count,
            "distinct_orphan_id_count": len(orphan_groups),
            "maximum_children_per_parent": maximum_observed_children,
            "parents_over_max_children": len(fanout_violations),
        },
        "thresholds": {
            "max_orphan_references": maximum_orphans,
            "max_unreferenced_parents": maximum_unreferenced,
            "max_children_per_parent": maximum_children,
        },
        "failures": failures,
        "orphan_references": orphan_groups[:max_details],
        "unreferenced_parents": unreferenced[:max_details],
        "largest_parent_cardinalities": parent_cardinality[:max_details],
        "fanout_violations": fanout_violations[:max_details],
        "details_truncated": {
            "orphan_references": len(orphan_groups) > max_details,
            "unreferenced_parents": len(unreferenced) > max_details,
            "parent_cardinalities": len(parent_cardinality) > max_details,
            "fanout_violations": len(fanout_violations) > max_details,
        },
        "settings": {
            "parent_id_field": parent_field,
            "child_reference_field": child_field,
            "scalar_values_reported_beyond_ids": False,
            "max_details": max_details,
        },
    }
