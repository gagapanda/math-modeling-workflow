"""Shared filesystem and document helpers for workflow scripts."""

from __future__ import annotations

import hashlib
import json
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path


DOCX_NAMESPACES = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
}

DOCX_W = DOCX_NAMESPACES["w"]
DOCX_M = DOCX_NAMESPACES["m"]


def ensure_inside(case_dir: Path, path: Path, label: str) -> Path:
    root = case_dir.expanduser().resolve()
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the case directory: {path}") from exc
    return resolved


def resolve_inside(case_dir: Path, value: str, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty relative path")
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError(f"{label} must be relative to the case directory")
    return ensure_inside(case_dir, case_dir / candidate, label)


def resolve_path_inside(case_dir: Path, value: Path, label: str) -> Path:
    candidate = value.expanduser()
    if not candidate.is_absolute():
        candidate = case_dir / candidate
    return ensure_inside(case_dir, candidate, label)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_path(path: Path) -> str:
    """Hash a declared workflow input, whether it is a file or a directory."""
    if path.is_file():
        return sha256_file(path)
    if not path.is_dir():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())
    for item in files:
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(item)))
    return digest.hexdigest()

def same_existing_file(first: Path, second: Path) -> bool:
    try:
        return first.exists() and second.exists() and first.samefile(second)
    except OSError:
        return False


def hash_evidence(paths: dict[str, Path]) -> dict[str, dict[str, str]]:
    return {
        name: {"path": str(path), "sha256": sha256_file(path)}
        for name, path in paths.items()
        if path.is_file()
    }


def verify_evidence_hashes(evidence: object) -> list[str]:
    if not isinstance(evidence, dict) or not evidence:
        return ["hash-bound evidence is missing"]
    errors = []
    for name, entry in evidence.items():
        if not isinstance(entry, dict):
            errors.append(f"evidence entry {name} must be an object")
            continue
        path_value = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(path_value, str) or not isinstance(expected, str):
            errors.append(f"evidence entry {name} is missing path or sha256")
            continue
        path = Path(path_value)
        if not path.is_file():
            errors.append(f"evidence file {name} is missing: {path}")
        elif sha256_file(path) != expected:
            errors.append(f"evidence file {name} changed after compliance audit")
    return errors


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            stream.write(content)
            temporary = Path(stream.name)
        temporary.replace(path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: dict) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def append_failure_event(
    log_path: Path,
    *,
    source: str,
    report: object,
    command: list[str] | None = None,
) -> bool:
    """Persist a bounded, machine-readable record for a failed workflow attempt.

    Failure logging is deliberately best-effort: inability to write the log must
    never hide the original workflow error. The JSONL format keeps each attempt
    append-only and easy to inspect after a disconnected session or restart.
    """
    if not isinstance(report, dict):
        return False
    errors = report.get("errors", [])
    if not isinstance(errors, list):
        errors = [str(errors)]
    failure = report.get("failure")
    if not isinstance(failure, dict):
        failure = {}
    remediation = failure.get("remediation", [])
    if not isinstance(remediation, list):
        remediation = [str(remediation)]
    event = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "phase": str(report.get("phase", "unknown")),
        "failed_stage": str(failure.get("failed_stage", report.get("phase", "unknown"))),
        "cause_code": str(failure.get("cause_code", "unclassified_failure")),
        "retryable": bool(failure.get("retryable", True)),
        "errors": [str(item)[-2000:] for item in errors[:20]],
        "remediation": [str(item)[-2000:] for item in remediation[:20]],
    }
    if command:
        event["command"] = [str(item) for item in command]
    try:
        log_path = log_path.expanduser().resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        return True
    except (OSError, UnicodeError):
        return False


def _docx_paragraph_text(paragraph: ET.Element) -> str:
    parts = []
    for node in paragraph.iter():
        if node.tag in {f"{{{DOCX_W}}}t", f"{{{DOCX_M}}}t"}:
            parts.append(node.text or "")
        elif node.tag == f"{{{DOCX_W}}}tab":
            parts.append("\t")
        elif node.tag in {f"{{{DOCX_W}}}br", f"{{{DOCX_W}}}cr"}:
            parts.append("\n")
    return "".join(parts)


def _docx_block_text(element: ET.Element) -> list[str]:
    paragraph_tag = f"{{{DOCX_W}}}p"
    table_tag = f"{{{DOCX_W}}}tbl"
    row_tag = f"{{{DOCX_W}}}tr"
    cell_tag = f"{{{DOCX_W}}}tc"
    if element.tag == paragraph_tag:
        return [_docx_paragraph_text(element)]
    if element.tag == table_tag:
        rows = []
        for row in element.findall(f"./{row_tag}"):
            cells = []
            for cell in row.findall(f"./{cell_tag}"):
                blocks = []
                for child in cell:
                    blocks.extend(_docx_block_text(child))
                cells.append("\n".join(blocks))
            rows.append("\t".join(cells))
        return rows

    blocks = []
    for child in element:
        blocks.extend(_docx_block_text(child))
    return blocks


def extract_docx_xml_text(root: ET.Element) -> str:
    body = root.find("./w:body", DOCX_NAMESPACES)
    if body is None:
        return ""
    blocks = []
    for child in body:
        blocks.extend(_docx_block_text(child))
    return "\n".join(blocks)


def extract_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as package:
            root = ET.fromstring(package.read("word/document.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise ValueError(f"cannot parse DOCX {path}: {exc}") from exc
    return extract_docx_xml_text(root)


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("pypdf is required to extract PDF text") from exc
    try:
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    except Exception as exc:
        raise ValueError(f"cannot parse PDF {path}: {exc}") from exc
