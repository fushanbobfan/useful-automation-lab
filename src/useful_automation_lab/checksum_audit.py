"""Verify a portable SHA-256 checksum file without modifying artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any


_CHECKSUM_LINE = re.compile(r"([0-9A-Fa-f]{64}) ([ *])(.+)")


def _positive_integer(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _validate_limits(
    *,
    max_checksum_bytes: int,
    max_entries: int,
    max_file_bytes: int,
    max_total_bytes: int,
    max_errors: int,
) -> dict[str, int]:
    return {
        "max_checksum_bytes": _positive_integer(
            "max_checksum_bytes", max_checksum_bytes
        ),
        "max_entries": _positive_integer("max_entries", max_entries),
        "max_file_bytes": _positive_integer("max_file_bytes", max_file_bytes),
        "max_total_bytes": _positive_integer("max_total_bytes", max_total_bytes),
        "max_errors": _positive_integer("max_errors", max_errors),
    }


def _validate_relative_path(value: str, *, line_number: int) -> str:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value != path.as_posix()
        or value == "."
        or ".." in path.parts
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(
            f"checksum line {line_number} path must be a normalized relative POSIX path"
        )
    return value


def _load_checksum_file(
    path: Path, *, max_checksum_bytes: int, max_entries: int
) -> list[dict[str, str]]:
    with path.open("rb") as handle:
        data = handle.read(max_checksum_bytes + 1)
    if len(data) > max_checksum_bytes:
        raise ValueError(
            f"checksum file exceeds max_checksum_bytes ({max_checksum_bytes})"
        )
    text = data.decode("utf-8")
    lines = text.splitlines()
    if not lines:
        raise ValueError("checksum file must contain at least one entry")

    entries = []
    seen_paths: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line:
            raise ValueError(f"checksum line {line_number} must not be blank")
        match = _CHECKSUM_LINE.fullmatch(line)
        if match is None:
            raise ValueError(
                f"checksum line {line_number} must use SHA256<space><space-or-star>path"
            )
        digest, _, raw_path = match.groups()
        relative_path = _validate_relative_path(raw_path, line_number=line_number)
        if relative_path in seen_paths:
            raise ValueError(f"checksum line {line_number} repeats path {relative_path!r}")
        seen_paths.add(relative_path)
        entries.append({"path": relative_path, "sha256": digest.lower()})
        if len(entries) > max_entries:
            raise ValueError(f"checksum file exceeds max_entries ({max_entries})")
    return entries


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _has_symlink_component(root: Path, relative_path: str) -> bool:
    current = root
    for part in PurePosixPath(relative_path).parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _audit_entries(
    root: Path,
    entries: list[dict[str, str]],
    *,
    limits: dict[str, int],
) -> dict[str, Any]:
    if not root.is_dir():
        raise ValueError(f"directory does not exist: {root}")
    resolved_root = root.resolve()
    issues = []
    issue_codes: Counter[str] = Counter()
    issue_count = 0
    matched_files = 0
    mismatched_files = 0
    missing_files = 0
    unsafe_files = 0
    bytes_hashed = 0
    entries_processed = 0
    stopped_early = False

    def add_issue(code: str, path: str, **details: Any) -> None:
        nonlocal issue_count
        issue_count += 1
        issue_codes[code] += 1
        if len(issues) < limits["max_errors"]:
            issues.append({"code": code, "path": path, **details})

    for entry in sorted(entries, key=lambda item: item["path"]):
        relative_path = entry["path"]
        target = root.joinpath(*PurePosixPath(relative_path).parts)
        if _has_symlink_component(root, relative_path):
            unsafe_files += 1
            add_issue("symlink_path", relative_path)
            entries_processed += 1
            continue
        if not target.exists():
            missing_files += 1
            add_issue("missing_file", relative_path)
            entries_processed += 1
            continue
        if not target.is_file():
            unsafe_files += 1
            add_issue("not_regular_file", relative_path)
            entries_processed += 1
            continue
        try:
            target.resolve().relative_to(resolved_root)
        except ValueError:
            unsafe_files += 1
            add_issue("path_escapes_root", relative_path)
            entries_processed += 1
            continue

        size = target.stat().st_size
        if size > limits["max_file_bytes"]:
            unsafe_files += 1
            add_issue(
                "file_too_large",
                relative_path,
                actual_bytes=size,
                maximum_bytes=limits["max_file_bytes"],
            )
            entries_processed += 1
            continue
        if bytes_hashed + size > limits["max_total_bytes"]:
            add_issue(
                "total_byte_budget_exceeded",
                relative_path,
                bytes_hashed=bytes_hashed,
                next_file_bytes=size,
                maximum_bytes=limits["max_total_bytes"],
            )
            entries_processed += 1
            stopped_early = True
            break

        actual_digest = _sha256(target)
        bytes_hashed += size
        entries_processed += 1
        if actual_digest == entry["sha256"]:
            matched_files += 1
        else:
            mismatched_files += 1
            add_issue(
                "sha256_mismatch",
                relative_path,
                expected_sha256=entry["sha256"],
                actual_sha256=actual_digest,
            )

    return {
        "passed": issue_count == 0,
        "summary": {
            "listed_files": len(entries),
            "entries_processed": entries_processed,
            "entries_unprocessed": len(entries) - entries_processed,
            "matched_files": matched_files,
            "mismatched_files": mismatched_files,
            "missing_files": missing_files,
            "unsafe_files": unsafe_files,
            "bytes_hashed": bytes_hashed,
            "stopped_early": stopped_early,
            "issue_count": issue_count,
            "reported_issues": len(issues),
            "truncated_issues": issue_count - len(issues),
            "issue_codes": dict(sorted(issue_codes.items())),
        },
        "configuration": limits,
        "issues": issues,
    }


def audit_sha256_checksums(
    root: Path,
    checksum_file: Path,
    *,
    max_checksum_bytes: int = 1024 * 1024,
    max_entries: int = 10_000,
    max_file_bytes: int = 1024 * 1024 * 1024,
    max_total_bytes: int = 4 * 1024 * 1024 * 1024,
    max_errors: int = 100,
) -> dict[str, Any]:
    """Verify strict portable SHA-256 entries under one directory."""

    limits = _validate_limits(
        max_checksum_bytes=max_checksum_bytes,
        max_entries=max_entries,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
        max_errors=max_errors,
    )
    entries = _load_checksum_file(
        checksum_file,
        max_checksum_bytes=limits["max_checksum_bytes"],
        max_entries=limits["max_entries"],
    )
    return _audit_entries(root, entries, limits=limits)


def _paths_alias(first: Path, second: Path) -> bool:
    if first.resolve() == second.resolve():
        return True
    try:
        return first.samefile(second)
    except (FileNotFoundError, OSError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("checksums", type=Path)
    parser.add_argument("--max-checksum-bytes", type=int, default=1024 * 1024)
    parser.add_argument("--max-entries", type=int, default=10_000)
    parser.add_argument("--max-file-bytes", type=int, default=1024 * 1024 * 1024)
    parser.add_argument("--max-total-bytes", type=int, default=4 * 1024 * 1024 * 1024)
    parser.add_argument("--max-errors", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        limits = _validate_limits(
            max_checksum_bytes=args.max_checksum_bytes,
            max_entries=args.max_entries,
            max_file_bytes=args.max_file_bytes,
            max_total_bytes=args.max_total_bytes,
            max_errors=args.max_errors,
        )
        entries = _load_checksum_file(
            args.checksums,
            max_checksum_bytes=limits["max_checksum_bytes"],
            max_entries=limits["max_entries"],
        )
        if args.output is not None:
            if _paths_alias(args.checksums, args.output):
                raise ValueError("output must not alias the checksum file")
            for entry in entries:
                target = args.root.joinpath(*PurePosixPath(entry["path"]).parts)
                if _paths_alias(target, args.output):
                    raise ValueError("output must not alias a listed artifact")
        report = _audit_entries(args.root, entries, limits=limits)
        rendered = json.dumps(report, indent=2) + "\n"
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
