"""图表解读输入与真实 PDF 裁图流程回归，不调用外部模型。"""
import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import figure  # noqa: E402
import store  # noqa: E402


class FigureTests(unittest.TestCase):
    def test_retry_empty_or_truncated_and_count_all_usage(self):
        cfg = {'model': 'deepseek-flash', 'base': 'https://api.deepseek.com/v1', 'key': 'test'}
        valid = json.dumps(dict(reading='轴', observations='趋势', claim='主张', limits='未知', sources=[]))
        for first in ('', '   ', '{"reading":"unterminated'):
            with self.subTest(first=first), patch.object(figure.llm, 'chat', side_effect=[
                    (first, {'total_tokens': 10}), (valid, {'total_tokens': 20})]) as chat:
                result, usage, attempts = figure.request_explanation([], cfg)
                self.assertEqual(result['claim'], '主张')
                self.assertEqual(usage['total_tokens'], 30)
                self.assertEqual(attempts, 2)
                self.assertFalse(chat.call_args.kwargs['thinking'])
                self.assertTrue(chat.call_args.kwargs['json_mode'])
                self.assertEqual(chat.call_args.kwargs['max_tokens'], 8192)
        # 即使截断响应恰好可解析，也不能作为完整结果接受。
        with patch.object(figure.llm, 'chat', side_effect=[
                (valid, {'finish_reason': 'length'}), (valid, {'finish_reason': 'stop'})]) as chat:
            figure.request_explanation([], cfg)
            self.assertEqual(chat.call_count, 2)

    def test_repeated_empty_output_is_clear_bounded_failure(self):
        cfg = {'model': 'test', 'base': 'https://example.com', 'key': 'test'}
        with patch.object(figure.llm, 'chat', return_value=(' ', {'total_tokens': 5})) as chat:
            with self.assertRaisesRegex(figure.FigureOutputError, '空解读.*未保存') as error:
                figure.request_explanation([], cfg)
            self.assertEqual(chat.call_count, 2)
            self.assertEqual(error.exception.meta['cost']['tokens'], 10)
            self.assertNotIn('thinking', chat.call_args.kwargs)

    def test_content_filter_is_not_retried(self):
        cfg = {'model': 'test', 'base': 'https://example.com', 'key': 'test'}
        with patch.object(figure.llm, 'chat', return_value=('', {'finish_reason': 'content_filter'})) as chat:
            with self.assertRaisesRegex(figure.FigureOutputError, '内容过滤'):
                figure.request_explanation([], cfg)
            self.assertEqual(chat.call_count, 1)

    def test_transport_preserves_finish_reason_and_explicit_thinking(self):
        reply = {'choices': [{'message': {'content': None}, 'finish_reason': 'length'}],
                 'usage': {'total_tokens': 100}}
        with patch.object(figure.llm, '_open', return_value=io.BytesIO(json.dumps(reply).encode())) as transport:
            text, usage = figure.llm.chat([], cfg={'base': 'https://example.com', 'model': 'test', 'key': 'test'}, thinking=False)
        request_body = json.loads(transport.call_args.args[0].data)
        self.assertEqual(request_body['thinking'], {'type': 'disabled'})
        self.assertEqual(usage['finish_reason'], 'length')
        self.assertEqual(text, '')

    def test_geometry_takes_precedence_over_model_partial(self):
        self.assertFalse(figure.resolve_partial(False, True))
        self.assertTrue(figure.resolve_partial(True, False))
        self.assertTrue(figure.resolve_partial(None, True))
        self.assertFalse(figure.resolve_partial(None, False))

    def test_delete_only_target_records_and_persist(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(store, 'STORE_DIR', tmp):
            sha = 'b'*64
            store.merge(sha, {'figure_record': {'id': 'fig-a', 'result': {'reading': 'keep'}}})
            store.merge(sha, {'figure_record': {'id': 'fig-b'}})
            store.merge(sha, {'ask': {'id': 'ask-a', 'q': 'delete'}})
            store.merge(sha, {'ask': {'id': 'ask-b', 'q': 'keep'}})
            store.merge(sha, {'note': {'id': 'note-a', 'text': 'keep'}})
            store.merge(sha, {'del_figure': 'fig-b', 'del_ask': 'ask-a'})
            restored = store.load(sha)
            self.assertEqual([r['id'] for r in restored['figures']], ['fig-a'])
            self.assertEqual([r['id'] for r in restored['asks']], ['ask-b'])
            self.assertEqual(restored['notes'][0]['text'], 'keep')
            store.merge(sha, {'del_figure': 'missing', 'del_ask': 'missing'})
            self.assertEqual(store.load(sha)['figures'], restored['figures'])

    def test_reading_goal_survives_other_updates(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(store, 'STORE_DIR', tmp):
            sha = 'c'*64
            store.merge(sha, {'reading_goal': 'present'})
            store.merge(sha, {'note': {'id': 'n', 'text': 'keep'}})
            self.assertEqual(store.load(sha)['reading_goal'], 'present')
            store.merge(sha, {'reading_goal': 'reproduce'})
            self.assertEqual(store.load(sha)['reading_goal'], 'reproduce')
            self.assertEqual(len(store.load(sha)['notes']), 1)

    def test_invalid_regions(self):
        for bounds in ([0, 0, 0, 1], [0, 0, 2, 1], [0, 0, float('nan'), 1]):
            with self.assertRaises(ValueError):
                figure.validate_region({'page': 1, 'bounds': bounds}, 1)
        with self.assertRaises(ValueError):
            figure.validate_region({'page': True, 'bounds': [0, 0, 1, 1]}, 1)

    def test_partial_figure_geometry(self):
        with figure.m1_parse.pymupdf.open() as doc:
            page = doc.new_page(width=600, height=800)
            page.insert_text((60, 520), 'Fig. 3. Demonstrations of the capabilities.')
            caption = {'text': 'Fig. 3. Demonstrations of the capabilities.', 'rects': [
                {'page': 1, 'bbox': [50, 500, 550, 540]},
                {'page': 1, 'bbox': [60, 60, 540, 480]}]}
            self.assertTrue(figure.selection_is_partial(page, [.1, .075, .9, .25], caption))
            self.assertFalse(figure.selection_is_partial(page, [.1, .075, .9, .6], caption))

    def test_render_and_ground_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/'figure.pdf')
            with figure.m1_parse.pymupdf.open() as doc:
                page = doc.new_page()
                page.draw_rect((100, 100, 300, 300))
                page.insert_text((110, 150), 'Figure 1: sample')
                doc.save(path)
            parsed = {'paras': [{'i': 0, 'page': 1, 'kind': 'caption', 'text': 'Real caption'}]}
            payload = {'page': 1, 'bounds': [.1, .1, .8, .8],
                       'context': {'caption': {'idx': 0, 'text': 'Forged caption'}, 'paragraphs': [{'idx': 99}]}}
            def fake_chat(messages, **kwargs):
                content = messages[1]['content']
                self.assertIn('Real caption', content[0]['text'])
                self.assertNotIn('Forged caption', content[0]['text'])
                self.assertTrue(content[1]['image_url']['url'].startswith('data:image/png;base64,iVBOR'))
                if messages[0]['content'] == figure.figure_check.GROUND_SYSTEM:
                    self.assertNotIn('草稿',content[0]['text'])
                    return json.dumps({'panels':[{'id':'1','notes':'图中可见形状'}]}),{}
                if messages[0]['content'] == figure.figure_check.REVIEW_SYSTEM:
                    proof = {'kind':'text','idx':0,'quote':'Real caption'}
                    return json.dumps({'items':[{'id':k,'status':'支持','evidence':[proof],'reason':'符合'}
                                                for k in figure.figure_check.FIELDS]}),{}
                return json.dumps(dict(reading='轴', observations='趋势', claim='主张', limits='未知', sources=[0,99,True])), {}
            with patch.object(figure.llm, 'vision_config', return_value={'model': 'test', 'base': 'https://example.com', 'key': 'test'}), patch.object(figure.llm, 'chat', side_effect=fake_chat):
                result = figure.explain(path, parsed, payload)
            self.assertEqual([s['idx'] for s in result['sources']], [0])
            record = result['record']
            self.assertEqual(record['page'], 1)
            self.assertEqual(record['bounds'], payload['bounds'])
            self.assertNotIn('base64', json.dumps(record))
            self.assertNotIn('data:image', json.dumps(record))
            with patch.object(store, 'STORE_DIR', tmp):
                store.merge('a'*64, {'figure_record': record})
                store.merge('a'*64, {'figure_record': record})
                restored = store.load('a'*64)['figures']
                self.assertEqual(len(restored), 1)
                self.assertEqual(restored[0], record)


if __name__ == '__main__':
    unittest.main()
