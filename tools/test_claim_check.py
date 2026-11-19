"""语义支持核查的保守回退与缓存键测试。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import claim_check as check  # noqa: E402
import store  # noqa: E402


class CheckTests(unittest.TestCase):
    cfg={'base':'https://example.com','model':'test','key':'test'}
    claim={'idx':0,'claim':'X accuracy is 80%.'}
    source='X accuracy is 80% on dataset A.'

    def test_support_requires_matching_quote(self):
        for quote,status in [('X accuracy is 80%','支持'),('X accuracy is 90%','信息不足'),('','信息不足')]:
            raw={'status':'支持','reason':'reason','quote':quote}
            with self.subTest(quote=quote), patch.object(check.llm,'chat',return_value=(json.dumps(raw),{})):
                result=check.review(self.claim,self.source,self.cfg)
                self.assertEqual(result['status'],status)

    def test_cache_is_sensitive_to_claim_source_and_model(self):
        key=check.cache_key(self.claim,self.source,self.cfg)
        self.assertNotEqual(key,check.cache_key({**self.claim,'claim':'different'},self.source,self.cfg))
        self.assertNotEqual(key,check.cache_key(self.claim,self.source+' condition',self.cfg))
        self.assertNotEqual(key,check.cache_key(self.claim,self.source,{**self.cfg,'model':'other'}))

    def test_review_persists_without_rewriting_summary(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'STORE_DIR',tmp):
            summary={'claims':[self.claim]}
            store.merge('f'*64,{'summary':summary})
            item={'id':'review1','idx':0,'claim':self.claim['claim'],'status':'支持','source_text':self.source}
            store.merge('f'*64,{'claim_review':item})
            restored=store.load('f'*64)
            self.assertEqual(restored['claim_reviews']['review1'],item)
            self.assertEqual(restored['summary'],summary)

    def test_invalid_format_has_bounded_retry(self):
        with patch.object(check.llm,'chat',return_value=(' ',{})) as chat:
            with self.assertRaises(ValueError):check.review(self.claim,self.source,self.cfg)
            self.assertEqual(chat.call_count,2)


if __name__=='__main__':unittest.main()
