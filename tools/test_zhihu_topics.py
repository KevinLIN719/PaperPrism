import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import zhihu


class DiscussionTests(unittest.TestCase):
    bundle = {'summary':{'glossary':[{'term':'residual learning','zh':'残差学习'}]}}

    def test_topics_and_manual_fallback(self):
        queries=zhihu.pick_topic_queries(self.bundle)
        self.assertEqual([q['topic'] for q in queries],['concept','experiment','reproduce'])
        self.assertEqual(len(set(q['q'] for q in queries)),3)
        self.assertTrue(all('残差学习' in q['q'] for q in queries))
        with patch.object(zhihu,'has_secret',return_value=False),patch.object(zhihu,'search') as search:
            card,cached=zhihu.build_card(self.bundle)
        self.assertFalse(cached)
        self.assertEqual(card['asked'],0)
        self.assertEqual(len(card['queries']),3)
        self.assertTrue(all(q['url'].startswith('https://') for q in card['queries']))
        search.assert_not_called()

    def test_old_cache_requires_explicit_refresh(self):
        previous={'status':'ok','queries':[{'q':'old','items':[]}],'total':1}
        with patch.object(zhihu,'search') as search:
            card,cached=zhihu.build_card({**self.bundle,'zhihu':previous})
        self.assertTrue(cached)
        self.assertEqual(card['queries'],previous['queries'])
        search.assert_not_called()

    def test_refresh_preserves_topics_and_deduplicates(self):
        item={'title':'残差学习实验','url':'https://www.zhihu.com/question/1','snippet':'training setup','vote':1}
        with patch.object(zhihu,'has_secret',return_value=True),patch.object(zhihu,'search',return_value=([item],None)) as search,patch.object(zhihu,'_score',return_value=2):
            card,cached=zhihu.build_card(self.bundle,refresh=True)
        self.assertFalse(cached)
        self.assertEqual(search.call_count,3)
        self.assertEqual(card['total'],1)
        self.assertEqual([q['topic'] for q in card['queries']],['concept','experiment','reproduce'])

    def test_votes_do_not_change_relevance(self):
        item={'title':'residual training','snippet':'optimization'}
        self.assertEqual(zhihu._score({**item,'vote':0},['optimization'],'residual'),zhihu._score({**item,'vote':100000},['optimization'],'residual'))
        self.assertEqual(zhihu.pick_topic_queries({}),[])

    def test_topic_filter_rejects_generic_explanations(self):
        self.assertFalse(zhihu.topic_matches({'title':'形状记忆聚合物基本概念'},'reproduce'))
        self.assertTrue(zhihu.topic_matches({'title':'ResNet训练参数与代码实现'},'reproduce'))
        self.assertTrue(zhihu.topic_matches({'title':'SMP温度与测量实验'},'experiment'))
        self.assertFalse(zhihu.topic_matches({'title':'新材料实现形状记忆'},'reproduce'))

    def test_existing_topic_cache_is_filtered_without_network(self):
        previous={'status':'ok','total':1,'queries':[{'topic':'reproduce','items':[{'title':'形状记忆基本原理'}]}]}
        with patch.object(zhihu,'search') as search:
            card,cached=zhihu.build_card({'zhihu':previous})
        self.assertTrue(cached);self.assertEqual(card['total'],0);self.assertEqual(card['status'],'empty')
        self.assertEqual(len(previous['queries'][0]['items']),1)
        search.assert_not_called()


if __name__=='__main__':unittest.main()
