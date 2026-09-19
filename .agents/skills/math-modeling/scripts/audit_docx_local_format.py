#!/usr/bin/env python
"""Read-only, hash-bound allowlist for local DOCX formatting edits (not visual QA)."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
DOC = "word/document.xml"
RUN = {"w:sz", "w:szCs", "w:b", "w:bCs"}
PARA = {"w:jc", "w:spacing", "w:ind", "w:keepNext", "w:keepLines"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def q(name: str) -> str:
    if not isinstance(name, str) or not name.startswith("w:"):
        raise ValueError("property and attribute names must use the w: prefix")
    return "{" + W + "}" + name[2:]


def signature(node: ET.Element):
    return [node.tag, sorted(node.attrib.items()), node.text, node.tail,
            [signature(child) for child in node]]


def node_hash(node: ET.Element) -> str:
    return sha(json.dumps(signature(node), ensure_ascii=False).encode("utf-8"))


def package(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate ZIP member names")
        return {name: archive.read(name) for name in names}


def document(parts: dict[str, bytes]):
    raw = parts[DOC]
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DTD/entity declarations are not supported")
    root = ET.fromstring(raw)
    bodies = root.findall(q("w:body"))
    if len(bodies) != 1:
        raise ValueError("document requires exactly one body")
    return root, bodies[0]


def locate(body: ET.Element, path: object) -> ET.Element:
    if not isinstance(path, list) or not path or not all(type(i) is int and i >= 0 for i in path):
        raise ValueError("target path must be non-empty zero-based child indices from w:body")
    node = body
    for index in path:
        if index >= len(node):
            raise ValueError(f"target path does not exist: {path}")
        node = node[index]
    return node


def describe(path: Path) -> dict:
    _, body = document(package(path))
    targets = []

    def walk(node, indices):
        if node.tag in (q("w:p"), q("w:r"), "{" + M + "}r"):
            targets.append({"path": indices, "node_sha256": node_hash(node),
                            "kind": node.tag, "text": "".join(node.itertext())[:160]})
        for i, child in enumerate(node):
            walk(child, indices + [i])
    for i, child in enumerate(body):
        walk(child, [i])
    return {"schema_version": 1, "before_sha256": sha(path.read_bytes()), "targets": targets}


def audit(before: Path, after: Path, plan: dict) -> dict:
    errors = []
    report = {"schema_version": 1, "mode": "read_only_local_format", "passed": False,
              "errors": errors, "visual_review_passed": False,
              "boundary": "OOXML change scope only; no rendering, scientific validation or human approval."}
    try:
        if not isinstance(plan, dict) or type(plan.get("schema_version")) is not int or plan["schema_version"] != 1:
            raise ValueError("plan schema_version must be 1")
        bh, ah = sha(before.read_bytes()), sha(after.read_bytes())
        report.update(before_sha256=bh, after_sha256=ah,
                      requires_export_and_page_review=bh != ah)
        if plan.get("before_sha256") != bh:
            raise ValueError("stale base: before_sha256 mismatch")
        targets = plan.get("targets")
        if not isinstance(targets, list) or not targets:
            raise ValueError("targets must be a non-empty allowlist")
        bp, ap = package(before), package(after)
        changed_parts = sorted(name for name in set(bp) | set(ap) if bp.get(name) != ap.get(name))
        report["changed_parts"] = changed_parts
        for name in changed_parts:
            if name != DOC:
                errors.append(f"unapproved package part changed: {name}")
        br, bb = document(bp)
        ar, ab = document(ap)
        seen = set()
        # Resolve all paths before removing any properties from comparison trees.
        resolved = []
        for target in targets:
            if not isinstance(target, dict):
                raise ValueError("target must be an object")
            path = target.get("path")
            bn, an = locate(bb, path), locate(ab, path)
            key = tuple(path)
            if key in seen:
                raise ValueError("duplicate target path")
            seen.add(key)
            if target.get("node_sha256") != node_hash(bn):
                raise ValueError(f"stale target hash: {path}")
            if bn.tag != an.tag:
                raise ValueError(f"target kind changed: {path}")
            if bn.tag == q("w:p"):
                container, allowed = q("w:pPr"), PARA
            elif bn.tag in (q("w:r"), "{" + M + "}r"):
                container, allowed = q("w:rPr"), RUN
            else:
                raise ValueError("only paragraph or text/math run targets are supported")
            props = target.get("properties")
            if not isinstance(props, dict) or not props or not set(props) <= allowed:
                raise ValueError(f"unsupported/empty properties for target: {path}")
            resolved.append((bn, an, container, props, path))
        for bn, an, container, props, path in resolved:
            for node in (bn, an):
                if len(node.findall(container)) > 1:
                    raise ValueError("duplicate property containers")
            for name, expected in props.items():
                if expected is not None and (not isinstance(expected, dict)
                        or not all(isinstance(k, str) and k.startswith("w:") and isinstance(v, str)
                                   for k, v in expected.items())):
                    raise ValueError("expected property must be w: attribute map or null for removal")
                parent = an.find(container)
                matches = [] if parent is None else parent.findall(q(name))
                if expected is None:
                    if matches:
                        errors.append(f"expected property removal not satisfied: {path} {name}")
                elif (len(matches) != 1 or matches[0].attrib != {q(k): v for k, v in expected.items()}
                      or len(matches[0]) or (matches[0].text or "").strip()):
                    errors.append(f"expected property value not satisfied: {path} {name}")
                for node in (bn, an):
                    parent = node.find(container)
                    if parent is not None:
                        found = parent.findall(q(name))
                        if len(found) > 1:
                            raise ValueError("duplicate formatting properties")
                        for child in found:
                            parent.remove(child)
            # An added/removed empty property wrapper has no formatting effect.
            for node in (bn, an):
                parent = node.find(container)
                if parent is not None and not len(parent) and not parent.attrib and not parent.text and not parent.tail:
                    node.remove(parent)
        if signature(br) != signature(ar):
            errors.append("document changed outside allowed direct formatting properties (text/math/structure/other formatting)")
        report["target_count"] = len(targets)
        report["passed"] = not errors
    except (OSError, ValueError, KeyError, ET.ParseError, zipfile.BadZipFile) as exc:
        errors.append(str(exc))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--describe", action="store_true", help="Print base-bound target addresses, no edit authorization")
    args = parser.parse_args()
    try:
        if args.describe:
            if args.after or args.plan:
                parser.error("--describe cannot be combined with --after/--plan")
            report = describe(args.before)
        else:
            if not args.after or not args.plan:
                parser.error("audit requires --after and --plan")
            report = audit(args.before, args.after, json.loads(args.plan.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, ET.ParseError, zipfile.BadZipFile) as exc:
        report = {"passed": False, "errors": [str(exc)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report.get("passed") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
