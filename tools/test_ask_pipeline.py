"""自动追问必须在展示前通过核对，失败不得泄露未经处理草稿。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ask_pipeline as pipeline  # noqa: E402


class PipelineTests(unittest.TestCase):
    cfg={'base':'https://example.com','model':'test','key':'test'}
    def draft(self,text):
        return {'answer':text,'used':[0],'sources':[{'idx':0,'page':1,'text':'X is 80%.'}],'meta':{'usage':{'total_tokens':10}}}
    def audit(self,record,status='支持',claim=None):
        return {'answer':record['a'],'ask_id':record['id'],'items':[{'claim':claim or record['a'],'status':status,'quote':'X is 80%.','idx':0,'reason':'test'}],
                'meta':{'usage':{'total_tokens':5},'model':'test'}}

    def test_supported_answer_delivered_and_usage_combined(self):
        with patch.object(pipeline.llm,'config',return_value=self.cfg),patch.object(pipeline.llm,'ask',return_value=self.draft('X为80%。')),patch.object(pipeline.ask_check,'review',side_effect=lambda r,c:self.audit(r)):
            result=pipeline.complete({},'question')
        self.assertEqual(result['answer'],'X为80%。')
        self.assertEqual(result['record']['auto_review'],'checked')
        self.assertEqual(result['meta']['usage']['total_tokens'],15)

    def test_wrong_answer_corrected_then_rechecked(self):
        def audit(record,cfg):return self.audit(record,'不支持' if '90' in record['a'] else '支持')
        with patch.object(pipeline.llm,'config',return_value=self.cfg),patch.object(pipeline.llm,'ask',return_value=self.draft('X为90%。')),patch.object(pipeline.ask_check,'review',side_effect=audit) as reviews,patch.object(pipeline.llm,'chat',return_value=('X为80%。',{'total_tokens':3})):
            result=pipeline.complete({},'question')
        self.assertEqual(result['answer'],'X为80%。')
        self.assertEqual(result['record']['auto_review'],'corrected')
        self.assertEqual(reviews.call_count,2)
        self.assertEqual(result['meta']['usage']['total_tokens'],23)

    def test_audit_failure_does_not_deliver_draft(self):
        with patch.object(pipeline.llm,'config',return_value=self.cfg),patch.object(pipeline.llm,'ask',return_value=self.draft('UNSAFE DRAFT')),patch.object(pipeline.ask_check,'review',side_effect=RuntimeError('offline')):
            result=pipeline.complete({},'question')
        self.assertNotIn('UNSAFE',result['answer'])
        self.assertEqual(result['record']['auto_review'],'unavailable')
        self.assertIsNone(result['review'])

    def test_supported_part_survives_failed_rewrite(self):
        def audit(record,cfg):
            return {'answer':record['a'],'items':[{'claim':'X为80%。','status':'支持','idx':0,'quote':'X is 80%.','reason':'matches'},
                                                   {'claim':'耗时2小时。','status':'信息不足','idx':None,'quote':'','reason':'missing'}],
                    'meta':{'usage':{},'model':'test'}}
        with patch.object(pipeline.llm,'config',return_value=self.cfg),patch.object(pipeline.llm,'ask',return_value=self.draft('X为80%。耗时2小时。')),patch.object(pipeline.ask_check,'review',side_effect=audit),patch.object(pipeline.llm,'chat',side_effect=RuntimeError('rewrite failed')):
            result=pipeline.complete({},'question')
        self.assertEqual(result['record']['auto_review'],'partial')
        self.assertIn('X为80%',result['answer'])
        self.assertNotIn('耗时2小时',result['answer'])

    def test_omitted_assertions_not_treated_as_fully_checked(self):
        record={'a':'X为80%。Y为90%。'}
        self.assertFalse(pipeline.fully_supported(record,{'items':[{'claim':'X为80%。','status':'支持'}]}))
        self.assertFalse(pipeline.fully_supported({'a':'不是80%。'},{'items':[{'claim':'是80%。','status':'支持'}]}))


if __name__=='__main__':unittest.main()
