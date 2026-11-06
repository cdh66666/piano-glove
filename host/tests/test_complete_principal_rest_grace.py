"""Independent complete-meter/rest/grace controls; no user score coordinates."""
from pathlib import Path
from copy import deepcopy
import sys,unittest
ROOT=Path(__file__).resolve().parent;HOST=ROOT.parent
if not (HOST/'score_converter_engine.py').exists():
    HOST=ROOT.parent.parent/'repo/host'
sys.path.insert(0,str(HOST))
if (ROOT/'candidate/score_converter_engine.py').exists():sys.path.insert(0,str(ROOT/'candidate'))
from score_converter_engine import _recover_grace_principal_timing,_mark_unresolved_slashed_graces


def fixture(scale=1,dx=0,dy=0):
    gap=5*scale;xy=lambda x,y:[x*scale+dx,y*scale+dy]
    def note(ident,x,duration,staff='right'):
        p=xy(x,40);return dict(id=ident,staff=staff,hand='right' if staff=='right' else 'left',measure=1,
            origin=p,pitch_candidate='C5',duration=duration,beats=duration,measure_beat=None,issues=['measure_timing_unresolved'],
            rhythm_evidence={'head':'filled','stem':[p[0]+6*scale,p[1]-20*scale,p[1]],'stem_direction':'up','beams':0})
    a=note('first',20,2);g=note('ornament',45,.5);b=note('principal',100,1.5)
    g['issues']=['grace_or_cue_note_requires_review'];g['rhythm_evidence']['beams']=1
    rest=dict(id='rest',staff='right',hand='right',measure=1,origin=xy(70,40),bbox=[v for p in [xy(68,35),xy(74,45)] for v in p],
        duration=.5,measure_beat=None,issues=['measure_timing_unresolved'],rhythm_evidence={})
    left=[]
    for ident,x,duration,onset in [('left-a',20,2,0),('left-rest',70,.5,2),('left-b',100,1.5,2.5)]:
        n=note(ident,x,duration,'left');n['measure_beat']=onset;n['issues']=[];left.append(n)
    staves=[dict(id=s,gap=gap,measures=[dict(measure=1,meter_beats=4,timing_resolved=complete)])
            for s,complete in [('right',False),('left',True)]]
    sx=g['rhythm_evidence']['stem'][0];y=g['origin'][1]
    slash=(sx-4*scale,y-8*scale,sx+4*scale,y-14*scale,.5*scale)
    return staves,[a,g,rest,b]+left,[slash]


class CompletePrincipalRestGraceTests(unittest.TestCase):
    def test_verified_internal_slash_crosses_horizontal_rest_only_with_complete_principal_evidence(self):
        for scale,dx,dy in [(1,0,0),(.5,51,-20),(3,-150,90)]:
            staves,events,lines=fixture(scale,dx,dy)
            _recover_grace_principal_timing(staves,events,lines)
            first,grace,rest,main=events[:4]
            self.assertIsNone(grace['duration']);self.assertIsNone(grace['measure_beat'])
            self.assertEqual(grace['grace_kind'],'slashed');self.assertEqual(grace['grace_nominal_duration_beats'],.5)
            self.assertEqual(grace['main_anchor_id'],'principal')
            self.assertEqual([e['measure_beat'] for e in (first,rest,main)],[0,2,2.5])
            self.assertEqual(main['duration'],1.5);self.assertEqual(rest['duration'],.5)

    def test_review_issue_or_cue_without_actual_slash_does_not_cross_a_rest(self):
        for cue in (False,True):
            staves,events,_=fixture()
            if cue:events[1]['issues']=['small_notated_note_requires_review']
            before=deepcopy(events);_recover_grace_principal_timing(staves,events,[])
            self.assertEqual(events,before,cue)

    def test_no_meter_incomplete_unknown_duration_or_unverified_paired_voice_remains_unchanged(self):
        for mode in ('no_meter','incomplete','unknown','no_pair','contradicting_pair'):
            staves,events,lines=fixture()
            if mode=='no_meter':staves[0]['measures'][0]['meter_beats']=None
            elif mode=='incomplete':events[3]['duration']=1
            elif mode=='unknown':events[2]['duration']=None
            elif mode=='no_pair':events=events[:4];staves=staves[:1]
            else:events[-1]['measure_beat']=2
            before=deepcopy(events);_recover_grace_principal_timing(staves,events,lines)
            self.assertEqual(events,before,mode)

    def test_multiple_voices_cross_hand_and_competing_stems_cannot_use_the_exception(self):
        for mode in ('voice','voice_warning','hand','stems'):
            staves,events,lines=fixture()
            if mode=='voice':events[0]['voice']='up';events[3]['voice']='down'
            elif mode=='voice_warning':events[0]['issues'].append('multiple_voices_require_review')
            elif mode=='hand':events[1]['hand']='left'
            else:
                other=deepcopy(events[3]);other['id']='other';other['rhythm_evidence']['stem'][0]+=2;events.insert(4,other)
            before=deepcopy(events);_recover_grace_principal_timing(staves,events,lines)
            self.assertEqual(events,before,mode)

    def test_manual_timing_and_confirmation_are_preserved(self):
        for mode in ('duration_beats','measure_beat','confirmed'):
            staves,events,lines=fixture()
            if mode=='confirmed':events[1]['confirmed']=True
            else:events[1]['manual_fields']=[mode]
            before=deepcopy(events);_recover_grace_principal_timing(staves,events,lines)
            self.assertEqual(events,before,mode)

    def test_unresolved_fallback_still_rejects_an_intervening_rest_even_with_a_slash(self):
        staves,events,lines=fixture();before=deepcopy(events)
        _mark_unresolved_slashed_graces(staves,events,lines)
        self.assertEqual(events,before)


if __name__=='__main__':unittest.main(verbosity=2)
