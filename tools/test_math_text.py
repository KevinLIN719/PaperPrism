"""已知符号字体编码与下标基线回归。"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import m1_parse as m  # noqa: E402


class MathTests(unittest.TestCase):
    def test_known_symbol_font_only(self):
        spans=[{'font':'SymbolGreek','text':'\uf071 ≤ \uf070/2; \uf073; \uf06d'}]
        self.assertEqual(m.normalize_math_spans(spans)[0]['text'],'θ ≤ π/2; σ; μ')
        for font in ('MinionPro','Wingdings'):
            self.assertEqual(m.normalize_math_spans([{'font':font,'text':'\uf071'}])[0]['text'],'\uf071')
        self.assertEqual(m.normalize_math_spans([{'font':'Symbol','text':'∫ ∑ √ ≥'}])[0]['text'],'∫ ∑ √ ≥')

    def test_lower_baseline_preserves_index_not_footnote(self):
        base={'text':'T','font':'MinionPro-Italic','size':10,'origin':(0,10),'bbox':(0,0,5,14)}
        sub={'text':'g','font':'MinionPro-Italic','size':7,'origin':(5,11.5),'bbox':(5,5,8,14)}
        self.assertEqual(m.normalize_math_spans([dict(base),dict(sub)])[1]['text'],'_{g}')
        sup={**sub,'text':'1','origin':(5,7)}
        self.assertEqual(m.normalize_math_spans([dict(base),sup])[1]['text'],'1')


if __name__=='__main__': unittest.main()
