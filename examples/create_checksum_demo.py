"""Create a disposable artifact directory and matching SHA-256 file."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()

    args.directory.mkdir(parents=True)
    artifacts = {
        "artifact.bin": b"stable release artifact\n",
        "metadata.json": b'{"version":1,"channel":"demo"}\n',
    }
    lines = []
    for name, content in sorted(artifacts.items()):
        (args.directory / name).write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        lines.append(f"{digest}  {name}\n")
    (args.directory / "checksums.sha256").write_text(
        "".join(lines), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
