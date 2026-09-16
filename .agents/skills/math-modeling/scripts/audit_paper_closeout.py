#!/usr/bin/env python
"""Read-only closeout evidence binding; never certifies mathematical or human review."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from _workflow_common import resolve_inside, sha256_file

CATEGORIES = ('reviewer_reconstruction', 'references', 'ai_disclosure', 'anonymity')
RESIDUE = re.compile(r'本轮修复|旧视觉记录|旧交付冻结|正式写回|阶段\s*\d+|写回预检|套用其他题型模板|人为补入(?:回归性能比较|训练采纳规则)')
PLACEHOLDER = re.compile(r'\bTODO\b|待填写|待核验|占位|placeholder', re.I)


def narrative_lines(text):
    """Preserve line numbers; skip fenced source, not whole appendices or inline code."""
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r'^\s*(`{3,}|~{3,})', line)
        if match:
            mark = match[1]
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence) and not line.strip()[len(mark):].strip():
                fence = None
            continue
        if fence is None:
            yield number, line
    if fence:
        raise ValueError('Unclosed source fence; narrative scope is ambiguous')


def source_hygiene(text):
    return [{'line': n, 'text': line.strip()} for n, line in narrative_lines(text) if RESIDUE.search(line)]


def bound_file(case, item, label):
    if not isinstance(item, dict):
        raise ValueError(f'{label}: expected path/sha256 binding')
    path = resolve_inside(case, item.get('path'), label)
    digest = item.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', digest):
        raise ValueError(f'{label}: invalid SHA-256')
    if not path.is_file() or sha256_file(path).lower() != digest.lower():
        raise ValueError(f'{label}: missing or stale file {item.get("path")}')
    return path


def audit_closeout(case, review, docx, pdf):
    report = {'required': True, 'passed': False, 'scope': 'closeout_evidence_binding_only',
              'human_acceptance': False, 'semantic_correctness_proven': False, 'errors': []}
    case = case.resolve()
    try:
        if not review.resolve().is_relative_to(case):
            raise ValueError('Review must stay inside case')
        record = json.loads(review.read_text(encoding='utf-8-sig'))
        report['review_sha256'] = sha256_file(review)
        if record.get('schema_version') != 1 or record.get('status') != 'reviewed':
            raise ValueError('Closeout review pending or unsupported; do not promote a template to PASS')
        for key, target in [('docx', docx), ('pdf', pdf)]:
            if bound_file(case, record['artifacts'][key], key) != target.resolve():
                raise ValueError(f'{key}: review binds a different output')
        source = bound_file(case, record['artifacts']['source'], 'source')
        report['artifact_hashes'] = record['artifacts']
        text = source.read_text(encoding='utf-8-sig')
        residue = source_hygiene(text)
        report['internal_narrative_hits'] = residue
        if residue:
            report['errors'].append('Internal process narrative remains outside source-code fences')
        from datetime import datetime
        timestamp = datetime.fromisoformat(record['reviewed_at'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None or not record.get('reviewer', '').strip():
            raise ValueError('Actual reviewer and timezone-aware review time required')
        for category in CATEGORIES:
            entry = record['reviews'][category]
            findings = entry.get('findings', '')
            if entry.get('status') != 'reviewed' or not isinstance(findings, str) or len(findings.strip()) < 30 or PLACEHOLDER.search(findings):
                raise ValueError(f'{category}: substantive completed review required, not section/file presence')
            evidence = entry.get('evidence')
            if not isinstance(evidence, list) or not evidence:
                raise ValueError(f'{category}: source evidence bindings required')
            for item in evidence:
                bound_file(case, item, category)
        report['reviews'] = record['reviews']
        metadata_path = case / 'case.json'
        metadata = json.loads(metadata_path.read_text(encoding='utf-8-sig')) if metadata_path.exists() else {}
        if 'integration' in record:
            from audit_paper_integration import audit_integration
            plan_path = bound_file(case, record['integration']['plan'], 'integration plan')
            plan = json.loads(plan_path.read_text(encoding='utf-8-sig'))
            report['integration'] = audit_integration(case, source, docx, plan)
            if not report['integration']['passed']:
                report['errors'].extend('Integration: ' + e for e in report['integration']['errors'])
        elif metadata.get('paper_integration_required'):
            raise ValueError('Required integration plan binding missing')
        else:
            report['integration'] = {'status': 'not_run_legacy', 'passed': None}

        # This checks record freshness, not whether the named reviewer truly read the evidence.
        report['passed'] = not report['errors']
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        report['errors'].append(str(exc))
    return report


def audit_archive(case, package, manifest):
    """Verify actual ZIP membership and each payload against explicit source/hash/bytes.

    Manifest is external: do not add a self-hashing manifest or mutate a report in a
    ZIP after hashing. This supplements, never replaces, package_submission/M6/smoke.
    """
    report = {'passed': False, 'scope': 'archive_exact_inventory_only', 'errors': [],
              'human_acceptance': False, 'replay_proven': False}
    try:
        case = case.resolve()
        spec = json.loads(manifest.read_text(encoding='utf-8-sig'))
        if spec.get('schema_version') != 1:
            raise ValueError('Unsupported archive manifest')
        report['manifest_sha256'] = sha256_file(manifest)
        report['package_sha256'] = sha256_file(package)
        if spec.get('package_sha256', '').lower() != report['package_sha256'].lower():
            raise ValueError('Package hash differs from selected manifest')
        expected = spec['files']
        if not isinstance(expected, list) or not expected:
            raise ValueError('Archive inventory cannot be empty')
        records = {}
        for row in expected:
            name = row['path']
            if not isinstance(name, str) or '\\' in name or ':' in name or name.startswith('/') or any(x in ('', '.', '..') for x in name.split('/')):
                raise ValueError('Unsafe or non-canonical archive name')
            if name.casefold() in {n.casefold() for n in records}:
                raise ValueError('Duplicate manifest path')
            if isinstance(row.get('bytes'), bool) or not isinstance(row.get('bytes'), int) or row['bytes'] < 0:
                raise ValueError('Invalid declared byte count')
            path = bound_file(case, {'path': row.get('source', name), 'sha256': row.get('sha256')}, name)
            if path.stat().st_size != row['bytes']:
                raise ValueError(f'Source size mismatch: {name}')
            records[name] = row
        with zipfile.ZipFile(package) as archive:
            members = archive.infolist()
            names = [x.filename for x in members]
            if len({n.casefold() for n in names}) != len(names) or set(names) != set(records):
                raise ValueError('ZIP inventory differs, contains duplicates, or has unlisted entries')
            for info in members:
                row = records[info.filename]
                if info.flag_bits & 1 or info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Encrypted, directory or symlink entry is not allowed')
                if info.file_size != row['bytes']:
                    raise ValueError(f'Archive size mismatch: {info.filename}')
                digest = hashlib.sha256()
                count = 0
                with archive.open(info) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block); count += len(block)
                if count != row['bytes'] or digest.hexdigest().lower() != row['sha256'].lower():
                    raise ValueError(f'Archive payload mismatch: {info.filename}')
        report.update(passed=True, files_verified=len(records), package_bytes=package.stat().st_size)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, zipfile.BadZipFile, RuntimeError) as exc:
        report['errors'].append(str(exc))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case-dir', required=True, type=Path)
    p.add_argument('--review', default='paper/closeout-review.json')
    p.add_argument('--docx', default='paper/paper.docx')
    p.add_argument('--pdf', default='paper/paper.pdf')
    p.add_argument('--package', type=Path)
    p.add_argument('--manifest', type=Path)
    p.add_argument('--json', action='store_true')
    args = p.parse_args()
    try:
        if args.package or args.manifest:
            if not args.package or not args.manifest:
                raise ValueError('Both --package and --manifest are required')
            report = audit_archive(args.case_dir, args.package, args.manifest)
        else:
            case = args.case_dir.resolve()
            report = audit_closeout(case, resolve_inside(case, args.review, 'review'),
                                    resolve_inside(case, args.docx, 'docx'), resolve_inside(case, args.pdf, 'pdf'))
    except (OSError, ValueError) as exc:
        report = {'passed': False, 'errors': [str(exc)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    sys.exit(main())
