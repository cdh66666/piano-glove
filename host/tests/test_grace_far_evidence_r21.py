"""Independent distant-grace controls using real synthetic slash geometry."""
from pathlib import Path
from copy import deepcopy
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_converter_engine import _mark_unresolved_slashed_graces,_has_grace_slash


def fixture(scale=1,dx=0,dy=0):
    gap=6*scale;x=200*scale+dx;y=80*scale+dy;sx=x+1.2*gap
    grace=dict(id='ornament',staff='r',measure=1,hand='right',pitch_candidate='D5',origin=[x,y],
        duration=.25,beats=.25,measure_beat=None,issues=['grace_or_cue_note_requires_review'],
        rhythm_evidence={'head':'filled','stem':[sx,y-4*gap,y],'stem_direction':'up','beams':2})
    main=dict(id='principal',staff='r',measure=1,hand='right',pitch_candidate='C5',origin=[x+10*gap,y],
        duration=1,beats=1,measure_beat=2,issues=[],rhythm_evidence={})
    slash=(sx-.8*gap,y-2.5*gap,sx+.8*gap,y-3.5*gap,.12*gap)
    return [dict(id='r',gap=gap)],[grace,main],slash


class DistantGraceEvidenceTests(unittest.TestCase):
    def test_actual_stem_crossing_slash_can_anchor_a_distant_principal(self):
        for scale,dx,dy in [(1,0,0),(.5,75,-20),(3,-450,120)]:
            staves,events,slash=fixture(scale,dx,dy);grace,main=events
            self.assertTrue(_has_grace_slash(grace['rhythm_evidence'],[slash],staves[0]['gap']))
            _mark_unresolved_slashed_graces(staves,events,[slash])
            self.assertIsNone(grace['duration']);self.assertIsNone(grace['beats'])
            self.assertEqual(grace['grace_nominal_duration_beats'],.25)
            self.assertEqual(grace['main_anchor_id'],main['id'])
            self.assertEqual(main['duration'],1)

    def test_review_issue_without_a_crossing_thin_diagonal_cannot_extend_anchor(self):
        for mode in ('absent','beside_stem','horizontal','thick'):
            staves,events,slash=fixture();before=deepcopy(events);a,b,c,d,w=slash
            if mode=='absent':lines=[]
            elif mode=='beside_stem':lines=[(a-30,b,c-30,d,w)]
            elif mode=='horizontal':lines=[(a,b,c,b,w)]
            else:lines=[(a,b,c,d,staves[0]['gap'])]
            _mark_unresolved_slashed_graces(staves,events,lines)
            self.assertEqual(events,before,mode)

    def test_true_slash_does_not_override_a_rest_or_a_different_hand(self):
        for mode in ('rest','hand'):
            staves,events,slash=fixture()
            if mode=='rest':
                events.append(dict(id='rest',staff='r',measure=1,origin=[events[0]['origin'][0]+24,80]))
            else:events[1]['hand']='left'
            before=deepcopy(events)
            _mark_unresolved_slashed_graces(staves,events,[slash])
            self.assertEqual(events,before,mode)


if __name__=='__main__':unittest.main()
