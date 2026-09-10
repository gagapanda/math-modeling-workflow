from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
SCHEMAS = SKILL_DIR / "schemas"


def load_module(name: str, path: Path):
    import sys
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = load_module("math_modeling_support_smoke", SCRIPTS / "audit_support_package.py")


class SupportPackageSmokeTests(unittest.TestCase):
    def make_package(self, root: Path) -> tuple[Path, Path]:
        source = root / "src"
        source.mkdir()
        (source / "solve.py").write_text(
            "from pathlib import Path\nPath('results').mkdir(exist_ok=True)\nPath('results/out.txt').write_text('ok\\n')\n",
            encoding="utf-8",
        )
        package = root / "support.zip"
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(source / "solve.py", "src/solve.py")
        plan = {
            "schema_version": 1,
            "package": "support.zip",
            "tests": [
                {
                    "name": "solve",
                    "command": ["python", "src/solve.py"],
                    "cwd": ".",
                    "expected_outputs": ["results/out.txt"],
                    "timeout_seconds": 10,
                }
            ],
        }
        plan_path = root / "support-smoke-plan.json"
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        return package, plan_path

    def test_smoke_passes_and_records_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package, plan = self.make_package(Path(temporary))
            report = smoke.audit_support_package(package, plan)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(report["tests"][0]["exit_code"], 0)
            self.assertEqual(report["tests"][0]["expected_outputs"], ["results/out.txt"])
            from _json_schema import load_and_validate
            load_and_validate(report, SCHEMAS / "support-smoke-report.schema.json", "support smoke report")

    def test_smoke_rejects_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package, plan = self.make_package(Path(temporary))
            data = json.loads(plan.read_text(encoding="utf-8"))
            data["tests"][0]["command"] = ["python", "-c", "raise SystemExit(3)"]
            plan.write_text(json.dumps(data), encoding="utf-8")
            report = smoke.audit_support_package(package, plan)
            self.assertFalse(report["passed"])
            self.assertEqual(report["tests"][0]["exit_code"], 3)

    def test_smoke_rejects_absolute_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package, plan = self.make_package(Path(temporary))
            data = json.loads(plan.read_text(encoding="utf-8"))
            data["tests"][0]["command"] = [str(Path.cwd() / "python.exe"), "src/solve.py"]
            plan.write_text(json.dumps(data), encoding="utf-8")
            report = smoke.audit_support_package(package, plan)
            self.assertFalse(report["passed"])
            self.assertTrue(any("absolute" in error for error in report["errors"]))

    def test_smoke_enforces_case_relative_input_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "analyze.py"
            source.write_text(
                "from pathlib import Path\n"
                "value = Path('problem/source/attachment.txt').read_text(encoding='utf-8')\n"
                "Path('results').mkdir(exist_ok=True)\n"
                "Path('results/out.txt').write_text(value, encoding='utf-8')\n",
                encoding="utf-8",
            )
            attachment = root / "attachment.txt"
            attachment.write_text("verified\n", encoding="utf-8")
            package = root / "support.zip"
            plan = root / "support-smoke-plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "package": "support.zip",
                        "tests": [
                            {
                                "name": "main-analysis",
                                "command": ["python", "src/analyze.py"],
                                "cwd": ".",
                                "expected_outputs": ["results/out.txt"],
                                "timeout_seconds": 10,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(source, "src/analyze.py")
                archive.write(attachment, "problem/attachment.txt")
            report = smoke.audit_support_package(package, plan)
            self.assertFalse(report["passed"])
            self.assertEqual(report["tests"][0]["exit_code"], 1)
            self.assertIn("results/out.txt", report["tests"][0]["missing_outputs"])

            with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(source, "src/analyze.py")
                archive.write(attachment, "problem/source/attachment.txt")
            report = smoke.audit_support_package(package, plan)
            self.assertTrue(report["passed"], report["errors"])
            self.assertEqual(report["tests"][0]["missing_outputs"], [])


if __name__ == "__main__":
    unittest.main()
