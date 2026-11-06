"""Synthetic slashed grace and independently anchored beam geometry."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_converter_engine import _mark_unresolved_slashed_graces,_recover_clear_beam_family,_stem_beams


def event(ident,x,**changes):
    obj=dict(id=ident,staff='r',measure=1,hand='right',pitch_candidate='C4',origin=[x,30],
        duration=.125,beats=.125,measure_beat=None,issues=[],
        rhythm_evidence=dict(head='filled',stem=[x+6,10,30],stem_direction='up',beams=3,dots=0))
    obj.update(changes);return obj


def beam_fixture():
    left=event('left',100);right=event('right',120)
    target=event('target',110,duration=None,beats=None,issues=['beam_attachment_ambiguous'],
                 rhythm_evidence=dict(head='filled',stem=[116,10,30]))
    chars=[dict(char='Ŵ',x=x,y=30,bbox=[x,27,x+7,33]) for x in (100,110,120)]
    lines=[(106,y,126,y,2.25) for y in (10,13.5,17)]+[(106,6,126,14,2.25)]
    return [left,target,right],lines,chars


class UnmeasuredGraceTests(unittest.TestCase):
    def test_confirmed_slash_retains_nominal_and_anchors_unique_principal(self):
        grace=event('g',100,issues=['grace_or_cue_note_requires_review'])
        main=event('main',110,duration=1,beats=1,measure_beat=2)
        _mark_unresolved_slashed_graces([dict(id='r',gap=5)],[grace,main])
        self.assertEqual(grace['grace_kind'],'slashed')
        self.assertIsNone(grace['duration']);self.assertIsNone(grace['beats'])
        self.assertEqual(grace['grace_nominal_duration_beats'],.125)
        self.assertEqual(grace['main_anchor_id'],'main');self.assertEqual(grace['main_anchor_measure_beat'],2)
        self.assertEqual(main['duration'],1)

    def test_several_slashed_notes_share_one_main_chord_anchor(self):
        a=event('a',100,issues=['grace_or_cue_note_requires_review'])
        b=event('b',106,issues=['grace_or_cue_note_requires_review'])
        c=event('c',116,duration=1,beats=1);d=event('d',116,duration=1,beats=1,origin=[116,25])
        _mark_unresolved_slashed_graces([dict(id='r',gap=5)],[a,b,c,d])
        self.assertEqual([a['grace_order'],b['grace_order']],[0,1])
        self.assertEqual(a['main_anchor_ids'],['c','d']);self.assertEqual(b['main_anchor_ids'],['c','d'])

    def test_small_cue_far_target_cross_hand_and_intervening_rest_remain_unchanged(self):
        for change in ('cue','far','hand','rest'):
            grace=event('g',100,issues=['grace_or_cue_note_requires_review'])
            main=event('main',110,duration=1,beats=1)
            events=[grace,main]
            if change=='cue':grace['issues']=['small_notated_note_requires_review']
            elif change=='far':main['origin'][0]=150
            elif change=='hand':main['hand']='left'
            else:events.insert(1,dict(id='rest',staff='r',measure=1,origin=[105,30]))
            before=deepcopy(events)
            _mark_unresolved_slashed_graces([dict(id='r',gap=5)],events)
            self.assertEqual(events,before,change)


class BracketedBeamEvidenceTests(unittest.TestCase):
    def test_unique_family_crossing_three_stems_resolves_crossing_line(self):
        notes,lines,chars=beam_fixture()
        self.assertIsNone(_stem_beams(notes[1]['rhythm_evidence']['stem'],30,5,lines)[0])
        self.assertEqual(_recover_clear_beam_family([dict(id='r',gap=5)],notes,lines,chars),1)
        self.assertEqual(notes[1]['duration'],.125)
        self.assertEqual(notes[1]['rhythm_evidence']['beams'],3)
        self.assertEqual(notes[1]['rhythm_evidence']['beam_recovery']['anchor_ids'],['left','right'])
        self.assertNotIn('beam_attachment_ambiguous',notes[1]['issues'])

    def test_target_dot_is_preserved_from_actual_printed_glyph(self):
        notes,lines,chars=beam_fixture();chars.append(dict(char='Ǉ',x=116.5,y=30,bbox=[116,29,118,31]))
        self.assertEqual(_recover_clear_beam_family([dict(id='r',gap=5)],notes,lines,chars),1)
        self.assertEqual(notes[1]['duration'],.1875);self.assertEqual(notes[1]['rhythm_evidence']['dots'],1)

    def test_no_consensus_or_disconnected_hooks_remains_unknown(self):
        for change in ('different_beams','different_hand','disconnected','different_family','grace','no_glyph'):
            notes,lines,chars=beam_fixture()
            if change=='different_beams':notes[2]['rhythm_evidence']['beams']=2;notes[2]['duration']=.25
            elif change=='different_hand':notes[2]['hand']='left'
            elif change=='disconnected':lines=[(110,y,122,y,2.25) for y in (10,13.5,17)]
            elif change=='different_family':lines=lines[:3]+[(106,y-1,126,y+1,2.25) for y in (10,13.5,17)]
            elif change=='grace':notes[1]['issues'].append('grace_or_cue_note_requires_review')
            else:chars=[c for c in chars if c['x']!=110]
            before=deepcopy(notes)
            self.assertEqual(_recover_clear_beam_family([dict(id='r',gap=5)],notes,lines,chars),0,change)
            self.assertEqual(notes,before,change)

    def multi_fixture(self):
        notes=[event('left',100),event('unknown-a',110,duration=None,beats=None,
                    issues=['beam_attachment_ambiguous'],rhythm_evidence=dict(head='filled',stem=[116,10,30])),
               event('unknown-b',120,duration=None,beats=None,
                    issues=['beam_attachment_ambiguous'],rhythm_evidence=dict(head='filled',stem=[126,10,30])),
               event('right',130)]
        chars=[dict(char='Ŵ',x=x,y=30,bbox=[x,27,x+7,33]) for x in (100,110,120,130)]
        lines=[(start,y,end,y,2.25) for y in (10,13.5,17)
               for start,end in ((106,116),(116,126),(126,136))]
        # One unrelated crossing line makes the first shaft ambiguous in the
        # low-level reader, but does not establish a second full beam family.
        lines.append((106,6,136,18,2.25))
        return notes,lines,chars

    def test_two_unknown_middle_notes_recover_from_original_outer_anchors(self):
        notes,lines,chars=self.multi_fixture()
        self.assertIsNone(_stem_beams(notes[1]['rhythm_evidence']['stem'],30,5,lines)[0])
        self.assertEqual(_recover_clear_beam_family([dict(id='r',gap=5)],notes,lines,chars),2)
        self.assertEqual([n['duration'] for n in notes],[.125,.125,.125,.125])
        for n in notes[1:3]:
            self.assertEqual(n['rhythm_evidence']['beam_recovery']['anchor_ids'],['left','right'])
            self.assertEqual(n['rhythm_evidence']['beam_recovery']['segment_count'],9)

    def test_segmented_family_allows_small_ink_join_but_not_a_broken_beam(self):
        notes,lines,chars=self.multi_fixture()
        # Ink-width tolerance permits one small endpoint gap on every beam.
        lines=[(a+(.8 if a==116 else 0),b,c,d,w) for a,b,c,d,w in lines]
        self.assertEqual(_recover_clear_beam_family([dict(id='r',gap=5)],notes,lines,chars),2)
        notes,lines,chars=self.multi_fixture()
        # A visible gap larger than the stroke width prevents the family from
        # physically spanning the entire group; preserve both unknown values.
        lines=[(a+(3 if a==116 else 0),b,c,d,w) for a,b,c,d,w in lines]
        before=deepcopy(notes)
        self.assertEqual(_recover_clear_beam_family([dict(id='r',gap=5)],notes,lines,chars),0)
        self.assertEqual(notes,before)

    def test_small_drawing_slope_differences_are_one_family_not_competitors(self):
        notes,lines,chars=self.multi_fixture()
        lines=[]
        for y in (10,13.5,17):
            lines.extend([(106,y,116,y,2.25),(116,y,126,y+.1,2.25),
                          (126,y+.1,136,y+.2,2.25)])
        lines.append((106,6,136,18,2.25))
        self.assertEqual(_recover_clear_beam_family([dict(id='r',gap=5)],notes,lines,chars),2)
        self.assertEqual([n['duration'] for n in notes],[.125,.125,.125,.125])

    def test_beam_recovery_is_scale_and_translation_invariant(self):
        for factor in (.5,1.7,3):
            notes,lines,chars=self.multi_fixture()
            for index,n in enumerate(notes):
                n['id']='other-'+str(index)
                n['origin']=[n['origin'][0]*factor+41,n['origin'][1]*factor+27]
                shaft=n['rhythm_evidence']['stem']
                n['rhythm_evidence']['stem']=[shaft[0]*factor+41,shaft[1]*factor+27,shaft[2]*factor+27]
            for c in chars:
                c['x']=c['x']*factor+41;c['y']=c['y']*factor+27
                c['bbox']=[v*factor+(41 if i%2==0 else 27) for i,v in enumerate(c['bbox'])]
            lines=[(a*factor+41,b*factor+27,c*factor+41,d*factor+27,w*factor) for a,b,c,d,w in lines]
            self.assertEqual(_recover_clear_beam_family([dict(id='r',gap=5*factor)],notes,lines,chars),2,factor)
            self.assertEqual([n['duration'] for n in notes],[.125,.125,.125,.125])

    def test_mixed_hand_voice_extra_hook_and_competing_families_stay_unknown(self):
        for change in ('cross_hand','mixed_voice','partially_known_voice','opposite_stem','extra_hook','two_families','rest'):
            notes,lines,chars=self.multi_fixture()
            if change=='cross_hand':notes[2]['hand']='left'
            elif change=='mixed_voice':notes[0]['voice']='up';notes[-1]['voice']='down'
            elif change=='partially_known_voice':notes[0]['voice']='up'
            elif change=='opposite_stem':notes[2]['origin'][1]=10;chars[2]['y']=10
            elif change=='extra_hook':lines.append((116,20.5,122,20.5,2.25))
            elif change=='two_families':lines += [(106,y-1,136,y+2,2.25) for y in (10,13.5,17)]
            else:notes.append(dict(id='rest',staff='r',measure=1,origin=[121,30]))
            before=deepcopy(notes)
            self.assertEqual(_recover_clear_beam_family([dict(id='r',gap=5)],notes,lines,chars),0,change)
            self.assertEqual(notes,before,change)

    def test_nearby_printed_tuplet_blocks_unqualified_nominal_recovery(self):
        notes,lines,chars=self.multi_fixture()
        marker=dict(char='3',font='Text',bbox=[119,-2,123,2])
        before=deepcopy(notes)
        self.assertEqual(_recover_clear_beam_family([dict(id='r',gap=5)],notes,lines,chars,chars+[marker]),0)
        self.assertEqual(notes,before)


if __name__=='__main__':unittest.main()
