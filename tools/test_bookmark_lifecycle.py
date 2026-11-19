"""隔离书库验证同内容重导入和关联记录删除。"""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import store


class BookmarkLifecycleTests(unittest.TestCase):
    def test_upload_reopen_and_deleted_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            imported = root / 'papers' / 'imported'
            imported.mkdir(parents=True)
            pdf = server.m1_parse.pymupdf.open()
            pdf.new_page()
            content = pdf.tobytes()
            pdf.close()
            with patch.object(server, 'ROOT', str(root)), patch.object(server, 'PAPERS_DIR', str(root / 'papers')), patch.object(server, 'IMPORT_DIR', str(imported)), patch.object(store, 'STORE_DIR', str(root / 'store')), patch.object(server, 'DEMO', False):
                original = imported / 'first.pdf'
                original.write_bytes(content)
                sha = store.sha_of(original)
                mark = {'id':'bookmark', 'page':1, 'offset':.4, 'color':'#dce8da', 'question':'保留我的问题', 'figureId':'figure', 'questionRef':{'kind':'note','id':'note'}}
                store.merge(sha, {'parse':{'parse_version':server.m1_parse.PARSE_VERSION,'paras':[], 'page_sizes':{'1':[612,792]}}, 'reading_bookmark':{'bookmarks':[mark]}, 'note':{'id':'note','text':'批注'}, 'figure_record':{'id':'figure','page':1,'bounds':[.1,.1,.5,.5],'title':'图1','sources':[]}})
                class Upload:
                    headers = {'X-Filename':'renamed.pdf','Content-Length':str(len(content))}
                    rfile = io.BytesIO(content)
                    def send_json(self, body, code=200):
                        self.body, self.code = body, code
                upload = Upload()
                server.Handler.handle_upload(upload)
                self.assertEqual(upload.code, 200)
                opened = server.open_paper({'path':upload.body['path']})
                self.assertTrue(opened['cached'])
                self.assertEqual(opened['sha'],sha)
                self.assertEqual(opened['bundle']['reading_bookmark']['bookmarks'],[mark])
                store.merge(sha, {'del_note':'note','del_figure':'figure'})
                self.assertEqual(store.load(sha)['reading_bookmark']['bookmarks'],[mark])
                server.delete_paper({'path':upload.body['path'],'keep_records':True})
                self.assertEqual(store.load(sha)['reading_bookmark']['bookmarks'],[mark])
                server.delete_paper({'path':'papers/imported/first.pdf','keep_records':False})
                self.assertIsNone(store.load(sha))


if __name__ == '__main__':
    unittest.main()
