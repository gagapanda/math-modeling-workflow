from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
SCHEMAS = SKILL_DIR / "schemas"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _json_schema import DRAFT_2020_12, load_and_validate, validate, validate_schema


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class JsonSchemaTests(unittest.TestCase):
    def test_bundled_schemas_are_valid_draft_2020_12_documents(self) -> None:
        for path in sorted(SCHEMAS.glob("*.schema.json")):
            with self.subTest(schema=path.name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(schema["$schema"], DRAFT_2020_12)
                validate_schema(schema)

    def test_workflow_quality_gate_plan_is_optional_and_schema_validated(self) -> None:
        manifest = {
            "schema_version": 2,
            "profile": "practice",
            "quality_gate_plan": "paper/quality-gate-plan.json",
            "artifacts": {
                "docx": "paper/paper.docx",
                "pdf": "paper/paper.pdf",
                "render_dir": "paper/rendered-pages",
                "visual_review": "paper/visual-review.json",
            },
            "steps": [
                {"name": "analyze", "script": "src/analyze.py"}
            ],
        }
        load_and_validate(manifest, SCHEMAS / "workflow.schema.json", "workflow")

    def test_scaffolded_profiles_match_workflow_schema(self) -> None:
        scaffold = load_module("math_modeling_scaffold", SCRIPTS / "scaffold_case.py")
        schema = SCHEMAS / "workflow.schema.json"
        for profile in ("explore", "practice", "submission"):
            with self.subTest(profile=profile):
                load_and_validate(json.loads(scaffold.workflow_content(profile)), schema, "workflow")

    def test_data_cleaning_plan_matches_its_schema(self) -> None:
        plan = {
            "version": 1,
            "input_sha256": "a" * 64,
            "row_id_columns": ["id"],
            "rules": [
                {
                    "id": "trim_name",
                    "operation": "trim_whitespace",
                    "columns": ["name"],
                    "reason": "remove documented padding",
                    "expected_changes": 2,
                },
                {
                    "id": "clip_value",
                    "operation": "clip_numeric",
                    "columns": ["value"],
                    "minimum": 0,
                    "maximum": 100,
                    "reason": "reviewed instrument range",
                    "expected_changes": 1,
                },
            ],
        }
        load_and_validate(
            plan,
            SCHEMAS / "data-cleaning-plan.schema.json",
            "data cleaning plan",
        )

    def test_submission_package_plan_matches_its_schema(self) -> None:
        plan = {
            "schema_version": 1,
            "finalization_report": "paper/finalization-report.json",
            "paper": {
                "source": "paper/paper.pdf",
                "output_name": "paper.pdf",
                "max_bytes": 20 * 1024 * 1024,
            },
            "support": {
                "output_name": "support-materials.zip",
                "max_bytes": 20 * 1024 * 1024,
                "files": [
                    {"source": "src/solve.py", "archive_path": "src/solve.py"}
                ],
            },
            "anonymity": {"forbidden_terms": []},
        }
        load_and_validate(
            plan,
            SCHEMAS / "submission-package-plan.schema.json",
            "submission package plan",
        )

    def test_timed_rehearsal_plan_matches_its_schema(self) -> None:
        plan = {
            "schema_version": 1,
            "rehearsal_id": "2026-e-001",
            "mode": "timed-practice",
            "competition": "CUMCM 2026",
            "problem": "2025 E",
            "started_at": "2026-08-17T08:00:00+08:00",
            "deadline_at": "2026-08-18T08:00:00+08:00",
            "team": [{"member_id": "member-a", "role": "modeling"}],
            "phases": [
                {"id": phase_id, "planned_minutes": 60}
                for phase_id in (
                    "problem-selection", "baseline", "primary-model",
                    "synchronized-writing", "independent-review", "packaging",
                )
            ],
            "fault_injections": [],
        }
        load_and_validate(
            plan,
            SCHEMAS / "timed-rehearsal-plan.schema.json",
            "timed rehearsal plan",
        )

    def test_min_properties_is_enforced(self) -> None:
        schema = {"type": "object", "minProperties": 1}
        self.assertIn("at least 1 properties", str(validate({}, schema)[0]))
        self.assertEqual(validate({"value": 1}, schema), [])

    def test_workflow_conditionals_report_json_pointer(self) -> None:
        schema = SCHEMAS / "workflow.schema.json"
        manifest = {
            "schema_version": 2,
            "profile": "explore",
            "steps": [
                {
                    "name": "analyze",
                    "script": "src/analyze.py",
                    "cache": True,
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, r"/steps/0/outputs: is required"):
            load_and_validate(manifest, schema, "pipeline manifest")

        manifest["steps"][0]["outputs"] = ["results/out.json"]
        manifest["profile"] = "submission"
        with self.assertRaisesRegex(ValueError, r"/compliance: is required"):
            load_and_validate(manifest, schema, "pipeline manifest")

    def test_compliance_conditionals_require_used_detail_pdf(self) -> None:
        compliance = {
            "schema_version": 1,
            "competition": "CUMCM 2026",
            "year": 2026,
            "rules": {
                "verified_at": "2026-08-14",
                "max_age_days": 30,
                "sources": ["https://www.mcm.edu.cn/rules"],
            },
            "ai": {
                "status": "used",
                "usage_log": "ai/usage.md",
                "paper_statement": "Reviewed statement",
            },
        }
        with self.assertRaisesRegex(ValueError, r"/ai/detail_pdf: is required"):
            load_and_validate(
                compliance,
                SCHEMAS / "submission-compliance.schema.json",
                "submission compliance",
            )

        compliance["ai"]["status"] = "not-used"
        load_and_validate(
            compliance,
            SCHEMAS / "submission-compliance.schema.json",
            "submission compliance",
        )

    def test_semantic_path_validation_still_runs_after_schema(self) -> None:
        pipeline = load_module("math_modeling_pipeline_schema_test", SCRIPTS / "run_pipeline.py")
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            manifest_path = case_dir / "workflow.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "profile": "explore",
                        "steps": [
                            {"name": "analyze", "script": "../outside.py"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "escapes the case directory"):
                pipeline.load_manifest(case_dir, manifest_path)


if __name__ == "__main__":
    unittest.main()
