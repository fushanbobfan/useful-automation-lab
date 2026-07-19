import stat
import tempfile
import unittest
import warnings
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import useful_automation_lab
from useful_automation_lab.zip_audit import audit_zip


class ZipAuditTests(unittest.TestCase):
    def write_zip(self, directory, entries, *, compression=ZIP_DEFLATED):
        path = Path(directory) / "archive.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with ZipFile(path, "w", compression=compression) as handle:
                for name, contents in entries:
                    handle.writestr(name, contents)
        return path

    def test_zip_audit_api_is_available_from_package(self):
        self.assertIs(useful_automation_lab.audit_zip, audit_zip)

    def test_safe_archive_passes_with_central_directory_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.write_zip(
                directory,
                [("docs/readme.txt", "hello"), ("data/value.txt", "42")],
            )

            report = audit_zip(archive)

        self.assertTrue(report["passed"])
        self.assertEqual(report["summary"]["entry_count"], 2)
        self.assertEqual(report["summary"]["file_count"], 2)
        self.assertEqual(report["summary"]["total_uncompressed_bytes"], 7)
        self.assertEqual(report["summary"]["issue_codes"], {})

    def test_reports_path_link_size_and_ratio_hazards(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "hazards.zip"
            symlink = ZipInfo("link")
            symlink.create_system = 3
            symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with ZipFile(archive, "w", compression=ZIP_DEFLATED) as handle:
                    handle.writestr("/absolute.txt", "a")
                    handle.writestr("../escape.txt", "b")
                    handle.writestr("folder\\file.txt", "c")
                    handle.writestr("duplicate.txt", "first")
                    handle.writestr("duplicate.txt", "second")
                    handle.writestr("Case.txt", "upper")
                    handle.writestr("case.txt", "lower")
                    handle.writestr(symlink, "target")
                    handle.writestr("large.txt", "x" * 400)
            archive.write_bytes(
                archive.read_bytes().replace(
                    b"folder/file.txt", b"folder\\file.txt"
                )
            )

            report = audit_zip(
                archive,
                max_entry_uncompressed_bytes=100,
                max_total_uncompressed_bytes=300,
                max_compression_ratio=5,
            )

        codes = [issue["code"] for issue in report["issues"]]
        self.assertFalse(report["passed"])
        for code in (
            "absolute_or_drive_path",
            "parent_traversal",
            "backslash_path",
            "duplicate_path",
            "case_collision",
            "symlink_entry",
            "entry_too_large",
            "compression_ratio_exceeded",
            "archive_too_large",
        ):
            with self.subTest(code=code):
                self.assertIn(code, codes)
        self.assertEqual(report["summary"]["issue_count"], len(codes))

    def test_issue_details_are_bounded_without_hiding_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.write_zip(
                directory,
                [("../one", "1"), ("../two", "2"), ("../three", "3")],
            )

            report = audit_zip(archive, max_errors=2)

        self.assertEqual(report["summary"]["issue_count"], 3)
        self.assertEqual(report["summary"]["reported_issues"], 2)
        self.assertEqual(report["summary"]["truncated_issues"], 1)
        self.assertEqual(len(report["issues"]), 2)

    def test_invalid_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.write_zip(directory, [("safe.txt", "value")])
            for name, value in (
                ("max_entry_uncompressed_bytes", 0),
                ("max_total_uncompressed_bytes", True),
                ("max_compression_ratio", float("inf")),
                ("max_errors", -1),
            ):
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(ValueError, name):
                        audit_zip(archive, **{name: value})


if __name__ == "__main__":
    unittest.main()
