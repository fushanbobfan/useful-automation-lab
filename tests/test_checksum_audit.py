import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import useful_automation_lab
from useful_automation_lab.checksum_audit import audit_sha256_checksums, main


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ChecksumAuditTests(unittest.TestCase):
    def write_checksum(self, path: Path, entries: list[tuple[str, str]]) -> None:
        path.write_text(
            "".join(f"{digest}  {name}\n" for digest, name in entries),
            encoding="utf-8",
        )

    def test_checksum_audit_api_is_available_from_package(self):
        self.assertIs(
            useful_automation_lab.audit_sha256_checksums,
            audit_sha256_checksums,
        )

    def test_reports_matches_mismatches_and_missing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "release"
            root.mkdir()
            (root / "good.bin").write_bytes(b"stable")
            (root / "changed.bin").write_bytes(b"after")
            checksums = Path(directory) / "checksums.sha256"
            self.write_checksum(
                checksums,
                [
                    (sha256_bytes(b"before"), "changed.bin"),
                    (sha256_bytes(b"stable"), "good.bin"),
                    (sha256_bytes(b"missing"), "missing.bin"),
                ],
            )

            report = audit_sha256_checksums(root, checksums)

            self.assertFalse(report["passed"])
            self.assertEqual(report["summary"]["listed_files"], 3)
            self.assertEqual(report["summary"]["matched_files"], 1)
            self.assertEqual(report["summary"]["mismatched_files"], 1)
            self.assertEqual(report["summary"]["missing_files"], 1)
            self.assertEqual(
                [issue["code"] for issue in report["issues"]],
                ["sha256_mismatch", "missing_file"],
            )

    def test_issue_details_are_bounded_but_totals_remain_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "release"
            root.mkdir()
            checksums = Path(directory) / "checksums.sha256"
            self.write_checksum(
                checksums,
                [
                    (sha256_bytes(b"a"), "a.bin"),
                    (sha256_bytes(b"b"), "b.bin"),
                ],
            )

            report = audit_sha256_checksums(root, checksums, max_errors=1)

            self.assertEqual(report["summary"]["issue_count"], 2)
            self.assertEqual(report["summary"]["reported_issues"], 1)
            self.assertEqual(report["summary"]["truncated_issues"], 1)

    def test_large_files_are_not_hashed_past_the_per_file_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "release"
            root.mkdir()
            (root / "large.bin").write_bytes(b"1234")
            checksums = Path(directory) / "checksums.sha256"
            self.write_checksum(
                checksums,
                [(sha256_bytes(b"1234"), "large.bin")],
            )

            report = audit_sha256_checksums(root, checksums, max_file_bytes=3)

            self.assertEqual(report["issues"][0]["code"], "file_too_large")
            self.assertEqual(report["summary"]["bytes_hashed"], 0)

    def test_invalid_checksum_files_and_settings_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "release"
            root.mkdir()
            checksums = Path(directory) / "checksums.sha256"
            digest = sha256_bytes(b"x")
            invalid_lines = [
                "",
                "bad  file.bin\n",
                f"{digest}  ../file.bin\n",
                f"{digest}  /file.bin\n",
                f"{digest}  folder\\file.bin\n",
                f"{digest}  file.bin\n{digest}  file.bin\n",
            ]
            for content in invalid_lines:
                with self.subTest(content=content):
                    checksums.write_text(content, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        audit_sha256_checksums(root, checksums)

            self.write_checksum(checksums, [(digest, "file.bin")])
            invalid_settings = [
                {"max_checksum_bytes": 0},
                {"max_entries": 0},
                {"max_file_bytes": True},
                {"max_total_bytes": -1},
                {"max_errors": 0},
            ]
            for settings in invalid_settings:
                with self.subTest(settings=settings), self.assertRaises(ValueError):
                    audit_sha256_checksums(root, checksums, **settings)

    def test_cli_uses_stable_match_change_and_error_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "release"
            root.mkdir()
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"stable")
            checksums = Path(directory) / "checksums.sha256"
            output = Path(directory) / "report.json"
            self.write_checksum(
                checksums,
                [(sha256_bytes(b"stable"), "artifact.bin")],
            )

            self.assertEqual(
                main([str(root), str(checksums), "--output", str(output)]),
                0,
            )
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["passed"])

            artifact.write_bytes(b"changed")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(root), str(checksums)]), 1)

            original_checksums = checksums.read_bytes()
            original_artifact = artifact.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    main([str(root), str(checksums), "--output", str(checksums)]),
                    2,
                )
                self.assertEqual(
                    main([str(root), str(checksums), "--output", str(artifact)]),
                    2,
                )
                self.assertEqual(
                    main(
                        [
                            str(root),
                            str(checksums),
                            "--max-checksum-bytes",
                            "2",
                        ]
                    ),
                    2,
                )
            self.assertEqual(checksums.read_bytes(), original_checksums)
            self.assertEqual(artifact.read_bytes(), original_artifact)


if __name__ == "__main__":
    unittest.main()
