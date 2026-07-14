import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from useful_automation_lab.inventory import build_inventory
from useful_automation_lab.verify import main, verify_directory


class DirectoryVerificationTests(unittest.TestCase):
    def write_manifest(self, path: Path, root: Path) -> None:
        path.write_text(json.dumps(build_inventory(root)), encoding="utf-8")

    def test_unchanged_directory_matches_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "data"
            root.mkdir()
            (root / "file.txt").write_text("stable", encoding="utf-8")
            manifest = base / "manifest.json"
            self.write_manifest(manifest, root)

            report = verify_directory(root, manifest)

            self.assertEqual(
                report["summary"],
                {"added": 0, "removed": 0, "modified": 0, "unchanged": 1},
            )

    def test_manifest_created_inside_root_is_not_a_false_addition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "file.txt").write_text("stable", encoding="utf-8")
            manifest = root / "manifest.json"
            self.write_manifest(manifest, root)

            report = verify_directory(root, manifest)

            self.assertEqual(report["summary"]["added"], 0)
            self.assertEqual(report["summary"]["unchanged"], 1)

    def test_reports_added_removed_and_modified_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "data"
            root.mkdir()
            (root / "changed.txt").write_text("before", encoding="utf-8")
            (root / "removed.txt").write_text("remove", encoding="utf-8")
            manifest = base / "manifest.json"
            self.write_manifest(manifest, root)

            (root / "changed.txt").write_text("after", encoding="utf-8")
            (root / "removed.txt").unlink()
            (root / "added.txt").write_text("add", encoding="utf-8")

            report = verify_directory(root, manifest)

            self.assertEqual(
                report["summary"],
                {"added": 1, "removed": 1, "modified": 1, "unchanged": 0},
            )

    def test_missing_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manifest = base / "manifest.json"
            manifest.write_text("[]", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "does not exist"):
                verify_directory(base / "missing", manifest)

    def test_cli_returns_zero_and_writes_report_for_a_match(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "data"
            root.mkdir()
            (root / "file.txt").write_text("stable", encoding="utf-8")
            manifest = base / "manifest.json"
            output = base / "report.json"
            self.write_manifest(manifest, root)

            exit_code = main([str(root), str(manifest), "--output", str(output)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.read_text())["summary"]["unchanged"], 1)

    def test_cli_returns_one_when_directory_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "data"
            root.mkdir()
            manifest = base / "manifest.json"
            self.write_manifest(manifest, root)
            (root / "new.txt").write_text("new", encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = main([str(root), str(manifest)])

            self.assertEqual(exit_code, 1)
            self.assertEqual(json.loads(stdout.getvalue())["summary"]["added"], 1)

    def test_cli_returns_two_for_missing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manifest = base / "manifest.json"
            manifest.write_text("[]", encoding="utf-8")

            with contextlib.redirect_stderr(io.StringIO()):
                exit_code = main([str(base / "missing"), str(manifest)])

            self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
