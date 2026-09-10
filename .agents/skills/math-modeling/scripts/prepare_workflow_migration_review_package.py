#!/usr/bin/env python
"""Prepare a passive, hash-bound human-review package for one v1 workflow."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from pathlib import Path, PurePosixPath

sys.dont_write_bytecode = True

from _diagnostics import attach_diagnostics, diagnostic
from _json_schema import load_and_validate
from _workflow_common import resolve_path_inside, sha256_file
from analyze_workflow_migration import (
    READ_METHODS,
    PATH_SUFFIXES,
    WRITE_METHODS,
    analyze,
    call_name,
    open_access,
    relative_manifest_path,
)
from rehearse_workflow_migration import candidate_digest, tree_metadata
from review_workflow_migration import review_template


REPORT_SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "workflow-migration-review-package.schema.json"
)
INPUT_CALLS = {
    "Document",
    "add_picture",
    "check_rows",
    "load",
    "load_json",
    "load_workbook",
    "read",
    "replace_picture_before_caption",
    "sheet_metadata",
    "style_map",
    "workbook_parts",
}
OUTPUT_CALLS = {"save", "savefig", "savetxt", "write"}
CHECKLIST = [
    (
        "declared_inputs",
        "Inspect every source, helper, dynamic path, environment dependency, and upstream artifact before declaring inputs.",
    ),
    (
        "declared_outputs",
        "Confirm every completion artifact and output owner; candidates below are incomplete evidence.",
    ),
    (
        "timeout",
        "Choose a timeout from observed runtime evidence and failure behavior, not the conservative default alone.",
    ),
    (
        "determinism",
        "Review randomness, clocks, environment state, external services, mutable files, and ordering effects.",
    ),
    (
        "cache_enablement",
        "Keep cache disabled unless dependency closure, deterministic outputs, and output ownership are all confirmed.",
    ),
]
LIMITATION_MESSAGES = {
    "helper_cycle_detected": "Helper tracing stopped because this function already appears in the active call chain.",
    "helper_depth_limit_reached": "Helper tracing stopped at the maximum supported depth of four helper calls.",
    "dynamic_import_unresolved": "A dynamically imported helper cannot be resolved without executing Python.",
    "star_import_unresolved": "A star-imported helper cannot be resolved to one case-local function statically.",
    "helper_name_rebound": "A helper name was rebound or shadowed, so the original function is not traced.",
    "path_parameter_transformed": "A helper path parameter was transformed instead of flowing unchanged to the next helper or file sink.",
    "trace_budget_exhausted": "Static helper tracing stopped because this step reached the bounded call-event budget.",
}
MAX_PYTHON_SOURCE_BYTES = 1024 * 1024
MAX_AST_NODES_PER_MODULE = 50_000
MAX_CASE_LOCAL_MODULES_PER_STEP = 64
MAX_TRACE_CALL_EVENTS_PER_STEP = 10_000


def report_path(path: Path) -> str:
    """Return a stable display path without changing filesystem resolution."""
    return path.as_posix()


def bounded_python_tree(path: Path) -> ast.Module:
    size = path.stat().st_size
    if size > MAX_PYTHON_SOURCE_BYTES:
        raise ValueError(
            f"Python source exceeds {MAX_PYTHON_SOURCE_BYTES} byte review-package limit: {path}"
        )
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    node_count = sum(1 for _ in ast.walk(tree))
    if node_count > MAX_AST_NODES_PER_MODULE:
        raise ValueError(
            f"Python source AST exceeds {MAX_AST_NODES_PER_MODULE} node review-package limit: {path}"
        )
    return tree


def preflight_entry_sources(case_dir: Path, manifest: dict) -> None:
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("steps"), list):
        return
    for index, step in enumerate(manifest["steps"]):
        if not isinstance(step, dict) or step.get("type", "python") != "python":
            continue
        name = step.get("name", index)
        script = step.get("script")
        if not isinstance(script, str):
            continue
        path = resolve_path_inside(case_dir, Path(script), f"step {name} script")
        bounded_python_tree(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--expected-candidate-sha256")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()
    for name in ("expected_source_sha256", "expected_candidate_sha256"):
        value = getattr(args, name)
        if value is not None and (
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
        ):
            parser.error(f"--{name.replace('_', '-')} must be a lowercase SHA-256 digest")
    return args


def base_report(case_dir: Path, manifest_path: Path) -> dict:
    return {
        "schema_version": 1,
        "command": "prepare_workflow_migration_review_package",
        "mode": "passive_read_only",
        "case_dir": report_path(case_dir),
        "status": "failed",
        "applicable": False,
        "files_written": False,
        "case_steps_executed": False,
        "external_tools_started": False,
        "review_record_created": False,
        "candidate_exported": False,
        "cache_enabled": False,
        "source_unchanged": False,
        "bindings": {
            "source_manifest": {
                "path": report_path(manifest_path),
                "sha256": "0" * 64,
            },
            "base_candidate_sha256": None,
            "python_scripts": [],
            "support_modules": [],
        },
        "steps": [],
        "relationships": [],
        "gaps": [],
        "summary": {
            "python_steps": 0,
            "path_candidates": 0,
            "candidate_inputs": 0,
            "candidate_outputs": 0,
            "relationships": 0,
            "evidence_gaps": 0,
            "pending_checklist_items": 0,
            "cache_enable_recommended": 0,
            "provenance_chains": 0,
            "direct_provenance_chains": 0,
            "local_helper_provenance_chains": 0,
            "imported_helper_provenance_chains": 0,
            "trace_limitation_occurrences": 0,
            "unique_trace_limitations": 0,
            "trace_limitations": 0,
            "trace_limitation_groups": 0,
        },
        "errors": [],
        "warnings": [],
    }


def symbolic_path(node: ast.AST, symbols: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        if node.id.casefold() in {"base", "case_dir", "project_dir", "project_root", "root"}:
            return ""
        return symbols.get(node.id)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value.strip().replace("\\", "/")
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts:
            return None
        return path.as_posix()
    if isinstance(node, ast.Call) and node.args and call_name(node.func) in {
        "Path", "PurePath", "PurePosixPath", "PureWindowsPath", "str"
    }:
        return symbolic_path(node.args[0], symbols)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = symbolic_path(node.left, symbols)
        right = symbolic_path(node.right, symbols)
        if left is None or right is None:
            return None
        combined = "/".join(part for part in (left, right) if part)
        path = PurePosixPath(combined)
        if not combined or path.is_absolute() or ".." in path.parts:
            return None
        return path.as_posix()
    return None


def assignment_symbols(
    tree: ast.AST, initial: dict[str, str] | None = None
) -> dict[str, str]:
    symbols = dict(initial or {})
    assignments = [
        node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    for _ in range(len(assignments) + 1):
        changed = False
        for node in assignments:
            value = symbolic_path(node.value, symbols) if node.value is not None else None
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if value is None:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and symbols.get(target.id) != value:
                    symbols[target.id] = value
                    changed = True
        if not changed:
            break
    return symbols


def call_access(node: ast.Call) -> str | None:
    name = call_name(node.func)
    if name == "open":
        return open_access(node)
    if name in READ_METHODS or name in INPUT_CALLS:
        return "input"
    if name in WRITE_METHODS or name in OUTPUT_CALLS:
        return "output"
    return None


def direct_scope_nodes(scope: ast.AST) -> list[ast.AST]:
    nodes: list[ast.AST] = []

    def visit(node: ast.AST) -> None:
        if node is not scope and isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            return
        nodes.append(node)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(scope)
    return nodes


def module_root_symbols(tree: ast.Module) -> dict[str, str]:
    symbols: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(
            isinstance(item, ast.Name) and item.id == "__file__"
            for item in ast.walk(node.value)
        ):
            for target in targets:
                if isinstance(target, ast.Name):
                    symbols[target.id] = ""
    module = ast.Module(
        body=[node for node in tree.body if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))],
        type_ignores=[],
    )
    return assignment_symbols(module, symbols)


def relative_module_path(case_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(case_dir.resolve()).as_posix()


def load_module_info(
    case_dir: Path, path: Path, modules: dict[Path, dict]
) -> dict | None:
    resolved = path.resolve()
    try:
        resolved.relative_to(case_dir.resolve())
    except ValueError:
        return None
    if resolved in modules:
        return modules[resolved]
    if not resolved.is_file() or resolved.suffix.casefold() != ".py":
        return None
    if len(modules) >= MAX_CASE_LOCAL_MODULES_PER_STEP:
        raise ValueError(
            "case-local Python module count exceeds "
            f"{MAX_CASE_LOCAL_MODULES_PER_STEP} per-step review-package limit"
        )
    tree = bounded_python_tree(resolved)
    info = {
        "path": resolved,
        "tree": tree,
        "functions": {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        },
        "from_imports": {},
        "module_imports": {},
        "from_import_lines": {},
        "module_import_lines": {},
        "dynamic_imports": set(),
        "star_imports": [],
        "globals": module_root_symbols(tree),
    }
    modules[resolved] = info
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported_path = resolved.parent / (node.module.replace(".", "/") + ".py")
            if load_module_info(case_dir, imported_path, modules) is None:
                continue
            for alias in node.names:
                if alias.name == "*":
                    info["star_imports"].append(node.lineno)
                else:
                    local_name = alias.asname or alias.name
                    info["from_imports"][local_name] = (
                        imported_path.resolve(),
                        alias.name,
                    )
                    info["from_import_lines"][local_name] = node.lineno
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_path = resolved.parent / (alias.name.replace(".", "/") + ".py")
                if load_module_info(case_dir, imported_path, modules) is not None:
                    local_name = alias.asname or alias.name.split(".")[0]
                    info["module_imports"][local_name] = imported_path.resolve()
                    info["module_import_lines"][local_name] = node.lineno
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            if isinstance(node.value, ast.Call) and call_name(node.value.func) in {
                "import_module",
                "__import__",
            }:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                info["dynamic_imports"].update(
                    target.id for target in targets if isinstance(target, ast.Name)
                )
    return info


def assigned_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    targets: list[ast.AST] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    elif isinstance(node, (ast.For, ast.AsyncFor)):
        targets = [node.target]
    elif isinstance(node, (ast.With, ast.AsyncWith)):
        targets = [item.optional_vars for item in node.items if item.optional_vars]
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.add(node.name)
    for target in targets:
        names.update(
            item.id for item in ast.walk(target) if isinstance(item, ast.Name)
        )
    return names


def import_is_shadowed(
    module: dict, scope: ast.AST, name: str, call_line: int, import_line: int
) -> bool:
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        parameters = {
            item.arg
            for item in (
                *scope.args.posonlyargs,
                *scope.args.args,
                *scope.args.kwonlyargs,
            )
        }
        if scope.args.vararg:
            parameters.add(scope.args.vararg.arg)
        if scope.args.kwarg:
            parameters.add(scope.args.kwarg.arg)
        if name in parameters:
            return True
        local_nodes = direct_scope_nodes(scope)
        global_names = {
            item
            for node in local_nodes
            if isinstance(node, ast.Global)
            for item in node.names
        }
        if name not in global_names and any(
            name in assigned_names(node)
            for node in local_nodes
            if node is not scope
        ):
            return True
    return any(
        import_line < getattr(node, "lineno", 0) <= call_line
        and name in assigned_names(node)
        for node in module["tree"].body
    )


def resolve_helper(
    module: dict, node: ast.Call, modules: dict[Path, dict], scope: ast.AST
) -> tuple[dict, ast.FunctionDef | ast.AsyncFunctionDef] | None:
    if isinstance(node.func, ast.Name):
        if node.func.id in module["functions"]:
            local_function = module["functions"][node.func.id]
            if not import_is_shadowed(
                module,
                scope,
                node.func.id,
                node.lineno,
                local_function.lineno,
            ):
                return module, local_function
        imported = module["from_imports"].get(node.func.id)
        if imported and not import_is_shadowed(
            module,
            scope,
            node.func.id,
            node.lineno,
            module["from_import_lines"][node.func.id],
        ):
            target_module = modules.get(imported[0])
            target = target_module["functions"].get(imported[1]) if target_module else None
            if target is not None:
                return target_module, target
    if (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in module["module_imports"]
        and not import_is_shadowed(
            module,
            scope,
            node.func.value.id,
            node.lineno,
            module["module_import_lines"][node.func.value.id],
        )
    ):
        target_module = modules.get(module["module_imports"][node.func.value.id])
        target = target_module["functions"].get(node.func.attr) if target_module else None
        if target is not None:
            return target_module, target
    return None


def rebound_helper_call(module: dict, node: ast.Call, scope: ast.AST) -> bool:
    if isinstance(node.func, ast.Name):
        name = node.func.id
        if name in module["functions"]:
            return import_is_shadowed(
                module, scope, name, node.lineno, module["functions"][name].lineno
            )
        if name in module["from_imports"]:
            return import_is_shadowed(
                module,
                scope,
                name,
                node.lineno,
                module["from_import_lines"][name],
            )
    return bool(
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in module["module_imports"]
        and import_is_shadowed(
            module,
            scope,
            node.func.value.id,
            node.lineno,
            module["module_import_lines"][node.func.value.id],
        )
    )


def dynamic_helper_call(module: dict, node: ast.Call) -> bool:
    return bool(
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in module["dynamic_imports"]
    )


def call_record(
    case_dir: Path, module: dict, function: str, node: ast.Call
) -> dict:
    return {
        "module": relative_module_path(case_dir, module["path"]),
        "function": function,
        "line": node.lineno,
        "callee": call_name(node.func),
    }


def bound_symbols(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    node: ast.Call,
    caller_symbols: dict[str, str],
) -> dict[str, str]:
    parameters = [*function.args.posonlyargs, *function.args.args]
    bound: dict[str, str] = {}
    for parameter, argument in zip(parameters, node.args):
        value = symbolic_path(argument, caller_symbols)
        if value is not None:
            bound[parameter.arg] = value
    parameter_names = {parameter.arg for parameter in parameters}
    for keyword in node.keywords:
        if keyword.arg in parameter_names:
            value = symbolic_path(keyword.value, caller_symbols)
            if value is not None:
                bound[keyword.arg] = value
    return bound


def helper_symbols(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    globals_: dict[str, str],
    bound: dict[str, str],
) -> tuple[dict[str, str], set[str], set[str]]:
    symbols = {**globals_, **bound}
    flowed = set(bound)
    transformed: set[str] = set()
    assignments = sorted(
        (
            node
            for node in direct_scope_nodes(function)
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
        ),
        key=lambda node: node.lineno,
    )
    for node in assignments:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        target_names = [target.id for target in targets if isinstance(target, ast.Name)]
        referenced = {
            item.id for item in ast.walk(node.value) if isinstance(item, ast.Name)
        }
        exact_flow = isinstance(node.value, ast.Name) and node.value.id in flowed
        derived_flow = bool(referenced & (flowed | transformed)) and not exact_flow
        value = symbolic_path(node.value, symbols)
        for name in target_names:
            if derived_flow:
                symbols.pop(name, None)
                flowed.discard(name)
                transformed.add(name)
            elif value is not None:
                symbols[name] = value
                if exact_flow:
                    flowed.add(name)
                    transformed.discard(name)
                else:
                    flowed.discard(name)
                    transformed.discard(name)
    return symbols, flowed, transformed


def provenance_kind(entry_module: Path, chain: list[dict]) -> str:
    entry = entry_module.resolve()
    if any(Path(item["absolute_module"]).resolve() != entry for item in chain):
        return "imported_helper"
    return "local_helper" if len(chain) > 1 else "direct"


def public_chain(chain: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in item.items() if key != "absolute_module"}
        for item in chain
    ]


def add_limitation(limitations: list[dict], code: str, chain: list[dict]) -> None:
    call_chain = public_chain(chain)
    item = {
        **call_chain[-1],
        "code": code,
        "status": "review_required",
        "message": LIMITATION_MESSAGES[code],
        "call_chain": call_chain,
    }
    limitations.append(item)


def consume_trace_budget(
    budget: dict[str, int | bool], limitations: list[dict], chain: list[dict]
) -> bool:
    remaining = int(budget["remaining"])
    if remaining > 0:
        budget["remaining"] = remaining - 1
        return True
    if not budget["reported"]:
        add_limitation(limitations, "trace_budget_exhausted", chain)
        budget["reported"] = True
    return False


def trace_helper(
    case_dir: Path,
    entry_module: dict,
    module: dict,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    symbols: dict[str, str],
    chain: list[dict],
    modules: dict[Path, dict],
    seen: set[tuple[Path, str]],
    limitations: list[dict],
    trace_budget: dict[str, int | bool],
    depth: int = 0,
) -> list[dict]:
    key = (module["path"], function.name)
    if depth >= 4:
        add_limitation(limitations, "helper_depth_limit_reached", chain)
        return []
    if key in seen:
        add_limitation(limitations, "helper_cycle_detected", chain)
        return []
    local_symbols, flowed, transformed = helper_symbols(
        function, module["globals"], symbols
    )
    traced = []
    for inner in direct_scope_nodes(function):
        if not isinstance(inner, ast.Call):
            continue
        record = call_record(case_dir, module, function.name, inner)
        record["absolute_module"] = str(module["path"])
        next_chain = [*chain, record]
        if not consume_trace_budget(trace_budget, limitations, next_chain):
            break
        if dynamic_helper_call(module, inner):
            add_limitation(limitations, "dynamic_import_unresolved", next_chain)
            continue
        if rebound_helper_call(module, inner, function):
            add_limitation(limitations, "helper_name_rebound", next_chain)
            continue
        target = resolve_helper(module, inner, modules, function)
        if target is not None:
            nested_symbols = bound_symbols(target[1], inner, local_symbols)
            transformed_flow = any(
                transformed_symbol_flow(argument, flowed, transformed)
                for argument in [*inner.args, *(item.value for item in inner.keywords)]
            )
            if transformed_flow:
                add_limitation(limitations, "path_parameter_transformed", next_chain)
                continue
            traced.extend(
                trace_helper(
                    case_dir,
                    entry_module,
                    target[0],
                    target[1],
                    nested_symbols,
                    next_chain,
                    modules,
                    {*seen, key},
                    limitations,
                    trace_budget,
                    depth + 1,
                )
            )
            continue
        access = call_access(inner)
        if access is None:
            continue
        if any(
            transformed_symbol_flow(item, flowed, transformed)
            for item in call_path_nodes(inner)
        ):
            add_limitation(limitations, "path_parameter_transformed", next_chain)
            continue
        for path in call_paths(inner, local_symbols, flowed):
            traced.append(
                {
                    "path": path,
                    "access": access,
                    "line": chain[0]["line"],
                    "evidence": "case-relative path candidate with traced helper provenance",
                    "confidence": "review_candidate",
                    "provenance": {
                        "kind": provenance_kind(entry_module["path"], next_chain),
                        "call_chain": public_chain(next_chain),
                    },
                }
            )
    return traced


def exact_symbol_flow(node: ast.AST, flowed: set[str]) -> bool:
    referenced = {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}
    if not referenced & flowed:
        return True
    if isinstance(node, ast.Name):
        return node.id in flowed
    return (
        isinstance(node, ast.Call)
        and call_name(node.func) == "str"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id in flowed
    )


def transformed_symbol_flow(
    node: ast.AST, flowed: set[str], transformed: set[str]
) -> bool:
    referenced = {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}
    return bool(referenced & transformed) or (
        bool(referenced & flowed) and not exact_symbol_flow(node, flowed)
    )


def call_path_nodes(node: ast.Call) -> list[ast.AST]:
    nodes = list(node.args)
    if isinstance(node.func, ast.Attribute):
        nodes.insert(0, node.func.value)
    return nodes


def call_paths(
    node: ast.Call, symbols: dict[str, str], flowed: set[str] | None = None
) -> list[str]:
    values = []
    if isinstance(node.func, ast.Attribute):
        receiver = (
            symbolic_path(node.func.value, symbols)
            if flowed is None or exact_symbol_flow(node.func.value, flowed)
            else None
        )
        if receiver:
            values.append(receiver)
    for argument in node.args:
        if flowed is not None and not exact_symbol_flow(argument, flowed):
            continue
        candidate = symbolic_path(argument, symbols)
        if candidate:
            values.append(candidate)
        elif (
            isinstance(argument, ast.Call)
            and call_name(argument.func) == "str"
            and argument.args
        ):
            candidate = symbolic_path(argument.args[0], symbols)
            if candidate:
                values.append(candidate)
    return [
        value
        for value in dict.fromkeys(values)
        if PurePosixPath(value).suffix.casefold() in PATH_SUFFIXES
    ]


def add_evidence(evidence: dict[tuple[str, str], dict], item: dict) -> None:
    key = (item["path"], item["access"])
    provenance = item.pop("provenance")
    if key not in evidence:
        evidence[key] = {**item, "provenance": [provenance]}
        return
    existing = evidence[key]
    if existing["confidence"] != "static_literal_hint" and item["confidence"] == "static_literal_hint":
        existing.update({key: value for key, value in item.items() if key != "provenance"})
    if provenance not in existing["provenance"]:
        existing["provenance"].append(provenance)


def chain_key(provenance: dict) -> tuple[tuple[str, str, int, str], ...]:
    return tuple(
        (frame["module"], frame["function"], frame["line"], frame["callee"])
        for frame in provenance["call_chain"]
    )


def prune_provenance(values: list[dict]) -> list[dict]:
    kept = []
    for value in values:
        key = chain_key(value)
        if value["kind"] != "direct" and any(
            other["kind"] == value["kind"]
            and len(chain_key(other)) > len(key)
            and chain_key(other)[-len(key) :] == key
            for other in values
        ):
            continue
        kept.append(value)
    return sorted(kept, key=lambda item: (item["kind"], chain_key(item)))


def prune_limitations(values: list[dict]) -> list[dict]:
    unique = {
        (value["code"], chain_key(value)): value
        for value in values
    }
    kept = []
    for value in unique.values():
        key = chain_key(value)
        if any(
            other["code"] == value["code"]
            and other["call_chain"][-1] == value["call_chain"][-1]
            and len(chain_key(other)) > len(key)
            and chain_key(other)[-len(key) :] == key
            for other in unique.values()
        ):
            continue
        kept.append(value)
    return sorted(
        kept,
        key=lambda item: (item["code"], chain_key(item)),
    )


def limitation_group_key(value: dict) -> tuple[str, str, str, int, str]:
    return (
        value["code"],
        value["module"],
        value["function"],
        value["line"],
        value["callee"],
    )


def build_limitation_groups(occurrences: list[dict], unique: list[dict]) -> list[dict]:
    groups = {}
    for value in occurrences:
        key = limitation_group_key(value)
        if key not in groups:
            groups[key] = {
                "code": value["code"],
                "module": value["module"],
                "function": value["function"],
                "line": value["line"],
                "callee": value["callee"],
                "status": "review_required",
                "message": value["message"],
                "occurrences": 0,
                "unique_call_chains": 0,
            }
        groups[key]["occurrences"] += 1
    for value in unique:
        groups[limitation_group_key(value)]["unique_call_chains"] += 1
    return [groups[key] for key in sorted(groups)]


def validate_limitation_aggregation(report: dict) -> None:
    if report.get("status") != "ready_for_human_review":
        return
    steps = report["steps"]
    summary = report["summary"]
    occurrence_total = 0
    unique_total = 0
    group_total = 0
    for step in steps:
        limitations = step["trace_limitations"]
        groups = step["trace_limitation_groups"]
        limitation_counts = Counter(limitation_group_key(item) for item in limitations)
        group_counts = Counter(limitation_group_key(item) for item in groups)
        if any(count != 1 for count in group_counts.values()):
            raise ValueError(
                f"step {step['name']} has duplicate trace limitation group keys"
            )
        if set(group_counts) != set(limitation_counts):
            raise ValueError(
                f"step {step['name']} trace limitation groups do not match retained limitations"
            )
        for item in limitations:
            if item["call_chain"][-1] != {
                key: item[key]
                for key in ("module", "function", "line", "callee")
            }:
                raise ValueError(
                    f"step {step['name']} trace limitation stop does not match its call-chain tail"
                )
        for group in groups:
            key = limitation_group_key(group)
            if group["unique_call_chains"] != limitation_counts[key]:
                raise ValueError(
                    f"step {step['name']} trace limitation group unique-call-chain count is inconsistent"
                )
            if group["occurrences"] < group["unique_call_chains"]:
                raise ValueError(
                    f"step {step['name']} trace limitation group occurrences are below retained chains"
                )
            matching = [item for item in limitations if limitation_group_key(item) == key]
            if any(
                item["status"] != group["status"]
                or item["message"] != group["message"]
                for item in matching
            ):
                raise ValueError(
                    f"step {step['name']} trace limitation group metadata is inconsistent"
                )
        occurrence_total += sum(item["occurrences"] for item in groups)
        unique_total += len(limitations)
        group_total += len(groups)
    if summary["trace_limitation_occurrences"] != occurrence_total:
        raise ValueError("trace limitation occurrence summary is inconsistent")
    if summary["unique_trace_limitations"] != unique_total:
        raise ValueError("unique trace limitation summary is inconsistent")
    if summary["trace_limitations"] != unique_total:
        raise ValueError("trace limitation compatibility summary is inconsistent")
    if summary["trace_limitation_groups"] != group_total:
        raise ValueError("trace limitation group summary is inconsistent")


def enclosing_function(tree: ast.Module, line: int) -> str:
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.lineno <= line <= getattr(node, "end_lineno", node.lineno)
    ]
    return max(candidates, key=lambda node: node.lineno).name if candidates else "<module>"


def enhanced_path_evidence(
    case_dir: Path, script: Path, existing: list[dict]
) -> tuple[list[dict], list[dict], list[dict], int]:
    modules: dict[Path, dict] = {}
    module = load_module_info(case_dir, script, modules)
    if module is None:
        return [], [], [], 0
    tree = module["tree"]
    evidence: dict[tuple[str, str], dict] = {}
    limitations: list[dict] = []
    trace_budget: dict[str, int | bool] = {
        "remaining": MAX_TRACE_CALL_EVENTS_PER_STEP,
        "reported": False,
    }
    for item in existing:
        direct = call_record(
            case_dir,
            module,
            enclosing_function(tree, item["line"]),
            next(
                (
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call) and node.lineno == item["line"]
                ),
                ast.Call(func=ast.Name(id="unknown"), args=[], keywords=[], lineno=item["line"]),
            ),
        )
        direct["absolute_module"] = str(module["path"])
        add_evidence(
            evidence,
            {
                **item,
                "provenance": {
                    "kind": "direct",
                    "call_chain": public_chain([direct]),
                },
            },
        )

    scopes: list[tuple[str, ast.AST, dict[str, str]]] = [
        ("<module>", tree, module["globals"])
    ]
    scopes.extend(
        (node.name, node, assignment_symbols(node, module["globals"]))
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    for function_name, scope, symbols in scopes:
        for node in direct_scope_nodes(scope):
            if not isinstance(node, ast.Call):
                continue
            record = call_record(case_dir, module, function_name, node)
            record["absolute_module"] = str(module["path"])
            if not consume_trace_budget(trace_budget, limitations, [record]):
                break
            if dynamic_helper_call(module, node):
                add_limitation(limitations, "dynamic_import_unresolved", [record])
                continue
            if rebound_helper_call(module, node, scope):
                add_limitation(limitations, "helper_name_rebound", [record])
                continue
            target = resolve_helper(module, node, modules, scope)
            if target is not None:
                for item in trace_helper(
                    case_dir,
                    module,
                    target[0],
                    target[1],
                    bound_symbols(target[1], node, symbols),
                    [record],
                    modules,
                    set(),
                    limitations,
                    trace_budget,
                ):
                    add_evidence(evidence, item)
                continue
            if (
                module["star_imports"]
                and isinstance(node.func, ast.Name)
                and call_access(node) is None
                and node.func.id not in module["functions"]
                and node.func.id not in module["from_imports"]
                and call_paths(node, symbols)
            ):
                add_limitation(limitations, "star_import_unresolved", [record])
                continue
            access = call_access(node) or "unclassified"
            for path in call_paths(node, symbols):
                add_evidence(
                    evidence,
                    {
                        "path": path,
                        "access": access,
                        "line": node.lineno,
                        "evidence": f"case-relative path candidate used by {call_name(node.func)}()",
                        "confidence": "review_candidate",
                        "provenance": {
                            "kind": "direct",
                            "call_chain": public_chain([record]),
                        },
                    },
                )
    for item in evidence.values():
        item["provenance"] = prune_provenance(item["provenance"])
    unique_limitations = prune_limitations(limitations)
    return (
        sorted(
            evidence.values(),
            key=lambda item: (item["path"], item["access"], item["line"]),
        ),
        unique_limitations,
        build_limitation_groups(limitations, unique_limitations),
        len(limitations),
    )


def checklist() -> list[dict]:
    return [
        {"code": code, "status": "pending_human_review", "prompt": prompt}
        for code, prompt in CHECKLIST
    ]


def build_relationships(steps: list[dict]) -> list[dict]:
    relationships = []
    for producer in steps:
        outputs = set(producer["candidate_outputs"])
        for consumer in steps:
            if producer["order"] >= consumer["order"]:
                continue
            for path in sorted(outputs & set(consumer["candidate_inputs"])):
                relationships.append(
                    {
                        "producer_step": producer["name"],
                        "consumer_step": consumer["name"],
                        "path": path,
                        "evidence": "exact candidate output/input path match",
                        "confidence": "review_candidate",
                    }
                )
    return relationships


def build_gaps(steps: list[dict], relationships: list[dict]) -> list[dict]:
    related = {
        name
        for item in relationships
        for name in (item["producer_step"], item["consumer_step"])
    }
    gaps = []
    for step in steps:
        if not step["candidate_inputs"]:
            gaps.append(
                {
                    "step": step["name"],
                    "code": "no_input_candidates",
                    "message": "No input path candidate was discovered; inspect helpers, dynamic paths, and external state manually.",
                }
            )
        if not step["candidate_outputs"]:
            gaps.append(
                {
                    "step": step["name"],
                    "code": "no_output_candidates",
                    "message": "No output path candidate was discovered; identify the artifact that proves completion.",
                }
            )
        if step["unclassified_paths"]:
            gaps.append(
                {
                    "step": step["name"],
                    "code": "unclassified_path_candidates",
                    "message": "Some path candidates could not be classified as input or output and require source inspection.",
                }
            )
        if step["name"] not in related:
            gaps.append(
                {
                    "step": step["name"],
                    "code": "no_relationship_candidates",
                    "message": "No exact output-to-input path match connects this step to another Python step.",
                }
            )
    return gaps


def prepare(
    case_dir: Path,
    manifest_path: Path,
    expected_source_sha256: str | None,
    expected_candidate_sha256: str | None,
) -> dict:
    before = tree_metadata(case_dir)
    report = base_report(case_dir, manifest_path)
    entries = []
    try:
        source_sha256 = sha256_file(manifest_path)
        report["bindings"]["source_manifest"] = {
            "path": report_path(manifest_path),
            "sha256": source_sha256,
        }
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            preflight_entry_sources(case_dir, raw)
        analysis = analyze(case_dir, manifest_path)
        report["applicable"] = analysis["applicable"]
        if not analysis["applicable"]:
            report["status"] = "not_applicable"
            report["warnings"].append(
                "The source manifest already uses workflow schema version 2."
            )
        else:
            template = review_template(case_dir, manifest_path, analysis)
            report["bindings"]["base_candidate_sha256"] = template[
                "base_candidate_sha256"
            ]
            report["bindings"]["python_scripts"] = template["source_scripts"]
            if expected_source_sha256 and expected_source_sha256 != source_sha256:
                raise ValueError("expected source manifest hash is stale")
            if (
                expected_candidate_sha256
                and expected_candidate_sha256 != template["base_candidate_sha256"]
            ):
                raise ValueError("expected base candidate hash is stale")
            raw_steps = {item["name"]: item for item in raw["steps"]}
            analyzed_steps = {item["name"]: item for item in analysis["steps"]}
            steps = []
            trace_limitation_occurrences = 0
            for order, raw_step in enumerate(raw["steps"], start=1):
                if raw_step.get("type", "python") != "python":
                    continue
                name = raw_step["name"]
                script_path = resolve_path_inside(
                    case_dir, Path(raw_step["script"]), f"step {name} script"
                )
                (
                    path_evidence,
                    trace_limitations,
                    trace_limitation_groups,
                    limitation_occurrences,
                ) = enhanced_path_evidence(
                    case_dir, script_path, analyzed_steps[name]["static_path_hints"]
                )
                trace_limitation_occurrences += limitation_occurrences
                steps.append(
                    {
                        "order": order,
                        "name": name,
                        "script": raw_steps[name]["script"].replace("\\", "/"),
                        "script_sha256": sha256_file(script_path),
                        "path_evidence": path_evidence,
                        "candidate_inputs": sorted(
                            {item["path"] for item in path_evidence if item["access"] == "input"}
                        ),
                        "candidate_outputs": sorted(
                            {item["path"] for item in path_evidence if item["access"] == "output"}
                        ),
                        "unclassified_paths": sorted(
                            {item["path"] for item in path_evidence if item["access"] == "unclassified"}
                        ),
                        "trace_limitations": trace_limitations,
                        "trace_limitation_groups": trace_limitation_groups,
                        "checklist": checklist(),
                    }
                )
            relationships = build_relationships(steps)
            gaps = build_gaps(steps, relationships)
            entry_scripts = {Path(item["path"]).as_posix() for item in template["source_scripts"]}
            support_paths = sorted(
                {
                    frame["module"]
                    for step in steps
                    for evidence in step["path_evidence"]
                    for provenance in evidence["provenance"]
                    for frame in provenance["call_chain"]
                    if frame["module"] not in entry_scripts
                }
            )
            report["bindings"]["support_modules"] = [
                {"path": path, "sha256": sha256_file(resolve_path_inside(case_dir, Path(path), "support module"))}
                for path in support_paths
            ]
            report["steps"] = steps
            report["relationships"] = relationships
            report["gaps"] = gaps
            provenance = [
                item
                for step in steps
                for evidence in step["path_evidence"]
                for item in evidence["provenance"]
            ]
            report["summary"] = {
                "python_steps": len(steps),
                "path_candidates": sum(len(item["path_evidence"]) for item in steps),
                "candidate_inputs": sum(len(item["candidate_inputs"]) for item in steps),
                "candidate_outputs": sum(len(item["candidate_outputs"]) for item in steps),
                "relationships": len(relationships),
                "evidence_gaps": len(gaps),
                "pending_checklist_items": sum(len(item["checklist"]) for item in steps),
                "cache_enable_recommended": 0,
                "provenance_chains": len(provenance),
                "direct_provenance_chains": sum(item["kind"] == "direct" for item in provenance),
                "local_helper_provenance_chains": sum(item["kind"] == "local_helper" for item in provenance),
                "imported_helper_provenance_chains": sum(item["kind"] == "imported_helper" for item in provenance),
                "trace_limitation_occurrences": trace_limitation_occurrences,
                "unique_trace_limitations": sum(
                    len(item["trace_limitations"]) for item in steps
                ),
                "trace_limitations": sum(
                    len(item["trace_limitations"]) for item in steps
                ),
                "trace_limitation_groups": sum(
                    len(item["trace_limitation_groups"]) for item in steps
                ),
            }
            report["status"] = "ready_for_human_review"
            validate_limitation_aggregation(report)
            report["warnings"].extend(
                [
                    "Path evidence and exact-match relationships are review candidates, not declared dependencies.",
                    "Trace limitations locate unresolved static-analysis branches and require source or runtime review; they are not path candidates or migration blockers.",
                    "All checklist items remain pending; this package is not a completed review record.",
                ]
            )
            entries.append(
                diagnostic(
                    "warning",
                    "migration_review_package_requires_human_decisions",
                    "workflow_migration_review_package",
                    f"{report['summary']['pending_checklist_items']} checklist decisions remain pending",
                    remediation=["Inspect source and runtime evidence before completing a separate review record"],
                )
            )
    except (
        OSError, UnicodeError, json.JSONDecodeError, SyntaxError, ValueError,
        MemoryError, RecursionError,
    ) as exc:
        report["status"] = "failed"
        report["errors"].append(str(exc))
        entries.append(
            diagnostic(
                "error",
                "migration_review_package_failed",
                "workflow_migration_review_package",
                str(exc),
                remediation=["Repair stale bindings or unreadable source, then regenerate the package"],
            )
        )
    finally:
        report["source_unchanged"] = before == tree_metadata(case_dir)
        if not report["source_unchanged"]:
            report["status"] = "failed"
            report["errors"].append("review package generation changed the case file tree")
            entries.append(
                diagnostic(
                    "error",
                    "migration_review_package_source_changed",
                    "workflow_migration_review_package",
                    "review package generation changed the case file tree",
                    remediation=["Remove side effects from passive package generation"],
                )
            )
    report = attach_diagnostics(report, entries)
    load_and_validate(report, REPORT_SCHEMA, "workflow migration review package")
    return report


def print_human(report: dict) -> None:
    print(f"status={report['status']}")
    print(f"source_unchanged={str(report['source_unchanged']).lower()}")
    for step in report["steps"]:
        print(
            f"step.{step['name']}=inputs:{len(step['candidate_inputs'])} "
            f"outputs:{len(step['candidate_outputs'])} pending:{len(step['checklist'])}"
        )
    for item in report["relationships"]:
        print(
            f"relationship={item['producer_step']} -> {item['consumer_step']} ({item['path']})"
        )
    for error in report["errors"]:
        print(f"error: {error}")


def main() -> int:
    args = parse_args()
    case_dir = args.case_dir.expanduser().resolve()
    manifest_path = case_dir / "workflow.json"
    try:
        if not case_dir.is_dir():
            raise ValueError(f"case directory does not exist: {case_dir}")
        manifest_path = relative_manifest_path(case_dir, args.manifest)
        report = prepare(
            case_dir,
            manifest_path,
            args.expected_source_sha256,
            args.expected_candidate_sha256,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        report = base_report(case_dir, manifest_path)
        report["errors"].append(str(exc))
        report = attach_diagnostics(
            report,
            [
                diagnostic(
                    "error",
                    "migration_review_package_failed",
                    "workflow_migration_review_package",
                    str(exc),
                    remediation=["Provide an existing case and a manifest inside it"],
                )
            ],
        )
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_human(report)
    return 0 if report["status"] in {"ready_for_human_review", "not_applicable"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
