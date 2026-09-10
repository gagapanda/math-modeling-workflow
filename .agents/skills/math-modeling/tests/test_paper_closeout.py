from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S / 'scripts'))
import audit_paper_closeout as gate
import finalize_case as finalizer


def put(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CloseoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.case = Path(self.temp.name)
        (self.case/'paper/rendered-pages').mkdir(parents=True)
        for name, text in [('full-paper.md','# 问题一\n合理假设与公式推导；相关性不代表因果。'), ('paper.docx','docx-test'), ('paper.pdf','pdf-test'), ('evidence.md','Test-only detailed review evidence, not an actual scientific or human review.')]:
            (self.case/'paper'/name).write_text(text,encoding='utf-8')
        self.review = self.case/'paper/closeout-review.json'
        self.data = {'schema_version':1,'status':'reviewed','reviewer':'test-only AI fixture','reviewed_at':'2026-09-09T12:00:00+08:00','artifacts':{key:self.binding('paper/'+name) for key,name in [('source','full-paper.md'),('docx','paper.docx'),('pdf','paper.pdf')]},'reviews':{key:{'status':'reviewed','findings':'TEST ONLY: reviewed source-specific evidence and identified limits; not a real human approval.', 'evidence':[self.binding('paper/evidence.md')]} for key in gate.CATEGORIES}}
        put(self.review,self.data)

    def binding(self,name):
        return {'path':name,'sha256':digest(self.case/name)}

    def audit(self):
        return gate.audit_closeout(self.case,self.review,self.case/'paper/paper.docx',self.case/'paper/paper.pdf')

    def test_fresh_bindings_pass_but_not_semantic_or_human_acceptance(self):
        r=self.audit(); self.assertTrue(r['passed'],r)
        self.assertFalse(r['human_acceptance']); self.assertFalse(r['semantic_correctness_proven'])

    def test_pending_cannot_pass(self):
        self.data['status']='pending';put(self.review,self.data);self.assertFalse(self.audit()['passed'])

    def test_missing_review_cannot_pass(self):
        self.review.unlink();self.assertFalse(self.audit()['passed'])

    def test_source_docx_pdf_and_evidence_drift_fail(self):
        for name in ['full-paper.md','paper.docx','paper.pdf','evidence.md']:
            with self.subTest(name=name):
                p=self.case/'paper'/name;original=p.read_bytes();p.write_bytes(original+b'changed')
                self.assertFalse(self.audit()['passed']);p.write_bytes(original)

    def test_presence_only_disclosure_and_reference_review_fail(self):
        for category in gate.CATEGORIES:
            with self.subTest(category=category):
                original=self.data['reviews'][category]['findings']
                self.data['reviews'][category]['findings']='PDF exists';put(self.review,self.data)
                self.assertFalse(self.audit()['passed'])
                self.data['reviews'][category]['findings']=original

    def test_missing_evidence_and_placeholder_fail(self):
        self.data['reviews']['references']['evidence']=[];put(self.review,self.data)
        self.assertFalse(self.audit()['passed'])
        self.data['reviews']['references']['evidence']=[self.binding('paper/evidence.md')]
        self.data['reviews']['references']['findings']='TODO '*20;put(self.review,self.data)
        self.assertFalse(self.audit()['passed'])

    def test_wrong_output_and_path_escape_fail(self):
        self.data['artifacts']['pdf']=self.binding('paper/paper.docx');put(self.review,self.data)
        self.assertFalse(self.audit()['passed'])
        self.data['artifacts']['source']['path']='../outside.md';put(self.review,self.data)
        self.assertFalse(self.audit()['passed'])

    def test_narrative_cleanup_is_scoped_not_global_token_waiver(self):
        text='# 附录\n本轮修复完成\n```python\nprint("本轮修复")\n```\n局限：非随机观察不证明因果\n'
        self.assertEqual([x['line'] for x in gate.source_hygiene(text)],[2])
        self.assertEqual(gate.source_hygiene('```python\n# 旧视觉记录\n```\n保留AI披露和限制'),[])
        with self.assertRaises(ValueError):gate.source_hygiene('```python\nno closing fence')

    def test_finalizer_pending_and_deleted_required_record_block(self):
        put(self.case/'case.json',{'paper_closeout_required':True})
        args=argparse.Namespace(case_dir=self.case,docx=self.case/'paper/paper.docx',pdf=self.case/'paper/paper.pdf',render_dir=self.case/'paper/rendered-pages',register=None,visual_review_record=None,submission_compliance=None,qa_register=None,report=None,page_size='any',orientation='any',forbid=[])
        mock_report={'ready':True,'reconciled':True,'passed':True,'structural_ok':True,'pdf':{'pages':1},'errors':[]}
        for deleted in [False,True]:
            with self.subTest(deleted=deleted):
                if deleted:self.review.unlink()
                else:self.data['status']='pending';put(self.review,self.data)
                with patch.object(finalizer,'run_json',return_value=(mock_report,[])),patch.object(finalizer,'check_visual_review',return_value={'status':'passed','errors':[]}):
                    r,_,_=finalizer.run_finalization(args)
                self.assertFalse(r['ready_for_submission']);self.assertTrue(r['paper_closeout']['required'])
                self.assertFalse(r['paper_closeout']['passed'])

    def test_finalizer_accepts_bound_review_and_marks_legacy_not_run(self):
        args=argparse.Namespace(case_dir=self.case,docx=self.case/'paper/paper.docx',pdf=self.case/'paper/paper.pdf',render_dir=self.case/'paper/rendered-pages',register=None,visual_review_record=None,submission_compliance=None,qa_register=None,report=None,page_size='any',orientation='any',forbid=[])
        mock_report={'ready':True,'reconciled':True,'passed':True,'structural_ok':True,'pdf':{'pages':1},'errors':[]}
        for legacy in [False,True]:
            with self.subTest(legacy=legacy):
                if legacy:self.review.unlink()
                with patch.object(finalizer,'run_json',return_value=(mock_report,[])),patch.object(finalizer,'check_visual_review',return_value={'status':'passed','errors':[]}):
                    r,_,_=finalizer.run_finalization(args)
                self.assertTrue(r['ready_for_submission'],r)
                self.assertEqual(r['paper_closeout']['required'],not legacy)
                if legacy:self.assertEqual(r['paper_closeout']['scope'],'not_run_or_not_required')

    def run_mocked_finalizer(self):
        # These fixtures isolate closeout integration, not the numerical/visual gates.
        args=argparse.Namespace(case_dir=self.case,docx=self.case/'paper/paper.docx',pdf=self.case/'paper/paper.pdf',render_dir=self.case/'paper/rendered-pages',register=None,visual_review_record=None,submission_compliance=None,qa_register=None,report=None,page_size='any',orientation='any',forbid=[])
        other={'ready':True,'reconciled':True,'passed':True,'structural_ok':True,'pdf':{'pages':1},'errors':[]}
        with patch.object(finalizer,'run_json',return_value=(other,[])),patch.object(finalizer,'check_visual_review',return_value={'status':'passed','errors':[]}):
            return finalizer.run_finalization(args)

    def test_qa_write_invalidates_bound_evidence_and_persisted_pass(self):
        qa=self.case/'paper/qa-register.md'
        qa.write_text('TEST ONLY: completed reference review with explicit boundaries.',encoding='utf-8')
        self.data['reviews']['references']['evidence']=[self.binding('paper/qa-register.md')]
        put(self.review,self.data)
        r,path,_=self.run_mocked_finalizer()
        self.assertFalse(r['ready_for_submission'])
        self.assertFalse(r['paper_closeout']['passed'])
        self.assertFalse(json.loads(path.read_text(encoding='utf-8'))['ready_for_submission'])
        self.assertTrue(any('changed while' in e for e in r['paper_closeout']['errors']))

    def test_replacing_review_during_report_write_cannot_preserve_pass(self):
        original=finalizer.update_qa_register
        def update(*args,**kwargs):
            original(*args,**kwargs)
            self.data['reviewed_at']='2026-09-09T13:00:00+08:00'
            put(self.review,self.data)
        with patch.object(finalizer,'update_qa_register',side_effect=update):
            r,path,_=self.run_mocked_finalizer()
        self.assertFalse(r['ready_for_submission'])
        self.assertFalse(json.loads(path.read_text(encoding='utf-8'))['ready_for_submission'])

    def test_source_drift_during_report_write_cannot_preserve_pass(self):
        original=finalizer.update_qa_register
        def update(*args,**kwargs):
            original(*args,**kwargs)
            (self.case/'paper/full-paper.md').write_text('Changed scientific conclusions.',encoding='utf-8')
        with patch.object(finalizer,'update_qa_register',side_effect=update):
            r,path,_=self.run_mocked_finalizer()
        self.assertFalse(r['ready_for_submission'])
        self.assertFalse(json.loads(path.read_text(encoding='utf-8'))['paper_closeout']['passed'])

    def test_explicit_contact_sheet_cannot_prove_full_page_review(self):
        record={'schema_version':1,'status':'passed','reviewed_at':'2026-09-09T12:00:00+08:00','reviewer':'test AI','pdf_sha256':digest(self.case/'paper/paper.pdf'),'page_count':1,'reviewed_pages':[1],'rendered_pages_sha256':{'page-1.png':'a'*64},'notes':'Test evidence','inspection_scope':'contact_sheet_only'}
        path=self.case/'paper/visual.json';put(path,record)
        r=finalizer.check_visual_review(path,self.case/'paper/paper.pdf',1,{'page-1.png':'a'*64})
        self.assertNotEqual(r['status'],'passed');self.assertTrue(any('contact sheets' in x for x in r['errors']))

    def package(self):
        path=self.case/'support.zip';manifest=self.case/'inventory.json';f=self.case/'paper/evidence.md'
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:z.write(f,'evidence.md')
        record={'schema_version':1,'package_sha256':digest(path),'files':[{'path':'evidence.md','source':'paper/evidence.md','bytes':f.stat().st_size,'sha256':digest(f)}]}
        put(manifest,record);return path,manifest,record

    def test_exact_archive_roundtrip(self):
        p,m,_=self.package();r=gate.audit_archive(self.case,p,m)
        self.assertTrue(r['passed'],r);self.assertEqual(r['files_verified'],1);self.assertFalse(r['replay_proven'])

    def test_stale_report_after_packaging_is_rejected(self):
        p,m,_=self.package();(self.case/'paper/evidence.md').write_text('changed report',encoding='utf-8')
        self.assertFalse(gate.audit_archive(self.case,p,m)['passed'])

    def test_payload_tampering_even_with_updated_zip_hash(self):
        p,m,r=self.package();n=r['files'][0]['bytes']
        with zipfile.ZipFile(p,'w') as z:z.writestr('evidence.md',b'X'*n)
        r['package_sha256']=digest(p);put(m,r)
        self.assertFalse(gate.audit_archive(self.case,p,m)['passed'])

    def test_unlisted_and_duplicate_entries_fail(self):
        for name in ['extra.txt','evidence.md','EVIDENCE.MD']:
            with self.subTest(name=name):
                p,m,r=self.package()
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore',UserWarning)
                    with zipfile.ZipFile(p,'a') as z:z.writestr(name,'injected')
                r['package_sha256']=digest(p);put(m,r)
                self.assertFalse(gate.audit_archive(self.case,p,m)['passed'])

    def test_missing_member_size_and_unsafe_manifest_fail(self):
        p,m,r=self.package()
        for field,value in [('path','../escape'),('path','C:/escape'),('path','x\\y'),('path','./x'),('bytes',1),('source','../escape')]:
            with self.subTest(field=field,value=value):
                p,m,r=self.package();r['files'][0][field]=value;put(m,r)
                self.assertFalse(gate.audit_archive(self.case,p,m)['passed'])
        p,m,r=self.package()
        with zipfile.ZipFile(p,'w'):pass
        r['package_sha256']=digest(p);put(m,r)
        self.assertFalse(gate.audit_archive(self.case,p,m)['passed'])

    def test_new_scaffolds_default_pending_and_explore_exempt(self):
        for profile in ['practice','submission','explore']:
            # CLI is exercised using the existing public --root and positional case contract.
            result=subprocess.run([sys.executable,str(S/'scripts/scaffold_case.py'),'closeout-'+profile,'--root',str(self.case),'--profile',profile],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stderr)
            case=self.case/('closeout-'+profile)
            meta=json.loads((case/'case.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['paper_closeout_required'],profile!='explore')
            self.assertEqual((case/'paper/closeout-review.json').exists(),profile!='explore')
            if profile!='explore':self.assertEqual(json.loads((case/'paper/closeout-review.json').read_text(encoding='utf-8'))['status'],'pending')


if __name__=='__main__':unittest.main()
