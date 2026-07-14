"""Verify a directory against a saved deterministic inventory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .compare import compare_inventories, load_inventory
from .inventory import build_inventory


def verify_directory(root: Path, manifest: Path) -> dict[str, Any]:
    """Compare a current directory with a validated inventory manifest."""

    if not root.is_dir():
        raise ValueError(f"directory does not exist: {root}")

    expected = load_inventory(manifest)
    current = build_inventory(root)
    expected_paths = {entry["path"] for entry in expected}

    try:
        manifest_relative = manifest.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        manifest_relative = None
    if manifest_relative and manifest_relative not in expected_paths:
        current = [entry for entry in current if entry["path"] != manifest_relative]

    return compare_inventories(expected, current)
