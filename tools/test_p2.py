import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
import paper_compare
import figure_catalogue


class P2Tests(unittest.TestCase):
    def test_comparison_preserves_conditions_and_missing_cells(self):
        documents=[{'path':'a.pdf','file':'a.pdf','parse':{'paras':[
            {'kind':'body','page':1,'text':'We hypothesize a method for this problem.'},
            {'kind':'body','page':2,'text':'Our experiment uses dataset A at 25 C.'}]}},
            {'path':'b.pdf','file':'b.pdf','parse':{'paras':[{'kind':'body','page':4,'text':'Our experiment uses dataset B at 60 C.'}]}}]
        result=paper_compare.compare_documents(documents)
        self.assertEqual(result['rows'][1]['cells'][1],[])
        self.assertIn('dataset A',result['rows'][2]['cells'][0][0]['text'])
        self.assertIn('dataset B',result['rows'][2]['cells'][1][0]['text'])
        self.assertNotIn('winner',result)
        with self.assertRaises(ValueError):paper_compare.compare_documents(documents[:1])

    def test_native_report_and_catalogue_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/'report.pdf')
            doc=server.m1_parse.pymupdf.open()
            for n in range(3):
                page=doc.new_page(width=612,height=792)
                page.insert_text((40,50),'Native Report' if n==0 else 'Experimental Results',fontsize=18)
                for x,word in [(40,'LeftColumnMarker'),(320,'RightColumnMarker')]:
                    remaining=page.insert_textbox((x,100,x+230,280),(word+' experimental observations and assumptions are recorded for validation. ')*4,fontsize=10)
                    self.assertGreaterEqual(remaining,0)
                label='Fig. 1. Diagram of experiment.' if n==0 else 'Table 1. '+('Continued results.' if n==2 else 'Experimental results.')
                page.insert_text((40,330),label,fontsize=11)
                if n==0:
                    page.insert_text((40,345),'A',fontsize=11,fontname='hebo')
                    page.insert_text((51,345),'explains the caption, not a panel label.',fontsize=11)
                    page.insert_text((50,400),'A',fontsize=12,fontname='hebo')
                    page.insert_text((250,400),'B',fontsize=12,fontname='hebo')
                else:page.draw_rect((40,350,500,500))
            doc.save(path);doc.close()
            paras=server.m1_parse.parse_pdf(path)
            text=' '.join(p['text'] for p in paras)
            self.assertIn('LeftColumnMarker',text);self.assertIn('RightColumnMarker',text)
            parsed={'paras':[{'kind':'caption','page':n+1,'text':('Fig. 1. Diagram.' if n==0 else 'Table 1. '+('Continued results.' if n==2 else 'Results.')),
                'rects':[{'page':n+1,'bbox':[40,320,500,510]}]} for n in range(3)]}
            items=figure_catalogue.catalogue(path,parsed)
            self.assertEqual([p['label'] for p in items[0]['panels']],['A','B'])
            self.assertEqual(items[1]['continuations'],[2]);self.assertEqual(items[2]['continuations'],[1])
            self.assertTrue(all(0<=value<=1 for item in items for region in item['regions'] for value in region['bounds']))


if __name__=='__main__':unittest.main()
