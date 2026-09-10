#!/usr/bin/env python
"""Search a mathematical-modeling library by filename and relative path."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


SKIP_PARTS = {".agents", ".git", "tmp", "output", "outputs", "__pycache__"}


@dataclass(frozen=True)
class Match:
    score: int
    path: str
    size_bytes: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Space-separated filename/path search terms")
    parser.add_argument("--root", type=Path, default=None, help="Library root")
    parser.add_argument("--ext", action="append", default=[], help="Extension filter, repeatable")
    parser.add_argument("--limit", type=int, default=50, help="Maximum results")
    parser.add_argument("--any", action="store_true", help="Match any term instead of all terms")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def discover_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "资料索引.md").exists():
            return candidate
    raise SystemExit("Library root not found; pass --root explicitly")


def normalize_extensions(values: list[str]) -> set[str]:
    result = set()
    for value in values:
        extension = value.casefold()
        if not extension.startswith("."):
            extension = "." + extension
        result.add(extension)
    return result


def tokenize(query: str) -> list[str]:
    return [token.casefold() for token in re.split(r"\s+", query.strip()) if token]


def score_path(relative: str, tokens: list[str], require_all: bool) -> int:
    folded = relative.casefold()
    name = Path(relative).name.casefold()
    matched = [token for token in tokens if token in folded]
    if not matched or (require_all and len(matched) != len(tokens)):
        return 0
    score = 10 * len(matched)
    score += 5 * sum(token in name for token in matched)
    if len(matched) == len(tokens):
        score += 20
    return score


def search(
    root: Path, tokens: list[str], extensions: set[str], require_all: bool
) -> list[Match]:
    matches = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        if any(part.casefold() in SKIP_PARTS for part in relative_path.parts):
            continue
        if extensions and path.suffix.casefold() not in extensions:
            continue
        relative = relative_path.as_posix()
        score = score_path(relative, tokens, require_all)
        if score:
            matches.append(Match(score=score, path=relative, size_bytes=path.stat().st_size))
    return sorted(matches, key=lambda item: (-item.score, item.path.casefold()))


def main() -> int:
    args = parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be positive")
    tokens = tokenize(args.query)
    if not tokens:
        raise SystemExit("query must contain at least one term")
    root = args.root.expanduser().resolve() if args.root else discover_root(Path.cwd())
    if not root.is_dir():
        raise SystemExit(f"Library root does not exist: {root}")

    matches = search(
        root, tokens, normalize_extensions(args.ext), require_all=not args.any
    )[: args.limit]
    if args.json:
        print(json.dumps([asdict(match) for match in matches], ensure_ascii=False, indent=2))
    else:
        print(f"root={root}")
        print(f"matches={len(matches)}")
        for match in matches:
            print(f"{match.score:3d}  {match.size_bytes:12d}  {match.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
