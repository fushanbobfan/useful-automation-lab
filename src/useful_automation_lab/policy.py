"""Audit a validated inventory against an explicit file policy."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .compare import _validate_entries
from .inventory import _matches_pattern, _validated_patterns


_LIMITS = ("max_files", "max_total_bytes", "max_file_bytes")
_FIELDS = {"version", *_LIMITS, "required_paths", "forbidden_patterns"}
_GLOB_MARKERS = frozenset("*?[")


class InvalidPolicyError(ValueError):
    """Raised when a manifest policy does not match the version 1 schema."""


def _normalized_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidPolicyError("policy must contain a JSON object")
    unknown = sorted(set(value) - _FIELDS)
    if unknown:
        raise InvalidPolicyError(f"policy contains unknown fields: {', '.join(unknown)}")
    if type(value.get("version")) is not int or value["version"] != 1:
        raise InvalidPolicyError("policy version must be 1")

    normalized: dict[str, Any] = {"version": 1}
    for name in _LIMITS:
        if name not in value:
            continue
        limit = value[name]
        if type(limit) is not int or limit < 0:
            raise InvalidPolicyError(f"{name} must be a non-negative integer")
        normalized[name] = limit

    required = value.get("required_paths", [])
    if not isinstance(required, list):
        raise InvalidPolicyError("required_paths must be an array")
    if len(required) != len(set(required)):
        raise InvalidPolicyError("required_paths must not contain duplicates")
    required_paths = []
    for path in required:
        if not isinstance(path, str) or not path:
            raise InvalidPolicyError("required_paths must contain non-empty strings")
        normalized_path = PurePosixPath(path)
        if (
            normalized_path.is_absolute()
            or path != normalized_path.as_posix()
            or ".." in normalized_path.parts
            or "\\" in path
            or path == "."
            or any(marker in path for marker in _GLOB_MARKERS)
        ):
            raise InvalidPolicyError(
                "required_paths must use exact normalized relative POSIX paths"
            )
        required_paths.append(path)
    normalized["required_paths"] = sorted(required_paths)

    forbidden = value.get("forbidden_patterns", [])
    if not isinstance(forbidden, list):
        raise InvalidPolicyError("forbidden_patterns must be an array")
    if len(forbidden) != len(set(forbidden)):
        raise InvalidPolicyError("forbidden_patterns must not contain duplicates")
    try:
        forbidden_patterns = _validated_patterns(forbidden)
    except ValueError as error:
        raise InvalidPolicyError(str(error)) from error
    normalized["forbidden_patterns"] = sorted(forbidden_patterns)
    return normalized


def audit_inventory_policy(inventory: Any, policy: Any) -> dict[str, Any]:
    """Return a deterministic report without changing the inventory or source files."""

    entries = _validate_entries(inventory, "inventory")
    normalized_policy = _normalized_policy(policy)
    total_bytes = sum(entry["size"] for entry in entries)
    largest_file_bytes = max((entry["size"] for entry in entries), default=0)
    violations = []

    if len(entries) > normalized_policy.get("max_files", len(entries)):
        maximum = normalized_policy["max_files"]
        violations.append(
            {
                "rule": "max_files",
                "actual": len(entries),
                "maximum": maximum,
                "excess": len(entries) - maximum,
            }
        )
    if total_bytes > normalized_policy.get("max_total_bytes", total_bytes):
        maximum = normalized_policy["max_total_bytes"]
        violations.append(
            {
                "rule": "max_total_bytes",
                "actual": total_bytes,
                "maximum": maximum,
                "excess": total_bytes - maximum,
            }
        )
    if largest_file_bytes > normalized_policy.get("max_file_bytes", largest_file_bytes):
        maximum = normalized_policy["max_file_bytes"]
        violations.append(
            {
                "rule": "max_file_bytes",
                "actual": largest_file_bytes,
                "maximum": maximum,
                "offending_files": [
                    {"path": entry["path"], "size": entry["size"]}
                    for entry in sorted(entries, key=lambda item: item["path"])
                    if entry["size"] > maximum
                ],
            }
        )

    inventory_paths = {entry["path"] for entry in entries}
    for path in normalized_policy["required_paths"]:
        if path not in inventory_paths:
            violations.append({"rule": "required_path", "path": path})

    patterns = normalized_policy["forbidden_patterns"]
    for path in sorted(inventory_paths):
        pure_path = PurePosixPath(path)
        matching = [
            pattern for pattern in patterns if _matches_pattern(pure_path, [pattern])
        ]
        if matching:
            violations.append(
                {"rule": "forbidden_pattern", "path": path, "patterns": matching}
            )

    return {
        "passed": not violations,
        "summary": {
            "files": len(entries),
            "total_bytes": total_bytes,
            "largest_file_bytes": largest_file_bytes,
            "violations": len(violations),
        },
        "policy": normalized_policy,
        "violations": violations,
    }
