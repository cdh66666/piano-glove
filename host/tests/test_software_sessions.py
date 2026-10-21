import json
from pathlib import Path
import sys
import unittest
import threading
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_software_console import FakeBridge
from bridge import SoftwareConsole


class Tests(unittest.TestCase):
    def setUp(self):self.bridge=FakeBridge();self.console=SoftwareConsole(self.bridge)
    def test_same_controller_can_train_keep_stop(self):
        self.console.action('train',{'mask':1},'one');self.console.action('keep',{},'one');self.console.action('stop',{},'one')
        self.assertEqual(self.bridge.commands,['LIB TRAIN 1 50 100','LIB KEEP','LIB STOP'])
        self.assertIsNone(self.console.controller_id)
    def test_stale_tab_does_not_stop_or_sustain_new_session(self):
        self.console.action('train',{'mask':1},'one')
        for action in ['stop','keep','tempo']:
            with self.assertRaisesRegex(RuntimeError,'controller_mismatch'):
                self.console.action(action,{'tempo':100},'two')
        self.assertNotIn('LIB STOP',self.bridge.commands);self.assertNotIn('LIB KEEP',self.bridge.commands)
    def test_completed_device_does_not_leave_owner_locked(self):
        self.console.action('train',{'mask':1},'one')
        original=self.bridge.send
        def response(cmd,**kw):
            return {'ok':True,'lines':['LIB_STATE '+json.dumps({'active':False}),'OK LIB STATE']} if cmd=='LIB STATE' else original(cmd,**kw)
        with patch.object(self.bridge,'send',side_effect=response):
            self.console.action('train',{'mask':2},'two')
        self.assertEqual(self.console.controller_id,'two')
    def test_no_motion_while_chunk_upload_active(self):
        self.console.begin_upload(1,144,'one')
        before=list(self.bridge.commands)
        with self.assertRaisesRegex(RuntimeError,'upload_active'):
            self.console.action('train',{'mask':1},'one')
        self.assertEqual(self.bridge.commands,before)
    def test_owned_cleanup_does_not_stop_phone_run(self):
        with patch.object(self.console,'state',return_value={'active':True,'owner':'wifi'}):
            result=self.console.action('stop',{'scope':'owned'},'idle-pc')
        self.assertTrue(result['skipped'])
        self.assertNotIn('LIB STOP',self.bridge.commands)
    def test_owned_cleanup_rechecks_device_transport_despite_stale_usb_owner(self):
        self.console.controller_id='old-pc'
        with patch.object(self.console,'state',return_value={'active':True,'owner':'wifi'}):
            result=self.console.action('stop',{'scope':'owned'},'old-pc')
        self.assertTrue(result['skipped'])
        self.assertNotIn('LIB STOP',self.bridge.commands)
    def test_owned_cleanup_other_tab_skips_and_current_owner_can_stop(self):
        self.console.controller_id='one'
        with patch.object(self.console,'state',return_value={'active':True,'owner':'usb'}):
            self.assertTrue(self.console.action('stop',{'scope':'owned'},'two')['skipped'])
            self.assertFalse(self.console.action('stop',{'scope':'owned'},'one').get('skipped',False))
        self.assertEqual(self.bridge.commands,['LIB INFO','LIB STOP','SAFE'])
    def test_explicit_stop_preserves_legacy_global_serial_stop(self):
        self.console.action('stop',{},'idle-pc')
        self.assertEqual(self.bridge.commands,['LIB STOP'])
    def test_capable_firmware_release_is_atomic_without_global_fallback(self):
        original=self.bridge.send
        def response(cmd,**kw):
            if cmd in ('LIB INFO','LIB RELEASE'):
                self.bridge.commands.append(cmd)
                return {'ok':True,'lines':['OK LIB INFO release_usb=1' if cmd=='LIB INFO' else 'OK LIB RELEASE skipped=1']}
            return original(cmd,**kw)
        with patch.object(self.bridge,'send',side_effect=response):
            self.assertTrue(self.console.release_usb()['skipped'])
        self.assertEqual(self.bridge.commands,['LIB INFO','LIB RELEASE'])
    def test_legacy_release_skips_phone_and_unknown_active_owner(self):
        for owner in ['wifi',None]:
            self.bridge.commands=[]
            with patch.object(self.console,'state',return_value={'active':True,'owner':owner}):
                self.assertTrue(self.console.release_usb()['skipped'])
            self.assertEqual(self.bridge.commands,['LIB INFO'])
    def test_legacy_release_stops_usb_and_checks_safe_ack(self):
        with patch.object(self.console,'state',return_value={'active':True,'owner':'usb'}):
            self.assertFalse(self.console.release_usb()['skipped'])
        self.assertEqual(self.bridge.commands,['LIB INFO','LIB STOP','SAFE'])
    def test_release_failure_never_falls_back_to_global_stop(self):
        original=self.bridge.send
        def response(cmd,**kw):
            if cmd=='LIB INFO':
                self.bridge.commands.append(cmd)
                return {'ok':True,'lines':['OK LIB INFO release_usb=1']}
            if cmd=='LIB RELEASE':
                self.bridge.commands.append(cmd)
                return {'ok':True,'lines':['ERR LIB RELEASE failure']}
            return original(cmd,**kw)
        with patch.object(self.bridge,'send',side_effect=response):
            with self.assertRaisesRegex(RuntimeError,'failure'):self.console.release_usb()
        self.assertEqual(self.bridge.commands,['LIB INFO','LIB RELEASE'])
    def test_delayed_idle_packet_cannot_clear_new_controller_owner(self):
        sampled=threading.Event();release=threading.Event()
        original=self.console.command
        def response(cmd,*args,**kwargs):
            if cmd=='LIB STATE':
                sampled.set();self.assertTrue(release.wait(2))
                return ['LIB_STATE '+json.dumps({'active':False}),'OK LIB STATE']
            return original(cmd,*args,**kwargs)
        with patch.object(self.console,'command',side_effect=response):
            worker=threading.Thread(target=self.console.state);worker.start()
            self.assertTrue(sampled.wait(2))
            self.console.action('train',{'mask':1},'new-owner')
            release.set();worker.join(2)
        self.assertFalse(worker.is_alive());self.assertEqual(self.console.controller_id,'new-owner')


if __name__=='__main__':unittest.main()
