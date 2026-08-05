"""Audit dotenv keys against a JSON contract without reporting values."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


_CONTRACT_FIELDS = {
    "version",
    "required_keys",
    "optional_keys",
    "non_empty_keys",
    "allowed_prefixes",
}
_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class InvalidEnvContractError(ValueError):
    """Raised when an environment contract does not match version 1."""


def _read_bounded_utf8(path: Path, maximum_bytes: int, *, kind: str) -> str:
    if (
        isinstance(maximum_bytes, bool)
        or not isinstance(maximum_bytes, int)
        or maximum_bytes <= 0
    ):
        raise ValueError("max_file_bytes must be a positive integer")
    with path.open("rb") as handle:
        data = handle.read(maximum_bytes + 1)
    if len(data) > maximum_bytes:
        raise ValueError(f"{kind} exceeds max_file_bytes ({maximum_bytes})")
    return data.decode("utf-8-sig")


def _validate_key_list(name: str, value: Any) -> list[str]:
    if not isinstance(value, list):
        raise InvalidEnvContractError(f"{name} must be an array")
    for key in value:
        if not isinstance(key, str) or _KEY_PATTERN.fullmatch(key) is None:
            raise InvalidEnvContractError(
                f"{name} must contain portable dotenv key names"
            )
    if len(value) != len(set(value)):
        raise InvalidEnvContractError(f"{name} must not contain duplicates")
    return sorted(value)


def normalize_env_contract(value: Any) -> dict[str, Any]:
    """Validate and normalize a version 1 environment-key contract."""

    if not isinstance(value, Mapping):
        raise InvalidEnvContractError("contract must contain a JSON object")
    unknown = sorted(set(value) - _CONTRACT_FIELDS)
    if unknown:
        raise InvalidEnvContractError(
            f"contract contains unknown fields: {', '.join(unknown)}"
        )
    if type(value.get("version")) is not int or value["version"] != 1:
        raise InvalidEnvContractError("contract version must be 1")

    required = _validate_key_list("required_keys", value.get("required_keys", []))
    optional = _validate_key_list("optional_keys", value.get("optional_keys", []))
    overlap = sorted(set(required) & set(optional))
    if overlap:
        raise InvalidEnvContractError(
            f"required_keys and optional_keys overlap: {', '.join(overlap)}"
        )
    declared = set(required) | set(optional)
    non_empty = _validate_key_list(
        "non_empty_keys", value.get("non_empty_keys", [])
    )
    undeclared_non_empty = sorted(set(non_empty) - declared)
    if undeclared_non_empty:
        raise InvalidEnvContractError(
            "non_empty_keys must be declared required or optional: "
            + ", ".join(undeclared_non_empty)
        )
    prefixes = _validate_key_list(
        "allowed_prefixes", value.get("allowed_prefixes", [])
    )
    return {
        "version": 1,
        "required_keys": required,
        "optional_keys": optional,
        "non_empty_keys": non_empty,
        "allowed_prefixes": prefixes,
    }


def load_env_contract(
    path: Path, *, max_file_bytes: int = 1024 * 1024
) -> dict[str, Any]:
    """Load and validate a bounded UTF-8 JSON contract."""

    try:
        value = json.loads(
            _read_bounded_utf8(path, max_file_bytes, kind="contract file")
        )
    except json.JSONDecodeError as error:
        raise InvalidEnvContractError(
            f"invalid contract JSON at line {error.lineno}, column {error.colno}"
        ) from error
    return normalize_env_contract(value)


def parse_env_file(
    path: Path, *, max_file_bytes: int = 1024 * 1024
) -> dict[str, dict[str, Any]]:
    """Return dotenv key metadata while discarding every parsed value."""

    text = _read_bounded_utf8(path, max_file_bytes, kind="environment file")
    entries: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assignment = stripped[7:] if stripped.startswith("export ") else stripped
        if "=" not in assignment:
            raise ValueError(f"environment line {line_number} must contain '='")
        raw_key, _, raw_value = assignment.partition("=")
        if raw_key != raw_key.strip() or _KEY_PATTERN.fullmatch(raw_key) is None:
            raise ValueError(
                f"environment line {line_number} has an invalid key name"
            )
        if raw_key in entries:
            raise ValueError(
                f"environment line {line_number} duplicates key {raw_key}"
            )
        blank = raw_value.strip() in {"", "''", '\"\"'}
        entries[raw_key] = {"line": line_number, "blank": blank}
    return entries


def audit_env_contract(
    contract: Any,
    entries: Mapping[str, Mapping[str, Any]],
    *,
    max_extra_keys: int = 0,
    max_details: int = 50,
) -> dict[str, Any]:
    """Return key-only contract failures without copying environment values."""

    normalized = normalize_env_contract(contract)
    for name, value in (
        ("max_extra_keys", max_extra_keys),
        ("max_details", max_details),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")

    declared = set(normalized["required_keys"]) | set(normalized["optional_keys"])
    observed = set(entries)
    missing = sorted(set(normalized["required_keys"]) - observed)
    blank = sorted(
        key
        for key in set(normalized["non_empty_keys"]) & observed
        if entries[key].get("blank") is True
    )
    prefix_keys = sorted(
        key
        for key in observed - declared
        if any(key.startswith(prefix) for prefix in normalized["allowed_prefixes"])
    )
    extras = sorted(observed - declared - set(prefix_keys))
    extra_gate_failed = len(extras) > max_extra_keys

    violations = [
        {"code": "missing_required_key", "key": key} for key in missing
    ]
    violations.extend(
        {
            "code": "blank_non_empty_key",
            "key": key,
            "line": entries[key].get("line"),
        }
        for key in blank
    )
    if extra_gate_failed:
        violations.extend(
            {
                "code": "extra_key",
                "key": key,
                "line": entries[key].get("line"),
            }
            for key in extras
        )

    return {
        "passed": not violations,
        "summary": {
            "observed_key_count": len(observed),
            "required_key_count": len(normalized["required_keys"]),
            "present_required_key_count": len(normalized["required_keys"])
            - len(missing),
            "optional_key_count": len(normalized["optional_keys"]),
            "present_optional_key_count": len(
                set(normalized["optional_keys"]) & observed
            ),
            "allowed_prefix_key_count": len(prefix_keys),
            "missing_required_key_count": len(missing),
            "blank_non_empty_key_count": len(blank),
            "extra_key_count": len(extras),
            "violation_count": len(violations),
            "reported_violation_count": min(len(violations), max_details),
            "truncated_violation_count": max(0, len(violations) - max_details),
        },
        "contract": normalized,
        "thresholds": {"max_extra_keys": max_extra_keys},
        "violations": violations[:max_details],
        "details_truncated": len(violations) > max_details,
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
    parser.add_argument("contract", type=Path)
    parser.add_argument("environment", type=Path)
    parser.add_argument("--max-extra-keys", type=int, default=0)
    parser.add_argument("--max-details", type=int, default=50)
    parser.add_argument("--max-file-bytes", type=int, default=1024 * 1024)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.output is not None and (
            _paths_alias(args.contract, args.output)
            or _paths_alias(args.environment, args.output)
        ):
            raise ValueError("output must not alias an input file")
        report = audit_env_contract(
            load_env_contract(args.contract, max_file_bytes=args.max_file_bytes),
            parse_env_file(args.environment, max_file_bytes=args.max_file_bytes),
            max_extra_keys=args.max_extra_keys,
            max_details=args.max_details,
        )
        rendered = json.dumps(report, indent=2) + "\n"
        if args.output is None:
            print(rendered, end="")
        else:
            args.output.write_text(rendered, encoding="utf-8")
    except (
        InvalidEnvContractError,
        OSError,
        UnicodeError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
