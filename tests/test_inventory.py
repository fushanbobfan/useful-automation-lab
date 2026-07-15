import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from useful_automation_lab.inventory import build_inventory, main


class InventoryTests(unittest.TestCase):
    def test_inventory_is_sorted_and_excludes_git_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "b.txt").write_text("b", encoding="utf-8")
            (root / "a.txt").write_text("a", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("secret", encoding="utf-8")
            inventory = build_inventory(root)
            self.assertEqual([entry["path"] for entry in inventory], ["a.txt", "b.txt"])
            self.assertEqual(len(inventory[0]["sha256"]), 64)

    def test_exclude_patterns_match_files_and_directory_ancestors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "keep.txt").write_text("keep", encoding="utf-8")
            (root / "scratch.tmp").write_text("temporary", encoding="utf-8")
            (root / "cache").mkdir()
            (root / "cache" / "nested.txt").write_text("cache", encoding="utf-8")

            inventory = build_inventory(
                root,
                exclude_patterns=["*.tmp", "cache"],
            )

            self.assertEqual([entry["path"] for entry in inventory], ["keep.txt"])

    def test_multiple_patterns_preserve_deterministic_path_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "z.txt").write_text("z", encoding="utf-8")
            (root / "b.log").write_text("b", encoding="utf-8")
            (root / "a.txt").write_text("a", encoding="utf-8")

            inventory = build_inventory(root, exclude_patterns=["*.log", "missing/*"])

            self.assertEqual(
                [entry["path"] for entry in inventory],
                ["a.txt", "z.txt"],
            )

    def test_unsafe_or_ambiguous_patterns_are_rejected(self):
        for pattern in ("", "../secret", "/absolute", "nested\\file", "a//b", "."):
            with self.subTest(pattern=pattern):
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaisesRegex(ValueError, "patterns"):
                        build_inventory(Path(directory), exclude_patterns=[pattern])

    def test_cli_applies_repeated_exclusions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "keep.txt").write_text("keep", encoding="utf-8")
            (root / "debug.log").write_text("log", encoding="utf-8")
            (root / "cache").mkdir()
            (root / "cache" / "item.txt").write_text("cache", encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [str(root), "--exclude", "*.log", "--exclude", "cache"]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                [entry["path"] for entry in json.loads(stdout.getvalue())],
                ["keep.txt"],
            )

    def test_cli_returns_two_for_an_invalid_pattern(self):
        with tempfile.TemporaryDirectory() as directory:
            with contextlib.redirect_stderr(io.StringIO()):
                exit_code = main([directory, "--exclude", "../outside"])

            self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
