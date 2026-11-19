"""只删除项目列表PDF，保留或清除同内容记录，拒绝越界及旧任务回写。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402
import store  # noqa: E402


class PaperDeleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'papers/imported').mkdir(parents=True)
        patches = [patch.object(server,'ROOT',str(self.root)),patch.object(server,'PAPERS_DIR',str(self.root/'papers')),
                   patch.object(server,'DEMO',False),patch.object(store,'STORE_DIR',str(self.root/'store')),
                   patch.object(store,'_REMOVED_RECORDS',set())]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.pdf = self.root/'papers/imported/test.pdf'
        self.pdf.write_bytes(b'%PDF-test')
        self.sha = store.sha_of(self.pdf)
        self.book = {'notes':[{'text':'keep'}],'summary':{'tl_dr':['keep']},'asks':[{'q':'keep'}]}
        store.save(self.sha,self.book)

    def test_keep_records_and_restore_after_reimport(self):
        server.delete_paper({'path':'papers/imported/test.pdf','keep_records':True})
        self.assertFalse(self.pdf.exists())
        self.assertEqual(store.load(self.sha)['notes'],self.book['notes'])
        self.pdf.write_bytes(b'%PDF-test')
        sha,_,_ = server.paper_sha({'path':'papers/imported/test.pdf'})
        self.assertEqual(sha,self.sha)
        self.assertEqual(store.load(sha)['asks'],self.book['asks'])

    def test_delete_records_blocks_late_result_until_reimport(self):
        server.delete_paper({'path':'papers/imported/test.pdf','keep_records':False})
        self.assertFalse(self.pdf.exists())
        self.assertIsNone(store.load(self.sha))
        with self.assertRaises(ValueError):
            store.merge(self.sha,{'summary':{'tl_dr':['late']}})
        self.pdf.write_bytes(b'%PDF-test')
        server.paper_sha({'path':'papers/imported/test.pdf'})
        store.merge(self.sha,{'summary':{'tl_dr':['new']}})
        self.assertEqual(store.load(self.sha)['summary']['tl_dr'],['new'])

    def test_only_selected_copy_is_removed(self):
        copy = self.root/'papers/copy.pdf'
        copy.write_bytes(self.pdf.read_bytes())
        server.delete_paper({'path':'papers/imported/test.pdf','keep_records':True})
        self.assertTrue(copy.exists())
        self.assertIsNotNone(store.load(self.sha))

    def test_reject_outside_wrong_type_and_demo(self):
        outside = self.root/'outside.pdf'
        outside.write_bytes(b'keep')
        for payload in ({'path':'outside.pdf'},{'path':'papers/../outside.pdf'},
                        {'path':'papers/imported/test.pdf','keep_records':'false'}):
            with self.assertRaises(ValueError):
                server.delete_paper(payload)
        with patch.object(server,'DEMO',True),self.assertRaises(ValueError):
            server.delete_paper({'path':'papers/imported/test.pdf'})
        self.assertTrue(outside.exists())
        self.assertTrue(self.pdf.exists())


if __name__ == '__main__':
    unittest.main()
