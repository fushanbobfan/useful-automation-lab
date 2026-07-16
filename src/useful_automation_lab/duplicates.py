"""Find duplicate file content in a validated inventory."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .compare import _validate_entries


def find_duplicates(inventory: Any, *, min_size: int = 1) -> dict[str, Any]:
    """Group matching size and SHA-256 entries without touching source files."""

    if type(min_size) is not int or min_size < 0:
        raise ValueError("min_size must be a non-negative integer")
    entries = _validate_entries(inventory, "inventory")
    grouped: dict[tuple[int, str], list[str]] = defaultdict(list)
    for entry in entries:
        size = entry["size"]
        if size >= min_size:
            grouped[(size, entry["sha256"])].append(entry["path"])

    groups = []
    for (size, sha256), paths in grouped.items():
        if len(paths) < 2:
            continue
        ordered_paths = sorted(paths)
        groups.append(
            {
                "sha256": sha256,
                "size": size,
                "count": len(ordered_paths),
                "reclaimable_bytes": size * (len(ordered_paths) - 1),
                "paths": ordered_paths,
            }
        )
    groups.sort(
        key=lambda group: (
            -group["reclaimable_bytes"],
            -group["size"],
            group["sha256"],
            group["paths"],
        )
    )

    return {
        "summary": {
            "scanned_files": len(entries),
            "eligible_files": sum(entry["size"] >= min_size for entry in entries),
            "duplicate_groups": len(groups),
            "duplicate_files": sum(group["count"] for group in groups),
            "reclaimable_bytes": sum(group["reclaimable_bytes"] for group in groups),
        },
        "min_size": min_size,
        "groups": groups,
    }
