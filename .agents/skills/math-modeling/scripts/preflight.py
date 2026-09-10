#!/usr/bin/env python
"""Check whether the current machine can run the modeling workflow."""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from _diagnostics import enrich_legacy_report
from _workflow_common import append_failure_event


DEFAULT_MODULES = (
    "pypdf",
    "docx",
    "numpy",
    "pandas",
    "scipy",
    "matplotlib",
    "openpyxl",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--failure-log",
        type=Path,
        help="Optional JSONL path where a failed preflight attempt is recorded",
    )
    parser.add_argument(
        "--writable-dir",
        action="append",
        type=Path,
        default=[],
        help="Controlled output directory that must support create/delete; repeat as needed",
    )
    parser.add_argument(
        "--existing-file",
        action="append",
        type=Path,
        default=[],
        help="Declared output file to probe with r+b when it already exists; repeat as needed",
    )
    parser.add_argument(
        "--existing-file-root",
        action="append",
        type=Path,
        default=[],
        help="Declared output tree whose existing files must support r+b; repeat as needed",
    )
    parser.add_argument(
        "--module",
        action="append",
        dest="modules",
        help="Required import name; repeat to override the default module set",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def find_executable(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return str(Path(found).resolve())
    return None


def probe_executable_report(path: str, *arguments: str) -> dict:
    """Run a bounded startup probe and retain enough evidence to diagnose failure."""
    report = {
        "path": str(Path(path).resolve()),
        "arguments": list(arguments),
        "usable": False,
        "exit_code": None,
        "error": None,
        "stdout": "",
        "stderr": "",
    }
    try:
        completed = subprocess.run(
            [path, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        report["error"] = str(exc)
        return report
    report["exit_code"] = completed.returncode
    report["stdout"] = completed.stdout.strip()
    report["stderr"] = completed.stderr.strip()
    if completed.returncode != 0:
        report["error"] = f"exit code {completed.returncode}"
        return report
    report["usable"] = True
    return report


def probe_executable(path: str, *arguments: str) -> tuple[bool, str | None]:
    report = probe_executable_report(path, *arguments)
    return bool(report["usable"]), report["error"]


def poppler_candidate_paths(name: str) -> list[tuple[str, Path]]:
    """Return ordered Poppler candidates without claiming that any can start."""
    candidates: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def add(source: str, candidate: Path) -> None:
        resolved = candidate.resolve()
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            candidates.append((source, resolved))

    discovered = find_executable(name)
    if discovered:
        wrapper = Path(discovered).resolve()
        add("path", wrapper)
        if os.name == "nt" and wrapper.suffix.casefold() in {".cmd", ".bat"}:
            dependencies = wrapper.parent.parent.parent
            add(
                "bundled_native_from_wrapper",
                dependencies
                / "native"
                / "poppler"
                / "Library"
                / "bin"
                / f"{name}.exe",
            )
    if os.name == "nt":
        add(
            "codex_primary_runtime_native",
            Path(
                os.path.expandvars(
                    rf"%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\{name}.exe"
                )
            ),
        )
        add(
            "program_files",
            Path(
                os.path.expandvars(
                    rf"%ProgramFiles%\poppler\Library\bin\{name}.exe"
                )
            ),
        )
    return candidates


def resolve_poppler_tool(name: str) -> dict:
    """Resolve Poppler fail-closed and retain every candidate probe result."""
    candidates = []
    selected = None
    for source, candidate in poppler_candidate_paths(name):
        exists = candidate.is_file()
        probe = probe_executable_report(str(candidate), "-v") if exists else None
        result = {
            "source": source,
            "path": str(candidate),
            "exists": exists,
            "usable": bool(probe and probe["usable"]),
            "probe": probe,
        }
        candidates.append(result)
        if selected is None and result["usable"]:
            selected = result

    detected = any(candidate["exists"] for candidate in candidates)
    return {
        "name": name,
        "path": selected["path"] if selected else None,
        "source": selected["source"] if selected else None,
        "detected": detected,
        "usable": selected is not None,
        "selected": selected,
        "candidates": candidates,
        "error": None
        if selected
        else (
            "all detected Poppler candidates failed startup"
            if detected
            else "no Poppler candidate was detected"
        ),
    }


def resolve_poppler_executable(name: str) -> str | None:
    """Compatibility wrapper returning only a proven-working Poppler path."""
    return resolve_poppler_tool(name)["path"]


def probe_word_com(word: str | None) -> tuple[bool, str | None]:
    if word is None:
        return False, "Microsoft Word was not detected"
    shell = shutil.which("powershell.exe") or shutil.which("powershell")
    if shell is None:
        return False, "PowerShell was not found"
    script = (
        "$ErrorActionPreference='Stop';"
        "$word=$null;"
        "try{$word=New-Object -ComObject Word.Application;$word.Visible=$false}"
        "finally{if($null -ne $word){$word.Quit()}}"
    )
    try:
        completed = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        return False, detail or f"exit code {completed.returncode}"
    return True, None


def running_process_names() -> tuple[list[str], str | None]:
    """Return executable names without requiring optional process libraries."""
    if os.name != "nt":
        return [], None
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_snapshot = kernel32.CreateToolhelp32Snapshot
    create_snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    create_snapshot.restype = wintypes.HANDLE
    process_first = kernel32.Process32FirstW
    process_first.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    process_first.restype = wintypes.BOOL
    process_next = kernel32.Process32NextW
    process_next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    process_next.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    snapshot = create_snapshot(0x00000002, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if snapshot == invalid_handle:
        return [], ctypes.WinError(ctypes.get_last_error()).strerror
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(ProcessEntry32W)
        if not process_first(snapshot, ctypes.byref(entry)):
            return [], ctypes.WinError(ctypes.get_last_error()).strerror
        names = []
        while True:
            names.append(entry.szExeFile)
            if not process_next(snapshot, ctypes.byref(entry)):
                error = ctypes.get_last_error()
                if error == 18:  # ERROR_NO_MORE_FILES
                    return names, None
                return [], ctypes.WinError(error).strerror
    finally:
        close_handle(snapshot)


def assess_matlab_batch(
    matlab: str | None,
    process_names: list[str],
    process_check_error: str | None = None,
    *,
    windows: bool | None = None,
) -> dict:
    """Assess whether a new batch process can start without a known conflict."""
    is_windows = os.name == "nt" if windows is None else windows
    blockers = sorted(
        {
            name
            for name in process_names
            if name.casefold() in {"matlab.exe", "mathworksservicehost.exe"}
        },
        key=str.casefold,
    )
    error = process_check_error if is_windows else None
    safe_to_start = bool(matlab) and not blockers and error is None
    reason = None
    if matlab is None:
        reason = "MATLAB executable was not detected"
    elif blockers:
        reason = (
            "running MATLAB/MathWorks ServiceHost process blocks independent batch "
            "startup; use mcp-evidence or close MathWorks sessions first"
        )
    elif error:
        reason = f"could not verify running MathWorks processes: {error}"
    return {
        "available": matlab is not None,
        "safe_to_start": safe_to_start,
        "blocking_processes": blockers,
        "process_check_error": error,
        "reason": reason,
    }


def find_word() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None

    candidates = (
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\WINWORD.EXE"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\WINWORD.EXE"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\WINWORD.EXE"),
    )
    for hive, key_name in candidates:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                value, _ = winreg.QueryValueEx(key, None)
        except OSError:
            continue
        if value and Path(value).is_file():
            return str(Path(value).resolve())

    try:
        clsid = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID")
        command = winreg.QueryValue(
            winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32"
        )
    except OSError:
        return None
    executable = command.strip().strip('"').split('"')[0]
    return str(Path(executable).resolve()) if Path(executable).is_file() else None


def find_known_file(paths: tuple[str, ...]) -> str | None:
    for value in paths:
        candidate = Path(os.path.expandvars(value))
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def find_libreoffice() -> str | None:
    """Prefer LibreOffice's console launcher on Windows.

    soffice.exe is the GUI-subsystem launcher and may detach or wait indefinitely
    when stdout is captured. soffice.com is the supported console entry point and
    preserves output and exit codes for headless automation.
    """
    if os.name == "nt":
        discovered = find_executable("soffice.com", "libreoffice.com") or find_known_file(
            (
                r"%ProgramFiles%\LibreOffice\program\soffice.com",
                r"%ProgramFiles(x86)%\LibreOffice\program\soffice.com",
                r"%ProgramFiles%\LibreOffice\program\soffice.exe",
                r"%ProgramFiles(x86)%\LibreOffice\program\soffice.exe",
            )
        )
        if discovered is None:
            return None
        candidate = Path(discovered).resolve()
        if candidate.suffix.casefold() == ".exe":
            console_launcher = candidate.with_suffix(".com")
            if console_launcher.is_file():
                return str(console_launcher.resolve())
        return str(candidate)
    return find_executable("soffice", "libreoffice")


def check_writable(path: Path, require_existing: bool) -> dict:
    resolved = path.expanduser().resolve()
    result = {
        "path": str(resolved),
        "exists": resolved.exists(),
        "writable": False,
        "checked_directory": None,
        "error": None,
    }
    if require_existing and not resolved.is_dir():
        result["error"] = "directory does not exist"
        return result

    existing_parent = resolved
    missing_directories = []
    while not existing_parent.exists() and existing_parent != existing_parent.parent:
        missing_directories.append(existing_parent)
        existing_parent = existing_parent.parent
    if not existing_parent.is_dir():
        result["error"] = "no existing parent directory"
        return result

    created_directories = []
    try:
        for directory in reversed(missing_directories):
            directory.mkdir()
            created_directories.append(directory)
        target = resolved if missing_directories else existing_parent
        if not target.is_dir():
            raise OSError("path is not a directory")
        result["checked_directory"] = str(target)
        # Create one explicit probe file. NamedTemporaryFile retries many
        # random names on Windows after Access Denied, which can make preflight
        # appear hung when the directory is protected by the host sandbox.
        probe = target / f".math-modeling-write-test-{uuid.uuid4().hex}.tmp"
        descriptor = os.open(
            str(probe), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        os.close(descriptor)
        try:
            probe.unlink()
        except OSError:
            pass
    except OSError as exc:
        result["error"] = str(exc)
        return result
    finally:
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
    result["writable"] = True
    return result


def check_existing_files_writable(root: Path, sample_limit: int = 10) -> dict:
    """Probe whether existing controlled files can be opened for modification.

    Opening with ``r+b`` and closing immediately exercises the Windows file and ACL
    path without changing file contents. Missing controlled directories are reported
    as not applicable so temporary case directories can still use preflight.
    """
    resolved = root.expanduser().resolve()
    result = {
        "path": str(resolved),
        "exists": resolved.exists(),
        "applicable": False,
        "checked": False,
        "writable": True,
        "total_files": 0,
        "writable_files": 0,
        "blocked_files": 0,
        "blocked_by_reason": {},
        "sample_blocked": [],
        "error": None,
    }
    if not resolved.exists():
        return result
    result["applicable"] = True
    if not resolved.is_dir():
        result["checked"] = True
        result["writable"] = False
        result["error"] = "controlled path is not a directory"
        return result

    try:
        files = sorted(
            (
                candidate
                for candidate in resolved.rglob("*")
                if candidate.is_file() and not candidate.is_symlink()
            ),
            key=lambda candidate: os.path.normcase(str(candidate)),
        )
    except OSError as exc:
        result["checked"] = True
        result["writable"] = False
        result["error"] = str(exc)
        return result

    result["checked"] = True
    result["total_files"] = len(files)
    for candidate in files:
        try:
            with candidate.open("r+b"):
                pass
        except OSError as exc:
            result["blocked_files"] += 1
            reason = f"{type(exc).__name__}: {exc}"
            reasons = result["blocked_by_reason"]
            reasons[reason] = reasons.get(reason, 0) + 1
            if len(result["sample_blocked"]) < sample_limit:
                result["sample_blocked"].append(
                    {"path": str(candidate), "error": str(exc)}
                )
        else:
            result["writable_files"] += 1

    result["writable"] = result["blocked_files"] == 0
    if not result["writable"]:
        examples = ", ".join(
            item["path"] for item in result["sample_blocked"][:3]
        )
        first_reason = next(iter(result["blocked_by_reason"]), "unknown error")
        result["error"] = (
            f"{result['blocked_files']} existing file(s) failed r+b access"
            + f"; first error: {first_reason}"
            + (f"; examples: {examples}" if examples else "")
        )
    return result


def check_declared_files_writable(
    paths: list[Path], sample_limit: int = 10
) -> dict:
    """Probe exact declared output files without rejecting outputs not created yet."""
    unique: dict[str, Path] = {}
    for path in paths:
        resolved = path.expanduser().resolve()
        unique.setdefault(os.path.normcase(str(resolved)), resolved)
    candidates = [unique[key] for key in sorted(unique)]
    result = {
        "paths": [str(path) for path in candidates],
        "applicable": bool(candidates),
        "checked": bool(candidates),
        "writable": True,
        "declared_paths": len(candidates),
        "existing_files": 0,
        "missing_files": 0,
        "writable_files": 0,
        "blocked_files": 0,
        "blocked_by_reason": {},
        "sample_blocked": [],
        "error": None,
    }
    for candidate in candidates:
        if not candidate.exists():
            result["missing_files"] += 1
            continue
        result["existing_files"] += 1
        if not candidate.is_file() or candidate.is_symlink():
            exc = OSError("declared output is not a regular file")
        else:
            try:
                with candidate.open("r+b"):
                    pass
            except OSError as caught:
                exc = caught
            else:
                result["writable_files"] += 1
                continue
        result["blocked_files"] += 1
        reason = f"{type(exc).__name__}: {exc}"
        reasons = result["blocked_by_reason"]
        reasons[reason] = reasons.get(reason, 0) + 1
        if len(result["sample_blocked"]) < sample_limit:
            result["sample_blocked"].append(
                {"path": str(candidate), "error": str(exc)}
            )

    result["writable"] = result["blocked_files"] == 0
    if not result["writable"]:
        examples = ", ".join(
            item["path"] for item in result["sample_blocked"][:3]
        )
        first_reason = next(iter(result["blocked_by_reason"]), "unknown error")
        result["error"] = (
            f"{result['blocked_files']} declared output file(s) failed r+b access"
            + f"; first error: {first_reason}"
            + (f"; examples: {examples}" if examples else "")
        )
    return result


def choose_backends(
    tools: dict[str, str | None], probes: dict[str, dict] | None = None
) -> dict:
    probe_status = probes or {}
    docx_candidates = [
        ("Microsoft Word", "word", tools["word"]),
        ("LibreOffice", "libreoffice", tools["libreoffice"]),
    ]
    render_candidates = [
        ("pdftoppm", "pdftoppm", tools["pdftoppm"]),
        ("pdftocairo", "pdftocairo", tools["pdftocairo"]),
    ]

    def summarize(candidates: list[tuple[str, str, str | None]]) -> dict:
        detected = []
        for name, key, path in candidates:
            if path is None:
                continue
            probe = probe_status.get(key, {"usable": True, "error": None})
            detected.append(
                {
                    "name": name,
                    "path": path,
                    "usable": bool(probe.get("usable", True)),
                    "probe_error": probe.get("error"),
                }
            )
        available = [candidate for candidate in detected if candidate["usable"]]
        return {
            "primary": available[0] if available else None,
            "fallbacks": available[1:],
            "available": bool(available),
            "detected": detected,
        }

    return {
        "docx_to_pdf": summarize(docx_candidates),
        "pdf_to_images": summarize(render_candidates),
    }


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def run_preflight(args: argparse.Namespace) -> dict:
    modules = tuple(dict.fromkeys(args.modules or DEFAULT_MODULES))
    module_status = {name: module_available(name) for name in modules}
    poppler = {
        name: resolve_poppler_tool(name)
        for name in ("pdftoppm", "pdftocairo")
    }
    tools = {
        "word": find_word(),
        "libreoffice": find_libreoffice(),
        "pdftoppm": poppler["pdftoppm"]["path"],
        "pdftocairo": poppler["pdftocairo"]["path"],
        "tectonic": find_executable("tectonic"),
        "matlab": find_executable("matlab"),
    }
    tool_warnings = []
    probes = {}
    for name, resolution in poppler.items():
        selected_probe = (resolution.get("selected") or {}).get("probe")
        probes[name] = {
            "usable": bool(resolution["usable"]),
            "error": resolution["error"],
            "resolution": resolution,
        }
        if resolution["detected"] and not resolution["usable"]:
            tool_warnings.append(
                f"{name} detected but all candidates failed startup: "
                f"{resolution['error']}"
            )
    if tools["libreoffice"] is not None:
        working, error = probe_executable(tools["libreoffice"], "--version")
        probes["libreoffice"] = {"usable": working, "error": error}
        if not working:
            tool_warnings.append(
                f"LibreOffice detected but failed startup: {tools['libreoffice']} ({error})"
            )
    word_working, word_error = probe_word_com(tools["word"])
    probes["word"] = {"usable": word_working, "error": word_error}
    if tools["word"] is not None and not word_working:
        tool_warnings.append(
            f"Microsoft Word detected but COM startup failed: {word_error}"
        )
    process_names, process_check_error = running_process_names()
    matlab_batch = assess_matlab_batch(
        tools["matlab"], process_names, process_check_error
    )
    if matlab_batch["available"] and not matlab_batch["safe_to_start"]:
        tool_warnings.append(f"MATLAB batch unavailable: {matlab_batch['reason']}")
    paths = {
        "project_root": check_writable(args.project_root, True),
        "existing_files": check_existing_files_writable(
            args.project_root / ".agents" / "skills"
        ),
    }
    if args.output_dir is not None:
        paths["output_dir"] = check_writable(args.output_dir, False)
    writable_dirs = getattr(args, "writable_dir", [])
    if writable_dirs:
        paths["writable_dirs"] = [
            check_writable(path, False) for path in writable_dirs
        ]
    existing_file_paths = getattr(args, "existing_file", [])
    if existing_file_paths:
        paths["declared_output_files"] = check_declared_files_writable(
            existing_file_paths
        )
    existing_file_roots = getattr(args, "existing_file_root", [])
    if existing_file_roots:
        paths["declared_output_roots"] = [
            check_existing_files_writable(path) for path in existing_file_roots
        ]

    missing_modules = [name for name, present in module_status.items() if not present]
    path_errors = []
    for name, status in paths.items():
        statuses = status if isinstance(status, list) else [status]
        for index, item in enumerate(statuses):
            if not item["writable"]:
                label = f"{name}[{index}]" if isinstance(status, list) else name
                path_errors.append(f"{label}: {item['error']}")
    errors = [f"missing required Python module: {name}" for name in missing_modules]
    errors.extend(path_errors)
    warnings = tool_warnings
    backends = choose_backends(tools, probes)
    if not backends["docx_to_pdf"]["available"]:
        warnings.append("no Microsoft Word or LibreOffice DOCX-to-PDF backend detected")
    if not backends["pdf_to_images"]["available"]:
        warnings.append("no pdftoppm or pdftocairo PDF renderer detected")

    report = {
        "ready": not errors,
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "modules": module_status,
        "tools": tools,
        "tool_probes": probes,
        "poppler_resolution": poppler,
        "matlab_batch": matlab_batch,
        "backends": backends,
        "paths": paths,
        "errors": errors,
        "warnings": warnings,
    }
    return enrich_legacy_report(
        report,
        stage="preflight",
        error_code="environment_not_ready",
        warning_code="environment_advisory",
    )


def print_human(report: dict) -> None:
    print(f"ready={str(report['ready']).lower()}")
    print(
        f"python={report['python']['executable']} "
        f"version={report['python']['version']}"
    )
    for name, present in report["modules"].items():
        print(f"module.{name}={'ok' if present else 'missing'}")
    for name, path in report["tools"].items():
        print(f"tool.{name}={path or 'not_found'}")
    batch = report["matlab_batch"]
    print(f"matlab_batch.safe_to_start={str(batch['safe_to_start']).lower()}")
    if batch["blocking_processes"]:
        print(
            "matlab_batch.blocking_processes="
            + ",".join(batch["blocking_processes"])
        )
    existing_files = report["paths"].get("existing_files")
    if existing_files and existing_files["applicable"]:
        print(
            "existing_files="
            f"{existing_files['writable_files']}/{existing_files['total_files']} writable"
        )
        if existing_files["blocked_files"]:
            print(
                "existing_files.blocked="
                + str(existing_files["blocked_files"])
            )
    declared_files = report["paths"].get("declared_output_files")
    if declared_files and declared_files["applicable"]:
        print(
            "declared_output_files="
            f"{declared_files['writable_files']}/{declared_files['existing_files']} writable"
            f" ({declared_files['missing_files']} not-created)"
        )
    for index, root in enumerate(report["paths"].get("declared_output_roots", [])):
        if root["applicable"]:
            print(
                f"declared_output_roots[{index}]="
                f"{root['writable_files']}/{root['total_files']} writable"
            )
    for name, backend in report["backends"].items():
        primary = backend["primary"]
        print(f"backend.{name}={primary['name'] if primary else 'unavailable'}")
    for warning in report["warnings"]:
        print(f"warning: {warning}")
    for error in report["errors"]:
        print(f"error: {error}")


def main() -> int:
    args = parse_args()
    report = run_preflight(args)
    if not report["ready"] and args.failure_log:
        append_failure_event(
            args.failure_log,
            source="preflight",
            report=report,
            command=sys.argv,
        )
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_human(report)
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
