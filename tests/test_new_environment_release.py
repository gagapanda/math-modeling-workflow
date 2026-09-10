"""C2 dependency diagnostics and source-release guard regression tests."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


doc = load("export_doctor", ROOT / "tools/paper-export/doctor.py")
release = load("release_guard", ROOT / "scripts/check_release_inventory.py")


class NewEnvironmentAndRelease(unittest.TestCase):
    def test_missing_package_is_not_available(self):
        self.assertEqual(doc.probe_package("missing-distribution-37199", "missing_module_37199")["status"], "missing_or_broken")

    def test_missing_native_tool_fails(self):
        self.assertEqual(doc.probe_tool("pandoc", "missing-native-binary-37199")["status"], "missing")

    def test_shell_wrapper_is_not_a_native_tool(self):
        with patch.object(doc.shutil, "which", return_value="fake.cmd"):
            self.assertEqual(doc.probe_tool("pandoc", "fake")["status"], "missing")

    def test_probe_timeout_is_not_available(self):
        with patch.object(doc.shutil, "which", return_value="fake.exe"), patch.object(doc.subprocess, "run", side_effect=subprocess.TimeoutExpired("fake",15)):
            self.assertEqual(doc.probe_tool("pandoc", "fake")["status"], "probe_failed")

    def test_doctor_available_does_not_approve_submission(self):
        args = types.SimpleNamespace(pdf=True,pandoc="x",soffice="y",pdftoppm="z")
        with patch.object(doc,"probe_package",return_value={"status":"available"}),patch.object(doc,"probe_tool",return_value={"status":"available"}):
            result=doc.diagnose(args)
        self.assertTrue(result["ready_to_attempt_export"])
        self.assertFalse(result["submission_ready"])
        self.assertFalse(result["release_authorized"])

    def fixture(self, root):
        (root/"docs").mkdir()
        (root/"LICENSE").write_text("许可证将在审查后确定",encoding="utf-8")
        import hashlib
        rows=[{"path":"LICENSE","sha256":hashlib.sha256((root/"LICENSE").read_bytes()).hexdigest()},
              {"path":release.MANIFEST,"sha256":None}]
        for row in rows:
            row.update(source_class="project",source_reference="test",license_expression="NOASSERTION",authorization_status="pending")
        data={"schema_version":1,"project_license_status":"pending","dependency_distribution_review":"confirmed_source_only","files":rows}
        (root/release.MANIFEST).write_text(json.dumps(data),encoding="utf-8")
        return data

    def test_complete_inventory_is_not_release_permission(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.fixture(root);r=release.verify(root)
            self.assertTrue(r["inventory_valid"])
            self.assertFalse(r["release_ready"])
            self.assertEqual(r["pending_authorization_count"],2)

    def test_hash_tampering_fails(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.fixture(root);(root/"LICENSE").write_text("modified")
            self.assertFalse(release.verify(root)["inventory_valid"])

    def test_unregistered_file_fails(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.fixture(root);(root/"unexpected.py").write_text("# unreviewed")
            self.assertFalse(release.verify(root)["inventory_valid"])

    def test_deleted_file_fails(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.fixture(root);(root/"LICENSE").unlink()
            self.assertFalse(release.verify(root)["inventory_valid"])

    def test_duplicate_record_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);data=self.fixture(root);data["files"].append(data["files"][0])
            (root/release.MANIFEST).write_text(json.dumps(data))
            with self.assertRaises(ValueError):release.verify(root)

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);data=self.fixture(root);data["files"][0]["path"]="../LICENSE"
            (root/release.MANIFEST).write_text(json.dumps(data))
            with self.assertRaises(ValueError):release.verify(root)

    def test_fake_confirmation_needs_evidence(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);data=self.fixture(root)
            data["files"][0].update(authorization_status="confirmed",license_expression="MIT")
            (root/release.MANIFEST).write_text(json.dumps(data))
            self.assertFalse(release.verify(root)["inventory_valid"])


if __name__ == "__main__":
    unittest.main()
