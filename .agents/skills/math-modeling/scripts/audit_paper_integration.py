#!/usr/bin/env python
"""Read-only Markdown/Word integration checks; not a mathematical or visual review."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from _workflow_common import resolve_inside, sha256_file

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS = {'w': W, 'm': M, 'a': A}


def fenced_regions(text):
    """Return prose with fenced lines blanked and exact fenced payloads with line spans."""
    lines = text.splitlines(); prose = list(lines); blocks = []; opened = None
    for i, line in enumerate(lines):
        mark = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
        if opened is None:
            if mark:
                opened = (i, mark[1]); prose[i] = ''
        else:
            prose[i] = ''
            start, fence = opened
            if mark and mark[1][0] == fence[0] and len(mark[1]) >= len(fence) and not mark[2].strip():
                blocks.append((start, i, '\n'.join(lines[start+1:i]).strip('\n')))
                opened = None
    if opened is not None:
        raise ValueError('Unclosed source fence; cannot establish narrative scope')
    return '\n'.join(prose), blocks


def heading_region(text, heading):
    """Exact heading match outside fences, followed through subordinate headings."""
    prose, _ = fenced_regions(text)
    headings = [(i, len(m[1]), m[2].strip()) for i, line in enumerate(prose.splitlines())
                if (m := re.match(r'^(#{1,6})\s+(.+?)\s*$', line))]
    found = [x for x in headings if x[2] == heading]
    if len(found) != 1:
        raise ValueError(f'Heading must match exactly once: {heading}')
    start, level, _ = found[0]
    end = next((i for i, lev, _ in headings if i > start and lev <= level), len(text.splitlines()))
    return start, end


def validate_plan(plan):
    required = {'schema_version', 'status', 'body_end_heading', 'docx_body_end_heading',
                'equation_numbering', 'appendix_sources', 'support_manifest'}
    if not isinstance(plan, dict) or set(plan) != required:
        raise ValueError('Integration plan keys differ from the maintained template')
    if plan['schema_version'] != 1 or plan['status'] != 'reviewed':
        raise ValueError('Integration plan pending or unsupported')
    if plan['equation_numbering'] not in ('consecutive', 'explicit'):
        raise ValueError('equation_numbering must be consecutive or explicit')
    for key in ('body_end_heading', 'docx_body_end_heading', 'support_manifest'):
        if not isinstance(plan[key], str):
            raise ValueError(f'{key} must be a string')
    if bool(plan['body_end_heading']) != bool(plan['docx_body_end_heading']):
        raise ValueError('Both source and DOCX body boundaries must be declared, or both empty')
    if not isinstance(plan['appendix_sources'], list):
        raise ValueError('appendix_sources must be a list')
    seen = set()
    for item in plan['appendix_sources']:
        if not isinstance(item, dict) or set(item) != {'path', 'heading'}:
            raise ValueError('Each appendix source needs path and exact heading')
        if not all(isinstance(x, str) and x.strip() for x in item.values()):
            raise ValueError('Empty appendix mapping')
        if item['path'] in seen:
            raise ValueError('Duplicate appendix source path')
        seen.add(item['path'])
    if plan['appendix_sources'] and not plan['body_end_heading']:
        raise ValueError('Code appendix requires an explicit body boundary')


def audit_integration(case, source, docx, plan):
    report = {'passed': False, 'scope': 'markdown_word_integration_only',
              'semantic_correctness_proven': False, 'visual_review': 'not_performed',
              'human_acceptance': False, 'errors': [], 'checks': {}}
    try:
        validate_plan(plan)
        case = Path(case).resolve(); source = Path(source).resolve(); docx = Path(docx).resolve()
        if not source.is_relative_to(case) or not docx.is_relative_to(case):
            raise ValueError('Artifacts must remain inside the case')
        if source.suffix.lower() != '.md':
            raise ValueError('This adapter supports Markdown/Word only; use the reviewed native-format route')
        report['source_sha256'] = sha256_file(source); report['docx_sha256'] = sha256_file(docx)
        text = source.read_text(encoding='utf-8-sig'); narrative, codeblocks = fenced_regions(text)
        boundary = heading_region(text, plan['body_end_heading'])[0] if plan['body_end_heading'] else len(text.splitlines())
        body = '\n'.join(narrative.splitlines()[:boundary])
        # Only maintained Markdown display syntax is accepted; unknown routes must not pass as zero math.
        if re.search(r'\\begin\{(?:equation\*?|align\*?|gather\*?)\}', body):
            raise ValueError('Use $$ or bracket-delimited displays for this Markdown adapter')
        display_pattern = r'^\$\$[^\S\n]*\n(.*?)^\$\$[^\S\n]*$'
        displays = re.findall(display_pattern, body, re.M | re.S)
        without_dollars = re.sub(display_pattern, '', body, flags=re.M | re.S)
        if '$$' in without_dollars:
            raise ValueError('Unbalanced or unsupported display delimiters')
        bracket_pattern = r'\\\[(.*?)\\\]'
        displays += re.findall(bracket_pattern, without_dollars, re.S)
        outside_displays = re.sub(bracket_pattern, '', without_dollars, flags=re.S)
        if re.search(r'\\[\[\]]', outside_displays):
            raise ValueError('Unbalanced bracket display delimiters')
        if re.search(r'\\(?:eqref|ref|label)\{', body):
            raise ValueError('Symbolic LaTeX references require a reviewed native-format adapter')
        labels = re.findall(r'\\tag\{([^{}]+)\}', body)
        if len(labels) != len(set(labels)):
            raise ValueError('Duplicate equation tags')
        if plan['equation_numbering'] == 'consecutive' and labels != [str(i) for i in range(1, len(labels)+1)]:
            raise ValueError('Equation numbering has gaps or is out of order')
        if sum(len(re.findall(r'\\tag\{([^{}]+)\}', block)) for block in displays) != len(labels):
            raise ValueError('Equation tag outside a supported display')
        # Ref checks cover literal numbered refs; symbolic LaTeX refs require the native TeX route.
        refs = re.findall(r'(?:式\s*[（(]|\bEq(?:uation)?\.?\s*\()([0-9]+(?:\.[0-9]+)*[a-z]?)[）)]', body, re.I)
        if any(ref not in labels for ref in refs):
            raise ValueError('Dangling equation reference')
        with zipfile.ZipFile(docx) as package:
            root = ET.fromstring(package.read('word/document.xml'))
            docbody = root.find('w:body', NS)
            if docbody is None:
                raise ValueError('DOCX body missing')
            elements = list(docbody); stop = len(elements)
            if plan['docx_body_end_heading']:
                matches = [i for i, el in enumerate(elements) if el.tag == f'{{{W}}}p' and ''.join(n.text or '' for n in el.iter() if n.tag in (f'{{{W}}}t', f'{{{M}}}t')).strip() == plan['docx_body_end_heading']]
                if len(matches) != 1:
                    raise ValueError('DOCX body-end paragraph must match exactly once')
                stop = matches[0]
            front = elements[:stop]
            math_paragraphs = [p for el in front for p in ([el] if el.tag == f'{{{W}}}p' else list(el.iter(f'{{{W}}}p'))) if p.find(f'{{{M}}}oMathPara') is not None or (p.find(f'{{{M}}}oMath') is not None and re.fullmatch(r'\s*\([^()]+\)\s*', ''.join(t.text or '' for t in p.iter(f'{{{W}}}t'))))]
            visible_labels = []
            for p in math_paragraphs:
                tx = ''.join(t.text or '' for t in p.iter(f'{{{W}}}t')).strip()
                if tx:
                    if not re.fullmatch(r'\([^()]+\)', tx):
                        raise ValueError('Unexpected text beside native display math')
                    visible_labels.append(tx[1:-1])
            if len(math_paragraphs) != len(displays) or visible_labels != labels:
                raise ValueError('Native display count or visible equation labels differ from source')
            fronttext = '\n'.join(''.join(t.text or '' for t in el.iter(f'{{{W}}}t')) for el in front)
            if re.search(r'\\(?:tag|frac|begin|boldsymbol|hat)\b|\$\$', fronttext):
                raise ValueError('Unrendered LaTeX in DOCX narrative')
            if re.search(r'(?<!\\)\$[^$\n]+\$', fronttext):
                raise ValueError('Unrendered inline dollar math in DOCX narrative')
            # Inspect only media referenced by body drawings, not unused ZIP members or appendix images.
            relationships = {}
            if 'word/_rels/document.xml.rels' in package.namelist():
                for rel in ET.fromstring(package.read('word/_rels/document.xml.rels')):
                    if rel.get('TargetMode') != 'External':
                        import posixpath
                        target = rel.get('Target', '')
                        relationships[rel.get('Id')] = target.lstrip('/') if target.startswith('/') else posixpath.normpath('word/'+target)
            embedded = set()
            for el in front:
                for blip in el.iter(f'{{{A}}}blip'):
                    name = relationships.get(blip.get(f'{{{R}}}embed'))
                    if name: embedded.add(hashlib.sha256(package.read(name)).hexdigest())
            figures = re.findall(r'!\[[^\]]*\]\(\s*<?([^)>]+)>?\s*\)', body)
            if len(figures) != len(re.findall(r'!\[', body)):
                raise ValueError('Unsupported Markdown image syntax; use inline local image paths')
            for value in figures:
                p = (source.parent/value).resolve()
                if not p.is_relative_to(case) or not p.is_file() or sha256_file(p).lower() not in embedded:
                    raise ValueError(f'Body figure missing, outside case, or stale in DOCX: {value}')
        report['checks']['equations'] = {'display_blocks': len(displays), 'visible_labels': labels, 'references': refs}
        report['checks']['body_figures'] = len(figures)
        used_blocks = set()
        for item in plan['appendix_sources']:
            start, end = heading_region(text, item['heading'])
            candidates = [(a,b,payload) for a,b,payload in codeblocks if start < a < b < end]
            if start < boundary or len(candidates) != 1:
                raise ValueError(f'Appendix heading must contain exactly one fenced source: {item["heading"]}')
            a,b,payload = candidates[0]
            if a in used_blocks:
                raise ValueError('One appendix block reused by multiple sources')
            used_blocks.add(a)
            p = resolve_inside(case, item['path'], 'appendix source')
            if p.read_text(encoding='utf-8-sig').strip('\n') != payload:
                raise ValueError(f'Appendix differs from actual source: {item["path"]}')
        # No undeclared appendix block may silently escape equality checks.
        if used_blocks != {a for a,b,payload in codeblocks if a > boundary}:
            raise ValueError('Unmapped fenced block in source appendix')
        report['checks']['appendix_sources'] = len(used_blocks)
        if plan['support_manifest']:
            manifest = resolve_inside(case, plan['support_manifest'], 'support manifest')
            data = json.loads(manifest.read_text(encoding='utf-8-sig'))
            entries = data.get('files'); seen = set()
            if not isinstance(entries, list) or not entries:
                raise ValueError('Support manifest requires nonempty files')
            for item in entries:
                p = resolve_inside(case, item['path'], 'support member')
                if p == manifest or p in seen:
                    raise ValueError('Duplicate or self-referential support member')
                seen.add(p)
                if p.stat().st_size != item['bytes'] or sha256_file(p).lower() != item['sha256'].lower():
                    raise ValueError(f'Stale support manifest entry: {item["path"]}')
            if any(resolve_inside(case, x['path'], 'appendix') not in seen for x in plan['appendix_sources']):
                raise ValueError('Appendix source omitted from support manifest')
            report['checks']['support_members'] = len(seen)
        else:
            report['checks']['support_members'] = 'not_requested; not a support-package pass'
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ET.ParseError, zipfile.BadZipFile) as exc:
        report['errors'].append(str(exc))
    report['passed'] = not report['errors']
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-dir', type=Path, required=True)
    parser.add_argument('--source', default='paper/full-paper.md')
    parser.add_argument('--docx', default='paper/paper.docx')
    parser.add_argument('--plan', default='paper/integration-plan.json')
    args = parser.parse_args(); case = args.case_dir.resolve()
    try:
        plan = json.loads(resolve_inside(case, args.plan, 'plan').read_text(encoding='utf-8-sig'))
        report = audit_integration(case, resolve_inside(case, args.source, 'source'), resolve_inside(case, args.docx, 'docx'), plan)
    except (OSError, ValueError) as exc:
        report = {'passed': False, 'errors': [str(exc)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
