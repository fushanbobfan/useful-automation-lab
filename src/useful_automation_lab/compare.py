"""Compare two deterministic file inventories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any


_FIELDS = {"path", "size", "sha256"}
_HEX_DIGITS = frozenset("0123456789abcdef")


class InvalidInventoryError(ValueError):
    """Raised when an inventory does not match the expected schema."""


def _validate_entries(value: Any, source: str) -> list[dict[str, str | int]]:
    if not isinstance(value, list):
        raise InvalidInventoryError(f"{source} must contain a JSON array")

    entries: list[dict[str, str | int]] = []
    seen_paths: set[str] = set()
    for index, item in enumerate(value):
        label = f"{source} entry {index}"
        if not isinstance(item, dict) or set(item) != _FIELDS:
            raise InvalidInventoryError(
                f"{label} must contain exactly path, size, and sha256"
            )

        path = item["path"]
        size = item["size"]
        sha256 = item["sha256"]
        if not isinstance(path, str) or not path:
            raise InvalidInventoryError(f"{label} has an invalid path")

        normalized = PurePosixPath(path)
        if (
            normalized.is_absolute()
            or path != normalized.as_posix()
            or ".." in normalized.parts
            or "\\" in path
            or path == "."
        ):
            raise InvalidInventoryError(f"{label} path must be a normalized relative path")
        if path in seen_paths:
            raise InvalidInventoryError(f"{source} contains duplicate path: {path}")
        if type(size) is not int or size < 0:
            raise InvalidInventoryError(f"{label} has an invalid size")
        if (
            not isinstance(sha256, str)
            or len(sha256) != 64
            or any(character not in _HEX_DIGITS for character in sha256)
        ):
            raise InvalidInventoryError(f"{label} has an invalid SHA-256 digest")

        seen_paths.add(path)
        entries.append({"path": path, "size": size, "sha256": sha256})

    return entries


def load_inventory(path: Path) -> list[dict[str, str | int]]:
    """Load and validate an inventory JSON file."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise InvalidInventoryError(
            f"{path}: invalid JSON at line {error.lineno}, column {error.colno}"
        ) from error
    return _validate_entries(value, str(path))


def compare_inventories(before: Any, after: Any) -> dict[str, Any]:
    """Return a deterministic report of changes between two inventories."""

    before_entries = _validate_entries(before, "before inventory")
    after_entries = _validate_entries(after, "after inventory")
    before_by_path = {entry["path"]: entry for entry in before_entries}
    after_by_path = {entry["path"]: entry for entry in after_entries}

    before_paths = set(before_by_path)
    after_paths = set(after_by_path)
    added = [after_by_path[path] for path in sorted(after_paths - before_paths)]
    removed = [before_by_path[path] for path in sorted(before_paths - after_paths)]
    modified = []
    unchanged = 0
    for path in sorted(before_paths & after_paths):
        old = before_by_path[path]
        new = after_by_path[path]
        if old["size"] == new["size"] and old["sha256"] == new["sha256"]:
            unchanged += 1
            continue
        modified.append(
            {
                "path": path,
                "before": {"size": old["size"], "sha256": old["sha256"]},
                "after": {"size": new["size"], "sha256": new["sha256"]},
            }
        )

    return {
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "modified": len(modified),
            "unchanged": unchanged,
        },
        "added": added,
        "removed": removed,
        "modified": modified,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path, help="earlier inventory JSON file")
    parser.add_argument("after", type=Path, help="later inventory JSON file")
    parser.add_argument("--output", type=Path, help="write the JSON report to a file")
    args = parser.parse_args(argv)

    try:
        report = compare_inventories(
            load_inventory(args.before), load_inventory(args.after)
        )
        rendered = json.dumps(report, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
    except (InvalidInventoryError, OSError, UnicodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    summary = report["summary"]
    return int(any(summary[key] for key in ("added", "removed", "modified")))


if __name__ == "__main__":
    raise SystemExit(main())
