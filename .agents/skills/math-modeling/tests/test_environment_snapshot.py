from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_snapshot_module():
    spec = importlib.util.spec_from_file_location(
        "math_modeling_environment_snapshot", SCRIPTS / "snapshot_environment.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load snapshot_environment.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EnvironmentSnapshotTests(unittest.TestCase):
    def test_audit_timestamp_requires_and_preserves_timezone(self) -> None:
        snapshot = load_snapshot_module()
        parsed, rendered = snapshot.parse_audit_timestamp(
            "2026-08-18T23:59:59+08:00"
        )
        self.assertEqual(rendered, "2026-08-18T23:59:59+08:00")
        self.assertEqual(parsed.utcoffset().total_seconds(), 8 * 60 * 60)
        with self.assertRaisesRegex(ValueError, "timezone offset"):
            snapshot.parse_audit_timestamp("2026-08-18T23:59:59")

    def test_requirements_parser_accepts_only_exact_unique_pins(self) -> None:
        snapshot = load_snapshot_module()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "requirements.txt"
            path.write_text("NumPy==2.5.2\npython_docx==1.2.0 # core\n", encoding="utf-8")
            self.assertEqual(
                snapshot.parse_pinned_requirements(path),
                {"numpy": "2.5.2", "python-docx": "1.2.0"},
            )
            path.write_text("numpy>=2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exact == pins"):
                snapshot.parse_pinned_requirements(path)

    def test_poppler_wrapper_resolves_to_bundled_native_executable(self) -> None:
        snapshot = load_snapshot_module()
        with tempfile.TemporaryDirectory() as temporary:
            dependencies = Path(temporary) / "dependencies"
            wrapper = dependencies / "bin" / "override" / "pdftoppm.cmd"
            native = (
                dependencies
                / "native"
                / "poppler"
                / "Library"
                / "bin"
                / "pdftoppm.exe"
            )
            wrapper.parent.mkdir(parents=True)
            native.parent.mkdir(parents=True)
            wrapper.write_bytes(b"wrapper")
            native.write_bytes(b"binary")
            with (
                patch.object(snapshot.preflight.os, "name", "nt"),
                patch.object(
                    snapshot.preflight, "find_executable", return_value=str(wrapper)
                ),
                patch.object(
                    snapshot.preflight,
                    "probe_executable_report",
                    side_effect=lambda path, *arguments: {
                        "path": path,
                        "arguments": list(arguments),
                        "usable": Path(path).suffix.casefold() == ".exe",
                        "exit_code": 0 if Path(path).suffix.casefold() == ".exe" else 1,
                        "error": None if Path(path).suffix.casefold() == ".exe" else "exit code 1",
                        "stdout": "Poppler",
                        "stderr": "",
                    },
                ),
            ):
                found = snapshot.preflight.resolve_poppler_executable("pdftoppm")
            self.assertEqual(Path(found).suffix.casefold(), ".exe")
            self.assertTrue(Path(found).is_file())
            self.assertNotEqual(Path(found).suffix.casefold(), wrapper.suffix.casefold())

    def test_poppler_resolution_records_failed_wrapper_and_native_success(self) -> None:
        snapshot = load_snapshot_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrapper = root / "pdftoppm.cmd"
            native = root / "pdftoppm.exe"
            wrapper.write_bytes(b"wrapper")
            native.write_bytes(b"binary")
            with patch.object(
                snapshot.preflight,
                "poppler_candidate_paths",
                return_value=[("path", wrapper), ("bundled_native", native)],
            ), patch.object(
                snapshot.preflight,
                "probe_executable_report",
                side_effect=lambda path, *arguments: {
                    "path": path,
                    "arguments": list(arguments),
                    "usable": Path(path).suffix.casefold() == ".exe",
                    "exit_code": 0 if Path(path).suffix.casefold() == ".exe" else 7,
                    "error": None if Path(path).suffix.casefold() == ".exe" else "exit code 7",
                    "stdout": "",
                    "stderr": "wrapper failed",
                },
            ):
                report = snapshot.preflight.resolve_poppler_tool("pdftoppm")
            self.assertTrue(report["usable"])
            self.assertEqual(report["source"], "bundled_native")
            self.assertFalse(report["candidates"][0]["usable"])
            self.assertTrue(report["candidates"][1]["usable"])

    def test_poppler_resolution_fails_closed_when_all_candidates_fail(self) -> None:
        snapshot = load_snapshot_module()
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "pdftoppm.cmd"
            candidate.write_bytes(b"wrapper")
            with patch.object(
                snapshot.preflight,
                "poppler_candidate_paths",
                return_value=[("path", candidate)],
            ), patch.object(
                snapshot.preflight,
                "probe_executable_report",
                return_value={
                    "path": str(candidate),
                    "arguments": ["-v"],
                    "usable": False,
                    "exit_code": 9,
                    "error": "exit code 9",
                    "stdout": "",
                    "stderr": "failed",
                },
            ):
                report = snapshot.preflight.resolve_poppler_tool("pdftoppm")
            self.assertFalse(report["usable"])
            self.assertIsNone(report["path"])
            self.assertEqual(report["error"], "all detected Poppler candidates failed startup")
            self.assertEqual(report["candidates"][0]["probe"]["exit_code"], 9)

    def test_dependency_report_detects_version_mismatch(self) -> None:
        snapshot = load_snapshot_module()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "requirements.txt"
            path.write_text("numpy==0.0.0\n", encoding="utf-8")
            fake_command = {"ok": True, "exit_code": 0, "output": "numpy==2.5.2"}
            with patch.object(snapshot, "run_command", return_value=fake_command):
                report = snapshot.dependency_report(path)
            self.assertFalse(report["core_matches"])
            self.assertEqual(report["mismatches"], ["numpy"])

    def test_texlive_discovery_uses_latest_known_windows_install(self) -> None:
        snapshot = load_snapshot_module()
        with tempfile.TemporaryDirectory() as temporary:
            drive = Path(temporary)
            older = drive / "software" / "texlive" / "2025" / "bin" / "windows"
            latest = drive / "software" / "texlive" / "2026" / "bin" / "windows"
            older.mkdir(parents=True)
            latest.mkdir(parents=True)
            (older / "xelatex.exe").write_bytes(b"old")
            expected = latest / "xelatex.exe"
            expected.write_bytes(b"current")
            with (
                patch.object(snapshot.os, "name", "nt"),
                patch.object(snapshot.preflight, "find_executable", return_value=None),
                patch.object(snapshot, "windows_fixed_drive_roots", return_value=[drive]),
            ):
                found = snapshot.find_tex_executable("xelatex")
            self.assertEqual(Path(found), expected.resolve())

    def test_matlab_mcp_evidence_requires_expected_smoke_value(self) -> None:
        snapshot = load_snapshot_module()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "matlab.json"
            payload = {
                "schema_version": 1,
                "source": "matlab-mcp",
                "verified_at": "2026-08-17T09:00:00+08:00",
                "version": "26.1.0.3203278",
                "release": "R2026a",
                "smoke_expression": "sum((1:10).^2)",
                "expected_value": 385,
                "observed_value": 384,
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            report = snapshot.load_matlab_mcp_evidence(path)
            self.assertFalse(report["valid"])
            self.assertTrue(any("observed_value" in item for item in report["errors"]))

    def test_active_smoke_never_starts_matlab_batch(self) -> None:
        snapshot = load_snapshot_module()
        audit_time = datetime.fromisoformat("2026-08-18T23:59:59+08:00")
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch.object(
                    snapshot, "smoke_docx_pdf", return_value={"passed": True}
                ) as docx_smoke,
                patch.object(
                    snapshot, "smoke_xelatex", return_value={"passed": True}
                ) as xelatex_smoke,
                patch.object(snapshot.subprocess, "run") as subprocess_run,
            ):
                report = snapshot.run_active_smoke({}, Path(temporary), audit_time)
            self.assertTrue(report["passed"])
            self.assertEqual(report["audit_time"], "2026-08-18T23:59:59+08:00")
            self.assertFalse(report["matlab_batch_started"])
            root = Path(temporary).resolve()
            docx_smoke.assert_called_once_with(
                {}, root / "docx-pdf-render", audit_time
            )
            xelatex_smoke.assert_called_once_with({}, root / "xelatex", audit_time)
            subprocess_run.assert_not_called()

    def test_active_smoke_requires_explicit_generated_at(self) -> None:
        snapshot = load_snapshot_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            requirements = root / "requirements.txt"
            requirements.write_text("numpy==2.5.2\n", encoding="utf-8")
            args = Namespace(
                project_root=root,
                requirements=requirements,
                output=None,
                active_smoke=True,
                smoke_dir=root / "smoke",
                matlab_mcp_evidence=None,
                generated_at=None,
                json=False,
            )
            with self.assertRaisesRegex(ValueError, "--generated-at is required"):
                snapshot.build_report(args)

    def test_pdf_metadata_normalization_is_reopenable_and_repeatable(self) -> None:
        from pypdf import PdfReader, PdfWriter

        snapshot = load_snapshot_module()
        audit_time = datetime.fromisoformat("2026-08-18T23:59:59+08:00")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "smoke.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=595.28, height=841.89)
            writer.add_metadata(
                {
                    "/Title": "metadata smoke",
                    "/CreationDate": "D:20260819010101+08'00'",
                    "/ModDate": "D:20260819010101+08'00'",
                }
            )
            with path.open("wb") as stream:
                writer.write(stream)

            report = snapshot.normalize_pdf_metadata(path, audit_time)
            first_hash = snapshot.sha256_file(path)
            repeated_report = snapshot.normalize_pdf_metadata(path, audit_time)
            second_hash = snapshot.sha256_file(path)
            reopened = PdfReader(path)

            self.assertTrue(report["verified"])
            self.assertEqual(report["pdf_date"], "D:20260818235959+08'00'")
            self.assertEqual(reopened.metadata["/Title"], "metadata smoke")
            self.assertEqual(reopened.metadata["/CreationDate"], report["pdf_date"])
            self.assertEqual(reopened.metadata["/ModDate"], report["pdf_date"])
            self.assertEqual(len(reopened.pages), 1)
            self.assertEqual(repeated_report, report)
            self.assertEqual(second_hash, first_hash)

    def test_pdf_metadata_normalization_synchronizes_existing_xmp(self) -> None:
        from pypdf import PdfReader, PdfWriter

        snapshot = load_snapshot_module()
        audit_time = datetime.fromisoformat("2026-08-18T23:59:59+08:00")
        xmp = (
            b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>'
            b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
            b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            b'<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
            b'<dc:date><rdf:Seq><rdf:li>2026-08-19T01:01:01+08:00</rdf:li>'
            b'</rdf:Seq></dc:date></rdf:Description>'
            b'<rdf:Description rdf:about="" xmlns:pdf="http://ns.adobe.com/pdf/1.3/">'
            b'<pdf:Producer>LibreOffice</pdf:Producer></rdf:Description>'
            b'<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
            b'<xmp:CreateDate>2026-08-19T01:01:01+08:00</xmp:CreateDate>'
            b'<xmp:ModifyDate>2026-08-19T01:01:01+08:00</xmp:ModifyDate>'
            b'<xmp:MetadataDate>2026-08-19T01:01:01+08:00</xmp:MetadataDate>'
            b'</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "xmp.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=595.28, height=841.89)
            writer.xmp_metadata = xmp
            with path.open("wb") as stream:
                writer.write(stream)

            report = snapshot.normalize_pdf_metadata(path, audit_time)
            reopened = PdfReader(path)
            raw_xmp = snapshot.raw_xmp_bytes(reopened)

            self.assertTrue(report["verified"])
            self.assertIsNotNone(reopened.xmp_metadata)
            self.assertNotIn(b"2026-08-19", raw_xmp)
            self.assertEqual(
                report["xmp"],
                {
                    "present": True,
                    "create_date": "2026-08-18T23:59:59+08:00",
                    "modify_date": "2026-08-18T23:59:59+08:00",
                    "metadata_date": "2026-08-18T23:59:59+08:00",
                    "dc_dates": ["2026-08-18T23:59:59+08:00"],
                },
            )

    def test_passive_report_writes_only_explicit_output(self) -> None:
        snapshot = load_snapshot_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            requirements = root / "requirements.txt"
            requirements.write_text("numpy==2.5.2\n", encoding="utf-8")
            args = Namespace(
                project_root=root,
                requirements=requirements,
                output=None,
                active_smoke=False,
                smoke_dir=None,
                matlab_mcp_evidence=None,
                generated_at="2026-08-18T23:59:58+08:00",
                json=True,
            )
            dependency = {
                "core_matches": True,
                "pip_check": {"ok": True},
            }
            tools = {
                "word": {"available": False, "usable": False},
            }
            matlab = {"safe_to_start": True}
            before = sorted(path.relative_to(root) for path in root.rglob("*"))
            with (
                patch.object(snapshot, "dependency_report", return_value=dependency),
                patch.object(snapshot, "discover_tools", return_value=(tools, matlab)),
            ):
                report = snapshot.build_report(args)
            after = sorted(path.relative_to(root) for path in root.rglob("*"))
            self.assertTrue(report["ready"])
            self.assertFalse(report["smoke"]["requested"])
            self.assertEqual(report["generated_at"], "2026-08-18T23:59:58+08:00")
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
