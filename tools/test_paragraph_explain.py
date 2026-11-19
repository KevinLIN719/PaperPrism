import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import paragraph_explain as explain  # noqa: E402


class ExplainTests(unittest.TestCase):
    cfg={'base':'https://example.com','model':'test','key':'test'}
    sources=[{'idx':0,'page':1,'text':'We hypothesize that X is easier to optimize.'}]

    def test_scoped_revision_rechecked_and_wrong_english_removed(self):
        draft={'plain':'作者证明了X更易优化','background':'相关概念','expressions':[
            {'quote':'We hypothesize','meaning':'我们假设'}, {'quote':'We prove','meaning':'我们证明'}]}
        proof={'status':'支持','idx':0,'quote':'We hypothesize','evidence':[{'idx':0,'quote':'We hypothesize'}]}
        first={'plain':{**proof,'status':'部分支持','revision':'作者假设X更易优化'},'e0':proof}
        with patch.object(explain.llm,'chat',return_value=(json.dumps(draft),{'total_tokens':10})),patch.object(explain.summary_pipeline,'batch_review',side_effect=[(first,{'total_tokens':5}),({'plain':proof},{'total_tokens':5})]) as review:
            result=explain.complete(self.sources,self.cfg)
        self.assertEqual(result['plain'],'作者假设X更易优化')
        self.assertEqual(result['background'],'')
        self.assertEqual(result['expressions'],[draft['expressions'][0]])
        self.assertEqual(review.call_count,2)
        self.assertEqual(result['meta']['cost']['tokens'],20)

    def test_unsupported_plain_is_never_delivered(self):
        with patch.object(explain.llm,'chat',return_value=(json.dumps({'plain':'不可靠结论'}),{})),patch.object(explain.summary_pipeline,'batch_review',return_value=({},{})):
            with self.assertRaisesRegex(ValueError,'未通过'):
                explain.complete(self.sources,self.cfg)

    def test_plain_without_revision_gets_one_focused_review(self):
        draft={'plain':'作者假设X更容易优化。','background':'','expressions':[]}
        proof={'status':'支持','evidence':[{'idx':0,'quote':'We hypothesize'}]}
        with patch.object(explain.llm,'chat',return_value=(json.dumps(draft),{})), patch.object(explain.summary_pipeline,'batch_review',side_effect=[({'plain':{'status':'信息不足','revision':''}},{}),({'plain':proof},{})]) as review:
            result=explain.complete(self.sources,self.cfg)
        self.assertEqual(result['plain'],draft['plain'])
        self.assertEqual(review.call_count,2)
        self.assertEqual(review.call_args.args[0],[{'id':'plain','text':draft['plain']}])

    def test_cache_changes_with_source_and_model(self):
        key=explain.cache_key(self.sources,self.cfg)
        self.assertNotEqual(key,explain.cache_key(self.sources,{**self.cfg,'model':'other'}))
        self.assertNotEqual(key,explain.cache_key([{**self.sources[0],'text':'Changed'}],self.cfg))


if __name__ == '__main__':unittest.main()
