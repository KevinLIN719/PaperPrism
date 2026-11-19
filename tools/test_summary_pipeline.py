"""自动摘要只交付原文复核通过的概括，修正必须再核对。"""
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import summary_pipeline as pipeline  # noqa: E402


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.parsed={'paras':[{'i':0,'page':1,'kind':'body','text':'X is 80% on A.','anchor':{'idx':0,'head':'X is'}}]}
        self.summary={'tl_dr':['X为80%。'],'claims':[{'idx':0,'claim':'所有任务均80%。','quote':'','evidence':'old','strength':'中'}],'why':'可参考','worth_reading':'值得精读','glossary':[]}
        self.cfg={'base':'https://example.com','model':'test','key':'test'}

    def test_revision_rechecked_before_delivery(self):
        first={'t0':{'status':'支持','idx':0,'quote':'X is 80%','reason':'match'},
               'c0':{'status':'部分支持','idx':0,'quote':'X is 80%','reason':'scope','revision':'A任务上X为80%。'}}
        second={'c0':{'status':'支持','idx':0,'quote':'X is 80%','reason':'narrow'}}
        with patch.object(pipeline.llm,'config',return_value=self.cfg),patch.object(pipeline.llm,'jump1',return_value=(self.summary,{'usage':{'total_tokens':10}})),patch.object(pipeline,'batch_review',side_effect=[(first,{'total_tokens':2}),(second,{'total_tokens':3})]) as check:
            result,meta=pipeline.complete(self.parsed)
        self.assertEqual(result['claims'][0]['claim'],'A任务上X为80%。')
        self.assertNotIn('所有任务',str(result))
        self.assertEqual(check.call_count,2)
        self.assertEqual(meta['usage']['total_tokens'],15)

    def test_mismatched_quote_cannot_pass_batch(self):
        rows=[{'id':'c0','text':'X is 90%'}]
        raw={'items':[{'id':'c0','status':'支持','idx':0,'quote':'X is 90%','reason':'wrong'}]}
        with patch.object(pipeline.llm,'chat',return_value=(json.dumps(raw),{})):
            result,_=pipeline.batch_review(rows,[{'idx':0,'text':'X is 80%'}],self.cfg)
        self.assertEqual(result['c0']['status'],'信息不足')
        self.assertEqual(result['c0']['quote'],'')

    def test_overview_revision_is_rechecked_and_keeps_original_order(self):
        self.summary['tl_dr']=['过强的问题概括','已支持的方法','已支持的结果']
        proof={'status':'支持','idx':0,'quote':'X is 80%','reason':'match'}
        first={'t0':{**proof,'status':'部分支持','revision':'有条件的问题概括'},
               't1':proof,'t2':proof}
        with patch.object(pipeline.llm,'config',return_value=self.cfg),patch.object(pipeline.llm,'jump1',return_value=(self.summary,{})),patch.object(pipeline,'batch_review',side_effect=[(first,{}),({'t0':proof},{})]) as check:
            result,_=pipeline.complete(self.parsed)
        self.assertEqual(check.call_args.args[0],[{'id':'t0','text':'有条件的问题概括'}])
        self.assertEqual(result['tl_dr'],['有条件的问题概括','已支持的方法','已支持的结果'])
        self.assertEqual(result['auto_review']['revised'],1)

    def test_missing_overview_gets_one_targeted_retry(self):
        proof={'status':'支持','idx':0,'quote':'X is 80%','reason':'match'}
        with patch.object(pipeline.llm,'config',return_value=self.cfg),patch.object(pipeline.llm,'jump1',return_value=(self.summary,{})),patch.object(pipeline,'batch_review',side_effect=[({},{}),({'t0':proof},{})]) as check:
            result,_=pipeline.complete(self.parsed)
        self.assertEqual(check.call_count,2)
        self.assertEqual(check.call_args.args[0],[{'id':'t0','text':'X为80%。'}])
        self.assertEqual(result['tl_dr'],['X为80%。'])

    def test_unconfirmed_overview_revision_is_not_delivered(self):
        first={'t0':{'status':'部分支持','revision':'仍然未经支持的修正'}}
        with patch.object(pipeline.llm,'config',return_value=self.cfg),patch.object(pipeline.llm,'jump1',return_value=(self.summary,{})),patch.object(pipeline,'batch_review',side_effect=[(first,{}),({}, {})]) as check:
            result,_=pipeline.complete(self.parsed)
        self.assertEqual(check.call_count,2)
        self.assertNotIn('仍然未经支持的修正',str(result))

    def test_confirmed_claims_provide_overview_when_tldr_not_passed(self):
        checked={'c0':{'status':'支持','idx':0,'quote':'X is 80%','reason':'match'}}
        with patch.object(pipeline.llm,'config',return_value=self.cfg),patch.object(pipeline.llm,'jump1',return_value=(self.summary,{})),patch.object(pipeline,'batch_review',return_value=(checked,{})):
            result,_=pipeline.complete(self.parsed)
        self.assertEqual(result['tl_dr'],[self.summary['claims'][0]['claim']])
        self.assertTrue(result['auto_review']['overview_from_claims'])

    def test_multi_paragraph_evidence_is_validated_individually(self):
        rows=[{'id':'t0','text':'X is 80% and Y is 70%'}]
        raw={'items':[{'id':'t0','status':'支持','evidence':[{'idx':0,'quote':'X is 80%'},{'idx':1,'quote':'Y is 70%'}]}]}
        with patch.object(pipeline.llm,'chat',return_value=(json.dumps(raw),{})):
            result,_=pipeline.batch_review(rows,[{'idx':0,'text':'X is 80%'},{'idx':1,'text':'Y is 70%'}],self.cfg)
        self.assertEqual(result['t0']['status'],'支持')
        self.assertEqual(len(result['t0']['evidence']),2)
        raw['items'][0]['evidence'][1]['quote']='Y is 90%'
        with patch.object(pipeline.llm,'chat',return_value=(json.dumps(raw),{})):
            result,_=pipeline.batch_review(rows,[{'idx':0,'text':'X is 80%'},{'idx':1,'text':'Y is 70%'}],self.cfg)
        self.assertEqual(result['t0']['status'],'信息不足')

    def test_old_failed_overview_repaired_without_model(self):
        old={'tl_dr':['本次未能从所选原文中确认足够的概括，请先查看原文与阅读路线。'],
             'claims':[{'claim':'已确认事实','support_review':{'status':'支持'}}]}
        with patch.object(pipeline.llm,'chat') as chat:
            fixed=pipeline.repair_cached_overview(old)
        self.assertEqual(fixed['tl_dr'],['已确认事实'])
        chat.assert_not_called()

    def test_small_deepseek_paper_uses_single_read_budget(self):
        cfg={'base':'https://api.deepseek.com/v1','model':'deepseek-chat','key':'test'}
        with patch.object(pipeline.llm,'config',return_value=cfg),patch.object(pipeline.llm,'jump1',return_value=(self.summary,{})) as generate,patch.object(pipeline,'batch_review',return_value=({},{})):
            pipeline.complete(self.parsed)
        self.assertEqual(generate.call_args.kwargs['budget_override'],60000)

    def test_failed_review_does_not_show_raw_summary(self):
        with patch.object(pipeline.llm,'config',return_value=self.cfg),patch.object(pipeline.llm,'jump1',return_value=(self.summary,{})),patch.object(pipeline,'batch_review',side_effect=RuntimeError('offline')):
            result,_=pipeline.complete(self.parsed)
        self.assertEqual(result['claims'],[])
        self.assertNotIn('所有任务',str(result))
        self.assertNotEqual(result['tl_dr'],self.summary['tl_dr'])


if __name__=='__main__':unittest.main()
