import tempfile
import unittest
from pathlib import Path

from useful_automation_lab.inventory import build_inventory


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


if __name__ == "__main__":
    unittest.main()
