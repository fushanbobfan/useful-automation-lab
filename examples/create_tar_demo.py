"""Create a small safe archive for the TAR audit example."""

from __future__ import annotations

import argparse
import io
import tarfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output path already exists")

    with tarfile.open(args.output, "w:gz") as archive:
        for name, contents in (
            ("docs/readme.txt", b"safe example archive\n"),
            ("data/values.csv", b"id,value\n1,42\n"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(contents)
            archive.addfile(info, io.BytesIO(contents))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
