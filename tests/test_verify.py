import json
import tempfile
import unittest
from pathlib import Path

from useful_automation_lab.inventory import build_inventory
from useful_automation_lab.verify import verify_directory


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


if __name__ == "__main__":
    unittest.main()
