from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import audit_docx_local_format as guard


class LocalFormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.before, self.after = self.root / "before.docx", self.root / "after.docx"
        self.xml = (f'<w:document xmlns:w="{guard.W}" xmlns:m="{guard.M}"><w:body>'
                    '<w:p><w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>Abstract</w:t></w:r></w:p>'
                    '<w:p><w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>Other text (1)</w:t></w:r></w:p>'
                    '<w:p><m:oMath><m:r><w:rPr><w:sz w:val="24"/></w:rPr><m:t>x</m:t></m:r></m:oMath></w:p>'
                    '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>C: moisture kg/kg</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
                    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>'
                    '</w:body></w:document>').encode()
        self.parts = {guard.DOC: self.xml, "word/styles.xml": b"styles-baseline",
                      "word/_rels/document.xml.rels": b"relationships-baseline",
                      "word/media/image1.png": b"image-baseline"}
        self.write(self.before, self.parts)
        self.tree = ET.fromstring(self.xml)
        self.body = self.tree.find(guard.q("w:body"))
        node = self.body[0][0]
        self.plan = {"schema_version": 1, "before_sha256": guard.sha(self.before.read_bytes()),
                     "targets": [{"path": [0, 0], "node_sha256": guard.node_hash(node),
                                  "properties": {"w:sz": {"w:val": "26"}}}]}

    @staticmethod
    def write(path, parts):
        with zipfile.ZipFile(path, "w") as z:
            for key, value in parts.items():
                z.writestr(key, value)

    def result(self, parts=None):
        if parts is None:
            parts = dict(self.parts)
            parts[guard.DOC] = ET.tostring(self.tree)
        self.write(self.after, parts)
        return guard.audit(self.before, self.after, self.plan)

    def allowed_edit(self):
        self.body[0][0][0][0].set(guard.q("w:val"), "26")

    def test_only_selected_size_passes_but_invalidates_page_review(self):
        self.allowed_edit()
        r = self.result()
        self.assertTrue(r["passed"], r)
        self.assertTrue(r["requires_export_and_page_review"])
        self.assertFalse(r["visual_review_passed"])

    def test_unrelated_size_or_bold_is_blocked(self):
        self.allowed_edit()
        prop = self.body[1][0][0]
        prop[0].set(guard.q("w:val"), "18")
        self.assertFalse(self.result()["passed"])
        prop[0].set(guard.q("w:val"), "24")
        ET.SubElement(prop, guard.q("w:b"))
        self.assertFalse(self.result()["passed"])

    def test_even_selected_run_cannot_change_unlisted_bold_or_text(self):
        self.allowed_edit()
        r = self.body[0][0]
        bold = ET.SubElement(r[0], guard.q("w:b"))
        self.assertFalse(self.result()["passed"])
        r[0].remove(bold)
        r[1].text = "Changed scientific claim"
        self.assertFalse(self.result()["passed"])

    def test_formula_text_structure_and_number_are_protected(self):
        self.allowed_edit()
        base = ET.tostring(self.tree)
        for change in ("text", "structure", "number"):
            with self.subTest(change=change):
                self.tree = ET.fromstring(base)
                self.body = self.tree.find(guard.q("w:body"))
                if change == "text":
                    self.body[2][0][0][-1].text = "y"
                elif change == "structure":
                    self.body[2].remove(self.body[2][0])
                else:
                    self.body[1][0][-1].text = "Other text (2)"
                self.assertFalse(self.result()["passed"])

    def test_math_run_size_can_be_targeted_without_changing_formula(self):
        run = self.body[2][0][0]
        self.plan["targets"] = [{"path": [2, 0, 0], "node_sha256": guard.node_hash(run),
                                 "properties": {"w:sz": {"w:val": "22"}}}]
        run[0][0].set(guard.q("w:val"), "22")
        self.assertTrue(self.result()["passed"])
        run[-1].text = "y"
        self.assertFalse(self.result()["passed"])

    def test_symbol_table_and_section_geometry_are_protected(self):
        self.allowed_edit()
        self.body[3][0][0][0][0][0].text = "Missing symbol"
        self.assertFalse(self.result()["passed"])
        self.body[3][0][0][0][0][0].text = "C: moisture kg/kg"
        self.body[4][0].set(guard.q("w:w"), "10000")
        self.assertFalse(self.result()["passed"])

    def test_shared_styles_media_relationships_and_added_parts_block(self):
        self.allowed_edit()
        parts = dict(self.parts)
        parts[guard.DOC] = ET.tostring(self.tree)
        for key in ("word/styles.xml", "word/media/image1.png", "word/_rels/document.xml.rels",
                    "word/theme/theme1.xml", "word/numbering.xml", "word/header1.xml", "docProps/core.xml"):
            with self.subTest(key=key):
                modified = dict(parts)
                modified[key] = b"modified"
                r = self.result(modified)
                self.assertFalse(r["passed"])
                self.assertTrue(any(key in error for error in r["errors"]))

    def test_declared_paragraph_centering_and_bold_change(self):
        p = self.body[0]
        self.plan["targets"] = [{"path": [0], "node_sha256": guard.node_hash(p),
                                 "properties": {"w:jc": {"w:val": "center"}}}]
        pr = ET.Element(guard.q("w:pPr"))
        ET.SubElement(pr, guard.q("w:jc"), {guard.q("w:val"): "center"})
        p.insert(0, pr)
        self.assertTrue(self.result()["passed"])
        # Separate fixture: explicitly authorized direct bold is not a blanket pass.
        self.tree = ET.fromstring(self.xml)
        self.body = self.tree.find(guard.q("w:body"))
        run = self.body[0][0]
        self.plan["targets"] = [{"path": [0, 0], "node_sha256": guard.node_hash(run),
                                 "properties": {"w:b": {"w:val": "1"}}}]
        ET.SubElement(run[0], guard.q("w:b"), {guard.q("w:val"): "1"})
        self.assertTrue(self.result()["passed"])

    def test_expected_property_value_is_enforced(self):
        self.body[0][0][0][0].set(guard.q("w:val"), "48")
        r = self.result()
        self.assertFalse(r["passed"])
        self.assertIn("expected property value", " ".join(r["errors"]))

    def test_explicit_removal_and_unchanged_input(self):
        self.plan["targets"][0]["properties"] = {"w:sz": None}
        self.body[0][0].remove(self.body[0][0][0])
        self.assertTrue(self.result()["passed"])
        self.plan["targets"][0]["properties"] = {"w:sz": {"w:val": "24"}}
        r = guard.audit(self.before, self.before, self.plan)
        self.assertTrue(r["passed"], r)
        self.assertFalse(r["requires_export_and_page_review"])
        self.assertFalse(r["visual_review_passed"])

    def test_duplicate_zip_members_and_dtd_block(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.after, "w") as z:
                z.writestr(guard.DOC, self.xml)
                z.writestr(guard.DOC, self.xml)
        self.assertFalse(guard.audit(self.before, self.after, self.plan)["passed"])
        parts = dict(self.parts)
        parts[guard.DOC] = b'<!DOCTYPE document []>' + self.xml
        self.assertFalse(self.result(parts)["passed"])

    def test_guard_is_routed_and_pending_template_fails(self):
        skill = SCRIPTS.parent
        self.assertIn("audit_docx_local_format.py", (skill / "SKILL.md").read_text(encoding="utf8"))
        production = (skill / "references/paper-production.md").read_text(encoding="utf8")
        for marker in ("before exporting/promoting", "final full-page review", "shared styles", "node_sha256"):
            self.assertIn(marker, production)
        self.plan = json.loads((skill / "templates/docx-local-format-plan.json").read_text(encoding="utf8"))
        self.assertFalse(self.result()["passed"])

    def test_stale_base_or_node_and_duplicate_targets_rejected(self):
        self.allowed_edit()
        original = copy.deepcopy(self.plan)
        for mode in ("base", "node", "duplicate", "invalid_path", "unsupported", "bool_version"):
            self.plan = copy.deepcopy(original)
            if mode == "base": self.plan["before_sha256"] = "0" * 64
            if mode == "node": self.plan["targets"][0]["node_sha256"] = "0" * 64
            if mode == "duplicate": self.plan["targets"] *= 2
            if mode == "invalid_path": self.plan["targets"][0]["path"] = [True]
            if mode == "unsupported": self.plan["targets"][0]["properties"] = {"w:t": {}}
            if mode == "bool_version": self.plan["schema_version"] = True
            with self.subTest(mode=mode): self.assertFalse(self.result()["passed"])

    def test_insertion_before_target_and_duplicate_properties_block(self):
        self.allowed_edit()
        self.body.insert(0, ET.Element(guard.q("w:p")))
        self.assertFalse(self.result()["passed"])
        self.body.remove(self.body[0])
        ET.SubElement(self.body[0][0][0], guard.q("w:sz"), {guard.q("w:val"): "26"})
        self.assertFalse(self.result()["passed"])

    def test_cli_describe_and_audit_do_not_write_inputs(self):
        self.allowed_edit()
        self.result()
        plan = self.root / "plan.json"
        plan.write_text(json.dumps(self.plan), encoding="utf8")
        before = {p.name: guard.sha(p.read_bytes()) for p in self.root.iterdir()}
        for args in (["--describe"], ["--after", str(self.after), "--plan", str(plan)]):
            r = subprocess.run([sys.executable, "-B", str(SCRIPTS / "audit_docx_local_format.py"),
                                "--before", str(self.before), *args], capture_output=True, text=True,
                               encoding="utf8", timeout=15)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            json.loads(r.stdout)
        self.assertEqual(before, {p.name: guard.sha(p.read_bytes()) for p in self.root.iterdir()})


if __name__ == "__main__":
    unittest.main()
