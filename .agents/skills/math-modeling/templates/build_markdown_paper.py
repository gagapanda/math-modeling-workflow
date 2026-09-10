#!/usr/bin/env python
"""Build a case DOCX from Markdown with the workspace doc-export tool."""

from __future__ import annotations

import argparse
import subprocess
import os
import sys
from pathlib import Path


def resolve_inside(root: Path, value: str, label: str) -> Path:
    root = root.resolve()
    path = (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} must stay inside {root}") from exc
    return path


def find_workspace(case_dir: Path, spec_name: str) -> tuple[Path, Path, Path]:
    for root in (case_dir, *case_dir.parents):
        tool_dir = root / "tools" / "doc-export-enhanced"
        exporter = tool_dir / "exporter.py"
        interpreters = (
            tool_dir / ".venv" / "Scripts" / "python.exe",
            tool_dir / ".venv" / "bin" / "python",
        )
        python = next((path for path in interpreters if path.is_file()), None)
        if not exporter.is_file() or python is None:
            continue

        spec = resolve_inside(root / "doc-export-specs", spec_name, "export spec")
        if not spec.is_file():
            raise FileNotFoundError(f"export spec does not exist: {spec}")
        return python, exporter, spec

    raise FileNotFoundError(
        "cannot find tools/doc-export-enhanced with its project-local .venv"
    )


def find_public_backend(case_dir: Path, spec_name: str):
    for root in (case_dir, *case_dir.parents):
        exporter = root / "tools" / "paper-export" / "export_paper.py"
        if not exporter.is_file():
            continue
        # Only the known historical default is mapped; never ignore a custom spec.
        name = "paper-default.json" if spec_name == "cumcm-cn.yaml" else spec_name
        spec = resolve_inside(root / "doc-export-specs", name, "export spec")
        if not spec.is_file():
            raise FileNotFoundError(f"public export spec does not exist: {spec}")
        return exporter, spec
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--source", default="paper/full-paper.md")
    parser.add_argument("--output", default="paper/paper.docx")
    parser.add_argument("--spec", default="cumcm-cn.yaml")
    parser.add_argument(
        "--include-toc",
        action="store_true",
        help=(
            "Include a Word table of contents only when the current official "
            "competition rules or reviewed template explicitly permit it. "
            "CUMCM scaffolds intentionally omit this flag."
        ),
    )
    parser.add_argument("--document-python", default=os.environ.get("PAPER_DOCUMENT_PYTHON", sys.executable))
    parser.add_argument("--pdf", action="store_true", help="Public backend: also produce PDF and all-page evidence")
    parser.add_argument("--pandoc", default="pandoc")
    parser.add_argument("--soffice", default="soffice")
    parser.add_argument("--pdftoppm", default="pdftoppm")
    args = parser.parse_args()

    case_dir = args.case_dir.expanduser().resolve()
    if not case_dir.is_dir():
        raise NotADirectoryError(f"case directory does not exist: {case_dir}")

    source = resolve_inside(case_dir, args.source, "paper source")
    output = resolve_inside(case_dir, args.output, "paper output")
    if source.suffix.casefold() != ".md":
        raise ValueError("paper source must be a Markdown file")
    if output.suffix.casefold() != ".docx":
        raise ValueError("paper output must end in .docx")
    if not source.is_file():
        raise FileNotFoundError(f"paper source does not exist: {source}")

    public = find_public_backend(case_dir, args.spec)
    if public:
        exporter, spec = public
        command = [str(args.document_python), str(exporter), "--md", str(source),
                   "--spec", str(spec), "--out", str(output), "--asset-root", str(case_dir),
                   "--pandoc", args.pandoc, "--soffice", args.soffice, "--pdftoppm", args.pdftoppm]
        if args.pdf:
            command.append("--pdf")
        if args.include_toc:
            command.append("--toc")
        return subprocess.run(command, cwd=case_dir, check=False, timeout=2000).returncode
    if args.pdf:
        raise ValueError("--pdf requires the public paper-export backend")
    python, exporter, spec = find_workspace(case_dir, args.spec)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(python),
        str(exporter),
        "--md",
        str(source),
        "--spec",
        str(spec),
        "--out",
        str(output),
        "--formulas",
        "--page-numbers",
        "--refresh-fields",
    ]
    if args.include_toc:
        command.append("--toc")
    completed = subprocess.run(command, cwd=case_dir, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
