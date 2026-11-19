"""图表复核必须有来源、修正再核对、失败保留已通过部分且不泄露草稿。"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import figure_check as check  # noqa: E402


class FigureCheckTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {'base':'https://example.com','model':'test','key':'test'}
        self.sources = [{'idx':0,'page':1,'text':'X is 80%.'}]
        self.draft = dict.fromkeys(check.FIELDS,'草稿')
        self.image = 'data:image/png;base64,fake'
        self.proof = {'status':'支持','evidence':[{'kind':'image','bounds':[0,0,1,1],'detail':'纵轴Force(N)'}],
                      'reason':'与图相符','revision':''}
        grounding = patch.object(check,'ground_image',return_value=({'panels':[{'id':'A'}]},{}))
        grounding.start()
        self.addCleanup(grounding.stop)

    def test_image_alone_can_support_observation(self):
        raw = {'items':[{'id':'observations',**self.proof}]}
        with patch.object(check.llm,'chat',return_value=(json.dumps(raw),{})):
            result,_ = check.review({'observations':'纵轴是Force(N)'},[],self.image,self.cfg)
        self.assertEqual(result['observations']['status'],'支持')

    def test_invalid_text_or_image_cannot_be_support(self):
        for bad in ({'kind':'text','idx':0,'quote':'X is 90%'},
                    {'kind':'text','idx':99,'quote':'X is 80%'},
                    {'kind':'image','bounds':[0,0,2,1],'detail':'数值'},
                    {'kind':'image','bounds':[0,0,1,1],'detail':''}):
            raw = {'items':[{'id':'claim',**self.proof,'evidence':[bad]}]}
            with patch.object(check.llm,'chat',return_value=(json.dumps(raw),{})):
                result,_ = check.review({'claim':'数值'},self.sources,self.image,self.cfg)
            self.assertEqual(result['claim']['status'],'信息不足')

    def test_revisions_are_rechecked_and_usage_combined(self):
        first = {k:dict(self.proof) for k in check.FIELDS}
        first['claim'] = {**self.proof,'status':'部分支持','revision':'收窄后的主张'}
        with patch.object(check,'review',side_effect=[(first,{'total_tokens':10}),({'claim':self.proof},{'total_tokens':20})]) as review:
            output,meta,usage = check.complete(self.draft,self.sources,self.image,self.cfg)
        self.assertEqual(review.call_count,2)
        self.assertEqual(review.call_args.args[0],{'claim':'收窄后的主张'})
        self.assertEqual(output['claim'],'收窄后的主张')
        self.assertEqual(meta['status'],'corrected')
        self.assertEqual(usage['total_tokens'],30)
        self.assertNotIn('data:image',json.dumps(meta))

    def test_second_failure_keeps_approved_and_hides_wrong_revision(self):
        first = {'observations':self.proof,'claim':{**self.proof,'status':'不支持','revision':'错误修正'}}
        with patch.object(check,'review',side_effect=[(first,{}),check.ReviewError('offline',{'total_tokens':4})]):
            output,meta,usage = check.complete(self.draft,self.sources,self.image,self.cfg)
        self.assertEqual(output['observations'],'草稿')
        self.assertNotIn('错误修正',str(output))
        self.assertNotEqual(output['claim'],'草稿')
        self.assertEqual(meta['kept'],1)
        self.assertEqual(meta['status'],'partial')
        self.assertEqual(usage['total_tokens'],4)

    def test_missing_items_do_not_pass_and_unsupported_citations_removed(self):
        self.draft['sources'] = [0,99]
        with patch.object(check,'review',return_value=({'observations':self.proof},{})):
            output,meta,_ = check.complete(self.draft,self.sources,self.image,self.cfg)
        self.assertEqual(output['sources'],[])
        self.assertEqual(meta['kept'],1)

    def test_truncated_review_is_clear_failure_with_usage(self):
        with patch.object(check.llm,'chat',return_value=('{}',{'finish_reason':'length','total_tokens':7})):
            output,meta,usage = check.complete(self.draft,self.sources,self.image,self.cfg)
        self.assertEqual(meta['status'],'unavailable')
        self.assertNotIn('草稿',str(output))
        self.assertEqual(usage['total_tokens'],7)

    def test_extremum_cannot_contradict_read_values(self):
        text = '柱值依次为9、17、6 N，其中立方体最高。'
        audit = [{'assertion':'立方体最高','operator':'max','claimed_label':'立方体',
                  'values':[{'label':'立方体','value':9},{'label':'管','value':17},{'label':'环','value':6}]}]
        valid,fixed = check.check_extrema(text,audit)
        self.assertFalse(valid)
        self.assertEqual(fixed,'柱值依次为9、17、6 N，其中管最高。')
        self.assertEqual(check.check_extrema(fixed,[{**audit[0],'assertion':'管最高','claimed_label':'管'}]),(True,''))
        self.assertFalse(check.check_extrema(text,[])[0])
        self.assertFalse(check.check_extrema('立方体最高，管最低。',audit)[0])

    def test_unambiguous_short_object_name_is_not_rejected(self):
        audit = [{'assertion':'钥匙环最低','operator':'min','claimed_label':'钥匙环',
                  'values':[{'label':'钢钥匙环','value':2},{'label':'钢管','value':17}]}]
        self.assertEqual(check.check_extrema('钥匙环最低。',audit),(True,''))

    def test_full_caption_quote_can_match_without_truncating_or_changing_numbers(self):
        source = ('An experimental condition. '*40)+'Force 80 N.'
        raw = {'items':[{'id':'claim',**self.proof,'evidence':[{'kind':'text','idx':0,'quote':source}]}]}
        with patch.object(check.llm,'chat',return_value=(json.dumps(raw),{})):
            result,_ = check.review({'claim':'夹持力为80 N'},[{'idx':0,'text':source}],self.image,self.cfg)
        self.assertEqual(result['claim']['status'],'支持')
        raw['items'][0]['evidence'][0]['quote'] = source.replace('80 N','90 N')
        with patch.object(check.llm,'chat',return_value=(json.dumps(raw),{})):
            result,_ = check.review({'claim':'夹持力为90 N'},[{'idx':0,'text':source}],self.image,self.cfg)
        self.assertEqual(result['claim']['status'],'信息不足')

    def test_rejected_observation_uses_independent_values_only_after_recheck(self):
        facts = {'panels':[{'id':'C','metric':'夹持力','unit':'N',
                            'rows':[{'label':'钢管','value':17},{'label':'钢立方体','value':9}]}]}
        self.draft['observations'] = '错误的极值主张'
        with patch.object(check,'ground_image',return_value=(facts,{})),patch.object(check,'review',side_effect=[({},{}),({'observations':self.proof},{})]) as review:
            output,meta,_ = check.complete(self.draft,self.sources,self.image,self.cfg)
        candidate = review.call_args.args[0]['observations']
        self.assertIn('钢管为17N',candidate)
        self.assertNotIn('最高',candidate)
        self.assertEqual(output['observations'],candidate)
        self.assertEqual(meta['status'],'partial')
        self.assertNotIn('错误的极值',str(output))


if __name__ == '__main__':
    unittest.main()
