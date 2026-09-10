#!/usr/bin/env python
"""Case analysis entry point; replace this starter with reproducible analysis."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, default=Path.cwd())
    args = parser.parse_args()

    case_dir = args.case_dir.expanduser().resolve()
    if not case_dir.is_dir():
        raise NotADirectoryError(f"case directory does not exist: {case_dir}")

    print(
        "analysis_not_implemented: replace src/analyze.py with the case's "
        "deterministic analysis before running the build phase",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
