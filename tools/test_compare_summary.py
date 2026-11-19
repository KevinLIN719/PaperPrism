import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paper_compare as compare
import server
import store

CFG = {'base': 'https://api.deepseek.com', 'model': 'deepseek-chat'}


class ComparisonSummaryTests(unittest.TestCase):
    def test_api_reuses_local_records_and_preserves_notes(self):
        class Request:
            path = '/api/compare'
            def __init__(self, refresh=False):
                body = json.dumps({'paths':['a.pdf','b.pdf'], 'explain':True, 'refresh':refresh}).encode()
                self.headers = {'Content-Length':str(len(body))}
                self.rfile = io.BytesIO(body)
            def send_json(self, data, code=200):
                self.data, self.code = data, code
        result = {'items':{topic:{'text':'概括', 'evidence':[{'idx':0,'quote':'experiment problem'}]}
                           for topic in compare.TOPICS}, 'usage':{'total_tokens':4}, 'model':CFG['model']}
        with tempfile.TemporaryDirectory() as tmp, patch.object(store,'STORE_DIR',tmp), patch.object(
                server,'paper_sha',side_effect=lambda payload:(payload['path'],payload['path'],payload['path'])), patch.object(
                compare.llm,'config',return_value=CFG), patch.object(compare,'summarize',return_value=result) as generate:
            for path in ('a.pdf','b.pdf'):
                store.merge(path,{'parse':{'parse_version':server.m1_parse.PARSE_VERSION,'paras':[
                    {'kind':'body','page':1,'text':'experiment problem'}]},'note':{'id':'n','text':'保留笔记'}})
            first=Request();server.Handler.do_POST(first)
            self.assertEqual(first.code,200)
            self.assertEqual(generate.call_count,2)
            second=Request(True);server.Handler.do_POST(second)
            self.assertEqual(generate.call_count,2)
            self.assertTrue(all(item['cached'] for item in second.data['summaries']))
            self.assertEqual(second.data['meta']['cost']['tokens'],0)
            self.assertEqual(store.load('a.pdf')['notes'][0]['text'],'保留笔记')

    def test_sources_isolate_papers_and_keep_whole_paragraphs(self):
        docs = [{'path': name, 'file': name, 'parse': {'paras': [
            {'kind': 'body', 'page': 2, 'text': f'Our experiment addresses a problem with dataset {name}.'}]}}
            for name in ('A', 'B')]
        result = compare.compare_documents(docs)
        sources = compare.summary_sources(result, 0)
        self.assertEqual(len(sources), 1)
        self.assertIn('dataset A', sources[0]['text'])
        self.assertNotIn('dataset B', json.dumps(sources))
        for row in result['rows']:
            for source in row['cells'][0]:
                source['text'] = 'x' * 36001
        self.assertEqual(compare.summary_sources(result, 0), [])

    def test_supported_summary_and_condition_preserved(self):
        sources = [{'idx': 0, 'page': 1, 'text': 'The experiment uses dataset A at 25 C.'}]
        draft = {'items': [{'id': '实验条件', 'text': '实验使用数据集 A，温度为25°C。'}]}
        review = {'items': [{'id': '实验条件', 'status': '支持', 'evidence': [
            {'idx': 0, 'quote': sources[0]['text']}]}]}
        with patch.object(compare.llm, 'chat', side_effect=[
            (json.dumps(draft), {'total_tokens': 10}), (json.dumps(review), {'total_tokens': 20}),
            ('{"items":[]}', {})]) as call:
            result = compare.summarize(sources, CFG)
        self.assertEqual(result['usage']['total_tokens'], 30)
        self.assertIn('25°C', result['items']['实验条件']['text'])
        for invocation in call.call_args_list:
            self.assertIn('dataset A', invocation.args[0][1]['content'])

    def test_foreign_paper_quote_is_rejected(self):
        draft = {'items': [{'id': '实验条件', 'text': '使用数据集B。'}]}
        review = {'items': [{'id': '实验条件', 'status': '支持', 'evidence': [
            {'idx': 0, 'quote': 'Dataset B at 60 C.'}]}]}
        with patch.object(compare.llm, 'chat', side_effect=[(json.dumps(draft), {}), (json.dumps(review), {}), ('{"items":[]}', {})]):
            result = compare.summarize([{'idx': 0, 'text': 'Dataset A at 25 C.'}], CFG)
        self.assertEqual(result['items'], {})

    def test_revision_must_be_reviewed_again(self):
        draft = {'items': [{'id': '研究问题', 'text': '作者证明该方法总是有效。'}]}
        first = {'研究问题': {'status': '部分支持', 'revision': '作者假设该方法有效。'}}
        second = {'研究问题': {'status': '支持', 'evidence': [{'idx': 0, 'quote': 'We hypothesize.'}]}}
        with patch.object(compare.llm, 'chat', return_value=(json.dumps(draft), {})), patch.object(
                compare.summary_pipeline, 'batch_review', side_effect=[(first, {}), (second, {})]) as review:
            result = compare.summarize([{'idx': 0, 'text': 'We hypothesize.'}], CFG)
        self.assertEqual(review.call_count, 2)
        self.assertEqual(result['items']['研究问题']['text'], '作者假设该方法有效。')

    def test_missing_draft_gets_focused_repair_and_review(self):
        fixed = {'items':[{'id':'实验条件','text':'使用数据集A。'}]}
        approved = {'实验条件':{'status':'支持','evidence':[{'idx':7,'quote':'Dataset A.'}]}}
        with patch.object(compare.llm,'chat',side_effect=[('{"items":[]}',{}),(json.dumps(fixed),{})]), patch.object(
                compare.summary_pipeline,'batch_review',return_value=(approved,{})) as review:
            result=compare.summarize([{'idx':7,'text':'Dataset A.'}],CFG)
        self.assertEqual(result['items']['实验条件']['text'],'使用数据集A。')
        self.assertEqual(review.call_count,1)
        self.assertEqual(result['issues']['假设与前提'],'not_explicit')

    def test_repair_failure_keeps_previously_approved_items(self):
        draft={'items':[{'id':'研究问题','text':'研究问题A。'}]}
        approved={'研究问题':{'status':'支持','evidence':[{'idx':0,'quote':'Problem A.'}]}}
        with patch.object(compare.llm,'chat',side_effect=[(json.dumps(draft),{}),RuntimeError('offline')]), patch.object(
                compare.summary_pipeline,'batch_review',return_value=(approved,{})):
            result=compare.summarize([{'idx':0,'text':'Problem A.'}],CFG)
        self.assertIn('研究问题',result['items'])
        self.assertEqual(result['issues']['实验条件'],'review_incomplete')

    def test_sections_beat_repeated_challenge_and_method_context_is_kept(self):
        paras=[{'kind':'heading','text':'Abstract'}, {'kind':'body','page':1,'text':'We introduce a new approach.'},
               {'kind':'heading','text':'Training Hardware'}, {'kind':'body','page':2,'text':'Eight GPUs for twelve hours.'},
               {'kind':'heading','text':'Benchmark Results'},
               *[{'kind':'body','page':3,'text':'Challenge Challenge Challenge problem.'} for _ in range(5)]]
        docs=[{'path':p,'file':p,'parse':{'paras':paras}} for p in ('a','b')]
        comparison=compare.compare_documents(docs)
        self.assertIn(1,[s['idx'] for s in comparison['rows'][0]['cells'][0]])
        self.assertIn(3,[s['idx'] for s in comparison['rows'][2]['cells'][0]])
        sources=compare.summary_sources(comparison,0,docs[0]['parse'])
        self.assertIn('Eight GPUs for twelve hours.',[s['text'] for s in sources])

    def test_actual_boundary_beats_incidental_however(self):
        paras=[{'kind':'heading','text':'Introduction'},
               *[{'kind':'body','page':1,'text':'However other approaches address challenges.'} for _ in range(5)],
               {'kind':'heading','text':'Ablations'},
               {'kind':'body','page':4,'text':'These approximations hold only where the scene matches the assumptions.'},
               {'kind':'heading','text':'Discussion'},
               {'kind':'body','page':6,'text':'Our approach improves learning.'}]
        docs=[{'path':p,'file':p,'parse':{'paras':paras}} for p in ('a','b')]
        result=compare.compare_documents(docs)
        boundary=result['rows'][3]['cells'][0]
        self.assertIn(7,[s['idx'] for s in boundary])
        self.assertNotIn(9,[s['idx'] for s in boundary])

    def test_truncated_generation_cannot_be_delivered(self):
        with patch.object(compare.llm, 'chat', return_value=('{}', {'finish_reason': 'length'})):
            with self.assertRaises(ValueError):
                compare.summarize([{'idx': 1, 'text': 'Text.'}], CFG)

    def test_empty_sources_skip_model_and_cache_tracks_inputs(self):
        with patch.object(compare.llm, 'chat') as chat:
            self.assertEqual(compare.summarize([], CFG)['items'], {})
            chat.assert_not_called()
        key = compare.cache_key([], CFG)
        self.assertNotEqual(key, compare.cache_key([{'idx': 1, 'text': 'new'}], CFG))
        self.assertNotEqual(key, compare.cache_key([], {**CFG, 'model': 'other'}))


if __name__ == '__main__':
    unittest.main()
