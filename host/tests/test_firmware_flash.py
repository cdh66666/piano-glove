import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge
import firmware_flash as ff


class FirmwareTests(unittest.TestCase):
    def setUp(self):
        with patch.object(bridge, 'rank_ports', return_value=[]):
            self.b = bridge.Bridge(auto=False)
        self.f = self.b.firmware
        self.f.enumerate_ports = lambda: [SimpleNamespace(device='COM3', description='CP2102',
                                            vid=0x10c4, pid=0xea60, serial_number='0001')]

    def test_identity_and_confirmation(self):
        for payload in ({}, {'port':'COM3','powerOffConfirmed':1},
                        {'port':'COM3','bin':'evil'},
                        {'port':'COM7'}):
            with self.assertRaises(ValueError):
                self.f.start('flash',payload)
        self.f.enumerate_ports = lambda: [SimpleNamespace(device='COM3', description='S3',
                                            vid=0x303a, pid=0x1001, serial_number='0001')]
        with self.assertRaises(ValueError): self.f.identity('COM3')

    def test_all_serial_gates(self):
        self.f.busy=True
        self.f.serialExclusive=True
        for method,args in [(self.b.open,('COM3',)),(self.b.close,()),(self.b.probe,('COM3',)),
                            (self.b.autoconnect_once,()),(self.b._write,('INFO',)),
                            (self.b.fire,('INFO',)),(self.b.fire_many,(['INFO'],)),
                            (self.b.send,('INFO',))]:
            with self.assertRaisesRegex(RuntimeError,'维护'):
                method(*args)

    def test_http_busy_and_origin(self):
        self.f.busy=True
        self.f.serialExclusive=True
        server=bridge.ThreadingHTTPServer(('127.0.0.1',0),bridge.make_handler(self.b))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for path,origin,expected in [('/api/send',None,409),('/api/fire',None,409),
                   ('/api/connect',None,409),('/api/scan',None,409),
                   ('/api/firmware/build','http://localhost:8772',403),
                   ('/api/firmware/build','null',403),('/api/firmware/build',None,409)]:
                c=http.client.HTTPConnection('127.0.0.1',server.server_port)
                headers={'Content-Type':'application/json'}
                if origin: headers['Origin']=origin
                c.request('POST',path,'{}',headers);r=c.getresponse();r.read()
                self.assertEqual(r.status,expected,(path,origin));c.close()
        finally:
            server.shutdown();server.server_close();thread.join()

    def run_flash(self, mac='28:05:a5:c4:f1:88', fields='fw=PIANO_GLOVE_2 ver=2.2.4 armed=0', fail_verify=False):
        commands=[]
        self.f.update(written=False, hashVerified=False, verified=False, readback=None)
        with tempfile.TemporaryDirectory() as directory:
            artifacts=[]
            for offset,name in [(0x1000,'bootloader.bin'),(0x8000,'partitions.bin'),(0xe000,'boot_app0.bin'),(0x10000,'firmware.bin')]:
                p=Path(directory)/name;p.write_bytes(b'FAKE');artifacts.append((offset,p))
            def run(args,*rest):
                commands.append([str(a) for a in args])
                if 'chip_id' in args: return 'Chip is ESP32-D0WD-V3 (revision v3.1)\nMAC: '+mac
                if fail_verify and 'verify_flash' in args: raise RuntimeError('verify failed')
                return ''
            with patch.object(self.f,'build',return_value=artifacts),patch.object(self.f,'run',side_effect=run),\
                 patch.object(self.b,'open',side_effect=lambda *a: (setattr(self.b,'port','COM3') or True,'')),patch.object(self.b,'close') as close,\
                 patch.object(self.b,'send',return_value={'lines':['OK INFO '+fields]}),patch.object(ff.time,'sleep'):
                self.f.busy=True
                self.f._worker('flash','COM3',self.f.identity('COM3'))
                self.assertTrue(self.b.paused)
                self.assertFalse(self.f.busy)
        return commands,self.f.status()

    def test_success_verify_and_nvs(self):
        cmds,status=self.run_flash()
        self.assertTrue(status['verified']);self.assertTrue(status['hashVerified'])
        self.assertEqual(status['state'],'verified')
        self.assertTrue(any('verify_flash' in c for c in cmds))
        self.assertFalse(any('erase_flash' in c for c in cmds))
        write=next(c for c in cmds if 'write_flash' in c)
        self.assertNotIn('0x9000',write)

    def test_other_same_model_mac_accepted(self):
        cmds,status=self.run_flash(mac='00:11:22:33:44:55')
        self.assertTrue(any('write_flash' in c for c in cmds))
        self.assertEqual(status['detectedMac'],'00:11:22:33:44:55')
        self.assertTrue(status['verified'])

    def test_unknown_chip_no_write(self):
        with patch.object(self.f,'build',return_value=[]),patch.object(self.b,'open',side_effect=lambda *a: (setattr(self.b,'port','COM3') or True,'')),patch.object(self.b,'close'),patch.object(self.b,'send',return_value={'lines':[]}),patch.object(ff.time,'sleep'),patch.object(self.f,'run',return_value='Chip is ESP32-S3\nMAC: 00:11:22:33:44:55') as run:
            self.f._worker('flash','COM3',self.f.identity('COM3'))
            self.assertFalse(self.f.status()['written'])
            self.assertEqual(run.call_count,1)

    def test_flash_requires_only_port(self):
        with patch.object(threading.Thread,'start'):
            status=self.f.start('flash',{'port':'COM3'})
            self.assertTrue(status['serialExclusive'])

    def test_cp210x_natural_order_and_selection(self):
        ports=bridge.rank_ports([('COM10','CP','USB VID:PID=10C4:EA60'),('COM2','CP','USB VID:PID=10C4:EA60'),('COM1','S3','USB VID:PID=303A:1001'),('COM3','wrongPID','USB VID:PID=10C4:1234')])
        self.assertEqual([p['device'] for p in ports if p['candidate']],['COM2','COM10'])
        self.b.ports=ports
        opened=[]
        def open_port(port):
            opened.append(port);self.b.port=port;self.b.connected=True;return True,''
        with patch.object(self.b,'_reload_ports'),patch.object(self.b,'open',side_effect=open_port),patch.object(self.b,'_wait_info',return_value=True):
            self.b.autoconnect_once();self.assertEqual(opened,['COM2'])
            self.b.port='COM10';self.b.autoconnect_once();self.assertEqual(opened,['COM2'])
            self.assertEqual(self.b.status()['selected'],'COM10')
            self.b.connected=False;self.b.port=None;self.b.autoconnect_once()
            self.assertEqual(opened,['COM2','COM2'])

    def test_written_not_verified(self):
        _,status=self.run_flash(fields='fw=PIANO_GLOVE_2 ver=2.2.3 armed=0')
        self.assertEqual(status['state'],'written_unverified');self.assertFalse(status['verified'])
        _,status=self.run_flash(fail_verify=True)
        self.assertEqual(status['state'],'written_unverified');self.assertFalse(status['hashVerified'])

    def test_armed_readback_refused(self):
        _,status=self.run_flash(fields='fw=PIANO_GLOVE_2 ver=2.2.4 armed=1')
        self.assertFalse(status['verified'])

    def test_close_waits_for_reader(self):
        class Reader:
            def join(self,timeout): self.joined=True
            def is_alive(self): return True
        self.b._reader=Reader()
        with self.assertRaisesRegex(RuntimeError,'读线程'): self.b.close()
        self.assertTrue(self.b._reader.joined)

    def test_build_allows_safe(self):
        self.f.busy=True
        self.f.serialExclusive=False
        with patch.object(self.b,'_write',return_value=True) as write:
            self.b.fire('SAFE')
            write.assert_called_once_with('SAFE')
        original=self.b.paused
        with patch.object(self.f,'build',return_value=[]),patch.object(self.b,'send') as send,patch.object(self.b,'open') as opened:
            self.f._worker('build',None,None)
            send.assert_not_called();opened.assert_not_called()
            self.assertEqual(self.b.paused,original)

    def test_unknown_firmware_keeps_first_port(self):
        self.b.ports=bridge.rank_ports([('COM3','CP','USB VID:PID=10C4:EA60'),('COM10','CP','USB VID:PID=10C4:EA60')])
        opened=[]
        def open_port(port):
            opened.append(port);self.b.port=port;self.b.connected=True;return True,''
        with patch.object(self.b,'_reload_ports'),patch.object(self.b,'open',side_effect=open_port),patch.object(self.b,'_wait_info',return_value=False) as info,patch.object(self.b,'close') as close:
            ok,msg=self.b.autoconnect_once()
            self.assertTrue(ok);self.assertIn('固件未识别',msg)
            self.b.autoconnect_once()
            self.assertEqual(opened,['COM3']);info.assert_called_once();close.assert_not_called()
            self.assertFalse(self.b.status()['firmwareRecognized'])
            self.assertEqual(self.b.status()['selected'],'COM3')


if __name__=='__main__': unittest.main()
