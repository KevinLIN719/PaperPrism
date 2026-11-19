import io
import sys
import unittest
from pathlib import Path
from urllib.parse import urlencode
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server


class ExportTests(unittest.TestCase):
    def test_utf8_attachment_formats(self):
        for ext in ('md','html'):
            content='测试笔记\n原文来源'
            body=urlencode({'name':'论文-阅读笔记.'+ext,'content':content}).encode()
            class Request:
                path='/api/export-notes'
                headers={'Content-Length':str(len(body))}
                rfile=io.BytesIO(body)
                wfile=io.BytesIO()
                response_headers={}
                def send_response(self,code):self.code=code
                def send_header(self,key,value):self.response_headers[key]=value
                def end_headers(self):pass
            request=Request();server.Handler.do_POST(request)
            self.assertEqual(request.code,200)
            self.assertTrue(request.response_headers['Content-Disposition'].startswith('attachment;'))
            self.assertIn("filename*=UTF-8''",request.response_headers['Content-Disposition'])
            self.assertEqual(request.wfile.getvalue().decode('utf-8-sig'),content)


if __name__=='__main__':unittest.main()
