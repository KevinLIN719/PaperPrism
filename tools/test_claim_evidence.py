"""原文摘录只允许来自所引段落，不做语义支持性保证。"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import llm  # noqa: E402


class QuoteTests(unittest.TestCase):
    def test_exact_quote_and_whitespace(self):
        self.assertEqual(llm.match_source_quote('error is 25.03%', 'The error\n is 25.03% under testing.'),'error is 25.03%')
        for quote in ('error is 24.03%', '误差为25.03%', 'error is ... under testing.', '', None):
            self.assertEqual(llm.match_source_quote(quote,'The error is 25.03% under testing.'),'')

    def test_typography_and_omissions_recover_actual_source(self):
        self.assertEqual(llm.match_source_quote('Tg','T_{g}'),'T_{g}')
        self.assertEqual(llm.match_source_quote('A1','A_{12}'),'')
        self.assertEqual(llm.match_source_quote('theta is 45','theta\u200b is 45'),'theta\u200b is 45')
        source='The epoxy E44 (vendor) and agent D-230 (vendor) were mixed.'
        self.assertEqual(llm.match_source_quote('The epoxy E44 ... and agent D-230',source,recover_omissions=True),'The epoxy E44 (vendor) and agent D-230')
        self.assertEqual(llm.match_source_quote('The epoxy E44 ... and agent D-231',source,recover_omissions=True),'')

    def test_reduce_includes_original_source_not_only_chinese_notes(self):
        parsed={'paras':[{'i':0,'kind':'body','text':'Residual connections improve optimization.'}]}
        notes=[{'part':1,'of':1,'points':[{'idx':0,'point':'残差连接改善优化','why':'主张'}], 'numbers':[], 'terms':[]}]
        user=llm.build_reduce_messages(parsed,notes)[1]['content']
        self.assertIn('Residual connections improve optimization.',user)
        self.assertIn('残差连接改善优化',user)

    def test_wrong_paragraph_or_unknown_type_not_marked(self):
        parsed={'paras':[{'i':0,'kind':'body','text':'Accuracy improves under condition A.','anchor':{'head':'Accuracy improves'}}, {'i':1,'kind':'body','text':'Training is expensive.','anchor':{'head':'Training'}}]}
        obj={'claims':[{'idx':0,'claim':'Improves','quote':'Training is expensive.','statement_type':'verified'}, {'idx':1,'claim':'Costs','quote':'Training is expensive.','statement_type':'作者陈述'}]}
        result,_=llm.validate(obj,parsed)
        self.assertEqual(result['claims'][0]['quote'],'')
        self.assertEqual(result['claims'][0]['statement_type'],'待确认')
        self.assertEqual(result['claims'][1]['quote'],'Training is expensive.')


if __name__=='__main__':unittest.main()
