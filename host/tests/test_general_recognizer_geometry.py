"""Independent synthetic engraving tests: no corpus answers or PDF coordinates."""
from pathlib import Path
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import sys,tempfile,unittest,json
ROOT=Path(__file__).resolve().parent;HOST=ROOT.parent
sys.path.insert(0,str(HOST))
import score_converter_engine as engine
from recognizer_geometry import cross_staff_beam_hands,subdivided_beam_tuplets,digit_overlaps_attached_beam
from fingering_evidence import refine_fingering_evidence


def note(i,x,y=30,duration=.5,tip=70):
    return dict(id=str(i),origin=[x,y],glyph_bbox=[x,y-5,x+10,y+5],staff='upper',hand='right',
        measure=1,pitch_candidate='C5',duration=duration,beats=duration,measure_beat=None,
        rhythm_evidence={'head':'filled','beams':1,'stem':[x,y,tip],'stem_direction':'down'},
        issues=[],finger=None,finger_source=None,finger_candidates=[],source_fingering_state='unmarked')


class GenericGeometryTests(unittest.TestCase):
    def test_double_flat_reaches_real_recognizer_and_does_not_change_other_accidentals(self):
        # Independent synthetic treble G4 at the second staff line, with each
        # standard Aloisen accidental. The expected MIDI follows semitones.
        for glyph,semitones,spelling in [('ĥ',-2,'Gbb4'),('Ģ',-1,'Gb4'),('ģ',0,'G4'),('ġ',1,'G#4'),('Ĥ',2,'G##4')]:
            chars=[dict(char='ƀ',x=110,y=130,size=20,bbox=[110,90,125,160],font='Aloisen'),
                   dict(char=glyph,x=185,y=130,size=20,bbox=[185,110,198,140],font='Aloisen'),
                   dict(char='Ŵ',x=200,y=130,size=20,bbox=[200,125,212,135],font='Aloisen')]
            lines=[(100,y,550,y,1) for y in (100,110,120,130,140)]+[(211.4,100,211.4,130,1)]
            page=SimpleNamespace(rect=SimpleNamespace(width=612,height=792),page=None,
                chars=lambda music_only=True:deepcopy(chars),geometry=lambda:(lines,[]))
            @contextmanager
            def fake_open(_):yield [page]
            with tempfile.TemporaryDirectory() as tmp:
                pdf=Path(tmp)/'synthetic.pdf';pdf.write_bytes(b'synthetic geometry')
                with patch.object(engine,'open_document',fake_open):result=engine.recognize(pdf)
            self.assertEqual(len(result['notes']),1)
            self.assertEqual((result['notes'][0]['midi'],result['notes'][0]['pitch']),(67+semitones,spelling))

    def test_continuous_beam_requires_every_partition_to_have_its_own_marker(self):
        for scale,offset in [(1,0),(.5,230),(3,-500)]:
            notes=[note(i,offset+x*scale,y=30*scale,tip=70*scale) for i,x in enumerate((0,20,40,60,80,100))]
            line=(offset,70*scale,offset+100*scale,70*scale,4.5*scale)
            markers=[dict(char='3',font='Text',bbox=[offset+(x-3)*scale,78*scale,offset+(x+3)*scale,86*scale]) for x in (20,80)]
            subdivided_beam_tuplets(notes,{'gap':10*scale},[line],markers)
            self.assertEqual([n['duration'] for n in notes],[1/3]*6)
            negative=[note(i,offset+x*scale,y=30*scale,tip=70*scale) for i,x in enumerate((0,20,40,60,80,100))]
            subdivided_beam_tuplets(negative,{'gap':10*scale},[line],markers[:1])
            self.assertEqual([n['duration'] for n in negative],[.5]*6)

    def test_beam_partition_rejects_fingering_font_and_inconsistent_nominal_values(self):
        notes=[note(i,x) for i,x in enumerate((0,20,40,60,80,100))]
        markers=[dict(char='3',font='Aloisen',bbox=[x-3,78,x+3,86]) for x in (20,80)]
        subdivided_beam_tuplets(notes,{'gap':10},[(0,70,100,70,4.5)],markers)
        self.assertTrue(all(n['duration']==.5 for n in notes))
        for c in markers:c['font']='Text'
        notes[-1]['duration']=.25
        subdivided_beam_tuplets(notes,{'gap':10},[(0,70,100,70,4.5)],markers)
        self.assertEqual(notes[0]['duration'],.5)

    def test_dense_text_fingering_run_is_not_a_pair_of_triplet_markers(self):
        notes=[note(i,x,duration=.125) for i,x in enumerate((0,4,8,12,16,20))]
        labels=[dict(char=c,font='Text',bbox=[x-1.5,78,x+1.5,86])
                for x,c in zip((0,4,8,12,16,20),'321321')]
        subdivided_beam_tuplets(notes,{'gap':10},[(0,70,20,70,4.5)],labels)
        self.assertTrue(all(n['duration']==.125 for n in notes))

    def test_closed_tuplet_bracket_can_include_a_rest_without_making_extra_notes(self):
        for scale in (.5,1,3):
            notes=[note(i,x*scale,y=30*scale,duration=.25,tip=70*scale) for i,x in enumerate((30,50))]
            rest=dict(id='r',origin=[10*scale,50*scale],measure=1,bbox=[8*scale,40*scale,14*scale,60*scale],duration=.25,rhythm_evidence={})
            marker=dict(char='3',font='Text',bbox=[32*scale,75*scale,38*scale,85*scale])
            lines=[tuple(v*scale for v in l) for l in [(10,80,30,80,1),(40,80,55,80,1),(10,80,10,77,1),(55,80,55,77,1)]]
            engine._apply_bracketed_tuplets(notes,[rest],{'gap':10*scale},lines,[marker])
            self.assertEqual([n['duration'] for n in notes]+[rest['duration']],[1/6]*3)
            self.assertEqual(rest['rhythm_evidence']['tuplet']['actual'],3)
            self.assertEqual(len(notes),2)

    def test_rest_tuplet_requires_caps_and_unique_group_count(self):
        for no_cap,extra_rest in [(True,False),(False,True)]:
            notes=[note(i,x,duration=.25) for i,x in enumerate((30,50))]
            rests=[dict(id='r',origin=[10,50],measure=1,bbox=[8,40,14,60],duration=.25,rhythm_evidence={})]
            if extra_rest:rests.append(dict(id='r2',origin=[20,50],measure=1,bbox=[18,40,24,60],duration=.25,rhythm_evidence={}))
            marker=dict(char='3',font='Text',bbox=[32,75,38,85])
            lines=[(10,80,30,80,1),(40,80,55,80,1),(10,80,10,77,1),(55,80,55,77,1)]
            if no_cap:lines.pop()
            engine._apply_bracketed_tuplets(notes,rests,{'gap':10},lines,[marker])
            self.assertTrue(all(n['duration']==.25 for n in notes+rests))

    def test_remote_head_uses_beam_voice_but_keeps_printed_staff(self):
        for scale,offset in [(1,0),(.5,300),(3,-150)]:
            upper=dict(id='upper',gap=10*scale,top=50*scale,bottom=90*scale,hand='right',system=1,upper_partner=None)
            lower=dict(id='lower',gap=10*scale,top=200*scale,bottom=240*scale,hand='left',system=1,upper_partner=0)
            heads=[dict(x=offset+x*scale,y=y*scale) for x,y in [(20,90),(40,95),(60,220)]]
            upper['heads']=heads[:2];lower['heads']=heads[2:]
            rhythms={id(h):(.5,{'stem':[h['x'],70*scale,h['y']],'stem_direction':'up','beams':1},[]) for h in heads}
            result=cross_staff_beam_hands([upper,lower],rhythms,[(offset+20*scale,70*scale,offset+60*scale,70*scale,4.5*scale)])
            self.assertEqual(set(result),{id(heads[2])})
            self.assertEqual(result[id(heads[2])]['voice_staff'],'upper')
            self.assertEqual(lower['hand'],'left')

    def test_cross_staff_requires_two_anchor_stems_and_actual_attachment(self):
        upper=dict(id='u',gap=10,top=50,bottom=90,hand='right',system=1,upper_partner=None,heads=[dict(x=20,y=90)])
        lower=dict(id='l',gap=10,top=200,bottom=240,hand='left',system=1,upper_partner=0,heads=[dict(x=60,y=220)])
        rhythms={id(h):(.5,{'stem':[h['x'],70,h['y']],'stem_direction':'up','beams':1},[]) for s in (upper,lower) for h in s['heads']}
        self.assertEqual(cross_staff_beam_hands([upper,lower],rhythms,[(20,70,60,70,4.5)]),{})

    def test_overlapping_digit_loses_auto_assignment_but_manual_and_clear_digit_survive(self):
        digit=dict(char='ı',font='Aloisen',x=100,y=68,size=12,bbox=[100,63,106,73])
        lines=[(100,70,180,70,4.5),(100,64,112,64,4.5)]
        for source,confirmed,manual in [('printed',False,[]),('manual',False,['finger']),('printed',True,[])]:
            event=note(1,100);event['rhythm_evidence']['beams']=2
            event.update(finger=1,finger_source=source,finger_bbox=digit['bbox'],confirmed=confirmed,manual_fields=manual)
            group=[event];staff={'gap':10}
            refine_fingering_evidence([(staff,group,[group])],[staff],[digit],{},[],lines)
            self.assertEqual(event['finger'],None if source=='printed' and not confirmed else 1)
            if event['finger'] is None:self.assertEqual(event['source_fingering_state'],'unresolved')
        clear=dict(digit,bbox=[100,80,106,90],y=85)
        self.assertFalse(digit_overlaps_attached_beam(clear,[note(1,100)],10,lines))
        # A real finger can collide with one primary beam in old engravings;
        # this is insufficient evidence to retract the original assignment.
        self.assertFalse(digit_overlaps_attached_beam(digit,[note(1,100)],10,lines))

    def test_internal_small_ornament_needs_complete_principal_and_paired_voice(self):
        for valid in (True,False):
            staves=[dict(id=s,gap=10,measures=[dict(measure=1,meter_beats=4,timing_resolved=resolved)])
                    for s,resolved in [('upper',False),('lower',True)]]
            notes=[note(i,x,duration=1) for i,x in enumerate((10,40,70,100))]
            small=note('small',55,duration=.25);small['issues']=['small_notated_note_requires_review']
            notes.insert(2,small)
            for i,x in enumerate((10,40,70,100)):
                lower=note('l'+str(i),x,duration=1);lower.update(staff='lower',measure_beat=i)
                if not valid and i==2:lower['measure_beat']=2.5
                notes.append(lower)
            engine._recover_grace_principal_timing(staves,notes,[])
            self.assertEqual(small['duration'],None if valid else .25)
            if valid:
                self.assertEqual(small['grace_kind'],'unmeasured')
                self.assertEqual(small['main_anchor_id'],'2')
                self.assertEqual(small['grace_nominal_duration_beats'],.25)

    def test_small_notes_without_a_complete_principal_measure_stay_metered(self):
        staves=[dict(id='upper',gap=10,measures=[dict(measure=1,meter_beats=4,timing_resolved=False)])]
        notes=[note(i,x,duration=1) for i,x in enumerate((10,40,70))]
        small=note('small',55,duration=.25);small['issues']=['small_notated_note_requires_review'];notes.append(small)
        engine._recover_grace_principal_timing(staves,notes,[])
        self.assertEqual(small['duration'],.25)
        self.assertNotIn('grace_kind',small)


if __name__=='__main__':
    unittest.main(verbosity=2)
