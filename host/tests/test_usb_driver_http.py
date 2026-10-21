import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock,patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request,urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bridge

class DriverHttpTests(unittest.TestCase):
    def setUp(self):
        self.driver=Mock()
        self.driver.status.return_value={'busy':False,'state':'idle'}
        self.driver.start.return_value={'busy':True,'state':'running','phase':'download'}
        self.constructor=patch.object(bridge,'USBDriverInstaller',return_value=self.driver)
        self.constructor.start()
        self.diagnostic=patch.object(bridge,'get_driver_status',return_value={'state':'missing_driver','problem_code':28})
        self.diagnostic.start()
        self.ports=patch.object(bridge.list_ports,'comports',return_value=[])
        self.ports.start()
        self.device=Mock()
        self.device.firmware.serialExclusive=False
        self.server=ThreadingHTTPServer(('127.0.0.1',0),bridge.make_handler(self.device))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.constructor.stop();self.diagnostic.stop();self.ports.stop()
    def call(self,path,body=None,origin=None):
        headers={'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        req=Request(self.base+path,None if body is None else json.dumps(body).encode(),headers)
        with urlopen(req,timeout=3) as reply:return reply.status,json.load(reply)
    def test_read_only_diagnostics_can_find_device_without_com(self):
        _,status=self.call('/api/driver?refresh=1')
        self.assertEqual(status['state'],'missing_driver')
        self.assertEqual(status['installation']['state'],'idle')
        bridge.get_driver_status.assert_called_once_with([],refresh=True)
        self.driver.start.assert_not_called();self.device.send.assert_not_called()
    def test_install_only_after_explicit_scoped_post(self):
        code,status=self.call('/api/driver/install',{})
        self.assertEqual(code,202);self.assertTrue(status['busy'])
        self.driver.start.assert_called_once_with();self.device.send.assert_not_called()
    def test_custom_url_or_path_rejected(self):
        with self.assertRaises(HTTPError) as caught:self.call('/api/driver/install',{'url':'https://example.com/driver.zip'})
        self.assertEqual(caught.exception.code,400);self.driver.start.assert_not_called()
    def test_cross_site_install_is_rejected(self):
        with self.assertRaises(HTTPError) as caught:self.call('/api/driver/install',{},'https://example.com')
        self.assertEqual(caught.exception.code,403);self.driver.start.assert_not_called()

if __name__=='__main__':unittest.main()
