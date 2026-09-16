"""Synthetic OOXML tests; not visual or mathematical review."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
S=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(S/'scripts'))
import audit_paper_integration as gate
import audit_paper_closeout as closeout

def put(p,value):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.case=Path(self.temp.name);(self.case/'paper').mkdir();(self.case/'src').mkdir()
        self.source=self.case/'paper/full-paper.md';self.docx=self.case/'paper/paper.docx'
        self.plan=dict(schema_version=1,status='reviewed',body_end_heading='',docx_body_end_heading='',equation_numbering='consecutive',appendix_sources=[],support_manifest='')
        self.make()
    def make(self,labels=('1',),unnumbered=0,sources=0,figure=False,image=b'new'):
        self.plan['appendix_sources']=[];self.plan['support_manifest']=''
        self.plan['body_end_heading']=self.plan['docx_body_end_heading']='Sources' if sources else ''
        md='# Method\n';paragraphs=[]
        for label in [*labels,*([None]*unnumbered)]:
            tag=('\\tag{'+label+'}') if label else ''
            md+='$$\nx=1'+tag+'\n$$\n'
            tx='<w:r><w:t>('+label+')</w:t></w:r>' if label else ''
            paragraphs.append('<w:p><m:oMathPara><m:oMath><m:r><m:t>x=1</m:t></m:r></m:oMath></m:oMathPara>'+tx+'</w:p>')
        if labels:md+='由式（'+labels[0]+'）得到结果。\n'
        if figure:
            (self.case/'paper/figure.png').write_bytes(b'new');md+='![Evidence](figure.png)\n'
            paragraphs.append('<w:p><w:r><w:drawing><a:blip r:embed="image1"/></w:drawing></w:r></w:p>')
        if sources:
            md+='## Sources\n';paragraphs.append('<w:p>\n<w:r><w:t>Sources</w:t></w:r>\n</w:p>')
            for i in range(sources):
                name=f'src/code{i}.py';content=f'print({i})\n';heading=f'S.{i+1} code{i}'
                (self.case/name).write_text(content,encoding='utf-8')
                self.plan['appendix_sources'].append(dict(path=name,heading=heading))
                md+='### '+heading+'\n'+chr(96)*3+'python\n'+content+chr(96)*3+'\n'
        self.source.write_text(md,encoding='utf-8')
        xml=f'<w:document xmlns:w="{gate.W}" xmlns:m="{gate.M}" xmlns:a="{gate.A}" xmlns:r="{gate.R}"><w:body>'+''.join(paragraphs)+'</w:body></w:document>'
        with zipfile.ZipFile(self.docx,'w') as z:
            z.writestr('word/document.xml',xml)
            if figure:
                z.writestr('word/_rels/document.xml.rels','<Relationships><Relationship Id="image1" Target="media/used.png"/></Relationships>')
                z.writestr('word/media/used.png',image);z.writestr('word/media/unused.png',b'new')
    def source_change(self,f):self.source.write_text(f(self.source.read_text(encoding='utf-8')),encoding='utf-8')
    def xml_change(self,f):
        with zipfile.ZipFile(self.docx) as z:entries={n:z.read(n) for n in z.namelist()}
        entries['word/document.xml']=f(entries['word/document.xml'].decode()).encode()
        with zipfile.ZipFile(self.docx,'w') as z:
            for n,b in entries.items():z.writestr(n,b)
    def audit(self):return gate.audit_integration(self.case,self.source,self.docx,self.plan)
    def test_dynamic_sizes(self):
        for n in (0,1,3,7):
            with self.subTest(n=n):
                self.make(tuple(str(i+1) for i in range(n)),unnumbered=2,sources=n)
                r=self.audit();self.assertTrue(r['passed'],r);self.assertEqual(r['checks']['equations']['display_blocks'],n+2)
                self.assertFalse(r['semantic_correctness_proven'])
    def test_explicit(self):
        self.make(('3.1','3.4'));self.plan['equation_numbering']='explicit';self.assertTrue(self.audit()['passed'])
    def test_wrong_numbers(self):
        for labels in [('1','1'),('1','3'),('2','1')]:
            self.make(labels);self.assertFalse(self.audit()['passed'])
        self.make();self.source_change(lambda t:t+'式（99）');self.assertFalse(self.audit()['passed'])
    def test_docx_drift(self):
        self.xml_change(lambda t:t.replace('(1)','(2)'));self.assertFalse(self.audit()['passed'])
        self.make();self.xml_change(lambda t:t.replace('m:oMathPara','m:wrong'));self.assertFalse(self.audit()['passed'])
    def test_used_image(self):
        self.make(figure=True);self.assertTrue(self.audit()['passed'])
        self.make(figure=True,image=b'stale');self.assertFalse(self.audit()['passed'])
    def test_appendix_drift_unmapped(self):
        self.make(sources=2);(self.case/'src/code1.py').write_text('changed');self.assertFalse(self.audit()['passed'])
        self.make(sources=2);self.plan['appendix_sources'].pop();self.assertFalse(self.audit()['passed'])

    def test_unrendered(self):
        for text in ['$x$',r'\frac{1}{2}']:
            self.make();self.xml_change(lambda t:t.replace('</w:body>','<w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body>'))
            self.assertFalse(self.audit()['passed'])
    def test_unsupported_unbalanced(self):
        for text in [r'\begin{align}x\end{align}',r'\eqref{x}',r'\[x','$$\nx',chr(96)*3+'python\npass','![x][figure]']:
            self.make();self.source_change(lambda t:t+'\n'+text);self.assertFalse(self.audit()['passed'],text)
    def test_fenced_tags_excluded(self):
        self.source_change(lambda t:t+'\n'+chr(96)*3+'tex\n'+r'\tag{99}'+'\n'+chr(96)*3+'\n');self.assertTrue(self.audit()['passed'])
    def test_path_heading_duplicate(self):
        self.make(sources=1);original=copy.deepcopy(self.plan)
        for path in ['../escaped.py','src/missing.py']:
            self.plan=copy.deepcopy(original);self.plan['appendix_sources'][0]['path']=path;self.assertFalse(self.audit()['passed'])
        self.plan=copy.deepcopy(original);self.plan['appendix_sources']*=2;self.assertFalse(self.audit()['passed'])
        self.plan=copy.deepcopy(original);self.plan['appendix_sources'][0]['heading']='missing';self.assertFalse(self.audit()['passed'])
    def test_manifest(self):
        self.make(sources=2);self.plan['support_manifest']='support.json'
        entries=[dict(path=i['path'],bytes=(self.case/i['path']).stat().st_size,sha256=gate.sha256_file(self.case/i['path'])) for i in self.plan['appendix_sources']]
        put(self.case/'support.json',dict(files=entries));self.assertTrue(self.audit()['passed'])
        for values in [entries[:1],entries+entries,entries+[dict(path='support.json',bytes=0,sha256='0'*64)],[dict(entries[0],bytes=99),entries[1]]]:
            put(self.case/'support.json',dict(files=values));self.assertFalse(self.audit()['passed'])
    def test_pending_native(self):
        self.plan['status']='pending';self.assertFalse(self.audit()['passed'])
        self.plan['status']='reviewed';self.source=self.source.with_suffix('.tex');self.source.write_text('x');self.assertFalse(self.audit()['passed'])
    def review(self):
        pdf=self.case/'paper/paper.pdf';pdf.write_bytes(b'synthetic')
        def binding(p):return dict(path=str(p.relative_to(self.case)),sha256=gate.sha256_file(p))
        record=dict(schema_version=1,status='reviewed',reviewer='synthetic fixture',reviewed_at='2026-09-10T00:00:00+08:00',artifacts={k:binding(p) for k,p in [('source',self.source),('docx',self.docx),('pdf',pdf)]},reviews={k:dict(status='reviewed',findings='Synthetic review tests binding only, not mathematical or human acceptance.',evidence=[binding(self.source)]) for k in closeout.CATEGORIES})
        return record,pdf,binding
    def test_closeout_required_pending_stale_valid(self):
        put(self.case/'case.json',dict(paper_integration_required=True));record,pdf,binding=self.review();review=self.case/'paper/closeout-review.json'
        def audit():
            put(review,record);return closeout.audit_closeout(self.case,review,self.docx,pdf)
        self.assertFalse(audit()['passed']);pp=self.case/'paper/integration-plan.json';put(pp,dict(self.plan,status='pending'))
        record['integration']={'plan':binding(pp)};self.assertFalse(audit()['passed'])
        put(pp,self.plan);self.assertFalse(audit()['passed'])
        record['integration']={'plan':binding(pp)};self.assertTrue(audit()['passed'],audit())
        self.xml_change(lambda t:t.replace('(1)','(7)'));record['artifacts']['docx']=binding(self.docx);self.assertFalse(audit()['passed'])
    def test_legacy_not_run(self):
        record,pdf,_=self.review();p=self.case/'paper/closeout-review.json';put(p,record)
        r=closeout.audit_closeout(self.case,p,self.docx,pdf);self.assertTrue(r['passed']);self.assertEqual(r['integration']['status'],'not_run_legacy')
    def test_scaffold_default_pending_preserve(self):
        dest=self.case/'new';cmd=[sys.executable,'-B',str(S/'scripts/scaffold_case.py'),'new','--root',str(self.case),'--profile','practice']
        r=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue(json.loads((dest/'case.json').read_text())['paper_integration_required'])
        p=dest/'paper/integration-plan.json';self.assertEqual(json.loads(p.read_text())['status'],'pending')
        self.assertTrue((dest/'paper/chapter-integration.md').is_file());p.write_text('user content')
        r=subprocess.run(cmd,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(p.read_text(),'user content')

    def test_bracket_and_mixed_displays(self):
        self.make(('1','2'))
        self.source_change(lambda t:t.replace('$$\nx=1\\tag{1}\n$$',r'\[x=1\tag{1}\]'))
        self.assertTrue(self.audit()['passed'],self.audit())
        for text in [r'\]x\[','$$x$$']:
            self.make();self.source_change(lambda t:t+'\n'+text);self.assertFalse(self.audit()['passed'])
    def test_finalizer_cannot_skip_required_integration(self):
        import argparse
        from unittest.mock import patch
        import finalize_case as finalizer
        record,pdf,binding=self.review();put(self.case/'paper/closeout-review.json',record)
        put(self.case/'case.json',dict(paper_integration_required=True))
        args=argparse.Namespace(case_dir=self.case,docx=self.docx,pdf=pdf,render_dir=self.case/'paper/rendered-pages',register=None,visual_review_record=None,submission_compliance=None,qa_register=None,report=None,page_size='any',orientation='any',forbid=[])
        mock={'ready':True,'reconciled':True,'passed':True,'structural_ok':True,'pdf':{'pages':1},'errors':[]}
        for missing in [False,True]:
            if missing:(self.case/'paper/closeout-review.json').unlink()
            with patch.object(finalizer,'run_json',return_value=(mock,[])),patch.object(finalizer,'check_visual_review',return_value={'status':'passed','errors':[]}):
                r,_,_=finalizer.run_finalization(args)
            self.assertFalse(r['ready_for_submission']);self.assertTrue(r['paper_closeout']['required'])
