"""Generic synthetic printed tremolos; no customer PDF inputs."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_converter_engine import _resolve_mixed_tremolo_measure


def note(ident,x,y,duration,**changes):
    d=dict(id=ident,origin=[x,y],measure=1,hand='right',duration=duration,measure_beat=None,
           rhythm_evidence=dict(head='half' if duration==2 else 'filled',beams=0),
           issues=['measure_timing_unresolved'])
    d.update(changes);return d


def strokes(lo,hi,y=30,slope=.1):
    return [(lo,y+offset,hi,y+offset+(hi-lo)*slope,2.25) for offset in (0,3.5,7)]


def musical_bar():
    notes=[note('a',100,30,2),note('a-chord',100,40,2),note('b',140,35,2),
           note('c',190,30,1),note('d',230,40,1),note('tail',280,30,.5)]
    rests=[dict(id='rest',origin=[300,30],duration=.5,measure_beat=None,issues=['measure_timing_unresolved'])]
    return notes,rests,strokes(110,130)+strokes(200,220)


class MixedTremoloTests(unittest.TestCase):
    def test_two_alternations_plus_note_and_rest_fit_one_four_beat_bar(self):
        notes,rests,lines=musical_bar()
        result=_resolve_mixed_tremolo_measure(notes,rests,{'gap':5},4,lines)
        self.assertIsNotNone(result);self.assertEqual(result['total_beats'],4)
        self.assertEqual([n['measure_beat'] for n in notes],[0,0,0,2,2,3])
        self.assertEqual(rests[0]['measure_beat'],3.5)
        self.assertEqual([n.get('tremolo_side') for n in notes],[0,0,1,0,1,None])
        self.assertEqual([n.get('tremolo_span_beats') for n in notes],[2,2,2,1,1,None])
        self.assertEqual([n.get('tremolo_step_beats') for n in notes],[.125,.125,.125,.125,.125,None])
        self.assertNotEqual(notes[0]['tremolo_group'],notes[3]['tremolo_group'])
        self.assertEqual([n['duration'] for n in notes],[2,2,2,1,1,.5])

    def test_nearby_ordinary_beams_and_cross_hand_cannot_trigger(self):
        for change in ('thin','beamed','cross_hand','rest_between','bad_slope','incomplete'):
            notes,rests,lines=musical_bar()
            if change=='thin':lines=[(*line[:4],.5) for line in lines]
            elif change=='beamed':
                for n in notes:n['rhythm_evidence']['beams']=1
            elif change=='cross_hand':
                notes[2]['hand']='left';notes[4]['hand']='left'
            elif change=='rest_between':rests.append(dict(id='intervening',origin=[120,30],duration=.25,issues=[]))
            elif change=='bad_slope':lines=[(a,b,c,d+(4 if i%3==1 else 0),w) for i,(a,b,c,d,w) in enumerate(lines)]
            else:rests[0]['duration']=None
            before=deepcopy((notes,rests))
            self.assertIsNone(_resolve_mixed_tremolo_measure(notes,rests,{'gap':5},4,lines),change)
            self.assertEqual((notes,rests),before,change)

    def test_same_stem_displaced_chord_heads_form_one_alternation_side(self):
        notes,rests,lines=musical_bar()
        for n in notes[:2]:n['rhythm_evidence']['stem']=[106,10,45]
        notes[1]['origin'][0]=106
        result=_resolve_mixed_tremolo_measure(notes,rests,{'gap':5},4,lines)
        self.assertIsNotNone(result)
        self.assertEqual([n['measure_beat'] for n in notes[:3]],[0,0,0])

    def test_scale_translation_and_note_renaming_preserve_intervals(self):
        for factor in (.5,1.7,3):
            notes,rests,lines=musical_bar()
            for index,n in enumerate(notes+rests):
                n['id']='unrelated-'+str(index)
                n['origin']=[n['origin'][0]*factor+41,n['origin'][1]*factor+27]
            lines=[(a*factor+41,b*factor+27,c*factor+41,d*factor+27,w*factor) for a,b,c,d,w in lines]
            result=_resolve_mixed_tremolo_measure(notes,rests,{'gap':5*factor},4,lines)
            self.assertIsNotNone(result,factor)
            self.assertEqual([n['measure_beat'] for n in notes],[0,0,0,2,2,3])

    def test_real_tremolo_unresolved_if_measure_is_incomplete(self):
        notes,rests,lines=musical_bar();rests[0]['duration']=1
        before=deepcopy((notes,rests))
        self.assertIsNone(_resolve_mixed_tremolo_measure(notes,rests,{'gap':5},4,lines))
        self.assertEqual((notes,rests),before)

    def test_recognized_pairs_survive_right_hand_reflow_and_playable_export(self):
        from score_automatic import prepare_automatic_project,export_automatic
        from score_codec import decode,encode
        notes,rests,lines=musical_bar()
        self.assertIsNotNone(_resolve_mixed_tremolo_measure(notes,rests,{'gap':5},4,lines))
        for n,pitch,finger in zip(notes,('C4','E4','G4','A4','B4','C5'),(1,2,3,4,5,1)):
            x,y=n['origin']
            n.update(page=1,system=1,staff='r',pitch=pitch,finger=finger,finger_source='printed',
                     bbox=[x-2,y-2,x+2,y+2],duration_beats=n['duration'])
        for r in rests:
            x,y=r['origin'];r.update(page=1,system=1,measure=1,staff='r',hand='right',
                                     bbox=[x-2,y-2,x+2,y+2],duration_beats=r['duration'])
        p=dict(name='独立合成交替震音',notes=notes,rests=rests,
               staves=[dict(id='r',page=1,system=1,hand='right',meter_beats=4,
                            lines=[10,15,20,25,30],measures=[dict(measure=1,meter_beats=4,
                            timing_resolved=True,length_beats=4)])],
               selection=dict(bpm=120,start_beat=0,repeat_mode='written'))
        prepare_automatic_project(p)
        self.assertEqual([n['beat'] for n in notes],[0,0,0,2,2,3])
        self.assertTrue(p['automatic']['ready'],p['automatic'])
        encoded=decode(encode(export_automatic(p)))
        self.assertEqual(len(encoded['notes']),33)
        self.assertEqual(encoded['notes'][-1]['t_ms'],1500)
        self.assertEqual(encoded['duration_ms'],2000)


if __name__=='__main__':unittest.main()
