"""Verify a directory against a saved deterministic inventory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .compare import InvalidInventoryError, compare_inventories, load_inventory
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="directory to verify")
    parser.add_argument("manifest", type=Path, help="saved inventory JSON file")
    parser.add_argument("--output", type=Path, help="write the JSON report to a file")
    args = parser.parse_args(argv)

    try:
        report = verify_directory(args.root, args.manifest)
        rendered = json.dumps(report, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
    except (InvalidInventoryError, OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    summary = report["summary"]
    return int(any(summary[key] for key in ("added", "removed", "modified")))


if __name__ == "__main__":
    raise SystemExit(main())
