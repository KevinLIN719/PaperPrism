"""按学科复现评估与缓存隔离回归。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import repro  # noqa: E402
import store  # noqa: E402


class ProfilesTests(unittest.TestCase):
    def test_budget_retains_late_evidence_categories(self):
        paras=[{'i':i,'kind':'body','page':1,'text':'General discussion. '*40} for i in range(30)]
        for text in ['Data availability. Dataset and specimen sources.', 'Experimental setup. Temperature and grip speed.', 'Implementation details. Preprocessing and source code.', 'Supplementary materials. https://example.org/appendix']:
            paras.append({'i':len(paras),'kind':'body','page':3,'text':text})
        selected=repro.select_repro_evidence({'paras':paras},budget=1500)
        ids={item['para']['i'] for item in selected}
        self.assertTrue({30,31,32,33}.issubset(ids))
        self.assertLessEqual(sum(len(item['line'])+1 for item in selected),1500)
        self.assertEqual([item['order'] for item in selected],sorted(item['order'] for item in selected))

    def test_personal_resources_prompt_and_cache(self):
        resources = repro.normalize_resources({'equipment':' 笔记本 ', 'time':'每周5小时', 'goal':'核对图2'})
        self.assertEqual(resources['equipment'], '笔记本')
        self.assertEqual(resources['background'], '')
        self.assertNotEqual(repro.resource_cache_key('computing', resources), repro.resource_cache_key('computing', repro.normalize_resources({})))
        import server
        cfg = {'base':'https://example.com','model':'test'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(store,'STORE_DIR',tmp), patch.object(server,'paper_sha',return_value=('f'*64,'unused','paper')), patch.object(server,'parse_cached',return_value={'file':'paper','paras':[]}), patch.object(repro.llm,'config',return_value=cfg), patch.object(repro,'repro_check',return_value=({},{})) as check:
            self.assertFalse(server.repro_cached({'discipline':'computing','resources':resources})['cached'])
            self.assertTrue(server.repro_cached({'discipline':'computing','resources':resources})['cached'])
            self.assertFalse(server.repro_cached({'discipline':'computing','resources':{**resources,'time':'一小时'}})['cached'])
            self.assertEqual(check.call_count,2)
        raw = dict(value='信息不足',value_why='待确认',objective='核对图2',feasible='信息不足', personal_match='可用于阅读代码',personal_unknown='显存未提供',personal_next='先检查依赖')
        with patch.object(repro.llm,'chat',return_value=(json.dumps(raw),{})) as chat, patch.object(repro,'_repo_evidence',return_value={}):
            card,meta=repro.repro_check({'paras':[]},discipline='computing',resources=resources)
            self.assertIn('每周5小时',chat.call_args.args[0][1]['content'])
            self.assertEqual(card['personal_unknown'],'显存未提供')
            self.assertEqual(meta['resources'],resources)
        with self.assertRaises(ValueError):
            repro.normalize_resources({'time':42})

    def test_profiles_are_applied_to_prompt_and_result(self):
        parsed = {'paras': [{'i':0,'kind':'body','page':1,'text':'We measure the force at 30 degrees.'}]}
        result = dict(value='有条件值得验证',value_why='可验证趋势',objective='测量一个条件',feasible='信息不足',why='设备未知',datasets=['材料'],risks=[{'idx':0,'text':'设备条件'}],start={'idx':0,'text':'最小实验'},repo='')
        for key, (name, focus) in repro.DISCIPLINES.items():
            with self.subTest(key=key), patch.object(repro.llm,'chat',return_value=(json.dumps(result),{})) as chat, patch.object(repro,'_repo_evidence',return_value={}):
                card,meta = repro.repro_check(parsed,discipline=key)
                prompt = chat.call_args.args[0][1]['content']
                self.assertIn(name,prompt)
                self.assertIn(focus,prompt)
                self.assertNotIn('两周内用一张消费级显卡',prompt)
                self.assertEqual(meta['discipline'],key)
                self.assertEqual(card['feasible'],'信息不足')
                self.assertEqual(card['value'],'有条件值得验证')
        with self.assertRaises(ValueError):
            repro.discipline_profile('invalid')

    def test_context_preserves_parameters_after_old_cutoff(self):
        text = 'Experimental setup. ' + 'Details. ' * 100 + 'Learning rate 0.1; cure at 80 C for 2 h.'
        context = repro._context({'paras':[{'i':0,'kind':'body','text':text}]})
        self.assertIn('Learning rate 0.1',context)
        self.assertIn('cure at 80 C for 2 h',context)

    def test_backend_cache_is_scoped_by_discipline(self):
        import server
        cfg = {'base':'https://example.com','model':'test','key':'test'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(store,'STORE_DIR',tmp), patch.object(server,'paper_sha',return_value=('e'*64,'unused','paper')), patch.object(server,'parse_cached',return_value={'file':'paper','paras':[]}), patch.object(repro.llm,'config',return_value=cfg), patch.object(repro,'repro_check',return_value=({'value':'信息不足'},{'version':repro.REPRO_VERSION})) as check:
            first = server.repro_cached({'discipline':'engineering'})
            hit = server.repro_cached({'discipline':'engineering'})
            other = server.repro_cached({'discipline':'computing'})
            self.assertFalse(first['cached'])
            self.assertTrue(hit['cached'])
            self.assertFalse(other['cached'])
            self.assertEqual(check.call_count,2)

    def test_profiles_persist_without_overwriting_each_other(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(store,'STORE_DIR',tmp):
            for key in ('computing','engineering'):
                store.merge('d'*64,{'repro_profile':{'key':key,'result':{'card':{'objective':key}}}})
            data = store.load('d'*64)
            self.assertEqual(data['repro_profiles']['computing']['card']['objective'],'computing')
            self.assertEqual(data['repro_profiles']['engineering']['card']['objective'],'engineering')


if __name__ == '__main__':
    unittest.main()
