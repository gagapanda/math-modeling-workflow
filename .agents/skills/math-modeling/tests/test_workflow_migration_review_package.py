from __future__ import annotations

import ast
import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_DIR / "scripts"
SCHEMAS = SKILL_DIR / "schemas"
PACKAGER = SCRIPTS / "prepare_workflow_migration_review_package.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _json_schema import load_and_validate
from _workflow_common import ensure_inside, resolve_path_inside
import prepare_workflow_migration_review_package as review_package
from prepare_workflow_migration_review_package import (
    prune_limitations,
    validate_limitation_aggregation,
)


def run_packager(
    case_dir: Path, *arguments: str
) -> tuple[subprocess.CompletedProcess[str], dict]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(PACKAGER),
            "--case-dir",
            str(case_dir),
            *arguments,
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
    )
    return completed, json.loads(completed.stdout)


def run_packager_cli(
    case_dir: Path, *arguments: str
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            str(PACKAGER),
            "--case-dir",
            str(case_dir),
            *arguments,
        ],
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
    case_dir = root / "review-package-case"
    (case_dir / "src").mkdir(parents=True)
    (case_dir / "src" / "produce.py").write_text(
        "from pathlib import Path\n"
        "def write_result(path, value):\n"
        "    path.write_text(value, encoding='utf-8')\n"
        "root = Path(__file__).resolve().parents[1]\n"
        "result_dir = root / 'results'\n"
        "source = root / 'data' / 'source.json'\n"
        "value = source.read_text(encoding='utf-8')\n"
        "write_result(result_dir / 'shared.json', value)\n",
        encoding="utf-8",
    )
    (case_dir / "src" / "helpers.py").write_text(
        "def read_result(path):\n"
        "    return path.read_text(encoding='utf-8')\n",
        encoding="utf-8",
    )
    (case_dir / "src" / "consume.py").write_text(
        "from pathlib import Path\n"
        "from helpers import read_result\n"
        "root = Path(__file__).resolve().parents[1]\n"
        "source = root / 'results' / 'shared.json'\n"
        "target = root / 'paper' / 'summary.txt'\n"
        "target.write_text(read_result(source), encoding='utf-8')\n",
        encoding="utf-8",
    )
    (case_dir / "src" / "opaque.py").write_text(
        "print('not executed')\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": schema_version,
        "steps": [
            {"name": "produce", "script": "src/produce.py"},
            {"name": "consume", "script": "src/consume.py"},
            {"name": "opaque", "script": "src/opaque.py"},
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


def make_boundary_case(root: Path) -> tuple[Path, dict[str, str]]:
    case_dir = root / "review-package-boundaries"
    source_dir = case_dir / "src"
    source_dir.mkdir(parents=True)
    scripts = {
        "cycle": (
            "from pathlib import Path\n"
            "root = Path(__file__).resolve().parents[1]\n"
            "source = root / 'data' / 'cycle.json'\n"
            "def first(path):\n"
            "    return second(path)\n"
            "def second(path):\n"
            "    return first(path)\n"
            "first(source)\n"
        ),
        "too-deep": (
            "from pathlib import Path\n"
            "root = Path(__file__).resolve().parents[1]\n"
            "source = root / 'data' / 'too-deep.json'\n"
            "def h1(path): return h2(path)\n"
            "def h2(path): return h3(path)\n"
            "def h3(path): return h4(path)\n"
            "def h4(path): return h5(path)\n"
            "def h5(path): return path.read_text(encoding='utf-8')\n"
            "h1(source)\n"
        ),
        "dynamic-import": (
            "import importlib\n"
            "from pathlib import Path\n"
            "helpers = importlib.import_module('helpers')\n"
            "root = Path(__file__).resolve().parents[1]\n"
            "source = root / 'data' / 'dynamic.json'\n"
            "helpers.read_result(source)\n"
        ),
        "star-import": (
            "from pathlib import Path\n"
            "from helpers import *\n"
            "root = Path(__file__).resolve().parents[1]\n"
            "source = root / 'data' / 'star.json'\n"
            "read_result(source)\n"
        ),
        "transformed-parameter": (
            "from pathlib import Path\n"
            "root = Path(__file__).resolve().parents[1]\n"
            "directory = root / 'data'\n"
            "def read_nested(path):\n"
            "    return (path / 'transformed.json').read_text(encoding='utf-8')\n"
            "read_nested(directory)\n"
        ),
        "rebound-import": (
            "from pathlib import Path\n"
            "from helpers import read_result\n"
            "read_result = lambda path: path\n"
            "root = Path(__file__).resolve().parents[1]\n"
            "source = root / 'data' / 'rebound.json'\n"
            "read_result(source)\n"
        ),
        "rebound-local": (
            "from pathlib import Path\n"
            "def read_result(path):\n"
            "    return path.read_text(encoding='utf-8')\n"
            "read_result = lambda path: path\n"
            "root = Path(__file__).resolve().parents[1]\n"
            "source = root / 'data' / 'rebound-local.json'\n"
            "read_result(source)\n"
        ),
        "duplicate-suffix": (
            "import importlib\n"
            "from pathlib import Path\n"
            "helpers = importlib.import_module('helpers')\n"
            "root = Path(__file__).resolve().parents[1]\n"
            "source = root / 'data' / 'duplicate.json'\n"
            "def wrapper(path):\n"
            "    return helpers.read_result(path)\n"
            "wrapper(source)\n"
        ),
    }
    for name, source in scripts.items():
        (source_dir / f"{name}.py").write_text(source, encoding="utf-8")
    (source_dir / "helpers.py").write_text(
        "def read_result(path):\n"
        "    return path.read_text(encoding='utf-8')\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "steps": [
            {"name": name, "script": f"src/{name}.py"}
            for name in scripts
        ],
        "artifacts": {
            "docx": "paper/paper.docx",
            "pdf": "paper/paper.pdf",
            "render_dir": "paper/rendered-pages",
            "visual_review": "paper/visual-review.json",
        },
    }
    (case_dir / "workflow.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    forbidden = {
        "cycle": "data/cycle.json",
        "too-deep": "data/too-deep.json",
        "dynamic-import": "data/dynamic.json",
        "star-import": "data/star.json",
        "transformed-parameter": "data/transformed.json",
        "rebound-import": "data/rebound.json",
        "rebound-local": "data/rebound-local.json",
        "duplicate-suffix": "data/duplicate.json",
    }
    return case_dir, forbidden


class WorkflowMigrationReviewPackageTests(unittest.TestCase):
    def test_source_size_and_ast_limits_are_inclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_case(Path(temporary))
            source = case_dir / "src" / "produce.py"
            source_bytes = source.stat().st_size
            node_count = sum(
                1
                for _ in ast.walk(
                    ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
                )
            )

            with mock.patch.object(
                review_package, "MAX_PYTHON_SOURCE_BYTES", source_bytes
            ), mock.patch.object(
                review_package, "MAX_AST_NODES_PER_MODULE", node_count
            ):
                self.assertIsInstance(review_package.bounded_python_tree(source), ast.Module)

            for constant, value, message in (
                ("MAX_PYTHON_SOURCE_BYTES", source_bytes - 1, "byte review-package limit"),
                ("MAX_AST_NODES_PER_MODULE", node_count - 1, "node review-package limit"),
            ):
                with self.subTest(constant=constant), mock.patch.object(
                    review_package, constant, value
                ), self.assertRaisesRegex(ValueError, message):
                    review_package.bounded_python_tree(source)

    def test_entry_source_size_and_ast_limits_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_case(Path(temporary))
            before = snapshot(case_dir)
            limits = {
                "source bytes": ("MAX_PYTHON_SOURCE_BYTES", 10, "byte review-package limit"),
                "AST nodes": ("MAX_AST_NODES_PER_MODULE", 5, "node review-package limit"),
            }
            for name, (constant, value, message) in limits.items():
                with self.subTest(limit=name), mock.patch.object(
                    review_package, constant, value
                ):
                    report = review_package.prepare(
                        case_dir, case_dir / "workflow.json", None, None
                    )
                    self.assertEqual(report["status"], "failed")
                    self.assertTrue(report["source_unchanged"])
                    self.assertTrue(any(message in item for item in report["errors"]))
                    self.assertFalse(report["files_written"])
            self.assertEqual(snapshot(case_dir), before)

    def test_case_local_module_limit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_case(Path(temporary))
            before = snapshot(case_dir)
            with mock.patch.object(
                review_package, "MAX_CASE_LOCAL_MODULES_PER_STEP", 2
            ):
                boundary_report = review_package.prepare(
                    case_dir, case_dir / "workflow.json", None, None
                )
            self.assertEqual(boundary_report["status"], "ready_for_human_review")

            with mock.patch.object(
                review_package, "MAX_CASE_LOCAL_MODULES_PER_STEP", 1
            ):
                report = review_package.prepare(
                    case_dir, case_dir / "workflow.json", None, None
                )

            self.assertEqual(report["status"], "failed")
            self.assertTrue(report["source_unchanged"])
            self.assertTrue(
                any("module count exceeds 1" in item for item in report["errors"])
            )
            self.assertEqual(snapshot(case_dir), before)

    def test_trace_event_limit_is_inclusive_and_step_local(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_case(Path(temporary))
            script = case_dir / "src" / "produce.py"
            original = review_package.consume_trace_budget
            with mock.patch.object(
                review_package, "consume_trace_budget", wraps=original
            ) as observed:
                review_package.enhanced_path_evidence(case_dir, script, [])
            events = observed.call_count
            self.assertGreater(events, 1)

            with mock.patch.object(
                review_package, "MAX_TRACE_CALL_EVENTS_PER_STEP", events
            ):
                _, limitations, _, _ = review_package.enhanced_path_evidence(
                    case_dir, script, []
                )
            self.assertNotIn(
                "trace_budget_exhausted", {item["code"] for item in limitations}
            )

            with mock.patch.object(
                review_package, "MAX_TRACE_CALL_EVENTS_PER_STEP", events - 1
            ):
                _, limitations, _, _ = review_package.enhanced_path_evidence(
                    case_dir, script, []
                )
            exhausted = [
                item for item in limitations if item["code"] == "trace_budget_exhausted"
            ]
            self.assertEqual(len(exhausted), 1)

    def test_common_path_resolution_rejects_escapes_without_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case_dir = root / "case"
            inside = case_dir / "src" / "entry.py"
            outside = root / "outside.py"
            inside.parent.mkdir(parents=True)
            inside.write_text("pass\n", encoding="utf-8")
            outside.write_text("pass\n", encoding="utf-8")

            self.assertEqual(ensure_inside(case_dir, inside, "inside"), inside.resolve())
            self.assertEqual(
                resolve_path_inside(case_dir, Path("src/entry.py"), "inside"),
                inside.resolve(),
            )
            for value in (Path("../outside.py"), outside.resolve()):
                with self.subTest(value=value), self.assertRaisesRegex(
                    ValueError, "escapes the case directory"
                ):
                    resolve_path_inside(case_dir, value, "escaped")

    def test_cli_status_matrix_is_stable_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ready = make_case(root / "ready")
            not_applicable = make_case(root / "v2", schema_version=2)
            stale = make_case(root / "stale")
            corrupt = make_case(root / "corrupt")
            (corrupt / "src" / "produce.py").write_text(
                "def broken(:\n", encoding="utf-8"
            )

            cases = (
                ("ready", ready, ("--json",), 0, "ready_for_human_review"),
                ("not applicable", not_applicable, ("--json",), 0, "not_applicable"),
                (
                    "stale hash",
                    stale,
                    ("--expected-source-sha256", "0" * 64, "--json"),
                    2,
                    "failed",
                ),
                ("corrupt source", corrupt, ("--json",), 2, "failed"),
            )
            for name, case_dir, arguments, returncode, status in cases:
                with self.subTest(state=name):
                    before = snapshot(case_dir)
                    completed = run_packager_cli(case_dir, *arguments)
                    self.assertEqual(completed.returncode, returncode)
                    self.assertEqual(completed.stderr, "")
                    self.assertEqual(json.loads(completed.stdout)["status"], status)
                    self.assertEqual(snapshot(case_dir), before)

            before = snapshot(ready)
            invalid = run_packager_cli(ready, "--not-an-option")
            self.assertEqual(invalid.returncode, 2)
            self.assertEqual(invalid.stdout, "")
            self.assertIn("unrecognized arguments: --not-an-option", invalid.stderr)
            self.assertEqual(snapshot(ready), before)

            stdout = io.StringIO()
            stderr = io.StringIO()
            argv = [
                str(PACKAGER),
                "--case-dir",
                str(ready),
                "--json",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                review_package, "MAX_PYTHON_SOURCE_BYTES", 1
            ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                returncode = review_package.main()
            self.assertEqual(returncode, 2)
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(json.loads(stdout.getvalue())["status"], "failed")
            self.assertEqual(snapshot(ready), before)

    def test_trace_event_limit_stops_with_nonblocking_limitation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_case(Path(temporary))
            before = snapshot(case_dir)
            with mock.patch.object(
                review_package, "MAX_TRACE_CALL_EVENTS_PER_STEP", 1
            ):
                report = review_package.prepare(
                    case_dir, case_dir / "workflow.json", None, None
                )

            self.assertEqual(report["status"], "ready_for_human_review")
            limitations = [
                item
                for step in report["steps"]
                for item in step["trace_limitations"]
                if item["code"] == "trace_budget_exhausted"
            ]
            self.assertEqual(len(limitations), 2)
            self.assertEqual(
                {
                    step["name"]
                    for step in report["steps"]
                    if any(
                        item["code"] == "trace_budget_exhausted"
                        for item in step["trace_limitations"]
                    )
                },
                {"produce", "consume"},
            )
            self.assertTrue(
                all(item["status"] == "review_required" for item in limitations)
            )
            self.assertEqual(report["summary"]["cache_enable_recommended"], 0)
            self.assertFalse(report["review_record_created"])
            self.assertFalse(report["candidate_exported"])
            self.assertFalse(report["cache_enabled"])
            validate_limitation_aggregation(report)
            self.assertEqual(snapshot(case_dir), before)

    def test_corrupt_missing_and_escaped_sources_return_json_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mutations = {
                "invalid UTF-8": lambda case: (case / "src" / "produce.py").write_bytes(
                    b"\xff\xfe\x00"
                ),
                "missing": lambda case: (case / "src" / "produce.py").unlink(),
                "parent escape": lambda case: self._set_first_script(
                    case, "../outside.py"
                ),
                "absolute escape": lambda case: self._set_first_script(
                    case, str((root / "outside.py").resolve())
                ),
            }
            for index, (name, mutate) in enumerate(mutations.items()):
                with self.subTest(failure=name):
                    case_dir = make_case(root / str(index))
                    mutate(case_dir)
                    before = snapshot(case_dir)
                    completed, report = run_packager(case_dir)
                    self.assertEqual(completed.returncode, 2)
                    self.assertEqual(completed.stderr, "")
                    self.assertNotIn("Traceback", completed.stdout)
                    self.assertEqual(report["status"], "failed")
                    self.assertTrue(report["source_unchanged"])
                    self.assertFalse(report["files_written"])
                    self.assertEqual(snapshot(case_dir), before)

    @staticmethod
    def _set_first_script(case_dir: Path, value: str) -> None:
        manifest_path = case_dir / "workflow.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["steps"][0]["script"] = value
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_symlinked_source_escape_fails_closed_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside.py"
            outside.write_text("print('outside')\n", encoding="utf-8")
            case_dir = make_case(root / "case-root")
            link = case_dir / "src" / "escaped.py"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"file symlinks are unavailable: {exc}")
            self._set_first_script(case_dir, "src/escaped.py")
            before = snapshot(case_dir)

            completed, report = run_packager(case_dir)

            self.assertEqual(completed.returncode, 2)
            self.assertEqual(report["status"], "failed")
            self.assertTrue(any("escapes the case directory" in item for item in report["errors"]))
            self.assertEqual(snapshot(case_dir), before)

    def test_json_output_is_repeatable_for_deep_unicode_and_space_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "\u6570\u5b66 \u5efa\u6a21" / "deep level"
            case_dir = make_case(root)
            before = snapshot(case_dir)

            first, first_report = run_packager(case_dir)
            second, second_report = run_packager(case_dir)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(first.stdout.encode("utf-8"), second.stdout.encode("utf-8"))
            self.assertEqual(first_report, second_report)
            self.assertIn("\u6570\u5b66 \u5efa\u6a21", first_report["case_dir"])
            self.assertNotIn("\\", first_report["case_dir"])
            self.assertNotIn(
                "\\", first_report["bindings"]["source_manifest"]["path"]
            )
            self.assertEqual(snapshot(case_dir), before)

    def test_failed_generation_is_repeatable_and_leaves_no_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_case(Path(temporary))
            (case_dir / "src" / "produce.py").write_text(
                "def broken(:\n", encoding="utf-8"
            )
            before = snapshot(case_dir)

            first, first_report = run_packager(case_dir)
            second, second_report = run_packager(case_dir)

            self.assertEqual(first.returncode, 2)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(first.stdout.encode("utf-8"), second.stdout.encode("utf-8"))
            self.assertEqual(first_report, second_report)
            self.assertEqual(first_report["status"], "failed")
            self.assertFalse(first_report["files_written"])
            self.assertFalse(first_report["review_record_created"])
            self.assertFalse(first_report["candidate_exported"])
            self.assertEqual(snapshot(case_dir), before)

    def test_ready_package_runs_cross_field_semantic_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_case(Path(temporary))
            validator = review_package.validate_limitation_aggregation
            with mock.patch.object(
                review_package,
                "validate_limitation_aggregation",
                wraps=validator,
            ) as observed:
                report = review_package.prepare(
                    case_dir, case_dir / "workflow.json", None, None
                )

            self.assertEqual(report["status"], "ready_for_human_review")
            observed.assert_called_once_with(report)

    def test_limitation_aggregation_rejects_schema_valid_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, _ = make_boundary_case(Path(temporary))
            completed, report = run_packager(case_dir)
            self.assertEqual(completed.returncode, 0, completed.stderr)

            def changed(mutator) -> dict:
                candidate = copy.deepcopy(report)
                mutator(candidate)
                load_and_validate(
                    candidate,
                    SCHEMAS / "workflow-migration-review-package.schema.json",
                    "schema-valid tampered review package",
                )
                return candidate

            mutations = {
                "occurrences": lambda value: value["steps"][0][
                    "trace_limitation_groups"
                ][0].__setitem__("occurrences", 2),
                "unique_call_chains": lambda value: value["steps"][0][
                    "trace_limitation_groups"
                ][0].__setitem__("unique_call_chains", 2),
                "unmatched_stop": lambda value: value["steps"][0][
                    "trace_limitation_groups"
                ][0].__setitem__("line", 999),
                "duplicate_group": lambda value: (
                    value["steps"][0]["trace_limitation_groups"].append(
                        copy.deepcopy(
                            value["steps"][0]["trace_limitation_groups"][0]
                        )
                    ),
                    value["summary"].__setitem__(
                        "trace_limitation_groups",
                        value["summary"]["trace_limitation_groups"] + 1,
                    ),
                ),
                "cross_step_group": lambda value: value["steps"][1][
                    "trace_limitation_groups"
                ].append(value["steps"][0]["trace_limitation_groups"].pop()),
            }
            for name, mutator in mutations.items():
                with self.subTest(tampering=name):
                    with self.assertRaises(ValueError):
                        validate_limitation_aggregation(changed(mutator))

            for field in (
                "trace_limitation_occurrences",
                "unique_trace_limitations",
                "trace_limitations",
                "trace_limitation_groups",
            ):
                with self.subTest(summary=field):
                    candidate = changed(
                        lambda value, field=field: value["summary"].__setitem__(
                            field, value["summary"][field] + 1
                        )
                    )
                    with self.assertRaises(ValueError):
                        validate_limitation_aggregation(candidate)

    def test_limitation_deduplication_keeps_different_reason_codes(self) -> None:
        entry = {
            "module": "src/example.py",
            "function": "<module>",
            "line": 10,
            "callee": "wrapper",
        }
        stop = {
            "module": "src/example.py",
            "function": "wrapper",
            "line": 5,
            "callee": "read_text",
        }

        def limitation(code: str, chain: list[dict]) -> dict:
            return {
                **chain[-1],
                "code": code,
                "status": "review_required",
                "message": code,
                "call_chain": chain,
            }

        values = [
            limitation("path_parameter_transformed", [stop]),
            limitation("path_parameter_transformed", [entry, stop]),
            limitation("path_parameter_transformed", [entry, stop]),
            limitation("dynamic_import_unresolved", [stop]),
        ]

        kept = prune_limitations(values)

        self.assertEqual(len(kept), 2)
        self.assertEqual(
            {item["code"] for item in kept},
            {"path_parameter_transformed", "dynamic_import_unresolved"},
        )
        transformed = next(
            item for item in kept if item["code"] == "path_parameter_transformed"
        )
        self.assertEqual(transformed["call_chain"], [entry, stop])

    def test_helper_tracing_stops_at_conservative_static_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir, forbidden = make_boundary_case(Path(temporary))
            before = snapshot(case_dir)

            completed, report = run_packager(case_dir)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["status"], "ready_for_human_review")
            by_name = {item["name"]: item for item in report["steps"]}
            for name, path in forbidden.items():
                with self.subTest(boundary=name):
                    self.assertNotIn(path, by_name[name]["candidate_inputs"])
                    self.assertFalse(
                        any(
                            evidence["path"] == path
                            and any(
                                provenance["kind"] in {
                                    "local_helper",
                                    "imported_helper",
                                }
                                for provenance in evidence["provenance"]
                            )
                            for evidence in by_name[name]["path_evidence"]
                        )
                    )
            self.assertEqual(report["bindings"]["support_modules"], [])
            self.assertEqual(
                report["summary"]["imported_helper_provenance_chains"], 0
            )
            expected_codes = {
                "cycle": {"helper_cycle_detected"},
                "too-deep": {"helper_depth_limit_reached"},
                "dynamic-import": {"dynamic_import_unresolved"},
                "star-import": {"star_import_unresolved"},
                "transformed-parameter": {"path_parameter_transformed"},
                "rebound-import": {"helper_name_rebound"},
                "rebound-local": {"helper_name_rebound"},
                "duplicate-suffix": {"dynamic_import_unresolved"},
            }
            limitations = [
                item
                for step in report["steps"]
                for item in step["trace_limitations"]
            ]
            for name, codes in expected_codes.items():
                with self.subTest(limitation=name):
                    self.assertEqual(
                        {item["code"] for item in by_name[name]["trace_limitations"]},
                        codes,
                    )
            self.assertEqual({item["code"] for item in limitations}, set().union(*expected_codes.values()))
            self.assertEqual(report["summary"]["trace_limitations"], len(limitations))
            self.assertEqual(
                report["summary"]["unique_trace_limitations"], len(limitations)
            )
            self.assertGreaterEqual(
                report["summary"]["trace_limitation_occurrences"],
                len(limitations),
            )
            self.assertEqual(
                report["summary"]["trace_limitation_occurrences"], 11
            )
            self.assertEqual(len(limitations), 10)
            groups = [
                group
                for step in report["steps"]
                for group in step["trace_limitation_groups"]
            ]
            self.assertEqual(report["summary"]["trace_limitation_groups"], 9)
            self.assertEqual(len(groups), 9)
            self.assertEqual(sum(group["occurrences"] for group in groups), 11)
            self.assertEqual(
                sum(group["unique_call_chains"] for group in groups), 10
            )
            duplicate_limitations = by_name["duplicate-suffix"]["trace_limitations"]
            self.assertEqual(len(duplicate_limitations), 1)
            self.assertEqual(len(duplicate_limitations[0]["call_chain"]), 2)
            duplicate_groups = by_name["duplicate-suffix"][
                "trace_limitation_groups"
            ]
            self.assertEqual(len(duplicate_groups), 1)
            self.assertEqual(duplicate_groups[0]["occurrences"], 2)
            self.assertEqual(duplicate_groups[0]["unique_call_chains"], 1)
            self.assertEqual(
                len(by_name["cycle"]["trace_limitations"]), 3
            )
            self.assertEqual(
                sum(
                    group["occurrences"]
                    for group in by_name["cycle"]["trace_limitation_groups"]
                ),
                3,
            )
            self.assertEqual(
                sum(
                    group["unique_call_chains"]
                    for group in by_name["cycle"]["trace_limitation_groups"]
                ),
                3,
            )
            self.assertTrue(
                all(
                    item["status"] == "review_required"
                    and item["module"].startswith("src/")
                    and item["function"]
                    and item["line"] >= 1
                    and item["callee"]
                    and item["message"]
                    and 1 <= len(item["call_chain"]) <= 5
                    and item["call_chain"][-1]
                    == {
                        key: item[key]
                        for key in ("module", "function", "line", "callee")
                    }
                    for item in limitations
                )
            )
            self.assertTrue(report["source_unchanged"])
            self.assertEqual(snapshot(case_dir), before)
            load_and_validate(
                report,
                SCHEMAS / "workflow-migration-review-package.schema.json",
                "bounded review package",
            )
            legacy_limitation_report = copy.deepcopy(report)
            legacy_limitation_report["summary"].pop("trace_limitation_occurrences")
            legacy_limitation_report["summary"].pop("unique_trace_limitations")
            legacy_limitation_report["summary"].pop("trace_limitation_groups")
            for step in legacy_limitation_report["steps"]:
                step.pop("trace_limitation_groups")
                for item in step["trace_limitations"]:
                    item.pop("call_chain")
            load_and_validate(
                legacy_limitation_report,
                SCHEMAS / "workflow-migration-review-package.schema.json",
                "located limitation version 1 review package",
            )
            chained_limitation_report = copy.deepcopy(report)
            chained_limitation_report["summary"].pop("trace_limitation_groups")
            for step in chained_limitation_report["steps"]:
                step.pop("trace_limitation_groups")
            load_and_validate(
                chained_limitation_report,
                SCHEMAS / "workflow-migration-review-package.schema.json",
                "call-chain limitation version 1 review package",
            )
            legacy_report = copy.deepcopy(report)
            legacy_report["summary"].pop("trace_limitations")
            legacy_report["summary"].pop("trace_limitation_occurrences")
            legacy_report["summary"].pop("unique_trace_limitations")
            legacy_report["summary"].pop("trace_limitation_groups")
            for step in legacy_report["steps"]:
                step.pop("trace_limitations")
                step.pop("trace_limitation_groups")
            load_and_validate(
                legacy_report,
                SCHEMAS / "workflow-migration-review-package.schema.json",
                "pre-limitation version 1 review package",
            )

    def test_builds_hash_bound_pending_package_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_case(Path(temporary))
            before = snapshot(case_dir)

            completed, report = run_packager(case_dir)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["status"], "ready_for_human_review")
            self.assertTrue(report["applicable"])
            self.assertTrue(report["source_unchanged"])
            self.assertFalse(report["files_written"])
            self.assertFalse(report["case_steps_executed"])
            self.assertFalse(report["external_tools_started"])
            self.assertFalse(report["review_record_created"])
            self.assertFalse(report["candidate_exported"])
            self.assertFalse(report["cache_enabled"])
            self.assertRegex(
                report["bindings"]["source_manifest"]["sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertRegex(
                report["bindings"]["base_candidate_sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertEqual(len(report["bindings"]["python_scripts"]), 3)
            self.assertEqual(len(report["bindings"]["support_modules"]), 1)
            self.assertEqual(
                report["bindings"]["support_modules"][0]["path"],
                "src/helpers.py",
            )
            self.assertRegex(
                report["bindings"]["support_modules"][0]["sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertEqual(
                report["relationships"],
                [
                    {
                        "producer_step": "produce",
                        "consumer_step": "consume",
                        "path": "results/shared.json",
                        "evidence": "exact candidate output/input path match",
                        "confidence": "review_candidate",
                    }
                ],
            )
            by_name = {item["name"]: item for item in report["steps"]}
            self.assertIn("data/source.json", by_name["produce"]["candidate_inputs"])
            self.assertIn("results/shared.json", by_name["produce"]["candidate_outputs"])
            self.assertIn("results/shared.json", by_name["consume"]["candidate_inputs"])
            self.assertIn("paper/summary.txt", by_name["consume"]["candidate_outputs"])
            produce_output = next(
                item
                for item in by_name["produce"]["path_evidence"]
                if item["path"] == "results/shared.json" and item["access"] == "output"
            )
            self.assertIn(
                "local_helper",
                {item["kind"] for item in produce_output["provenance"]},
            )
            local_chain = next(
                item["call_chain"]
                for item in produce_output["provenance"]
                if item["kind"] == "local_helper"
            )
            self.assertEqual([frame["callee"] for frame in local_chain], ["write_result", "write_text"])
            consume_input = next(
                item
                for item in by_name["consume"]["path_evidence"]
                if item["path"] == "results/shared.json" and item["access"] == "input"
            )
            imported = next(
                item
                for item in consume_input["provenance"]
                if item["kind"] == "imported_helper"
            )
            self.assertEqual(
                [frame["module"] for frame in imported["call_chain"]],
                ["src/consume.py", "src/helpers.py"],
            )
            self.assertEqual(
                [frame["callee"] for frame in imported["call_chain"]],
                ["read_result", "read_text"],
            )
            self.assertEqual(len(by_name["opaque"]["checklist"]), 5)
            self.assertTrue(
                all(
                    check["status"] == "pending_human_review"
                    for item in report["steps"]
                    for check in item["checklist"]
                )
            )
            self.assertEqual(report["summary"]["pending_checklist_items"], 15)
            self.assertEqual(report["summary"]["cache_enable_recommended"], 0)
            self.assertGreaterEqual(report["summary"]["local_helper_provenance_chains"], 1)
            self.assertGreaterEqual(report["summary"]["imported_helper_provenance_chains"], 1)
            opaque_codes = {
                item["code"] for item in report["gaps"] if item["step"] == "opaque"
            }
            self.assertEqual(
                opaque_codes,
                {
                    "no_input_candidates",
                    "no_output_candidates",
                    "no_relationship_candidates",
                },
            )
            self.assertEqual(snapshot(case_dir), before)
            load_and_validate(
                report,
                SCHEMAS / "workflow-migration-review-package.schema.json",
                "review package",
            )

    def test_rejects_stale_source_or_candidate_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_case(Path(temporary))
            completed, current = run_packager(case_dir)
            self.assertEqual(completed.returncode, 0, completed.stderr)

            for option in (
                "--expected-source-sha256",
                "--expected-candidate-sha256",
            ):
                with self.subTest(option=option):
                    failed, report = run_packager(case_dir, option, "0" * 64)
                    self.assertEqual(failed.returncode, 2)
                    self.assertEqual(report["status"], "failed")
                    self.assertTrue(report["source_unchanged"])
                    self.assertTrue(
                        any("stale" in message for message in report["errors"])
                    )
                    self.assertFalse(report["review_record_created"])
                    self.assertFalse(report["candidate_exported"])
            bound, report = run_packager(
                case_dir,
                "--expected-source-sha256",
                current["bindings"]["source_manifest"]["sha256"],
                "--expected-candidate-sha256",
                current["bindings"]["base_candidate_sha256"],
            )
            self.assertEqual(bound.returncode, 0, bound.stderr)
            self.assertEqual(report["status"], "ready_for_human_review")

    def test_reports_v2_as_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = make_case(Path(temporary), schema_version=2)
            before = snapshot(case_dir)

            completed, report = run_packager(case_dir)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(report["status"], "not_applicable")
            self.assertFalse(report["applicable"])
            self.assertEqual(report["steps"], [])
            self.assertEqual(report["relationships"], [])
            self.assertIsNone(report["bindings"]["base_candidate_sha256"])
            self.assertTrue(report["source_unchanged"])
            self.assertEqual(snapshot(case_dir), before)
            load_and_validate(
                report,
                SCHEMAS / "workflow-migration-review-package.schema.json",
                "v2 review package",
            )


if __name__ == "__main__":
    unittest.main()
