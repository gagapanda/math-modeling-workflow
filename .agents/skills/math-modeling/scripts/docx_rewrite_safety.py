"""Narrow OOXML rewrite helpers; not a renderer, editor CLI or visual approval."""
from copy import deepcopy
from lxml import etree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
XML = '{http://www.w3.org/XML/1998/namespace}'


def validate_prefix_references(root):
    """Check namespace prefixes used as attribute VALUES (not just XML names)."""
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        for attr, value in node.attrib.items():
            local = attr[len(MC):] if attr.startswith(MC) else ''
            if local in ('Ignorable', 'MustUnderstand'):
                prefixes = value.split()
            elif local in ('ProcessContent', 'PreserveElements', 'PreserveAttributes'):
                prefixes = [v.split(':', 1)[0] for v in value.split() if ':' in v]
            elif node.tag == MC+'Choice' and attr == 'Requires':
                prefixes = value.split()
            else:
                continue
            for prefix in prefixes:
                if prefix != 'xml' and prefix not in node.nsmap:
                    raise ValueError('unbound compatibility prefix: '+prefix)


def parse_document(raw):
    parser = ET.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    root = ET.fromstring(raw, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError('DTD not supported')
    validate_prefix_references(root)
    return root


def serialize_document(root):
    validate_prefix_references(root)
    raw = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    parse_document(raw)
    return raw


def replace_plain_paragraph(paragraph, *, expected_text, segments):
    """Explicit style donor per new segment. Returns a copy, never edits input.

    segments = [{'text': '...', 'style_from_run': 1}, ...]. No default donor.
    Refuses math, fields, hyperlinks, revisions, bookmarks and other complex content.
    Donor includes inherited character style: caller must inspect effective appearance.
    """
    if paragraph.tag != W+'p':
        raise ValueError('expected paragraph')
    if any(n.tag not in (W+'pPr', W+'r') for n in paragraph):
        raise ValueError('complex paragraph requires a scoped editor')
    if len(paragraph.findall(W+'pPr')) > 1:
        raise ValueError('duplicate paragraph properties')
    runs = paragraph.findall(W+'r')
    for run in runs:
        if any(n.tag not in (W+'rPr', W+'t') for n in run):
            raise ValueError('complex run requires a scoped editor')
        if len(run.findall(W+'rPr')) > 1:
            raise ValueError('duplicate run properties')
    text = ''.join(n.text or '' for r in runs for n in r.findall(W+'t'))
    if text != expected_text:
        raise ValueError('stale paragraph text')
    if not isinstance(segments, list) or not segments:
        raise ValueError('explicit segments required')
    result = deepcopy(paragraph)
    for run in result.findall(W+'r'):
        result.remove(run)
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) != {'text', 'style_from_run'}:
            raise ValueError('explicit text and style donor required')
        index, value = segment['style_from_run'], segment['text']
        if type(index) is not int or not 0 <= index < len(runs) or not isinstance(value, str):
            raise ValueError('invalid segment or donor')
        run = ET.SubElement(result, W+'r')
        props = runs[index].find(W+'rPr')
        if props is not None:
            run.append(deepcopy(props))
        ET.SubElement(run, W+'t', {XML+'space': 'preserve'}).text = value
    return result
