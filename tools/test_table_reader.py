import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import m1_parse
import table_reader


def fixture(path, second_header='Force (N)', continued=True):
    doc=m1_parse.pymupdf.open()
    paras=[]
    for n in range(2):
        page=doc.new_page(width=612,height=792)
        caption='Table 1. '+('Continued measurements.' if n and continued else 'Measurements.')
        page.insert_text((50,65),caption,fontsize=12)
        for x in (50,260,470):page.draw_line((x,100),(x,190))
        for y in (100,130,160,190):page.draw_line((50,y),(470,y))
        values=[['Object','Force (N)' if not n else second_header],['Steel','12.5'],['Glass','8.0']]
        for row,cells in enumerate(values):
            for col,text in enumerate(cells):page.insert_text((60+210*col,120+30*row),text,fontsize=11)
        paras.append({'kind':'caption','page':n+1,'text':caption,
                      'figure_rects':[{'page':n+1,'bbox':[48,98,472,192]}],
                      'rects':[{'page':n+1,'bbox':[50,50,470,70]}]})
    doc.save(str(path));doc.close()
    return {'paras':paras}


class TableReaderTests(unittest.TestCase):
    def test_continuation_merges_headers_but_keeps_duplicate_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tables.pdf';parsed=fixture(path)
            result=table_reader.read_table(str(path),parsed,1)
        self.assertEqual(result['mode'],'merged')
        self.assertEqual(result['header'],['Object','Force (N)'])
        self.assertEqual(len(result['rows']),4)
        self.assertEqual([r['page'] for r in result['rows']],[1,1,2,2])
        self.assertEqual(result['rows'][0]['cells'],['Steel','12.5'])
        self.assertTrue(all(0<=v<=1 for r in result['rows'] for v in r['bounds']))

    def test_different_units_stay_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tables.pdf';parsed=fixture(path,'Pressure (kPa)')
            result=table_reader.read_table(str(path),parsed,0)
        self.assertEqual(result['mode'],'separate')
        self.assertEqual(len(result['segments']),2)
        self.assertEqual(result['rows'],[])
        self.assertEqual(result['segments'][1]['header'][1],'Pressure (kPa)')

    def test_same_number_without_continued_is_not_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tables.pdf';parsed=fixture(path,continued=False)
            result=table_reader.read_table(str(path),parsed,0)
        self.assertEqual(len(result['segments']),1)
        self.assertEqual(len(result['rows']),2)

    def test_unlocated_table_falls_back_without_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tables.pdf';parsed=fixture(path)
            parsed['paras'][1]['figure_rects']=[{'page':2,'bbox':[50,500,470,520]}]
            result=table_reader.read_table(str(path),parsed,0)
        self.assertEqual(result['mode'],'separate')
        self.assertTrue(result['segments'][1]['warning'])
        self.assertEqual(result['segments'][1]['rows'],[])

    def test_numeric_first_row_is_not_deleted_as_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tables.pdf';parsed=fixture(path,'20')
            result=table_reader.read_table(str(path),parsed,0)
        self.assertEqual(result['mode'],'separate')
        self.assertEqual(result['segments'][1]['rows'][0]['cells'],['Object','20'])

    def test_caption_only_geometry_uses_unique_adjacent_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tables.pdf';parsed=fixture(path)
            for para in parsed['paras']:
                para.pop('figure_rects')
            result=table_reader.read_table(str(path),parsed,0)
        self.assertEqual(result['mode'],'merged')
        self.assertEqual(len(result['rows']),4)

    def test_invalid_target_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'tables.pdf';parsed=fixture(path)
            with self.assertRaises(ValueError):table_reader.read_table(str(path),parsed,99)


if __name__=='__main__':unittest.main()
