"""Regression contracts for the public export backend, independent of private papers."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
TOOLS = ROOT / "tools" / "paper-export"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


engine = load("public_paper_export", TOOLS / "export_paper.py")
reviewer = load("public_page_review", TOOLS / "review_pages.py")
builder = load("public_build_adapter", ROOT / ".agents/skills/math-modeling/templates/build_markdown_paper.py")


class PublicExportContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "paper.md"
        self.source.write_text("# Synthetic\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def ast(self, blocks):
        return {"pandoc-api-version": [1, 23], "meta": {"author": "not transferred"}, "blocks": blocks}

    def image(self, url):
        return {"t": "Image", "c": [["", [], []], [], [url, ""]]}

    def prepare(self, blocks):
        return engine.prepare_ast(self.ast(blocks), self.source, self.root)

    def test_reject_remote_and_active_assets(self):
        for url in ("https://example.org/x.png", "file:///tmp/x.png", "//host/x.png", "data:image/png;base64,abc"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.prepare([self.image(url)])

    def test_reject_asset_escape(self):
        for url in ("../x.png", "%2e%2e/x.png", "sub/../../x.png", "a\\x.png"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.prepare([self.image(url)])

    def test_reject_raw_nodes(self):
        with self.assertRaises(ValueError):
            self.prepare([{"t": "RawBlock", "c": ["openxml", "injected"]}])

    def test_link_contract(self):
        with self.assertRaises(ValueError):
            self.prepare([{"t": "Link", "c": [["", [], []], [], ["file:///secret", ""]]}])
        self.prepare([{"t": "Link", "c": [["", [], []], [], ["https://example.org", ""]]}])

    def test_code_dollars_untouched_and_metadata_removed(self):
        block = {"t": "CodeBlock", "c": [["", ["python"], []], '$literal$']}
        result, labels, count, assets = self.prepare([block])
        self.assertEqual(result["blocks"], [block])
        self.assertEqual(result["meta"], {})
        self.assertEqual((labels, count, assets), ([], 0, {}))

    def test_nested_table_math_and_numeric_tags(self):
        math = {"t": "Math", "c": [{"t": "DisplayMath"}, r'x=1\tag{2.1}']}
        inline = {"t": "Math", "c": [{"t": "InlineMath"}, 'y_i']}
        result, labels, count, _ = self.prepare([math, {"t": "Table", "c": [[[inline]]]}])
        self.assertEqual(labels, ["2.1"])
        self.assertEqual(count, 2)
        self.assertEqual(result["blocks"][0]["c"][1], "x=1")

    def test_duplicate_and_malformed_tags_rejected(self):
        tagged = {"t": "Math", "c": [{"t": "DisplayMath"}, r'x\tag{1}']}
        with self.assertRaises(ValueError):
            self.prepare([tagged, json.loads(json.dumps(tagged))])
        with self.assertRaises(ValueError):
            self.prepare([{"t": "Math", "c": [{"t": "InlineMath"}, r'x\tag{1}']}])

    def test_page_break_is_explicit_and_empty(self):
        result, _, _, _ = self.prepare([{"t": "Div", "c": [["", ["page-break"], []], []]}])
        self.assertIn('w:type="page"', result["blocks"][0]["c"][1])
        with self.assertRaises(ValueError):
            self.prepare([{"t": "Div", "c": [["", ["page-break"], []], [{"t": "Para", "c": []}]]}])

    def test_configuration_rejects_unknown_and_out_of_range(self):
        config = engine.load_spec(ROOT / "doc-export-specs/paper-default.json")
        for key, value in (("margin_cm", 0), ("render_dpi", 9000), ("timeout_seconds", True), ("unknown", "x")):
            path = self.root / "bad.json"
            path.write_text(json.dumps(dict(config, **{key: value})), encoding="utf-8")
            with self.subTest(key=key), self.assertRaises(ValueError):
                engine.load_spec(path)

    def test_missing_binary_fails(self):
        with self.assertRaises(ValueError):
            engine.executable("nonexistent-paper-export-binary-371992")

    def test_failed_subprocess_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError, "failed"):
            engine.run([sys.executable, "-c", "raise SystemExit(7)"], timeout=10)

    def test_timeout_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            engine.run([sys.executable, "-c", "import time;time.sleep(10)"], timeout=.1)

    def test_public_adapter_default_and_custom_spec(self):
        (self.root / "tools/paper-export").mkdir(parents=True)
        (self.root / "tools/paper-export/export_paper.py").write_text("# fake")
        (self.root / "doc-export-specs").mkdir()
        (self.root / "doc-export-specs/paper-default.json").write_text("{}")
        tool, spec = builder.find_public_backend(self.root, "cumcm-cn.yaml")
        self.assertEqual(spec.name, "paper-default.json")
        with self.assertRaises(FileNotFoundError):
            builder.find_public_backend(self.root, "custom.json")
        with self.assertRaises(ValueError):
            builder.find_public_backend(self.root, "../private.json")

    def test_public_adapter_routes_pdf_and_document_runtime(self):
        (self.root / "paper").mkdir()
        (self.root / "paper/full-paper.md").write_text("# Example")
        with patch.object(builder, "find_public_backend", return_value=(TOOLS / "export_paper.py", ROOT / "doc-export-specs/paper-default.json")), patch.object(sys, "argv", ["build", "--case-dir", str(self.root), "--document-python", "document-runtime", "--pdf"]), patch.object(builder.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(builder.main(), 0)
            command = run.call_args.args[0]
            self.assertEqual(command[0], "document-runtime")
            self.assertIn("--asset-root", command)
            self.assertIn("--pdf", command)
            self.assertNotIn("--toc", command)
            self.assertNotIn("--refresh-fields", command)

    def test_bundle_tampering_and_escape_rejected(self):
        path = self.root / "artifact.bin"
        path.write_bytes(b"before")
        item = {"file": path.name, "sha256": engine.digest(path)}
        self.assertEqual(reviewer.checked_file(self.root, item), path)
        path.write_bytes(b"after")
        with self.assertRaises(ValueError):
            reviewer.checked_file(self.root, item)
        with self.assertRaises(ValueError):
            reviewer.checked_file(self.root, {"file": "../outside", "sha256": "x"})

    def bundle(self):
        from PIL import Image
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        pdf = self.root / "paper.pdf"
        with pdf.open("wb") as stream:
            writer.write(stream)
        docx = self.root / "paper.docx"
        docx.write_bytes(b"hash-only fixture; not a DOCX validation test")
        image = self.root / "page-1.png"
        Image.new("RGB", (10, 10), "white").save(image)
        data = {"schema_version": 1, "status": "pending_visual_review", "submission_ready": False,
                "artifacts": [{"file": p.name, "sha256": engine.digest(p)} for p in (pdf, docx)],
                "page_count": 1, "pages": [{"page": 1, "file": image.name, "sha256": engine.digest(image)}]}
        manifest = self.root / "paper.export.json"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        return manifest, data

    def test_page_bundle_stays_pending(self):
        manifest, _ = self.bundle()
        result = reviewer.verify(manifest)
        self.assertEqual(result["visual_review"], "pending")
        self.assertFalse(result["submission_ready"])

    def test_page_loss_and_false_acceptance_rejected(self):
        manifest, data = self.bundle()
        for change in ({"pages": []}, {"submission_ready": True}, {"page_count": 2}):
            manifest.write_text(json.dumps(dict(data, **change)), encoding="utf-8")
            with self.assertRaises(ValueError):
                reviewer.verify(manifest)

    def test_complete_ai_review_not_human_acceptance(self):
        manifest, data = self.bundle()
        review = self.root / "ai-review.json"
        observation = {"manifest_sha256": engine.digest(manifest), "reviewer_kind": "ai",
                       "pages": [{"page": 1, "sha256": data["pages"][0]["sha256"], "status": "pass", "notes": "synthetic unit test only"}]}
        review.write_text(json.dumps(observation), encoding="utf-8")
        result = reviewer.verify(manifest, review)
        self.assertEqual(result["visual_review"], "ai_pass")
        self.assertEqual(result["human_acceptance"], "not_recorded")
        self.assertFalse(result["submission_ready"])
        observation["pages"][0]["status"] = "fail"
        review.write_text(json.dumps(observation), encoding="utf-8")
        self.assertEqual(reviewer.verify(manifest, review)["visual_review"], "ai_fail")
        for invalid in (None, [], {}, 0, " "):
            observation["pages"][0]["notes"] = invalid
            review.write_text(json.dumps(observation), encoding="utf-8")
            with self.assertRaises(ValueError):
                reviewer.verify(manifest, review)

    def test_stale_or_incomplete_ai_review_rejected(self):
        manifest, data = self.bundle()
        path = self.root / "review.json"
        for observation in (
            {"manifest_sha256": "stale", "reviewer_kind": "ai", "pages": []},
            {"manifest_sha256": engine.digest(manifest), "reviewer_kind": "ai", "pages": []},
            {"manifest_sha256": engine.digest(manifest), "reviewer_kind": "human", "pages": data["pages"]},
        ):
            path.write_text(json.dumps(observation), encoding="utf-8")
            with self.assertRaises(ValueError):
                reviewer.verify(manifest, path)

    @unittest.skipUnless(shutil.which("pandoc"), "Pandoc not available: native equation integration NOT VERIFIED")
    def test_native_equation_order_tables_code_and_numbering(self):
        # Use the explicitly selected document runtime in managed document environments.
        runtime = os.environ.get("PAPER_DOCUMENT_PYTHON", sys.executable)
        self.source.write_text('# Native math\n\nBefore $x_i$ middle **bold** $y_i$ after.\n\n'
                               '| Symbol | Meaning |\n|---|---|\n| $z_i$ | sample |\n\n'
                               '$$\\frac{x}{2}=y\\tag{1}$$\n\n```python\nlabel="$literal$"\n```\n', encoding='utf-8')
        output = self.root / "native.docx"
        command = [runtime, "-B", str(TOOLS / "export_paper.py"), "--md", str(self.source),
                   "--asset-root", str(self.root), "--spec", str(ROOT / "doc-export-specs/paper-default.json"), "--out", str(output)]
        completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=150)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        import zipfile
        from xml.etree import ElementTree as ET
        ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
              'm':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
        with zipfile.ZipFile(output) as archive:
            tree = ET.fromstring(archive.read('word/document.xml'))
            self.assertEqual(len(tree.findall('.//m:oMath',ns)),4)
            texts = ''.join(tree.itertext())
            self.assertIn('(1)',texts)
            self.assertIn('$literal$',texts)
            self.assertNotIn('\\frac',texts)
            paragraph = next(p for p in tree.findall('.//w:p',ns) if 'Before' in ''.join(p.itertext()))
            text = ''.join(paragraph.itertext())
            self.assertLess(text.index('Before'),text.index('middle'))
            self.assertLess(text.index('middle'),text.index('after'))
            self.assertEqual(len(paragraph.findall('.//m:oMath',ns)),2)
            self.assertTrue(paragraph.findall('.//w:b',ns))
            self.assertTrue(tree.findall('.//w:tc//m:oMath',ns))
        data = json.loads(output.with_suffix('.export.json').read_text())
        self.assertFalse(data['submission_ready'])
        with self.assertRaises(ValueError):
            reviewer.verify(output.with_suffix('.export.json'))
        again = subprocess.run(command, capture_output=True, timeout=150)
        self.assertNotEqual(again.returncode, 0)


if __name__ == "__main__":
    unittest.main()

