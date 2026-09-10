#!/usr/bin/env python
"""Read-only diagnosis for the optional paper-export backend. Does not install tools."""
from __future__ import annotations
import argparse
import importlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys

PACKAGES = {"python-docx": "docx", "pypdf": "pypdf", "Pillow": "PIL", "lxml": "lxml.etree", "typing_extensions": "typing_extensions"}


def probe_package(distribution, module):
    try:
        imported = importlib.import_module(module)
        version = importlib.metadata.version(distribution)
        return {"name": distribution, "status": "available", "version": version,
                "module_file": getattr(imported, "__file__", None)}
    except (ImportError, OSError, importlib.metadata.PackageNotFoundError) as exc:
        return {"name": distribution, "status": "missing_or_broken", "detail": str(exc)}


def probe_tool(name, value):
    found = shutil.which(value)
    if not found or Path(found).suffix.lower() in {".cmd", ".bat", ".ps1"}:
        return {"name": name, "status": "missing", "detail": "Provide a native executable via PATH or the explicit flag"}
    try:
        flag = "-v" if name == "pdftoppm" else "--version"
        completed = subprocess.run([found, flag], capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=15, check=False)
        text = (completed.stdout + "\n" + completed.stderr).strip()
        if completed.returncode:
            return {"name": name, "status": "probe_failed", "returncode": completed.returncode, "detail": text[:1000]}
        return {"name": name, "status": "available", "executable": str(Path(found).resolve()), "version": text.splitlines()[0] if text else "unreported"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"name": name, "status": "probe_failed", "detail": str(exc)}


def diagnose(args):
    packages = [probe_package(name, module) for name, module in PACKAGES.items()]
    tools = [probe_tool("pandoc", args.pandoc)]
    if args.pdf:
        tools.extend([probe_tool("soffice", args.soffice), probe_tool("pdftoppm", args.pdftoppm)])
    supported = sys.version_info >= (3, 10)
    return {"schema_version": 1, "command": "paper_export_doctor", "python": sys.version,
            "executable": sys.executable, "python_supported": supported,
            "scope": "docx_pdf_pages" if args.pdf else "docx_only",
            "packages": packages, "tools": tools,
            "ready_to_attempt_export": supported and all(p["status"] == "available" for p in packages + tools),
            "fonts": "not_verified; inspect rendered pages on this machine",
            "submission_ready": False, "release_authorized": False,
            "limits": ["Availability/version probes are not an actual export test", "No font, security-vulnerability, license or competition approval", "This doctor does not replace the main workflow preflight"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", action="store_true")
    parser.add_argument("--pandoc", default="pandoc")
    parser.add_argument("--soffice", default="soffice")
    parser.add_argument("--pdftoppm", default="pdftoppm")
    report = diagnose(parser.parse_args())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready_to_attempt_export"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
