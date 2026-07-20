import tempfile
import unittest
from pathlib import Path

import useful_automation_lab
from useful_automation_lab.text_audit import audit_text_file


class TextAuditTests(unittest.TestCase):
    def test_reports_newline_and_line_hygiene_issues(self):
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "sample.txt"
            document.write_bytes(b"alpha \r\nbeta\nlast")

            report = audit_text_file(document, max_line_bytes=5)

        self.assertIs(useful_automation_lab.audit_text_file, audit_text_file)
        self.assertFalse(report["passed"])
        self.assertEqual(report["summary"]["line_count"], 3)
        self.assertEqual(report["summary"]["newline_style"], "mixed")
        self.assertEqual(report["summary"]["crlf_endings"], 1)
        self.assertEqual(report["summary"]["lf_endings"], 1)
        self.assertEqual(report["summary"]["bare_cr_endings"], 0)
        self.assertFalse(report["summary"]["has_final_newline"])
        self.assertEqual(report["summary"]["trailing_whitespace_lines"], 1)
        self.assertEqual(report["summary"]["maximum_line_bytes"], 6)
        self.assertEqual(
            report["summary"]["issue_codes"],
            {
                "line_too_large": 1,
                "missing_final_newline": 1,
                "mixed_newlines": 1,
                "trailing_whitespace": 1,
            },
        )

    def test_reports_encoding_bom_nul_and_bare_cr_issues(self):
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "sample.txt"
            document.write_bytes(b"\xef\xbb\xbfalpha\x00\xff\r")

            report = audit_text_file(document)

        self.assertEqual(
            report["summary"]["issue_codes"],
            {
                "bare_cr_newline": 1,
                "invalid_utf8": 1,
                "nul_bytes": 1,
                "utf8_bom": 1,
            },
        )
        self.assertEqual(report["summary"]["newline_style"], "cr")
        self.assertTrue(report["summary"]["has_final_newline"])

    def test_bom_and_missing_final_newline_can_be_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "sample.txt"
            document.write_bytes(b"\xef\xbb\xbfalpha")

            report = audit_text_file(
                document,
                allow_utf8_bom=True,
                require_final_newline=False,
            )

        self.assertTrue(report["passed"])
        self.assertTrue(report["summary"]["has_utf8_bom"])

    def test_detailed_issues_are_bounded_without_losing_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "sample.txt"
            document.write_bytes(b"one \ntwo \nthree ")

            report = audit_text_file(document, max_errors=2)

        self.assertEqual(report["summary"]["issue_count"], 4)
        self.assertEqual(report["summary"]["reported_issues"], 2)
        self.assertEqual(report["summary"]["truncated_issues"], 2)

    def test_size_limit_and_invalid_configuration_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "sample.txt"
            document.write_bytes(b"hello")

            with self.assertRaisesRegex(ValueError, "exceeds"):
                audit_text_file(document, max_file_bytes=4)
            for value in (0, -1, True, "large"):
                with self.subTest(value=value):
                    with self.assertRaisesRegex(ValueError, "positive integer"):
                        audit_text_file(document, max_errors=value)


if __name__ == "__main__":
    unittest.main()
