"""Inspect ZIP archive metadata for extraction hazards without extracting files."""

from __future__ import annotations

import math
import stat
from collections import Counter
from pathlib import Path, PureWindowsPath
from typing import Any
from zipfile import ZipFile


def _positive_integer(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_number(name: str, value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be a finite positive number")
    return float(value)


def audit_zip(
    archive: Path,
    *,
    max_entry_uncompressed_bytes: int = 100 * 1024 * 1024,
    max_total_uncompressed_bytes: int = 1024 * 1024 * 1024,
    max_compression_ratio: float = 100.0,
    max_errors: int = 100,
) -> dict[str, Any]:
    """Return a bounded report based only on a ZIP central directory."""

    maximum_entry_bytes = _positive_integer(
        "max_entry_uncompressed_bytes", max_entry_uncompressed_bytes
    )
    maximum_total_bytes = _positive_integer(
        "max_total_uncompressed_bytes", max_total_uncompressed_bytes
    )
    maximum_ratio = _positive_number(
        "max_compression_ratio", max_compression_ratio
    )
    maximum_errors = _positive_integer("max_errors", max_errors)

    issues = []
    issue_count = 0
    issue_codes: Counter[str] = Counter()

    def add_issue(code: str, **details: Any) -> None:
        nonlocal issue_count
        issue_count += 1
        issue_codes[code] += 1
        if len(issues) < maximum_errors:
            issues.append({"code": code, **details})

    entry_count = 0
    file_count = 0
    directory_count = 0
    total_compressed_bytes = 0
    total_uncompressed_bytes = 0
    largest_entry_bytes = 0
    highest_finite_ratio = 0.0
    unbounded_ratio_entries = 0
    seen_names: dict[str, int] = {}
    logical_paths: dict[str, tuple[str, str, int]] = {}

    with ZipFile(archive) as handle:
        for entry_index, info in enumerate(handle.infolist(), start=1):
            entry_count += 1
            name = info.orig_filename
            is_directory = info.is_dir()
            if is_directory:
                directory_count += 1
            else:
                file_count += 1
            total_compressed_bytes += info.compress_size
            total_uncompressed_bytes += info.file_size
            largest_entry_bytes = max(largest_entry_bytes, info.file_size)

            path_is_unsafe = False
            if not name or "\x00" in name:
                add_issue("invalid_path", entry_index=entry_index, path=name)
                path_is_unsafe = True
            if name.startswith(("/", "\\")) or PureWindowsPath(name).drive:
                add_issue("absolute_or_drive_path", entry_index=entry_index, path=name)
                path_is_unsafe = True

            translated = name.replace("\\", "/")
            trimmed = translated[:-1] if translated.endswith("/") else translated
            parts = trimmed.split("/") if trimmed else []
            if "\\" in name:
                add_issue("backslash_path", entry_index=entry_index, path=name)
                path_is_unsafe = True
            if ".." in parts:
                add_issue("parent_traversal", entry_index=entry_index, path=name)
                path_is_unsafe = True
            if not parts or any(part in {"", "."} for part in parts):
                add_issue("non_normalized_path", entry_index=entry_index, path=name)
                path_is_unsafe = True

            if name in seen_names:
                add_issue(
                    "duplicate_path",
                    entry_index=entry_index,
                    path=name,
                    first_entry_index=seen_names[name],
                )
            else:
                seen_names[name] = entry_index

            if not path_is_unsafe:
                canonical = "/".join(parts)
                logical_key = canonical.casefold()
                previous = logical_paths.get(logical_key)
                if previous is not None and previous[1] != name:
                    previous_canonical, previous_name, previous_index = previous
                    add_issue(
                        (
                            "normalized_path_collision"
                            if previous_canonical == canonical
                            else "case_collision"
                        ),
                        entry_index=entry_index,
                        path=name,
                        first_path=previous_name,
                        first_entry_index=previous_index,
                    )
                elif previous is None:
                    logical_paths[logical_key] = (canonical, name, entry_index)

            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                add_issue("symlink_entry", entry_index=entry_index, path=name)
            if info.flag_bits & 0x1:
                add_issue("encrypted_entry", entry_index=entry_index, path=name)

            if not is_directory and info.file_size > maximum_entry_bytes:
                add_issue(
                    "entry_too_large",
                    entry_index=entry_index,
                    path=name,
                    actual_bytes=info.file_size,
                    maximum_bytes=maximum_entry_bytes,
                )

            if not is_directory and info.file_size:
                if info.compress_size == 0:
                    unbounded_ratio_entries += 1
                    add_issue(
                        "compression_ratio_exceeded",
                        entry_index=entry_index,
                        path=name,
                        actual_ratio=None,
                        maximum_ratio=maximum_ratio,
                        reason="non-empty entry has zero compressed bytes",
                    )
                else:
                    ratio = info.file_size / info.compress_size
                    highest_finite_ratio = max(highest_finite_ratio, ratio)
                    if ratio > maximum_ratio:
                        add_issue(
                            "compression_ratio_exceeded",
                            entry_index=entry_index,
                            path=name,
                            actual_ratio=ratio,
                            maximum_ratio=maximum_ratio,
                        )

    if total_uncompressed_bytes > maximum_total_bytes:
        add_issue(
            "archive_too_large",
            actual_bytes=total_uncompressed_bytes,
            maximum_bytes=maximum_total_bytes,
        )

    return {
        "passed": issue_count == 0,
        "summary": {
            "entry_count": entry_count,
            "file_count": file_count,
            "directory_count": directory_count,
            "total_compressed_bytes": total_compressed_bytes,
            "total_uncompressed_bytes": total_uncompressed_bytes,
            "largest_entry_uncompressed_bytes": largest_entry_bytes,
            "highest_finite_compression_ratio": highest_finite_ratio,
            "unbounded_compression_ratio_entries": unbounded_ratio_entries,
            "issue_count": issue_count,
            "reported_issues": len(issues),
            "truncated_issues": issue_count - len(issues),
            "issue_codes": dict(sorted(issue_codes.items())),
        },
        "configuration": {
            "max_entry_uncompressed_bytes": maximum_entry_bytes,
            "max_total_uncompressed_bytes": maximum_total_bytes,
            "max_compression_ratio": maximum_ratio,
            "max_errors": maximum_errors,
        },
        "issues": issues,
    }
