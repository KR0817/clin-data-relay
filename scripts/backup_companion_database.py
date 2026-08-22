"""Create a consistent SQLite backup and verified restore evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.backup import backup_database


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    arguments = parser.parse_args()
    evidence_path = backup_database(arguments.source, arguments.output_dir)
    print(evidence_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
