#!/usr/bin/env python
"""Build and verify final paper and support-material submission files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from _json_schema import load_and_validate
from _workflow_common import (
    extract_docx_text,
    extract_pdf_text,
    resolve_inside,
    resolve_path_inside,
    sha256_file,
    verify_evidence_hashes,
)


SKILL_DIR = Path(__file__).resolve().parent.parent
PLAN_SCHEMA = SKILL_DIR / "schemas" / "submission-package-plan.schema.json"
REPORT_SCHEMA = SKILL_DIR / "schemas" / "submission-package-report.schema.json"
FINALIZATION_SCHEMA = SKILL_DIR / "schemas" / "finalization-report.schema.json"
REPORT_NAME = "submission-package-report.json"
MANIFEST_NAME = "submission-manifest.json"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".csv", ".h", ".hpp", ".ini", ".json", ".m",
    ".md", ".py", ".r", ".rst", ".tex", ".toml", ".tsv", ".txt", ".yaml", ".yml",
}
LOCAL_ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?i)(?<![a-z0-9])(?:file:///)?[a-z]:/[^\s<>'\"]+"),
    re.compile(
        r"(?i)(?<![a-z0-9])(?:file://)?[a-z]:\\"
        r"(?:(?:[^\\/\s<>'\"]+\\)+[^\\/\s<>'\"]+"
        r"|[^\\/\s<>'\"]+\.[a-z0-9]{1,10})"
        r"(?![a-z])"
    ),
    re.compile(r"(?i)(?:file://)?/(?:home|Users|tmp)/[^\s<>'\"]+"),
    re.compile(r"(?i)\\\\[^\s\\/]+[\\/][^\s<>'\"]+"),
)

WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul", *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("submission-package"))
    parser.add_argument(
        "--generated-at",
        help=(
            "Explicit timezone-aware report timestamp; defaults to the "
            "finalization report timestamp"
        ),
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace only a previously verified package managed by this tool",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def normalize_generated_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("generated_at must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("generated_at must include a timezone offset")
    return parsed.isoformat(timespec="seconds")


def load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def validate_leaf_name(value: str, label: str, suffix: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty filename")
    if value in {".", ".."} or value != value.strip(" ."):
        raise ValueError(f"{label} has unsafe leading or trailing characters")
    if len(value) > 180 or any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} is too long or contains control characters")
    if any(char in '<>:"/\\|?*' for char in value):
        raise ValueError(f"{label} contains a separator or Windows-invalid character")
    if Path(value).stem.casefold() in WINDOWS_RESERVED:
        raise ValueError(f"{label} uses a reserved Windows filename")
    if not value.casefold().endswith(suffix):
        raise ValueError(f"{label} must end with {suffix}")
    return value


def validate_archive_path(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{label} must be a non-empty normalized POSIX path")
    if any(ord(char) < 32 for char in value) or value.endswith("/"):
        raise ValueError(f"{label} contains control characters or names a directory")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} is absolute or contains traversal")
    if path.as_posix() != value:
        raise ValueError(f"{label} is not normalized")
    if value.casefold() == MANIFEST_NAME.casefold():
        raise ValueError(f"{label} conflicts with the generated manifest")
    for part in path.parts:
        if part != part.strip(" .") or any(char in '<>:"|?*' for char in part):
            raise ValueError(f"{label} contains a Windows-unsafe path component")
        if Path(part).stem.casefold() in WINDOWS_RESERVED:
            raise ValueError(f"{label} contains a reserved Windows path component")
    return value


def reject_link_components(case_dir: Path, path: Path, label: str) -> None:
    try:
        relative = path.relative_to(case_dir)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the case directory: {path}") from exc
    current = case_dir
    for part in relative.parts:
        current = current / part
        is_junction = getattr(current, "is_junction", lambda: False)()
        if current.is_symlink() or is_junction:
            raise ValueError(f"{label} uses a symbolic link or junction: {current}")


def resolve_regular_source(case_dir: Path, value: str, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty relative path")
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError(f"{label} must be relative to the case directory")
    lexical = case_dir / candidate
    reject_link_components(case_dir, lexical, label)
    return resolve_inside(case_dir, value, label)


def physical_identity(path: Path) -> tuple[int, int]:
    info = path.stat()
    return info.st_dev, info.st_ino


def pdf_page_count(path: Path) -> int:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("pypdf is required to validate the submission PDF") from exc
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise ValueError("submission PDF must not be encrypted")
        pages = len(reader.pages)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"cannot read submission PDF: {exc}") from exc
    if pages < 1:
        raise ValueError("submission PDF has no pages")
    return pages


def extract_ooxml_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as package:
            chunks = []
            for name in sorted(package.namelist()):
                if name.casefold().endswith(".xml"):
                    chunks.append(package.read(name).decode("utf-8", errors="ignore"))
            return "\n".join(re.sub(r"<[^>]+>", " ", chunk) for chunk in chunks)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"cannot inspect Office file {path}: {exc}") from exc


def extract_metadata_text(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".docx":
        from audit_paper_quality_gates import inspect_docx_metadata

        block = inspect_docx_metadata(path)
    elif suffix == ".pdf":
        from audit_paper_quality_gates import inspect_pdf_metadata

        block = inspect_pdf_metadata(path)
    else:
        return ""
    errors = block.get("errors", [])
    if errors:
        raise ValueError(f"cannot inspect identity metadata {path}: {'; '.join(errors)}")
    return "\n".join(
        f"{label}: {value}"
        for label, value in block.get("values", {}).items()
        if value
    )


def extract_scannable_text(path: Path) -> str | None:
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return "\n".join((extract_pdf_text(path), extract_metadata_text(path)))
    if suffix == ".docx":
        return "\n".join((extract_docx_text(path), extract_metadata_text(path)))
    if suffix in {".xlsx", ".xlsm"}:
        return extract_ooxml_text(path)
    if suffix in TEXT_SUFFIXES:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="replace")
    return None


def find_forbidden_matches(terms: list[str], named_texts: list[tuple[str, str]]) -> list[str]:
    matches = []
    folded_terms = [(term, term.casefold()) for term in terms]
    for label, value in named_texts:
        folded = value.casefold()
        for original, term in folded_terms:
            if term in folded:
                matches.append(f"{label}: {original}")
    return sorted(set(matches), key=str.casefold)


def find_local_absolute_path_matches(named_texts: list[tuple[str, str]]) -> list[str]:
    matches = []
    for label, value in named_texts:
        for pattern in LOCAL_ABSOLUTE_PATH_PATTERNS:
            for match in pattern.finditer(value):
                matches.append(f"{label}: {match.group(0)}")
    return sorted(set(matches), key=str.casefold)


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.flag_bits |= 0x800
    return info


def write_support_zip(path: Path, entries: list[dict], manifest_bytes: bytes) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for entry in entries:
            package.writestr(zip_info(entry["archive_path"]), Path(entry["resolved_source"]).read_bytes())
        package.writestr(zip_info(MANIFEST_NAME), manifest_bytes)


def validate_zip_round_trip(path: Path, entries: list[dict], manifest_bytes: bytes) -> None:
    expected = {entry["archive_path"]: entry["sha256"] for entry in entries}
    expected[MANIFEST_NAME] = hashlib.sha256(manifest_bytes).hexdigest()
    with zipfile.ZipFile(path) as package:
        if package.testzip() is not None:
            raise ValueError("support ZIP failed CRC validation")
        names = package.namelist()
        if len(names) != len(set(name.casefold() for name in names)):
            raise ValueError("support ZIP contains duplicate or case-colliding names")
        if set(names) != set(expected):
            raise ValueError("support ZIP entry list differs from the package plan")
        for info in package.infolist():
            normalized = validate_archive_path(info.filename, f"ZIP entry {info.filename}") if info.filename != MANIFEST_NAME else info.filename
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"support ZIP contains a symbolic link: {normalized}")
            data = package.read(info)
            actual = __import__("hashlib").sha256(data).hexdigest()
            if actual != expected[info.filename]:
                raise ValueError(f"support ZIP hash mismatch: {info.filename}")
        with tempfile.TemporaryDirectory(prefix="submission-package-extract-") as temporary:
            root = Path(temporary).resolve()
            for info in package.infolist():
                target = (root / PurePosixPath(info.filename)).resolve()
                try:
                    target.relative_to(root)
                except ValueError as exc:
                    raise ValueError(f"support ZIP entry escapes extraction root: {info.filename}") from exc
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(package.read(info))
            for name, digest in expected.items():
                extracted = root / PurePosixPath(name)
                if not extracted.is_file() or sha256_file(extracted) != digest:
                    raise ValueError(f"support ZIP round-trip mismatch: {name}")


def validate_prior_package(output_dir: Path, targets: list[Path]) -> None:
    report_path = output_dir / REPORT_NAME
    if not report_path.is_file():
        raise ValueError("--replace requires an existing managed package report")
    report = load_json(report_path, "existing package report")
    load_and_validate(report, REPORT_SCHEMA, "existing package report")
    if not report.get("packaged"):
        raise ValueError("existing package report is not successful")
    reported = [Path(report["outputs"][key]["path"]).resolve() for key in ("paper", "support")]
    if reported != [target.resolve() for target in targets[:2]]:
        raise ValueError("existing package report does not own the requested output paths")
    for key, target in zip(("paper", "support"), targets[:2]):
        if not target.is_file() or sha256_file(target) != report["outputs"][key]["sha256"]:
            raise ValueError(f"existing managed {key} output is missing or changed")


def commit_transaction(
    staged: list[tuple[Path, Path]],
    staging_dir: Path,
    expected_hashes: dict[Path, str],
) -> None:
    backups = staging_dir / "backups"
    backups.mkdir()
    moved_backups: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for _, target in staged:
            if target.exists():
                backup = backups / target.name
                os.replace(target, backup)
                moved_backups.append((backup, target))
        for source, target in staged:
            os.replace(source, target)
            installed.append(target)
        for target in installed:
            if not target.is_file() or sha256_file(target) != expected_hashes[target]:
                raise RuntimeError(f"committed output hash mismatch: {target}")
    except Exception:
        for target in reversed(installed):
            target.unlink(missing_ok=True)
        for backup, target in reversed(moved_backups):
            if backup.exists():
                os.replace(backup, target)
        raise


def package_submission(
    case_dir: Path,
    plan_path: Path,
    output_dir: Path,
    replace: bool = False,
    generated_at: str | None = None,
) -> dict:
    case_dir = case_dir.expanduser().resolve()
    if not case_dir.is_dir():
        raise ValueError(f"case directory does not exist: {case_dir}")
    plan_path = resolve_path_inside(case_dir, plan_path, "package plan")
    output_dir = resolve_path_inside(case_dir, output_dir, "package output directory")
    if output_dir == case_dir:
        raise ValueError("package output directory must not be the case root")
    plan = load_json(plan_path, "package plan")
    load_and_validate(plan, PLAN_SCHEMA, "package plan")

    finalization_path = resolve_regular_source(
        case_dir, plan["finalization_report"], "finalization report"
    )
    finalization = load_json(finalization_path, "finalization report")
    load_and_validate(finalization, FINALIZATION_SCHEMA, "finalization report")
    if not finalization.get("ready_for_submission"):
        raise ValueError("finalization report is not ready_for_submission")
    if Path(finalization["case_dir"]).resolve() != case_dir:
        raise ValueError("finalization report belongs to a different case directory")
    report_generated_at = normalize_generated_at(
        generated_at or finalization["generated_at"]
    )

    paper = resolve_regular_source(case_dir, plan["paper"]["source"], "paper source")
    if not paper.is_file() or paper.stat().st_size == 0:
        raise ValueError("paper source is missing or empty")
    if paper.suffix.casefold() != ".pdf":
        raise ValueError("paper source must be a PDF")
    finalized_pdf = Path(finalization["artifacts"].get("pdf", "")).resolve()
    expected_pdf_hash = finalization["artifact_hashes"].get("after", {}).get("pdf")
    current_pdf_hash = sha256_file(paper)
    if finalized_pdf != paper or expected_pdf_hash != current_pdf_hash:
        raise ValueError("paper source does not match the finalization report PDF binding")
    compliance = finalization.get("submission_compliance", {})
    if compliance.get("required"):
        if not compliance.get("passed") or compliance.get("errors"):
            raise ValueError("required submission compliance did not pass finalization")
        if compliance.get("scope") == "full_m6" and not compliance.get("full_m6_proven"):
            raise ValueError("full-M6 finalization does not prove an accepted human M6 decision")
        evidence_errors = verify_evidence_hashes(compliance.get("evidence_sha256"))
        if evidence_errors:
            raise ValueError("submission compliance evidence is stale: " + "; ".join(evidence_errors))

    paper_name = validate_leaf_name(plan["paper"]["output_name"], "paper output_name", ".pdf")
    support_name = validate_leaf_name(plan["support"]["output_name"], "support output_name", ".zip")
    if paper_name.casefold() in {support_name.casefold(), REPORT_NAME.casefold()} or support_name.casefold() == REPORT_NAME.casefold():
        raise ValueError("package output filenames must be distinct")

    entries = []
    archive_names: set[str] = set()
    identities = {physical_identity(paper): "paper source"}
    named_texts: list[tuple[str, str]] = [
        ("paper output filename", paper_name),
        ("support output filename", support_name),
        ("paper source path", paper.relative_to(case_dir).as_posix()),
    ]
    scanned_files = 0
    paper_text = extract_scannable_text(paper)
    if paper_text is not None:
        named_texts.append(("paper text", paper_text))
        scanned_files += 1
    for index, item in enumerate(plan["support"]["files"]):
        source = resolve_regular_source(
            case_dir, item["source"], f"support file {index} source"
        )
        if not source.is_file() or source.stat().st_size == 0:
            raise ValueError(f"support file {index} is missing or empty")
        identity = physical_identity(source)
        if identity in identities:
            raise ValueError(f"support file {index} aliases {identities[identity]}")
        identities[identity] = f"support file {index}"
        archive_path = validate_archive_path(item["archive_path"], f"support file {index} archive_path")
        folded = archive_path.casefold()
        if folded in archive_names:
            raise ValueError(f"duplicate or case-colliding archive path: {archive_path}")
        archive_names.add(folded)
        relative_source = source.relative_to(case_dir).as_posix()
        entry = {
            "source": relative_source,
            "archive_path": archive_path,
            "size_bytes": source.stat().st_size,
            "sha256": sha256_file(source),
            "resolved_source": str(source),
        }
        entries.append(entry)
        named_texts.extend(((f"support source path {index}", relative_source), (f"archive path {index}", archive_path)))
        text = extract_scannable_text(source)
        if text is not None:
            named_texts.append((f"support text {archive_path}", text))
            scanned_files += 1
    entries.sort(key=lambda entry: entry["archive_path"].casefold())

    terms = plan["anonymity"]["forbidden_terms"]
    if any(not term.strip() for term in terms):
        raise ValueError("anonymity forbidden_terms must not be blank")
    matches = find_forbidden_matches(terms, named_texts)
    if matches:
        raise ValueError("forbidden anonymity terms found: " + "; ".join(matches))
    absolute_path_matches = find_local_absolute_path_matches(named_texts)
    if absolute_path_matches:
        raise ValueError(
            "local absolute paths found in submission content: "
            + "; ".join(absolute_path_matches)
        )

    public_entries = [{key: entry[key] for key in ("source", "archive_path", "size_bytes", "sha256")} for entry in entries]
    manifest = {
        "schema_version": 1,
        "finalization_report_sha256": sha256_file(finalization_path),
        "paper_sha256": current_pdf_hash,
        "files": public_entries,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()

    output_dir_existed = output_dir.exists()
    if output_dir_existed and not output_dir.is_dir():
        raise ValueError("package output path exists and is not a directory")
    if output_dir_existed:
        reject_link_components(case_dir, output_dir, "package output directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    paper_target = output_dir / paper_name
    support_target = output_dir / support_name
    report_target = output_dir / REPORT_NAME
    allowed_existing = {paper_name.casefold(), support_name.casefold(), REPORT_NAME.casefold()}
    unexpected = [path.name for path in output_dir.iterdir() if path.name.casefold() not in allowed_existing]
    if unexpected:
        raise ValueError("package output directory contains unrelated entries: " + ", ".join(sorted(unexpected)))
    existing = [path for path in (paper_target, support_target, report_target) if path.exists()]
    if existing and not replace:
        raise ValueError("package outputs already exist; use --replace only for a verified managed package")
    if replace:
        validate_prior_package(output_dir, [paper_target, support_target, report_target])

    staging_dir = Path(tempfile.mkdtemp(prefix=".submission-package-", dir=output_dir))
    try:
        staged_paper = staging_dir / paper_name
        staged_support = staging_dir / support_name
        staged_report = staging_dir / REPORT_NAME
        shutil.copyfile(paper, staged_paper)
        if sha256_file(staged_paper) != current_pdf_hash:
            raise ValueError("copied paper hash differs from the finalized source")
        pages = pdf_page_count(staged_paper)
        write_support_zip(staged_support, entries, manifest_bytes)
        validate_zip_round_trip(staged_support, entries, manifest_bytes)
        if staged_paper.stat().st_size > plan["paper"]["max_bytes"]:
            raise ValueError("packaged paper exceeds paper.max_bytes")
        if staged_support.stat().st_size > plan["support"]["max_bytes"]:
            raise ValueError("support ZIP exceeds support.max_bytes")
        report = {
            "schema_version": 1,
            "generated_at": report_generated_at,
            "packaged": True,
            "case_dir": str(case_dir),
            "bindings": {
                "plan": {"path": str(plan_path), "sha256": sha256_file(plan_path)},
                "finalization_report": {"path": str(finalization_path), "sha256": sha256_file(finalization_path)},
                "source_paper": {"path": str(paper), "sha256": current_pdf_hash},
            },
            "outputs": {
                "paper": {
                    "path": str(paper_target), "size_bytes": staged_paper.stat().st_size,
                    "max_bytes": plan["paper"]["max_bytes"], "sha256": sha256_file(staged_paper),
                },
                "support": {
                    "path": str(support_target), "size_bytes": staged_support.stat().st_size,
                    "max_bytes": plan["support"]["max_bytes"], "sha256": sha256_file(staged_support),
                    "entries": public_entries, "manifest_sha256": manifest_sha,
                },
            },
            "anonymity": {"forbidden_terms": terms, "files_scanned": scanned_files, "matches": []},
            "validation": {
                "pdf_readable": True, "pdf_pages": pages, "zip_tested": True,
                "zip_round_trip": True, "size_limits_passed": True,
            },
            "errors": [],
        }
        load_and_validate(report, REPORT_SCHEMA, "submission package report")
        staged_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staged = [
            (staged_paper, paper_target),
            (staged_support, support_target),
            (staged_report, report_target),
        ]
        commit_transaction(
            staged,
            staging_dir,
            {target: sha256_file(source) for source, target in staged},
        )
        return report
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        if not output_dir_existed:
            try:
                output_dir.rmdir()
            except OSError:
                pass


def main() -> int:
    args = parse_args()
    try:
        report = package_submission(
            args.case_dir,
            args.plan,
            args.output_dir,
            args.replace,
            generated_at=args.generated_at,
        )
    except Exception as exc:
        failure = {"packaged": False, "errors": [str(exc)]}
        if args.json:
            print(json.dumps(failure, ensure_ascii=False, indent=2))
        else:
            print(f"Submission package failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Submission package ready: {report['outputs']['paper']['path']}")
        print(f"Support materials ready: {report['outputs']['support']['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
