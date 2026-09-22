import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import docx_rewrite_safety as s

RAW = b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:w14="urn:test-w14" mc:Ignorable="w14"><w:body><w:p><w:pPr><w:jc w:val="both"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="24"/></w:rPr><w:t>Answer:</w:t></w:r><w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>old</w:t></w:r></w:p></w:body></w:document>'''


class RewriteSafetyTests(unittest.TestCase):
    def setUp(self):
        self.root = s.parse_document(RAW)
        self.p = self.root.find('.//'+s.W+'p')

    def edit(self, segments):
        return s.replace_plain_paragraph(self.p, expected_text='Answer:old', segments=segments)

    def test_normal_donor_does_not_spread_bold(self):
        out = self.edit([{'text':'new prose', 'style_from_run':1}])
        self.assertIsNone(out.find('.//'+s.W+'b'))
        self.assertEqual(out.find('.//'+s.W+'sz').get(s.W+'val'), '24')
        self.assertIsNotNone(out.find(s.W+'pPr'))
        self.assertEqual(''.join(self.p.itertext()), 'Answer:old')

    def test_emphasis_is_explicit_per_segment(self):
        out = self.edit([{'text':'Answer:', 'style_from_run':0}, {'text':' normal', 'style_from_run':1}])
        self.assertEqual(len(out.findall('.//'+s.W+'b')), 1)
        self.assertEqual(out.findall(s.W+'r')[1].find(s.W+'t').get(s.XML+'space'), 'preserve')

    def test_missing_invalid_donor_fails_without_mutation(self):
        before = s.ET.tostring(self.p)
        for segments in ([], [{'text':'x'}], [{'text':'x','style_from_run':True}], [{'text':'x','style_from_run':9}]):
            with self.subTest(segments=segments), self.assertRaises(ValueError): self.edit(segments)
        self.assertEqual(before, s.ET.tostring(self.p))

    def test_stale_text_rejected(self):
        with self.assertRaises(ValueError):
            s.replace_plain_paragraph(self.p, expected_text='different', segments=[{'text':'x','style_from_run':1}])

    def test_complex_objects_refused(self):
        for tag in ('hyperlink','bookmarkStart','ins'):
            self.setUp();s.ET.SubElement(self.p,s.W+tag)
            with self.assertRaises(ValueError): self.edit([{'text':'x','style_from_run':1}])
        for tag in ('fldChar','drawing','tab'):
            self.setUp();s.ET.SubElement(self.p.find(s.W+'r'),s.W+tag)
            with self.assertRaises(ValueError): self.edit([{'text':'x','style_from_run':1}])
        self.setUp();s.ET.SubElement(self.p,'{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath')
        with self.assertRaises(ValueError): self.edit([{'text':'x','style_from_run':1}])

    def test_prefixes_survive_roundtrip(self):
        out=s.parse_document(s.serialize_document(self.root))
        self.assertEqual(out.nsmap['w14'],'urn:test-w14')
        self.assertEqual(out.get(s.MC+'Ignorable'),'w14')

    def test_elementtree_prefix_loss_reproduces_failure(self):
        broken=ElementTree.tostring(ElementTree.fromstring(RAW))
        with self.assertRaisesRegex(ValueError,'unbound'): s.parse_document(broken)

    def test_other_compatibility_attributes_and_dtd(self):
        for attr,value in [('MustUnderstand','absent'),('PreserveElements','absent:item')]:
            self.setUp();self.root.set(s.MC+attr,value)
            with self.assertRaises(ValueError): s.serialize_document(self.root)
        self.setUp();n=s.ET.SubElement(self.root,s.MC+'Choice');n.set('Requires','absent')
        with self.assertRaises(ValueError): s.serialize_document(self.root)
        with self.assertRaises(ValueError): s.parse_document(b'<!DOCTYPE x>'+RAW)


if __name__ == '__main__': unittest.main()
