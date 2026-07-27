import contextlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

import useful_automation_lab
from useful_automation_lab.tar_audit import audit_tar, main


class TarAuditTests(unittest.TestCase):
    def write_tar(self, directory, entries, *, mode="w"):
        archive = Path(directory) / (
            "archive.tar.gz" if mode.endswith(":gz") else "archive.tar"
        )
        with tarfile.open(archive, mode) as handle:
            for name, contents in entries:
                payload = contents.encode()
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                handle.addfile(info, io.BytesIO(payload))
        return archive

    def test_safe_archive_passes_with_header_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.write_tar(
                directory,
                [("docs/readme.txt", "hello"), ("data/value.txt", "42")],
            )

            report = audit_tar(archive)

        self.assertIs(useful_automation_lab.audit_tar, audit_tar)
        self.assertTrue(report["passed"])
        self.assertEqual(report["summary"]["inspected_members"], 2)
        self.assertEqual(report["summary"]["file_count"], 2)
        self.assertEqual(report["summary"]["total_file_bytes"], 7)
        self.assertFalse(report["summary"]["inspection_truncated"])
        self.assertEqual(report["summary"]["issue_codes"], {})

    def test_reports_path_link_special_file_and_size_hazards(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "hazards.tar.gz"
            with tarfile.open(archive, "w:gz") as handle:
                for name, contents in (
                    ("/absolute.txt", b"a"),
                    ("../escape.txt", b"b"),
                    ("folder\\file.txt", b"c"),
                    ("duplicate.txt", b"first"),
                    ("duplicate.txt", b"second"),
                    ("Case.txt", b"upper"),
                    ("case.txt", b"lower"),
                    ("large.txt", b"x" * 50_000),
                ):
                    info = tarfile.TarInfo(name)
                    info.size = len(contents)
                    handle.addfile(info, io.BytesIO(contents))

                symbolic = tarfile.TarInfo("links/symbolic")
                symbolic.type = tarfile.SYMTYPE
                symbolic.linkname = "../../outside"
                handle.addfile(symbolic)

                hard = tarfile.TarInfo("links/hard")
                hard.type = tarfile.LNKTYPE
                hard.linkname = "../outside"
                handle.addfile(hard)

                fifo = tarfile.TarInfo("named-pipe")
                fifo.type = tarfile.FIFOTYPE
                handle.addfile(fifo)

            report = audit_tar(
                archive,
                max_member_bytes=100,
                max_total_bytes=300,
                max_expansion_ratio=2,
            )

        codes = [issue["code"] for issue in report["issues"]]
        self.assertFalse(report["passed"])
        for code in (
            "absolute_or_drive_path",
            "parent_traversal",
            "backslash_path",
            "duplicate_path",
            "case_collision",
            "symbolic_link_entry",
            "hard_link_entry",
            "unsafe_link_target",
            "special_file_entry",
            "member_too_large",
            "archive_contents_too_large",
            "expansion_ratio_exceeded",
        ):
            with self.subTest(code=code):
                self.assertIn(code, codes)

    def test_member_limit_stops_header_scan_and_marks_totals_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.write_tar(
                directory,
                [("one.txt", "1"), ("two.txt", "2"), ("three.txt", "3")],
            )

            report = audit_tar(archive, max_members=2)

        self.assertFalse(report["passed"])
        self.assertEqual(report["summary"]["inspected_members"], 2)
        self.assertTrue(report["summary"]["inspection_truncated"])
        self.assertIsNone(report["summary"]["expansion_ratio"])
        self.assertEqual(
            report["summary"]["issue_codes"],
            {"member_count_exceeded": 1},
        )

    def test_issue_details_are_bounded_without_hiding_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.write_tar(
                directory,
                [("../one", "1"), ("../two", "2"), ("../three", "3")],
            )

            report = audit_tar(archive, max_errors=2)

        self.assertEqual(report["summary"]["issue_count"], 3)
        self.assertEqual(report["summary"]["reported_issues"], 2)
        self.assertEqual(report["summary"]["truncated_issues"], 1)

    def test_oversized_archive_is_not_opened(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.write_tar(directory, [("safe.txt", "value")])

            report = audit_tar(archive, max_archive_bytes=1)

        self.assertFalse(report["passed"])
        self.assertEqual(report["summary"]["inspected_members"], 0)
        self.assertTrue(report["summary"]["inspection_truncated"])
        self.assertEqual(
            report["summary"]["issue_codes"],
            {"archive_file_too_large": 1},
        )

    def test_invalid_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.write_tar(directory, [("safe.txt", "value")])
            for name, value in (
                ("max_archive_bytes", 0),
                ("max_member_bytes", True),
                ("max_total_bytes", -1),
                ("max_members", 0),
                ("max_expansion_ratio", float("inf")),
                ("max_errors", 0),
            ):
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(ValueError, name):
                        audit_tar(archive, **{name: value})

    def test_cli_writes_a_passing_report(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.write_tar(directory, [("safe.txt", "value")])
            output = Path(directory) / "report.json"

            exit_code = main([str(archive), "--output", str(output)])

            self.assertEqual(exit_code, 0)
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["passed"])

    def test_cli_returns_one_for_archive_hazards(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.write_tar(directory, [("../escape.txt", "value")])
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = main([str(archive)])

            self.assertEqual(exit_code, 1)
            self.assertEqual(
                json.loads(stdout.getvalue())["issues"][0]["code"],
                "parent_traversal",
            )

    def test_cli_returns_two_for_invalid_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "not-a-tar.tar"
            archive.write_text("not a tar", encoding="utf-8")

            with contextlib.redirect_stderr(io.StringIO()):
                exit_code = main([str(archive)])

            self.assertEqual(exit_code, 2)

    def test_cli_refuses_direct_and_hard_link_output_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.write_tar(directory, [("safe.txt", "value")])
            hard_link = Path(directory) / "archive-link.tar"
            os.link(archive, hard_link)

            for output in (archive, hard_link):
                with self.subTest(output=output):
                    with contextlib.redirect_stderr(io.StringIO()):
                        exit_code = main(
                            [str(archive), "--output", str(output)]
                        )
                    self.assertEqual(exit_code, 2)

            self.assertTrue(audit_tar(archive)["passed"])


if __name__ == "__main__":
    unittest.main()
