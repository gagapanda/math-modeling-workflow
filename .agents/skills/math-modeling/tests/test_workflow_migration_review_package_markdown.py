from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
PACKAGER = SCRIPTS / "prepare_workflow_migration_review_package.py"
RENDERER = SCRIPTS / "render_workflow_migration_review_package.py"


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
    )


def snapshot(case_dir: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(case_dir)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in case_dir.rglob("*")
        if path.is_file()
    }


def make_case(root: Path, *, schema_version: int = 1) -> Path:
    case_dir = root / "markdown-review-case"
    (case_dir / "src").mkdir(parents=True)
    (case_dir / "src" / "produce.py").write_text(
        "from pathlib import Path\n"
        "root = Path(__file__).resolve().parents[1]\n"
        "source = root / 'data' / 'source_[x]*.json'\n"
        "target = root / 'results' / 'shared.json'\n"
        "target.write_text(source.read_text(encoding='utf-8'), encoding='utf-8')\n",
        encoding="utf-8",
    )
    (case_dir / "src" / "consume.py").write_text(
        "from pathlib import Path\n"
        "from helpers import read_result as load_result\n"
        "root = Path(__file__).resolve().parents[1]\n"
        "source = root / 'results' / 'shared.json'\n"
        "target = root / 'paper' / 'summary.txt'\n"
        "target.write_text(load_result(source), encoding='utf-8')\n"
        "def read_nested(path):\n"
        "    return (path / 'hidden.json').read_text(encoding='utf-8')\n"
        "read_nested(root / 'data')\n",
        encoding="utf-8",
    )
    (case_dir / "src" / "helpers.py").write_text(
        "def read_result(path):\n"
        "    return path.read_text(encoding='utf-8')\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": schema_version,
        "steps": [
            {"name": "produce-x", "script": "src/produce.py"},
            {"name": "consume", "script": "src/consume.py"},
        ],
    }
    if schema_version == 1:
        manifest["artifacts"] = {
            "docx": "paper/paper.docx",
            "pdf": "paper/paper.pdf",
            "render_dir": "paper/rendered-pages",
            "visual_review": "paper/visual-review.json",
        }
    else:
        manifest["profile"] = "explore"
    (case_dir / "workflow.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return case_dir


def package(case_dir: Path) -> dict:
    completed = run(
        [
            sys.executable,
            str(PACKAGER),
            "--case-dir",
            str(case_dir),
            "--json",
        ]
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)


class WorkflowMigrationReviewPackageMarkdownTests(unittest.TestCase):
    def test_markdown_is_repeatable_for_deep_unicode_and_space_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "\u4e2d\u6587 \u8def\u5f84" / "nested review"
            case_dir = make_case(root)
            before = snapshot(case_dir)
            command = [sys.executable, str(RENDERER), "--case-dir", str(case_dir)]

            first = run(command)
            second = run(command)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(first.stdout.encode("utf-8"), second.stdout.encode("utf-8"))
            self.assertIn("\u4e2d\u6587 \u8def\u5f84", first.stdout)
            case_line = next(
                line for line in first.stdout.splitlines() if line.startswith("- Case: ")
            )
            self.assertNotIn("\\", case_line)
            self.assertEqual(snapshot(case_dir), before)

    def test_renderer_rejects_file_output_and_leaves_no_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_case(Path(temporary))
            output = case_dir / "human-review.md"
            before = snapshot(case_dir)

            completed = run(
                [
                    sys.executable,
                    str(RENDERER),
                    "--case-dir",
                    str(case_dir),
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("unrecognized arguments: --output", completed.stderr)
            self.assertFalse(output.exists())
            self.assertEqual(snapshot(case_dir), before)

    def test_renders_complete_hash_bound_stdout_view_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_case(Path(temporary))
            report = package(case_dir)
            before = snapshot(case_dir)

            completed = run(
                [
                    sys.executable,
                    str(RENDERER),
                    "--case-dir",
                    str(case_dir),
                    "--expected-source-sha256",
                    report["bindings"]["source_manifest"]["sha256"],
                    "--expected-candidate-sha256",
                    report["bindings"]["base_candidate_sha256"],
                ]
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            markdown = completed.stdout
            self.assertTrue(markdown.startswith("# Workflow Migration Human Review Work Package\n"))
            self.assertIn(report["bindings"]["source_manifest"]["sha256"], markdown)
            self.assertIn(report["bindings"]["base_candidate_sha256"], markdown)
            for binding in report["bindings"]["python_scripts"]:
                self.assertIn(binding["sha256"], markdown)
            for binding in report["bindings"]["support_modules"]:
                self.assertIn(binding["sha256"], markdown)
            self.assertIn("### Traced Support Modules", markdown)
            self.assertIn("`produce-x` -> `consume` via `results/shared.json`", markdown)
            self.assertIn("`data/source_[x]*.json`", markdown)
            self.assertEqual(markdown.count("- [ ]"), 10)
            self.assertEqual(markdown.count("`pending_human_review`"), 10)
            self.assertIn("- Files written: `false`", markdown)
            self.assertIn("- Case steps executed: `false`", markdown)
            self.assertIn("- Cache-enable recommendations: 0", markdown)
            self.assertIn("- Provenance chains: ", markdown)
            self.assertIn("- Trace limitation occurrences: 1", markdown)
            self.assertIn("- Unique trace limitations: 1", markdown)
            self.assertIn("- Trace limitations: 1", markdown)
            self.assertIn("- Trace limitation groups: 1", markdown)
            self.assertIn("Provenance `direct`:", markdown)
            self.assertIn("Provenance `imported_helper`:", markdown)
            self.assertIn("## Trace Limitations", markdown)
            self.assertIn("`path_parameter_transformed`", markdown)
            self.assertIn(
                "##### Stop `src/consume.py:read_nested:8:read_text`", markdown
            )
            self.assertIn("- Occurrences: 1", markdown)
            self.assertIn("- Unique call chains: 1", markdown)
            self.assertIn(
                "src/consume.py:<module>:9:read_nested -> "
                "src/consume.py:read_nested:8:read_text",
                markdown,
            )
            self.assertIn("`review_required`", markdown)
            self.assertIn(
                "src/consume.py:<module>:6:load_result -> src/helpers.py:read_result:2:read_text",
                markdown,
            )
            self.assertNotIn("<script", markdown.casefold())
            self.assertEqual(snapshot(case_dir), before)

    def test_stale_binding_fails_closed_and_remains_stdout_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_case(Path(temporary))
            before = snapshot(case_dir)

            completed = run(
                [
                    sys.executable,
                    str(RENDERER),
                    "--case-dir",
                    str(case_dir),
                    "--expected-source-sha256",
                    "0" * 64,
                ]
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("> Status: `failed`", completed.stdout)
            self.assertIn("expected source manifest hash is stale", completed.stdout)
            self.assertEqual(snapshot(case_dir), before)

    def test_v2_is_rendered_as_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_case(Path(temporary), schema_version=2)
            before = snapshot(case_dir)

            completed = run(
                [sys.executable, str(RENDERER), "--case-dir", str(case_dir)]
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("> Status: `not_applicable`", completed.stdout)
            self.assertNotIn("## Step Review", completed.stdout)
            self.assertEqual(snapshot(case_dir), before)


if __name__ == "__main__":
    unittest.main()
