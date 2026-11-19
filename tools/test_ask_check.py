"""逐项追问核查不能编造答案句子或越过输入快照。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ask_check  # noqa: E402
import store  # noqa: E402


class AskCheckTests(unittest.TestCase):
    record={'id':'q1','a':'X准确率为80%。训练耗时为2小时。','citation_version':1,'sources':[{'idx':0,'page':1,'text':'X accuracy is 80%.'}]}

    def test_only_answer_phrases_and_matching_source(self):
        raw={'items':[
            {'claim':'X准确率为80%。','status':'支持','reason':'matching','idx':0,'quote':'X accuracy is 80%.'},
            {'claim':'训练耗时为2小时。','status':'支持','reason':'fabrication','idx':99,'quote':'two hours'},
            {'claim':'答案中没有这句话','status':'支持','reason':'invented','idx':0,'quote':'X accuracy is 80%.'}]}
        items=ask_check.validate_items(raw,self.record)
        self.assertEqual(len(items),2)
        self.assertEqual(items[0]['status'],'支持')
        self.assertEqual(items[1]['status'],'信息不足')
        self.assertIsNone(items[1]['idx'])

    def test_legacy_snapshot_does_not_trigger_model(self):
        with patch.object(ask_check.llm,'chat') as chat:
            with self.assertRaisesRegex(ValueError,'快照'):ask_check.review({'id':'old','a':'answer'})
            chat.assert_not_called()

    def test_delete_history_removes_its_reviews_only(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'STORE_DIR',tmp):
            sha='b'*64
            store.merge(sha,{'ask':self.record})
            store.merge(sha,{'ask_review':{'id':'review1','ask_id':'q1'}})
            store.merge(sha,{'ask_review':{'id':'review2','ask_id':'q2'}})
            store.merge(sha,{'del_ask':'q1'})
            data=store.load(sha)
            self.assertEqual(data['asks'],[])
            self.assertEqual(list(data['ask_reviews']),['review2'])


if __name__=='__main__':unittest.main()
