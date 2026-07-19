"""Create a small safe archive for the ZIP audit example."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output path already exists")

    with ZipFile(args.output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("docs/readme.txt", "safe example archive\n")
        archive.writestr("data/values.csv", "id,value\n1,42\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
