"""Native-only JSON transfer equivalence; synthetic replies, no socket or device."""
import base64
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_api import NativeAPI

class JsonTextTests(unittest.TestCase):
    def api(self,payload,mime='application/json; charset=utf-8',status=200):
        class Handler:
            def __init__(self,path,method,body,headers):
                self.wfile=io.BytesIO();self.response_status=status;self.response_headers={'content-type':mime,'content-length':str(len(payload))}
            def do_GET(self):self.wfile.write(payload)
        api=NativeAPI.__new__(NativeAPI);api._handler=Handler;return api

    def test_large_success_json_can_skip_reparse_with_an_explicit_marker_and_exact_semantic_equivalence(self):
        value={'name':'独立合成JSON往返','notes':[{'id':i,'pitch':'F#4','finger':None if i%5==0 else i%5+1,
                'beat':i/3,'duration_beats':.25,'confirmed':False,'details':'synthetic '*40} for i in range(10000)]}
        payload=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf8')
        self.assertGreater(len(payload),4*1024*1024)
        api=self.api(payload);default=api.request('/api/software/check')
        with patch('native_api.json.loads',side_effect=AssertionError('opt-in success must not reconstruct JSON objects')):
            text=api.request('/api/software/check',headers={'x-piano-json-text':'1'})
        self.assertEqual(text['body_encoding'],'json-text');self.assertFalse(text['binary']);self.assertEqual(text['body'],payload.decode('utf8'))
        self.assertEqual(json.loads(text['body']),default['body']);self.assertEqual(default['body'],value);self.assertNotIn('body_encoding',default)

    def test_default_and_non_opted_direct_callers_keep_object_bodies(self):
        api=self.api(b'{"ok":true,"notes":[1,null]}')
        for headers in [None,{}, {'X-Piano-Json-Text':'0'},{'X-Piano-Json-Text':'true'}]:
            result=api.request('/api/software/check',headers=headers)
            self.assertEqual(result['body'],{'ok':True,'notes':[1,None]});self.assertNotIn('body_encoding',result)
        for route in ['/api/software/convert','/api/score?slot=2','/api/status']:
            result=api.request(route,headers={'X-Piano-Json-Text':'1'})
            self.assertEqual(result['body'],{'ok':True,'notes':[1,None]});self.assertNotIn('body_encoding',result)

    def test_error_status_and_adapter_errors_keep_the_original_object_contract(self):
        result=self.api(b'{"ok":false,"error":"unchanged"}',status=400).request('/api/software/check',headers={'X-Piano-Json-Text':'1'})
        self.assertEqual(result['status'],400);self.assertEqual(result['body']['error'],'unchanged');self.assertNotIn('body_encoding',result)
        invalid=self.api(b'{}').request('https://outside.invalid',headers={'X-Piano-Json-Text':'1'})
        self.assertEqual(invalid['status'],400);self.assertIsInstance(invalid['body'],dict);self.assertNotIn('body_encoding',invalid)

    def test_binary_and_non_json_text_are_not_reencoded_or_marked(self):
        binary=b'\x89PNG\r\n\x1a\n\x00\x80\xff';result=self.api(binary,'image/png').request('/api/image',headers={'X-Piano-Json-Text':'1'})
        self.assertEqual(base64.b64decode(result['body']),binary);self.assertTrue(result['binary']);self.assertNotIn('body_encoding',result)
        result=self.api('原样文本'.encode('utf8'),'text/plain').request('/api/text',headers={'X-Piano-Json-Text':'1'})
        self.assertEqual(result['body'],'原样文本');self.assertFalse(result['binary']);self.assertNotIn('body_encoding',result)

if __name__=='__main__':unittest.main()
