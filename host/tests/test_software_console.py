"""Protocol-only USB adapter tests. No device access or motion."""
import base64
import os
import sys
import types
import unittest
import threading
import json
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from bridge import SoftwareConsole, make_handler
from score_codec import encode

SCORE = dict(version=1,hand='right',title='测试曲',duration_ms=200,
             notes=[dict(t_ms=0,duration_ms=200,pitch=60,finger=1)])

def compact_state():
    return dict(v=1,a=1,i=0,m=0,s=3,t=1234,d=4567,q=150,k=5,h=40,r=1,o=1,e='none',
                x=1,z=4,p=0,l='completed',la=901,pa=910,pm=920,ts=5000,mm=12,
                f=[[1100+i,1200+i,20+i,52,31+i,-50+i,400+i,100+i,1] for i in range(6)])

class FakeBridge:
    def __init__(self):
        self.firmware = types.SimpleNamespace(serialExclusive=False)
        self.commands = []
        self.fail = None
        self.blob = encode(SCORE)
    def send(self, cmd, **kwargs):
        self.commands.append(cmd)
        if cmd == 'SAFE': return {'ok':True,'lines':['OK SAFE']}
        if self.fail and self.fail in cmd:
            return {'ok':True,'lines':['ERR LIB test_failure']}
        op=cmd.split()[1]
        lines=['OK LIB '+op]
        if op=='INFO': lines=['OK LIB INFO ready=1 count=1 max=100 total=1048576 used=160 free=1048416 ap=PianoGlove-1234 ip=192.168.4.1']
        if op=='LIST': lines=['LIB_ITEM slot=1 bytes=144 stored=48 notes=1 duration_ms=200 title_hex='+SCORE['title'].encode().hex(),'OK LIB LIST count=1']
        if op=='STATE': lines=['OK LIB STATE active=1 mode=train slot=0 elapsed_ms=100 tempo=100 mask=1 hold=50 error=none']
        if op=='READ': lines=['LIB_DATA hex='+self.blob.hex(),'OK LIB READ']
        return {'ok':True,'lines':lines}

class Tests(unittest.TestCase):
    def setUp(self): self.bridge=FakeBridge();self.console=SoftwareConsole(self.bridge)
    def test_list_capacity_titles(self):
        r=self.console.library();self.assertEqual(r['slots'][0]['title'],'测试曲');self.assertEqual(r['capacity']['max'],100)
    def test_state(self): self.assertEqual(self.console.state()['hold'],50)
    def test_state_json_firmware(self):
        self.bridge.send=lambda *a,**kw: {'ok':True,'lines':['LIB_STATE {"active":true,"tempo":125,"elapsed_ms":240,"mask":2}','OK LIB STATE']}
        self.assertEqual(self.console.state()['elapsed_ms'],240)
    def test_compact_serial_state_expands_public_fields_and_fixed_mapping(self):
        sample=compact_state()
        self.bridge.send=lambda *a,**kw: {'ok':True,'lines':['LIB_STATE '+json.dumps(sample),'OK LIB STATE']}
        result=self.console.state()
        self.assertTrue(result['active']);self.assertFalse(result['initializing'])
        self.assertEqual(result['mode'],'score');self.assertEqual(result['owner'],'usb')
        self.assertEqual(result['slot'],3);self.assertEqual(result['elapsed_ms'],1234)
        self.assertEqual(result['duration_ms'],4567);self.assertEqual(result['tempo'],150)
        self.assertEqual(result['mask'],5);self.assertEqual(result['hold'],40)
        self.assertTrue(result['hold_variable']);self.assertTrue(result['hold_adjustable'])
        self.assertEqual(result['test_mode'],'OFFHAND');self.assertEqual(result['recovery_mask'],4)
        self.assertEqual(result['model'],'STS3032-C001')
        self.assertEqual(result['piano_ids'],[2,3,4,5,6]);self.assertEqual(result['thumb_pose_id'],1)
        self.assertEqual(result['press_directions'],['min']*6)
        self.assertEqual(result['direction_source'],'fixed_model')
        self.assertEqual(result['device_ms'],5000);self.assertEqual(result['moving_mask'],12)
        self.assertEqual(result['last_stop_reason'],'completed');self.assertEqual(result['last_stop_at_ms'],901)
        self.assertEqual(result['last_prepare_ms'],910);self.assertEqual(result['last_pose_ms'],920)
        self.assertEqual(result['feedback'][2],dict(id=3,position=1102,target=1202,
            min=None,max=None,allowed_min=None,allowed_max=None,calibration_valid=None,
            sample_age_ms=22,position_age_ms=22,voltage_raw=52,temperature=33,current_raw=-48,
            hold_limit=402,health_age_ms=102,health_valid=True,
            pos_valid=None,position_valid=None,position_sample_ms=4978))
    def test_pattern_mode_steps_and_fastest_feedback(self):
        sample=compact_state();sample.update(m=2,q=0,pt=2,ps=7,pc=12,pf=1)
        result=SoftwareConsole.expand_state(sample)
        self.assertEqual((result['mode'],result['pattern'],result['pattern_step'],result['pattern_total']),
                         ('pattern',2,7,12))
        self.assertTrue(result['fastest']);self.assertEqual(result['tempo'],0)
        sample['pf']=0
        self.assertFalse(SoftwareConsole.expand_state(sample)['fastest'])
    def test_old_compact_pattern_fields_and_ranges_are_unknown(self):
        result=SoftwareConsole.expand_state(compact_state())
        for name in ('pattern','pattern_step','pattern_total','fastest','clock_paused','clock_limit_ms','score_index','score_total'):
            self.assertIsNone(result[name])
        self.assertEqual(result['encoder_range'],4095)
        for row in result['feedback']:
            for name in ('min','max','allowed_min','allowed_max','calibration_valid'):
                self.assertIsNone(row[name])
    def test_calibration_range_and_margin_clamp_for_both_models(self):
        sample=compact_state();sample.update(er=4095,b=[[100,3900,250,1]]*6)
        result=SoftwareConsole.expand_state(sample)
        self.assertEqual(result['encoder_range'],4095)
        self.assertEqual({k:result['feedback'][1][k] for k in ('min','max','allowed_min','allowed_max','calibration_valid')},
                         dict(min=100,max=3900,allowed_min=0,allowed_max=4095,calibration_valid=True))
        sample.update(p=1,er=1023,b=[[10,990,50,1]]*6)
        result=SoftwareConsole.expand_state(sample)
        self.assertEqual(result['encoder_range'],1023)
        self.assertEqual((result['feedback'][5]['allowed_min'],result['feedback'][5]['allowed_max']),(0,1023))
        del sample['er']
        self.assertEqual(SoftwareConsole.expand_state(sample)['encoder_range'],1023)
    def test_uncalibrated_axis_does_not_publish_fake_zero_range(self):
        sample=compact_state();sample['b']=[[10,500,30,1]]*5+[[0,0,0,0]]
        row=SoftwareConsole.expand_state(sample)['feedback'][5]
        self.assertFalse(row['calibration_valid'])
        for name in ('min','max','allowed_min','allowed_max'):
            self.assertIsNone(row[name])
    def test_uncalibrated_reversed_bounds_do_not_hide_live_feedback(self):
        for profile,encoder_range in ((0,4095),(1,1023)):
            sample=compact_state();sample.update(p=profile,er=encoder_range,pv=63,
                                                b=[[encoder_range,0,0,0]]*6)
            result=SoftwareConsole.expand_state(sample)
            for index,row in enumerate(result['feedback']):
                self.assertEqual(row['position'],1100+index)
                self.assertTrue(row['position_valid'])
                self.assertFalse(row['calibration_valid'])
                for name in ('min','max','allowed_min','allowed_max'):
                    self.assertIsNone(row[name])
    def test_score_clock_pause_boundary_is_reported_without_host_time_inference(self):
        sample=compact_state();sample.update(cp=1,cl=750,t=749)
        result=SoftwareConsole.expand_state(sample)
        self.assertTrue(result['clock_paused']);self.assertEqual(result['clock_limit_ms'],750)
        self.assertEqual(result['elapsed_ms'],749)
        sample.update(cp=0,cl=1125,t=750)
        result=SoftwareConsole.expand_state(sample)
        self.assertFalse(result['clock_paused']);self.assertEqual(result['clock_limit_ms'],1125)
        self.assertEqual(result['elapsed_ms'],750)
    def test_idle_and_pattern_clock_use_explicit_unbounded_sentinel(self):
        for mode in (0,1,2):
            sample=compact_state();sample.update(a=0,m=mode,cp=0,cl=-1)
            result=SoftwareConsole.expand_state(sample)
            self.assertFalse(result['clock_paused']);self.assertIsNone(result['clock_limit_ms'])
        sample=compact_state();sample.update(cp=1,cl=0,t=0)
        result=SoftwareConsole.expand_state(sample)
        self.assertEqual(result['clock_limit_ms'],0);self.assertEqual(result['elapsed_ms'],0)
    def test_invalid_clock_fields_are_rejected(self):
        for key,invalid in [('cp',True),('cp',2),('cp',None),('cl',True),('cl',-2),('cl',86400001),('cl','750'),('cl',None)]:
            sample=compact_state();sample[key]=invalid
            with self.assertRaises(ValueError,msg=key):SoftwareConsole.expand_state(sample)
    def test_continuous_clock_and_advisory_calibration_are_explicit_capabilities(self):
        sample=compact_state();sample.update(ct=1,ca=1,cp=0,cl=-1)
        result=SoftwareConsole.expand_state(sample)
        self.assertEqual(result['score_clock'],'continuous-v1')
        self.assertTrue(result['calibration_advisory'])
        self.assertFalse(result['clock_paused']);self.assertIsNone(result['clock_limit_ms'])
        sample.update(ct=0,ca=0)
        result=SoftwareConsole.expand_state(sample)
        self.assertIsNone(result['score_clock']);self.assertFalse(result['calibration_advisory'])
    def test_missing_continuous_markers_do_not_claim_new_firmware_policy(self):
        result=SoftwareConsole.expand_state(compact_state())
        self.assertIsNone(result['score_clock']);self.assertIsNone(result['calibration_advisory'])
    def test_invalid_continuous_policy_markers_are_rejected(self):
        for key in ('ct','ca'):
            for invalid in (True,False,-1,2,'1',None):
                sample=compact_state();sample[key]=invalid
                with self.assertRaises(ValueError,msg=str((key,invalid))):SoftwareConsole.expand_state(sample)
    def test_score_counts_preserve_partial_and_completed_submissions(self):
        for index,total in ((0,0),(3,7),(7,7),(60000,60000)):
            sample=compact_state();sample.update(si=index,sn=total)
            result=SoftwareConsole.expand_state(sample)
            self.assertEqual((result['score_index'],result['score_total']),(index,total))
        sample=compact_state();sample.update(a=0,si=7,sn=7,l='completed')
        result=SoftwareConsole.expand_state(sample)
        self.assertEqual((result['score_index'],result['score_total']),(7,7))
        self.assertFalse(result['active'])
    def test_missing_one_score_count_is_not_inferred_from_other(self):
        for present,absent in (('si','score_total'),('sn','score_index')):
            sample=compact_state();sample[present]=7
            result=SoftwareConsole.expand_state(sample)
            self.assertIsNone(result[absent])
    def test_invalid_score_counts_rejected(self):
        for field,invalid in [('si',-1),('sn',60001),('si',True),('sn','7'),('si',None)]:
            sample=compact_state();sample[field]=invalid
            with self.assertRaises(ValueError,msg=field):SoftwareConsole.expand_state(sample)
        sample=compact_state();sample.update(si=8,sn=7)
        with self.assertRaises(ValueError):SoftwareConsole.expand_state(sample)
    def test_valid_calibration_requires_order_and_uses_integer_margin_exactly(self):
        for lo,hi in ((1800,1800),(2480,1667)):
            sample=compact_state();sample['b']=[[lo,hi,121,1]]*6
            with self.assertRaises(ValueError):SoftwareConsole.expand_state(sample)
        sample=compact_state();sample['b']=[[1667,2480,121,1]]*6
        row=SoftwareConsole.expand_state(sample)['feedback'][5]
        self.assertEqual((row['allowed_min'],row['allowed_max']),(1546,2601))
    def test_invalid_optional_bounds_and_pattern_fields_rejected(self):
        for key,value in [('er',0),('er',True),('er',65536),('pt',3),('pt',True),('ps',-1),('pc','12'),('pf',True),('pf',2)]:
            sample=compact_state();sample[key]=value
            with self.assertRaises(ValueError,msg=key):SoftwareConsole.expand_state(sample)
        sample=compact_state();sample.update(ps=8,pc=7)
        with self.assertRaises(ValueError):SoftwareConsole.expand_state(sample)
        invalid_rows=[[],[[10,500,20,1]]*5,[[10,500,20]]*6,
                      [[10,500,20,True]]*6,[[500,10,20,1]]*6,[[10,4096,20,1]]*6,
                      [[10,10,20,1]]*6,[[10,500,-1,1]]*6]
        for rows in invalid_rows:
            sample=compact_state();sample['b']=rows
            with self.assertRaises(ValueError):SoftwareConsole.expand_state(sample)
    def test_position_validity_mask_preserved_and_old_packets_unknown(self):
        sample=compact_state();sample['pv']=0b101001
        rows=SoftwareConsole.expand_state(sample)['feedback']
        self.assertEqual([r['position_valid'] for r in rows],[True,False,False,True,False,True])
        self.assertEqual([r['pos_valid'] for r in rows],[True,False,False,True,False,True])
        sample['pv']=0
        self.assertFalse(any(r['position_valid'] for r in SoftwareConsole.expand_state(sample)['feedback']))
        sample['pv']=63
        self.assertTrue(all(r['position_valid'] for r in SoftwareConsole.expand_state(sample)['feedback']))
        del sample['pv']
        self.assertTrue(all(r['position_valid'] is None for r in SoftwareConsole.expand_state(sample)['feedback']))
    def test_position_timestamp_wrap_and_invalid_mask(self):
        sample=compact_state();sample['ts']=4;sample['f'][0][2]=10;sample['pv']=63
        self.assertEqual(SoftwareConsole.expand_state(sample)['feedback'][0]['position_sample_ms'],4294967290)
        for invalid in (-1,64,True,'63'):
            sample['pv']=invalid
            with self.assertRaises(ValueError):SoftwareConsole.expand_state(sample)
    def test_compact_scs_profile_and_owner_flags(self):
        sample=compact_state();sample.update(p=1,a=0,r=0,o=2,x=0,m=1)
        result=SoftwareConsole.expand_state(sample)
        self.assertEqual(result['model'],'SC09');self.assertFalse(result['hold_adjustable'])
        self.assertEqual(result['press_directions'],['min']*6)
        self.assertEqual(result['owner'],'wifi');self.assertEqual(result['mode'],'train')
        self.assertFalse(result['active']);self.assertFalse(result['hold_variable'])
        self.assertEqual(result['test_mode'],'NORMAL')
    def test_feedback_ages_and_invalid_health_are_not_fabricated_as_fresh(self):
        sample=compact_state();sample['f'][0]=[0,0,4294967295,0,0,0,0,4294967295,0]
        row=SoftwareConsole.expand_state(sample)['feedback'][0]
        self.assertEqual(row['sample_age_ms'],4294967295)
        self.assertEqual(row['position_age_ms'],4294967295)
        self.assertEqual(row['health_age_ms'],4294967295)
        self.assertFalse(row['health_valid'])
    def test_legacy_state_remains_unchanged(self):
        value={'active':False,'feedback':[{'id':1,'position':123}], 'error':'none'}
        self.assertEqual(SoftwareConsole.expand_state(value),value)
    def test_compact_unknown_version_and_bad_flags_rejected(self):
        for key,value in [('v',2),('p',9),('o',9),('a',2),('i',True),('q','100'),('e',None)]:
            sample=compact_state();sample[key]=value
            with self.assertRaises(ValueError,msg=key):SoftwareConsole.expand_state(sample)
    def test_compact_malformed_feedback_rows_rejected(self):
        for malformed in ([], [[1]*9]*5, [[1]*8]*6, [[1]*9]*5+[[1]*8+[2]], [[1]*9]*5+[[1]*8+[True]]):
            sample=compact_state();sample['f']=malformed
            with self.assertRaises(ValueError):SoftwareConsole.expand_state(sample)
    def test_upload_crc_and_exact_chunks(self):
        blob=encode(SCORE);self.console.upload(100,blob)
        chunks=[bytes.fromhex(c.split()[-1]) for c in self.bridge.commands if c.startswith('LIB CHUNK')]
        self.assertEqual(b''.join(chunks),blob);self.assertEqual(self.bridge.commands[-1],'LIB COMMIT')
    def test_advertised_384_byte_transfer_preserves_full_payload(self):
        original = self.bridge.send
        def response(cmd, **kwargs):
            result = original(cmd, **kwargs)
            if cmd == 'LIB INFO': result['lines'][0] += ' chunk_max=384'
            return result
        self.bridge.send = response
        self.console.library()
        score=dict(version=1,hand='right',title='大曲谱',duration_ms=2000,
                   notes=[dict(t_ms=i*10,duration_ms=10,pitch=60,finger=1) for i in range(200)])
        blob=encode(score);self.console.upload(1,blob)
        chunks=[bytes.fromhex(c.split()[-1]) for c in self.bridge.commands if c.startswith('LIB CHUNK')]
        self.assertEqual(self.console.chunk_max,384)
        self.assertEqual(len(chunks[0]),384)
        self.assertEqual(len(chunks),(len(blob)+383)//384)
        self.assertEqual(b''.join(chunks),blob)
    def test_invalid_chunk_capability_falls_back_to_legacy(self):
        original=self.bridge.send
        for capability in ('0','385','-10','999999','abc'):
            def response(cmd, **kwargs):
                result=original(cmd, **kwargs)
                if cmd=='LIB INFO':result['lines'][0]+=' chunk_max='+capability
                return result
            self.bridge.send=response
            self.console.library()
            self.assertEqual(self.console.chunk_max,96)
    def test_library_lookup_waits_for_complete_upload(self):
        entered=threading.Event();release=threading.Event();library_done=threading.Event()
        original=self.bridge.send
        def response(cmd, **kwargs):
            if cmd.startswith('LIB CHUNK'):
                entered.set()
                self.assertTrue(release.wait(2))
            return original(cmd,**kwargs)
        self.bridge.send=response
        upload=threading.Thread(target=lambda:self.console.upload(1,encode(SCORE)))
        lookup=threading.Thread(target=lambda:(self.console.library(),library_done.set()))
        upload.start();self.assertTrue(entered.wait(2));lookup.start()
        self.assertFalse(library_done.wait(.03));self.assertNotIn('LIB INFO',self.bridge.commands)
        release.set();upload.join(2);lookup.join(2)
        self.assertTrue(library_done.is_set())
        self.assertLess(self.bridge.commands.index('LIB COMMIT'),self.bridge.commands.index('LIB INFO'))
    def test_bad_crc_never_sent(self):
        blob=bytearray(encode(SCORE));blob[-1]=99
        with self.assertRaises(ValueError):self.console.upload(1,blob)
        self.assertEqual(self.bridge.commands,[])
    def test_bad_slot(self):
        for slot in (0,101,1.5,True,'1\nLIB PLAY 1 100 100'):
            with self.assertRaises(ValueError):self.console.upload(slot,encode(SCORE))
    def test_failure_aborts(self):
        self.bridge.fail='CHUNK'
        with self.assertRaises(RuntimeError):self.console.upload(1,encode(SCORE))
        self.assertEqual(self.bridge.commands[-1],'LIB ABORT')
    def test_read_roundtrip(self):
        r=self.console.score(1);self.assertEqual(r['notes'][0]['finger'],1);self.assertEqual(base64.b64decode(r['base64']),self.bridge.blob)
    def test_no_maintenance_access(self):
        self.bridge.firmware.serialExclusive=True
        with self.assertRaises(RuntimeError):self.console.state()
        self.assertFalse(self.bridge.commands)
    def test_thumb_is_finger_bit_not_servo_id(self):
        self.console.action('train',{'mask':1,'hold':40,'amplitude':80});self.assertEqual(self.bridge.commands[-1],'LIB TRAIN 1 40 80')
    def test_play_params(self):
        self.console.action('play',{'slot':2,'tempo':150,'amplitude':60});self.assertEqual(self.bridge.commands[-1],'LIB PLAY 2 150 60 100')
    def test_live_tempo(self):
        self.console.action('tempo',{'tempo':125});self.assertEqual(self.bridge.commands[-1],'LIB TEMPO 125')
    def test_invalid_action(self):
        with self.assertRaises(ValueError):self.console.action('unknown',{})
    def test_invalid_tempo(self):
        for tempo in (0,49,1001,True,1.5):
            for action,body in [('play',{'slot':1,'tempo':tempo}),('tempo',{'tempo':tempo})]:
                with self.assertRaises(ValueError):self.console.action(action,body)
    def test_normal_tempo_supports_fifty_to_one_thousand(self):
        for tempo in (50,500,1000):
            self.console.action('play',{'slot':1,'tempo':tempo})
            self.assertEqual(self.bridge.commands[-1],'LIB PLAY 1 %d 100 100'%tempo)
            self.console.action('tempo',{'tempo':tempo})
            self.assertEqual(self.bridge.commands[-1],'LIB TEMPO %d'%tempo)
    def test_single_pattern_command_includes_repeats_and_fastest(self):
        self.console.action('pattern',{'pattern':2,'repeats':20,'tempo':0,'amplitude':60,'hold':50})
        self.assertEqual(self.bridge.commands,['LIB PATTERN 2 20 0 60 50'])
        for tempo in (50,1000):
            self.console.action('pattern',{'pattern':0,'repeats':1,'tempo':tempo})
            self.assertEqual(self.bridge.commands[-1],'LIB PATTERN 0 1 %d 100 50'%tempo)
    def test_invalid_pattern_never_reaches_bridge(self):
        valid={'pattern':1,'repeats':3,'tempo':100,'amplitude':100,'hold':50}
        for field,invalid in [('pattern',-1),('pattern',3),('pattern',True),('repeats',0),('repeats',21),
                              ('tempo',1),('tempo',49),('tempo',1001),('tempo',True),('amplitude',0),('hold',101)]:
            body=dict(valid);body[field]=invalid
            with self.assertRaises(ValueError,msg=field):self.console.action('pattern',body)
        with self.assertRaises(ValueError):self.console.action('pattern',{})
        self.assertEqual(self.bridge.commands,[])
    def test_missing_ack_fails(self):
        self.bridge.send=lambda *a,**kw: {'ok':True,'lines':['LIB_ITEM slot=1']}
        with self.assertRaises(RuntimeError):self.console.library()
    def test_stop_keep(self):
        self.console.action('stop',{});self.console.action('keep',{});self.assertEqual(self.bridge.commands,['LIB STOP','LIB KEEP'])

class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge=FakeBridge()
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(cls.bridge))
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def call(self,path,body=None,content='application/x-www-form-urlencoded'):
        request=Request(self.base+path,data=body,headers={'Content-Type':content})
        with urlopen(request,timeout=3) as response:return json.load(response)
    def test_binary_upload(self):
        blob=encode(SCORE);r=self.call('/api/upload?slot=1',blob,'application/octet-stream');self.assertEqual(r['bytes'],len(blob))
    def test_form_train(self):self.assertTrue(self.call('/api/train',b'mask=3&hold=60&amplitude=80')['ok'])
    def test_form_pattern_is_one_device_side_command(self):
        before=len(self.bridge.commands)
        self.assertTrue(self.call('/api/pattern',b'pattern=1&repeats=2&tempo=0&amplitude=80&hold=60')['ok'])
        self.assertEqual(self.bridge.commands[before:],['LIB PATTERN 1 2 0 80 60'])
    def test_json_pattern_and_high_song_tempo(self):
        r=self.call('/api/pattern',json.dumps(dict(pattern=2,repeats=1,tempo=1000,amplitude=100,hold=50)).encode(),'application/json')
        self.assertTrue(r['ok']);self.assertEqual(self.bridge.commands[-1],'LIB PATTERN 2 1 1000 100 50')
        self.assertTrue(self.call('/api/play',b'slot=1&tempo=1000&amplitude=100')['ok'])
        self.assertTrue(self.call('/api/tempo',b'tempo=1000')['ok'])
    def test_invalid_pattern_or_zero_song_tempo_http_error_without_commands(self):
        from urllib.error import HTTPError
        before=len(self.bridge.commands)
        for path,payload in [('/api/pattern',b'pattern=5&repeats=1&tempo=0'),('/api/pattern',b'pattern=0&tempo=20'),
                             ('/api/pattern',b'repeats=2'),('/api/play',b'slot=1&tempo=0'),('/api/tempo',b'tempo=0')]:
            with self.assertRaises(HTTPError) as caught:self.call(path,payload)
            self.assertEqual(caught.exception.code,409)
            self.assertFalse(json.load(caught.exception)['ok'])
        self.assertEqual(len(self.bridge.commands),before)
    def test_read_library(self):self.assertEqual(self.call('/api/library')['slots'][0]['title'],'测试曲')
    def test_compact_device_state_keeps_http_public_schema(self):
        original=self.bridge.send
        def response(cmd,**kwargs):
            if cmd=='LIB STATE':return {'ok':True,'lines':['LIB_STATE '+json.dumps(compact_state()),'OK LIB STATE']}
            return original(cmd,**kwargs)
        with patch.object(self.bridge,'send',side_effect=response):
            result=self.call('/api/state')
        self.assertTrue(result['ok']);self.assertTrue(result['active'])
        self.assertEqual(result['model'],'STS3032-C001')
        self.assertEqual(result['feedback'][5]['id'],6)
        self.assertEqual(result['feedback'][5]['position_age_ms'],25)
        self.assertNotIn('f',result);self.assertNotIn('v',result)
    def test_http_pattern_state_includes_calibrated_waterlines(self):
        sample=compact_state();sample.update(m=2,pt=1,ps=4,pc=20,pf=1,er=4095,b=[[1000,1800,120,1]]*6)
        with patch.object(self.bridge,'send',return_value={'ok':True,'lines':['LIB_STATE '+json.dumps(sample),'OK LIB STATE']}):
            result=self.call('/api/state')
        self.assertEqual(result['mode'],'pattern');self.assertEqual(result['pattern_step'],4)
        self.assertTrue(result['fastest']);self.assertEqual(result['encoder_range'],4095)
        self.assertEqual(result['feedback'][1]['min'],1000)
        self.assertEqual(result['feedback'][1]['allowed_max'],1920)
    def test_http_state_preserves_virtual_clock_pause_and_unknown_legacy_clock(self):
        sample=compact_state();sample.update(cp=1,cl=375,t=374)
        with patch.object(self.bridge,'send',return_value={'ok':True,'lines':['LIB_STATE '+json.dumps(sample),'OK LIB STATE']}):
            result=self.call('/api/state')
        self.assertTrue(result['clock_paused']);self.assertEqual(result['clock_limit_ms'],375)
        self.assertEqual(result['elapsed_ms'],374)
        with patch.object(self.bridge,'send',return_value={'ok':True,'lines':['LIB_STATE '+json.dumps(compact_state()),'OK LIB STATE']}):
            result=self.call('/api/state')
        self.assertIsNone(result['clock_paused']);self.assertIsNone(result['clock_limit_ms'])
    def test_http_score_event_counts_survive_completed_status(self):
        sample=compact_state();sample.update(a=0,si=7,sn=7,l='completed')
        with patch.object(self.bridge,'send',return_value={'ok':True,'lines':['LIB_STATE '+json.dumps(sample),'OK LIB STATE']}):
            result=self.call('/api/state')
        self.assertFalse(result['active'])
        self.assertEqual((result['score_index'],result['score_total']),(7,7))
    def test_export_blocks_unreviewed(self):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as caught:self.call('/api/software/export',b'{"project":{"selection":{}}}','application/json')
        self.assertEqual(caught.exception.code,400)
    def test_export_reviewed(self):
        project={'name':'复核曲','selection':{'bpm':120,'start_beat':0,'range_reviewed':True},'notes':[{'id':1,'page':1,'hand':'right','pitch':'C4','finger':1,'beat':0,'duration_beats':1,'confirmed':True}]}
        r=self.call('/api/software/export',json.dumps({'project':project}).encode(),'application/json')
        self.assertEqual(r['bytes'],144)
    def test_conversion_returns_actual_rendered_pdf_pages(self):
        import io
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        document=PdfWriter()
        font=document._add_object(DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')}))
        for text in ('Actual PDF page one','Actual PDF page two'):
            page=document.add_blank_page(width=595,height=842)
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
            content=DecodedStreamObject();content.set_data(('BT /F1 24 Tf 70 750 Td ('+text+') Tj ET').encode())
            page[NameObject('/Contents')]=document._add_object(content)
        stream=io.BytesIO();document.write(stream);blob=stream.getvalue();document.close()
        payload=json.dumps({'filename':'real-pages.pdf','base64':base64.b64encode(blob).decode(),'bpm':120}).encode()
        with patch('score_converter.recognize_pdf',return_value={'notes':[],'source_sha256':'source-checksum'}):
            r=self.call('/api/software/convert',payload,'application/json')
        self.assertEqual(r['project']['source_sha256'],'source-checksum')
        previews=r['project']['page_previews'];self.assertEqual(len(previews),2)
        images=[]
        for entry in previews:
            image=base64.b64decode(entry['data'].split(',',1)[1]);self.assertTrue(image.startswith(b'\x89PNG'))
            from PIL import Image
            with Image.open(io.BytesIO(image)) as pixmap:
                self.assertLessEqual(pixmap.width,1200);self.assertLessEqual(pixmap.height,1600)
                self.assertLess(min(low for low,high in pixmap.getextrema()),100) # Real text, not a white placeholder.
            images.append(image)
        self.assertNotEqual(images[0],images[1])

if __name__=='__main__':unittest.main()
