"""Inspect TAR metadata for extraction hazards without extracting members."""

from __future__ import annotations

import math
import posixpath
from collections import Counter
from pathlib import Path, PureWindowsPath
from tarfile import open as open_tar
from typing import Any


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


def _path_parts(name: str) -> tuple[list[str], bool]:
    translated = name.replace("\\", "/")
    trimmed = translated[:-1] if translated.endswith("/") else translated
    return (trimmed.split("/") if trimmed else []), "\\" in name


def _unsafe_link_target(member_name: str, target: str, *, symbolic: bool) -> bool:
    if (
        not target
        or "\x00" in target
        or target.startswith(("/", "\\"))
        or PureWindowsPath(target).drive
        or "\\" in target
    ):
        return True
    target_parts = target.split("/")
    if any(part in {"", "."} for part in target_parts):
        return True
    base = posixpath.dirname(member_name) if symbolic else ""
    combined = posixpath.normpath(posixpath.join(base, target))
    return combined == ".." or combined.startswith("../") or combined.startswith("/")


def audit_tar(
    archive: Path,
    *,
    max_archive_bytes: int = 512 * 1024 * 1024,
    max_member_bytes: int = 100 * 1024 * 1024,
    max_total_bytes: int = 1024 * 1024 * 1024,
    max_members: int = 10_000,
    max_expansion_ratio: float = 100.0,
    max_errors: int = 100,
) -> dict[str, Any]:
    """Return a bounded report based on TAR headers without extracting members."""

    maximum_archive_bytes = _positive_integer(
        "max_archive_bytes", max_archive_bytes
    )
    maximum_member_bytes = _positive_integer("max_member_bytes", max_member_bytes)
    maximum_total_bytes = _positive_integer("max_total_bytes", max_total_bytes)
    maximum_members = _positive_integer("max_members", max_members)
    maximum_ratio = _positive_number("max_expansion_ratio", max_expansion_ratio)
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

    archive_bytes = archive.stat().st_size
    if archive_bytes > maximum_archive_bytes:
        add_issue(
            "archive_file_too_large",
            actual_bytes=archive_bytes,
            maximum_bytes=maximum_archive_bytes,
        )
        return {
            "passed": False,
            "summary": {
                "archive_bytes": archive_bytes,
                "inspected_members": 0,
                "file_count": 0,
                "directory_count": 0,
                "symbolic_link_count": 0,
                "hard_link_count": 0,
                "special_file_count": 0,
                "other_member_count": 0,
                "total_file_bytes": 0,
                "largest_member_bytes": 0,
                "expansion_ratio": None,
                "inspection_truncated": True,
                "issue_count": issue_count,
                "reported_issues": len(issues),
                "truncated_issues": issue_count - len(issues),
                "issue_codes": dict(sorted(issue_codes.items())),
            },
            "configuration": {
                "max_archive_bytes": maximum_archive_bytes,
                "max_member_bytes": maximum_member_bytes,
                "max_total_bytes": maximum_total_bytes,
                "max_members": maximum_members,
                "max_expansion_ratio": maximum_ratio,
                "max_errors": maximum_errors,
            },
            "issues": issues,
        }

    inspected_members = 0
    file_count = 0
    directory_count = 0
    symbolic_link_count = 0
    hard_link_count = 0
    special_file_count = 0
    other_member_count = 0
    total_file_bytes = 0
    largest_member_bytes = 0
    inspection_truncated = False
    seen_names: dict[str, int] = {}
    logical_paths: dict[str, tuple[str, str, int]] = {}

    with open_tar(archive, mode="r:*") as handle:
        for member_index, member in enumerate(handle, start=1):
            if member_index > maximum_members:
                inspection_truncated = True
                add_issue(
                    "member_count_exceeded",
                    inspected_members=inspected_members,
                    maximum_members=maximum_members,
                )
                break
            inspected_members += 1
            name = member.name
            path_is_unsafe = False
            if not name or "\x00" in name:
                add_issue("invalid_path", member_index=member_index, path=name)
                path_is_unsafe = True
            if name.startswith(("/", "\\")) or PureWindowsPath(name).drive:
                add_issue(
                    "absolute_or_drive_path",
                    member_index=member_index,
                    path=name,
                )
                path_is_unsafe = True

            parts, has_backslash = _path_parts(name)
            if has_backslash:
                add_issue("backslash_path", member_index=member_index, path=name)
                path_is_unsafe = True
            if ".." in parts:
                add_issue("parent_traversal", member_index=member_index, path=name)
                path_is_unsafe = True
            if not parts or any(part in {"", "."} for part in parts):
                add_issue(
                    "non_normalized_path",
                    member_index=member_index,
                    path=name,
                )
                path_is_unsafe = True

            if name in seen_names:
                add_issue(
                    "duplicate_path",
                    member_index=member_index,
                    path=name,
                    first_member_index=seen_names[name],
                )
            else:
                seen_names[name] = member_index

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
                        member_index=member_index,
                        path=name,
                        first_path=previous_name,
                        first_member_index=previous_index,
                    )
                elif previous is None:
                    logical_paths[logical_key] = (
                        canonical,
                        name,
                        member_index,
                    )

            if member.isfile():
                file_count += 1
                total_file_bytes += member.size
                largest_member_bytes = max(largest_member_bytes, member.size)
                if member.size > maximum_member_bytes:
                    add_issue(
                        "member_too_large",
                        member_index=member_index,
                        path=name,
                        actual_bytes=member.size,
                        maximum_bytes=maximum_member_bytes,
                    )
            elif member.isdir():
                directory_count += 1
            elif member.issym():
                symbolic_link_count += 1
                add_issue(
                    "symbolic_link_entry",
                    member_index=member_index,
                    path=name,
                    target=member.linkname,
                )
                if _unsafe_link_target(name, member.linkname, symbolic=True):
                    add_issue(
                        "unsafe_link_target",
                        member_index=member_index,
                        path=name,
                        target=member.linkname,
                    )
            elif member.islnk():
                hard_link_count += 1
                add_issue(
                    "hard_link_entry",
                    member_index=member_index,
                    path=name,
                    target=member.linkname,
                )
                if _unsafe_link_target(name, member.linkname, symbolic=False):
                    add_issue(
                        "unsafe_link_target",
                        member_index=member_index,
                        path=name,
                        target=member.linkname,
                    )
            elif member.ischr() or member.isblk() or member.isfifo():
                special_file_count += 1
                kind = (
                    "character_device"
                    if member.ischr()
                    else "block_device"
                    if member.isblk()
                    else "fifo"
                )
                add_issue(
                    "special_file_entry",
                    member_index=member_index,
                    path=name,
                    member_type=kind,
                )
            else:
                other_member_count += 1
                add_issue(
                    "unsupported_member_type",
                    member_index=member_index,
                    path=name,
                    type_code=member.type.decode("ascii", errors="backslashreplace"),
                )

    if total_file_bytes > maximum_total_bytes:
        add_issue(
            "archive_contents_too_large",
            actual_bytes=total_file_bytes,
            maximum_bytes=maximum_total_bytes,
        )
    expansion_ratio = (
        total_file_bytes / archive_bytes
        if archive_bytes > 0 and not inspection_truncated
        else None
    )
    if expansion_ratio is not None and expansion_ratio > maximum_ratio:
        add_issue(
            "expansion_ratio_exceeded",
            actual_ratio=expansion_ratio,
            maximum_ratio=maximum_ratio,
        )

    return {
        "passed": issue_count == 0,
        "summary": {
            "archive_bytes": archive_bytes,
            "inspected_members": inspected_members,
            "file_count": file_count,
            "directory_count": directory_count,
            "symbolic_link_count": symbolic_link_count,
            "hard_link_count": hard_link_count,
            "special_file_count": special_file_count,
            "other_member_count": other_member_count,
            "total_file_bytes": total_file_bytes,
            "largest_member_bytes": largest_member_bytes,
            "expansion_ratio": expansion_ratio,
            "inspection_truncated": inspection_truncated,
            "issue_count": issue_count,
            "reported_issues": len(issues),
            "truncated_issues": issue_count - len(issues),
            "issue_codes": dict(sorted(issue_codes.items())),
        },
        "configuration": {
            "max_archive_bytes": maximum_archive_bytes,
            "max_member_bytes": maximum_member_bytes,
            "max_total_bytes": maximum_total_bytes,
            "max_members": maximum_members,
            "max_expansion_ratio": maximum_ratio,
            "max_errors": maximum_errors,
        },
        "issues": issues,
    }
