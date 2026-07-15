"""Create a deterministic, content-addressed directory inventory."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path, PurePosixPath


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_patterns(patterns: Sequence[str]) -> tuple[str, ...]:
    validated = []
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("exclude patterns must be non-empty strings")
        normalized = PurePosixPath(pattern)
        if (
            normalized.is_absolute()
            or pattern != normalized.as_posix()
            or ".." in normalized.parts
            or "\\" in pattern
            or pattern == "."
        ):
            raise ValueError(
                "exclude patterns must use normalized relative POSIX paths"
            )
        validated.append(pattern)
    return tuple(validated)


def _matches_pattern(path: PurePosixPath, patterns: Sequence[str]) -> bool:
    candidates = [path.as_posix()]
    candidates.extend(
        parent.as_posix() for parent in path.parents if parent != PurePosixPath(".")
    )
    return any(
        fnmatch.fnmatchcase(candidate, pattern)
        for candidate in candidates
        for pattern in patterns
    )


def build_inventory(
    root: Path,
    excluded_names: set[str] | None = None,
    *,
    exclude_patterns: Sequence[str] = (),
) -> list[dict[str, str | int]]:
    root = root.resolve()
    excluded = {".git", "__pycache__"} if excluded_names is None else excluded_names
    patterns = _validated_patterns(exclude_patterns)
    entries = []
    for path in sorted(root.rglob("*")):
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if (
            not path.is_file()
            or any(part in excluded for part in relative.parts)
            or _matches_pattern(relative, patterns)
        ):
            continue
        entries.append(
            {
                "path": relative.as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(build_inventory(args.root), indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
