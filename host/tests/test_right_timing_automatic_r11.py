"""Right-hand estimation through validation/export; independent synthetic score."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_automatic import check_project, export_automatic, prepare_automatic_project
from score_codec import decode, encode


def sample():
    def event(ident,x,pitch,finger,**extra):
        n=dict(id=ident,page=1,system=1,measure=1,staff='r1',hand='right',
               origin=[x,30],bbox=[x-3,27,x+3,33],pitch=pitch,finger=finger,
               finger_source='printed',duration=.5,duration_beats=.5,
               beat=None,written_beat=None,measure_beat=None,measure_start_beat=0,
               meter_beats=4,issues=['measure_timing_unresolved','global_timing_requires_review'])
        n.update(extra)
        return n
    notes=[event('a',20,'C4',1),event('b',40,'D4',2),event('chord',40,'F4',4),
           event('c',80,'E4',3),event('d',20,'G4',5,page=2,staff='r2',measure_beat=0,
                                   duration=1,duration_beats=1),
           event('left',20,'C2',1,hand='left',staff='l1',beat=999,
                 duration=16,duration_beats=16,measure_beat=0)]
    rests=[dict(id='rest',hand='right',staff='r1',page=1,system=1,measure=1,
                origin=[60,30],bbox=[57,27,63,33],duration=.5,beat=None,measure_beat=None),
           dict(id='tail',hand='right',staff='r2',page=2,system=1,measure=1,
                origin=[60,30],bbox=[57,27,63,33],duration=3,beat=None,measure_beat=1)]
    staves=[dict(id='r1',hand='right',page=1,system=1,meter_beats=4,lines=[10,20,30,40,50],
                 measures=[dict(measure=1,meter_beats=4,total_beats=2,timing_resolved=False,length_beats=None)]),
            dict(id='r2',hand='right',page=2,system=1,meter_beats=4,lines=[10,20,30,40,50],
                 measures=[dict(measure=1,meter_beats=4,total_beats=4,timing_resolved=True,length_beats=4)]),
            dict(id='l1',hand='left',page=1,system=1,meter_beats=16,lines=[70,80,90,100,110],
                 measures=[dict(measure=1,meter_beats=16,total_beats=16,timing_resolved=True,length_beats=16)])]
    return dict(name='独立合成右手练习',notes=notes,rests=rests,staves=staves,
                selection=dict(bpm=120,start_beat=0,end_beat=None,repeat_mode='written'))


class RightTimingAutomaticTests(unittest.TestCase):
    def test_estimate_warns_source_without_blocking_export_or_chord_rest(self):
        p=sample();left=deepcopy(p['notes'][-1])
        prepare_automatic_project(p)
        self.assertEqual({k:p['notes'][-1][k] for k in left},left)
        self.assertTrue(p['automatic']['ready'])
        self.assertEqual(p['automatic']['attention_notes'],0)
        self.assertEqual(p['automatic']['timing_warning_notes'],1)
        self.assertEqual(p['automatic']['timing_warning_note_ids'],['a'])
        heads={n['id']:n for n in p['notes']}
        self.assertEqual([heads[i]['beat'] for i in ('a','b','chord','c','d')],[0,.5,.5,1.5,2])
        result=export_automatic(p)
        self.assertEqual([n['t_ms'] for n in decode(encode(result))['notes']],[0,250,250,750,1000])
        self.assertTrue(result['timing']['estimated'])
        self.assertEqual([w['id'] for w in result['timing']['warnings']],['a'])

    def test_check_returns_cross_page_updates_and_preserves_callers_edits(self):
        p=prepare_automatic_project(sample())
        p['notes'][0].update(beat=1.25,manual_fields=['beat'])
        before=deepcopy(p);checked=check_project(p)
        self.assertEqual(p,before)
        self.assertIn('right_hand_timing',checked)
        states={n['id']:n for n in checked['notes']}
        self.assertEqual([states[i]['beat'] for i in ('a','b','chord','c','d')],[1.25,1.75,1.75,2.75,3.25])
        self.assertEqual(checked['automatic']['timing_warning_notes'],0)
        for n in checked['notes']:
            self.assertNotIn('pitch',n);self.assertNotIn('finger',n)

    def test_unknown_note_duration_remains_a_real_blocker_but_later_time_exists(self):
        p=sample();p['notes'][0].update(duration=None,duration_beats=None)
        prepare_automatic_project(p)
        self.assertIsNone(p['notes'][0]['duration_beats'])
        self.assertFalse(p['automatic']['ready'])
        self.assertIn('选择音值',p['notes'][0]['automatic_reasons'])
        self.assertTrue(all(isinstance(n['beat'],(int,float)) for n in p['notes'][1:5]))

    def test_excerpt_uses_only_right_hand_boundaries(self):
        p=sample();p['selection'].update(start_page=1,end_page=1)
        prepare_automatic_project(p)
        self.assertEqual(p['export_scope']['start_beat'],0)
        self.assertEqual(p['export_scope']['end_beat'],2)
        self.assertEqual(export_automatic(p)['duration_ms'],1000)


if __name__=='__main__':unittest.main()
