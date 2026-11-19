"""追问来源必须与当次输入及回答实际引用一致。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import llm  # noqa: E402
import store  # noqa: E402


class AskEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.parsed={'paras':[{'i':i,'kind':'body','page':i+1,'text':'Paragraph %d '%i+'x'*4000} for i in range(4)]}
        self.cfg={'base':'https://example.com','model':'test','key':'test'}

    def test_fallback_materials_are_recorded_but_not_all_cited(self):
        with patch.object(llm,'retrieve',return_value=[]),patch.object(llm,'chat',return_value=('结论 [#1]，另见 [#99]',{})),patch.object(llm,'config',return_value=self.cfg):
            result=llm.ask(self.parsed,'中文问题')
        self.assertEqual(result['used'],[0,1,2])
        self.assertEqual(result['cited'],[1])
        self.assertEqual(result['unverified_citations'],[99])
        self.assertTrue(all(s['truncated'] and len(s['text'])==3500 for s in result['sources']))

    def test_existing_but_not_provided_paragraph_not_verified(self):
        with patch.object(llm,'retrieve',return_value=[1]),patch.object(llm,'chat',return_value=('答案 [#3]',{})),patch.object(llm,'config',return_value=self.cfg):
            result=llm.ask(self.parsed,'question',idx=0)
        self.assertEqual(result['used'],[0,1])
        self.assertEqual(result['cited'],[])
        self.assertEqual(result['unverified_citations'],[3])

    def test_english_query_terms_find_materials_instead_of_summary(self):
        parsed={'paras':[{'kind':'body','text':'SMP grippers can move objects.'},
                         {'kind':'body','text':'SMP shape recovery permits release.'},
                         {'kind':'body','text':'Synthesis: epoxy monomer and curing agent are mixed.'}]}
        self.assertEqual(llm.retrieve(parsed,'composition synthesis monomer curing agent',k=1),[2])

    def test_chinese_intent_survives_generic_rewrite(self):
        with patch.object(llm,'chat',return_value=(' {"terms":["SMP"]}',{})),patch.object(llm,'config',return_value=self.cfg):
            query,_=llm.search_query(self.parsed,'SMP的组成原料')
        self.assertIn('synthesis',query)
        self.assertIn('monomer',query)
        with patch.object(llm,'chat',side_effect=RuntimeError('offline')),patch.object(llm,'config',return_value=self.cfg):
            query,_=llm.search_query(self.parsed,'SMP的组成原料')
        self.assertIn('synthesis',query)

    def test_snapshots_survive_history_reload(self):
        record={'id':'q1','a':'Answer [#0]','used':[0,1],'citation_version':1,
                'sources':[{'idx':0,'page':1,'text':'original snapshot','truncated':False}], 'cited':[0]}
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'STORE_DIR',tmp):
            store.merge('a'*64,{'ask':record})
            self.assertEqual(store.load('a'*64)['asks'][0],record)

    def test_empty_answer_not_saved_as_normal_response(self):
        with patch.object(llm,'retrieve',return_value=[]),patch.object(llm,'chat',return_value=(' ',{})),patch.object(llm,'config',return_value=self.cfg):
            with self.assertRaisesRegex(ValueError,'完整回答'):llm.ask(self.parsed,'question')


if __name__=='__main__':unittest.main()
