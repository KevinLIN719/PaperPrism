"""真实Science三线表与旧书库坐标升级，正文与引用不能漂移。"""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import m1_parse as parser  # noqa: E402
import figure  # noqa: E402
import server  # noqa: E402
import store  # noqa: E402

PAPER = Path(__file__).resolve().parents[1]/'demo_papers/science.1133687.pdf'


class TableGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paras = parser.parse_pdf(str(PAPER))

    def test_science_table_contains_last_row_and_excludes_neighbor(self):
        cap = next(p for p in self.paras if p['text'].startswith('Table 1.'))
        # 底行位于y=295.6；右侧Fig3从x=392.9开始。
        self.assertTrue(any(r['bbox'][3] >= 298 for r in cap['rects']))
        self.assertTrue(all(r['bbox'][2] <= 381 for r in cap['rects']))
        self.assertEqual(cap['page'],4)
        with parser.pymupdf.open(PAPER) as doc:
            page = doc[3]
            bounds = [36/page.rect.width,146/page.rect.height,381/page.rect.width,300/page.rect.height]
            self.assertFalse(figure.selection_is_partial(page,bounds,cap))
            bounds[3] = 230/page.rect.height
            self.assertTrue(figure.selection_is_partial(page,bounds,cap))

    def test_science_figure_and_table_have_distinct_click_owners(self):
        captions = [p for p in self.paras if p['page'] == 4 and p['kind'] == 'caption']
        for x,y,prefix in ((100,80,'Table 1.'),(460,100,'Fig. 3.'),(460,230,'Fig. 3.')):
            owners = [p for p in captions if any(r['bbox'][0] <= x <= r['bbox'][2]
                      and r['bbox'][1] <= y <= r['bbox'][3] for r in p['rects'])]
            self.assertEqual(len(owners),1)
            self.assertTrue(owners[0]['text'].startswith(prefix))
        fig = next(p for p in captions if p['text'].startswith('Fig. 3.'))
        self.assertTrue(all(r['bbox'][0] >= 390 and r['bbox'][1] >= 35 for r in fig['rects']))

    def test_old_coordinates_upgrade_only_once_and_keep_text(self):
        old = {'geometry_version':1,'paras':copy.deepcopy(self.paras)}
        cap = next(p for p in old['paras'] if p['text'].startswith('Table 1.'))
        cap['rects'] = [{'page':4,'bbox':[36,39,576,198]}]
        cap.pop('figure_rects',None)
        fig = next(p for p in old['paras'] if p['text'].startswith('Fig. 3.'))
        fig['rects'] = [{'page':4,'bbox':[30,18,576,198]}, {'page':4,'bbox':[392,197,558,346]}]
        before = [(p['text'],p['kind'],p['page']) for p in old['paras']]
        with patch.dict(parser.LAST_PAGE_SIZES,{99:[123,456]},clear=True):
            self.assertTrue(parser.refresh_caption_geometry(str(PAPER),old))
            self.assertEqual(parser.LAST_PAGE_SIZES,{99:[123,456]})
        self.assertEqual(before,[(p['text'],p['kind'],p['page']) for p in old['paras']])
        self.assertFalse(parser.refresh_caption_geometry(str(PAPER),old))
        self.assertTrue(all(r['bbox'][2] <= 381 for r in cap['rects']))
        self.assertTrue(all(r['bbox'][0] >= 390 for r in fig['rects']))

    def test_no_horizontal_rules_does_not_invent_table_bounds(self):
        with parser.pymupdf.open() as doc:
            p = doc.new_page()
            p.insert_text((50,50),'Table 1. Results')
            p.insert_text((50,80),'Unrelated ordinary text.')
            self.assertIsNone(parser.table_caption_rects(p,'Table 1. Results'))

    def test_open_upgrades_geometry_without_invalidating_user_work(self):
        parsed = {'parse_version':parser.PARSE_VERSION,'paras':copy.deepcopy(self.paras)}
        saved = {'parse':parsed,'summary':{'tl_dr':['保留摘要']},'annots':{'0':{'role':'方法'}},
                 'notes':[{'text':'保留笔记'}],'asks':[{'q':'保留追问'}],'figures':[],
                 'reading_goal':'present','usage':{'tokens':123}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(store,'STORE_DIR',tmp),patch.object(server,'paper_sha',return_value=('d'*64,str(PAPER),'papers/science.1133687.pdf')):
            store.save('d'*64,saved)
            response = server.open_paper({})
            self.assertTrue(response['cached'])
            book = response['bundle']
            self.assertEqual(book['parse']['geometry_version'],parser.GEOMETRY_VERSION)
            for key in ('summary','annots','notes','asks','usage','reading_goal'):
                self.assertEqual(book[key],saved[key])


if __name__ == '__main__':
    unittest.main()
