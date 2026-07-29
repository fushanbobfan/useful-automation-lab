"""Audit inventory paths for common cross-platform portability hazards."""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from .compare import InvalidInventoryError, _validate_entries, load_inventory


_WINDOWS_FORBIDDEN = frozenset('<>:"|?*')
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _collision_code(first: str, second: str) -> str:
    first_nfc = unicodedata.normalize("NFC", first)
    second_nfc = unicodedata.normalize("NFC", second)
    if first.casefold() == second.casefold():
        return "case_collision"
    if first_nfc == second_nfc:
        return "unicode_normalization_collision"
    return "case_unicode_collision"


def audit_path_portability(inventory: Any) -> dict[str, Any]:
    """Return deterministic path hazards without touching the source directory."""

    entries = _validate_entries(inventory, "inventory")
    issues = []
    issue_codes: Counter[str] = Counter()
    affected_paths: set[str] = set()

    def add_issue(code: str, path: str, **details: Any) -> None:
        issue_codes[code] += 1
        affected_paths.add(path)
        first_path = details.get("first_path")
        if isinstance(first_path, str):
            affected_paths.add(first_path)
        issues.append({"code": code, "path": path, **details})

    portable_paths: dict[str, str] = {}
    for entry in sorted(entries, key=lambda item: item["path"]):
        path = str(entry["path"])
        for component_index, component in enumerate(PurePosixPath(path).parts):
            control_characters = sorted(
                {
                    f"U+{ord(character):04X}"
                    for character in component
                    if ord(character) < 32 or ord(character) == 127
                }
            )
            if control_characters:
                add_issue(
                    "control_character",
                    path,
                    component=component,
                    component_index=component_index,
                    characters=control_characters,
                )
            forbidden = "".join(
                sorted({character for character in component if character in _WINDOWS_FORBIDDEN})
            )
            if forbidden:
                add_issue(
                    "windows_forbidden_character",
                    path,
                    component=component,
                    component_index=component_index,
                    characters=forbidden,
                )
            if component.endswith((" ", ".")):
                add_issue(
                    "windows_trailing_space_or_dot",
                    path,
                    component=component,
                    component_index=component_index,
                )
            windows_stem = component.rstrip(" .").split(".", 1)[0].upper()
            if windows_stem in _WINDOWS_RESERVED:
                add_issue(
                    "windows_reserved_name",
                    path,
                    component=component,
                    component_index=component_index,
                    reserved_name=windows_stem,
                )

        portable_key = unicodedata.normalize("NFC", path).casefold()
        first_path = portable_paths.get(portable_key)
        if first_path is not None and first_path != path:
            add_issue(
                _collision_code(first_path, path),
                path,
                first_path=first_path,
            )
        elif first_path is None:
            portable_paths[portable_key] = path

    return {
        "passed": not issues,
        "summary": {
            "files": len(entries),
            "issue_count": len(issues),
            "affected_path_count": len(affected_paths),
            "issue_codes": dict(sorted(issue_codes.items())),
        },
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        report = audit_path_portability(load_inventory(args.inventory))
        rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.output is None:
            print(rendered, end="")
        else:
            args.output.write_text(rendered, encoding="utf-8")
    except (InvalidInventoryError, OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
