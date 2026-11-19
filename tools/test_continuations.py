"""数字引用与行内根式的断段回归：python tools/test_continuations.py。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import m1_parse as m  # noqa: E402


class ContinuationTests(unittest.TestCase):
    def paragraphs(self, left, right):
        return [dict(kind='body', text=t, page=1, rects=[]) for t in (left, right)]

    def test_numeric_citation_at_column_start(self):
        left = 'These passive designs work well for complex geometries, but cannot handle planar or smaller objects'
        result = m.rejoin_unfinished(self.paragraphs(left, '(13, 24). Suction-based grippers are suitable for planar objects.'))
        self.assertEqual(len(result), 1)

    def test_radical_with_invisible_formula_characters(self):
        left = 'The adhesion strength is related to compliance and true interfacial contact area as P a ∼ √\u2009_'
        result = m.rejoin_unfinished(self.paragraphs(left, '\u200bA\u200bt\u200a/\u200bC\u200b. As the temperature increases, adhesion changes.'))
        self.assertEqual(len(result), 1)

    def test_independent_paragraphs_stay_separate(self):
        left = 'These passive designs work well for complex geometries and can handle planar or smaller objects.'
        for right in ('(13, 24). Suction-based grippers are suitable.', '(1) A new numbered item', 'Another critical factor is temperature.'):
            self.assertEqual(len(m.rejoin_unfinished(self.paragraphs(left, right))), 2)
        self.assertFalse(m._special_continuation('An unfinished sentence', '(1) A new numbered item'))
        self.assertFalse(m._special_continuation('An unfinished sentence', 'Another paragraph starts here.'))


if __name__ == '__main__':
    unittest.main()
