"""Audit text-file encoding and line hygiene without changing the file."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _positive_integer(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _optional_positive_integer(name: str, value: int | None) -> int | None:
    if value is None:
        return None
    return _positive_integer(name, value)


def audit_text_file(
    path: Path,
    *,
    max_file_bytes: int = 10 * 1024 * 1024,
    max_line_bytes: int | None = None,
    max_errors: int = 100,
    allow_utf8_bom: bool = False,
    require_final_newline: bool = True,
) -> dict[str, Any]:
    """Return a bounded report for one UTF-8 text file."""

    maximum_file_bytes = _positive_integer("max_file_bytes", max_file_bytes)
    maximum_line_bytes = _optional_positive_integer(
        "max_line_bytes", max_line_bytes
    )
    maximum_errors = _positive_integer("max_errors", max_errors)
    if not isinstance(allow_utf8_bom, bool):
        raise ValueError("allow_utf8_bom must be a boolean")
    if not isinstance(require_final_newline, bool):
        raise ValueError("require_final_newline must be a boolean")

    with path.open("rb") as handle:
        data = handle.read(maximum_file_bytes + 1)
    if len(data) > maximum_file_bytes:
        raise ValueError(f"file exceeds max_file_bytes ({maximum_file_bytes})")

    issues = []
    issue_count = 0
    issue_codes: Counter[str] = Counter()

    def add_issue(code: str, **details: Any) -> None:
        nonlocal issue_count
        issue_count += 1
        issue_codes[code] += 1
        if len(issues) < maximum_errors:
            issues.append({"code": code, **details})

    has_bom = data.startswith(b"\xef\xbb\xbf")
    if has_bom and not allow_utf8_bom:
        add_issue("utf8_bom")
    nul_bytes = data.count(b"\x00")
    if nul_bytes:
        add_issue("nul_bytes", count=nul_bytes)
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as error:
        add_issue("invalid_utf8", byte_offset=error.start)

    crlf_endings = data.count(b"\r\n")
    lf_endings = data.count(b"\n") - crlf_endings
    bare_cr_endings = data.count(b"\r") - crlf_endings
    ending_styles = [
        name
        for name, count in (
            ("lf", lf_endings),
            ("crlf", crlf_endings),
            ("cr", bare_cr_endings),
        )
        if count
    ]
    newline_style = (
        "none"
        if not ending_styles
        else ending_styles[0]
        if len(ending_styles) == 1
        else "mixed"
    )
    if len(ending_styles) > 1:
        add_issue("mixed_newlines", styles=ending_styles)
    if bare_cr_endings:
        add_issue("bare_cr_newline", count=bare_cr_endings)

    has_final_newline = not data or data.endswith((b"\n", b"\r"))
    if require_final_newline and not has_final_newline:
        add_issue("missing_final_newline")

    lines = re.split(br"\r\n|\r|\n", data) if data else []
    if lines and has_final_newline:
        lines = lines[:-1]
    trailing_whitespace_lines = 0
    maximum_observed_line_bytes = 0
    for line_number, line in enumerate(lines, start=1):
        maximum_observed_line_bytes = max(maximum_observed_line_bytes, len(line))
        if line.endswith((b" ", b"\t")):
            trailing_whitespace_lines += 1
            add_issue("trailing_whitespace", line=line_number)
        if maximum_line_bytes is not None and len(line) > maximum_line_bytes:
            add_issue(
                "line_too_large",
                line=line_number,
                actual_bytes=len(line),
                maximum_bytes=maximum_line_bytes,
            )

    return {
        "passed": issue_count == 0,
        "summary": {
            "byte_count": len(data),
            "line_count": len(lines),
            "newline_style": newline_style,
            "lf_endings": lf_endings,
            "crlf_endings": crlf_endings,
            "bare_cr_endings": bare_cr_endings,
            "has_final_newline": has_final_newline,
            "has_utf8_bom": has_bom,
            "nul_bytes": nul_bytes,
            "trailing_whitespace_lines": trailing_whitespace_lines,
            "maximum_line_bytes": maximum_observed_line_bytes,
            "issue_count": issue_count,
            "reported_issues": len(issues),
            "truncated_issues": issue_count - len(issues),
            "issue_codes": dict(sorted(issue_codes.items())),
        },
        "configuration": {
            "max_file_bytes": maximum_file_bytes,
            "max_line_bytes": maximum_line_bytes,
            "max_errors": maximum_errors,
            "allow_utf8_bom": allow_utf8_bom,
            "require_final_newline": require_final_newline,
        },
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--max-file-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--max-line-bytes", type=int)
    parser.add_argument("--max-errors", type=int, default=100)
    parser.add_argument("--allow-utf8-bom", action="store_true")
    parser.add_argument("--allow-missing-final-newline", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        report = audit_text_file(
            args.document,
            max_file_bytes=args.max_file_bytes,
            max_line_bytes=args.max_line_bytes,
            max_errors=args.max_errors,
            allow_utf8_bom=args.allow_utf8_bom,
            require_final_newline=not args.allow_missing_final_newline,
        )
        rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
    except (OSError, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
