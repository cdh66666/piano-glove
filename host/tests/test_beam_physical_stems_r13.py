"""Independent synthetic shaft/beam evidence; no user PDF or answer tables."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_converter_engine import _recover_beam_from_physical_stems,_stem_beams


def event(identity,x,*,unknown=False,direction='up',shaft=None,y=None,**extra):
    if y is None:y=30 if direction=='up' else 10
    if shaft is None:shaft=[x+6,10,30] if direction=='up' else [x,10,30]
    n=dict(id=identity,staff='r',measure=1,hand='right',pitch_candidate='C4',origin=[x,y],
           duration=None if unknown else .125,beats=None if unknown else .125,
           issues=['beam_attachment_ambiguous'] if unknown else [],
           rhythm_evidence=dict(head='filled',stem=shaft))
    if not unknown:n['rhythm_evidence'].update(beams=3,dots=0,stem_direction=direction)
    n.update(extra);return n


def glyph(n,size=10,font='Aloisen'):
    x,y=n['origin'];return dict(char='Ŵ',x=x,y=y,bbox=[x,y-3,x+7,y+3],size=size,font=font)


def fixture(direction='up'):
    a=event('anchor',100,direction=direction)
    b=event('unknown',110,unknown=True,direction=direction)
    ax=a['rhythm_evidence']['stem'][0];bx=b['rhythm_evidence']['stem'][0]
    levels=(10,13.5,17) if direction=='up' else (23,26.5,30)
    lines=[(ax,y,bx,y,2.25) for y in levels]
    tip=10 if direction=='up' else 30
    lines.append((bx-5,tip-4,bx+5,tip+4,2.25))
    return [a,b],lines,[glyph(a),glyph(b)]


class PhysicalStemBeamTests(unittest.TestCase):
    def recover(self,notes,lines,chars,text=None):
        return _recover_beam_from_physical_stems([dict(id='r',gap=5)],notes,lines,chars,text)

    def test_one_anchor_unique_parallel_family_recovers_up_and_down(self):
        for direction in ('up','down'):
            notes,lines,chars=fixture(direction)
            stem=notes[1]['rhythm_evidence']['stem']
            self.assertIsNone(_stem_beams(stem,notes[1]['origin'][1],5,lines)[0])
            self.assertEqual(self.recover(notes,lines,chars),1,direction)
            self.assertEqual(notes[1]['duration'],.125)
            self.assertEqual(notes[1]['rhythm_evidence']['beam_recovery']['method'],
                             'unique_adjacent_shaft_beam_family')

    def test_same_physical_stem_recovers_displaced_chord_head(self):
        shaft=[106,10,35]
        a=event('known',100,y=35,shaft=shaft)
        b=event('displaced',107,y=30,shaft=shaft,unknown=True)
        notes=[a,b];chars=[glyph(a),glyph(b)]
        self.assertEqual(self.recover(notes,[],chars),1)
        self.assertEqual(b['duration'],.125)
        self.assertEqual(b['rhythm_evidence']['beam_recovery']['method'],'shared_original_stem')

    def test_small_head_needs_matching_normal_peer_and_retains_warning(self):
        notes,lines,chars=fixture();notes[1]['issues'].append('small_notated_note_requires_review')
        chars[0]['size']=8.5;chars[1]['size']=8.45
        self.assertEqual(self.recover(notes,lines,chars),1)
        self.assertIn('small_notated_note_requires_review',notes[1]['issues'])
        for change in ('grace_anchor','different_size','different_font','unknown_font','slashed'):
            notes,lines,chars=fixture();notes[1]['issues'].append('small_notated_note_requires_review')
            chars[0]['size']=8.5;chars[1]['size']=8.45
            if change=='grace_anchor':notes[0]['issues'].append('grace_or_cue_note_requires_review')
            elif change=='different_size':chars[1]['size']=6
            elif change=='different_font':chars[1]['font']='OtherMusic'
            elif change=='unknown_font':chars[1].pop('font')
            else:notes[1]['issues'].append('grace_or_cue_note_requires_review')
            before=deepcopy(notes);self.assertEqual(self.recover(notes,lines,chars),0,change)
            self.assertEqual(notes,before,change)

    def test_extra_hook_broken_beam_and_competing_families_remain_unknown(self):
        for change in ('hook','broken','two_families'):
            notes,lines,chars=fixture();ax=notes[0]['rhythm_evidence']['stem'][0];bx=notes[1]['rhythm_evidence']['stem'][0]
            if change=='hook':lines.append((bx,20.5,bx+6,20.5,2.25))
            elif change=='broken':lines=[(ax,y,bx-4,y,2.25) for y in (10,13.5,17)]+lines[-1:]
            else:lines += [(ax,y-1,bx,y,2.25) for y in (10,13.5,17)]
            before=deepcopy(notes);self.assertEqual(self.recover(notes,lines,chars),0,change)
            self.assertEqual(notes,before,change)

    def test_tuplet_intervening_rest_cross_hand_and_missing_glyph_stay_unknown(self):
        for change in ('tuplet','rest','cross_hand','no_glyph'):
            notes,lines,chars=fixture();text=[]
            if change=='tuplet':text=[dict(char='3',font='Text',bbox=[108,-2,112,2])]
            elif change=='rest':notes.append(dict(id='r0',staff='r',measure=1,origin=[112,20]))
            elif change=='cross_hand':notes[0]['hand']='left'
            else:chars.pop()
            before=deepcopy(notes);self.assertEqual(self.recover(notes,lines,chars,text),0,change)
            self.assertEqual(notes,before,change)

    def test_extra_voice_or_conflicting_beam_on_next_attached_stem_stays_unknown(self):
        for change in ('other_hand','other_direction','different_beam_count'):
            notes,lines,chars=fixture()
            other=event('outside',120)
            if change=='other_hand':other['hand']='left'
            elif change=='other_direction':
                other['origin'][1]=10;other['rhythm_evidence']['stem_direction']='down'
            else:other['rhythm_evidence']['beams']=2;other['duration']=other['beats']=.25
            notes.append(other);chars.append(glyph(other))
            lines=[(106,y,126,y,2.25) for y in (10,13.5,17)]+[(111,6,121,14,2.25)]
            before=deepcopy(notes);self.assertEqual(self.recover(notes,lines,chars),0,change)
            self.assertEqual(notes,before,change)

    def test_tuplet_over_connected_beam_beyond_anchor_pair_is_not_ignored(self):
        notes,lines,chars=fixture();other=event('outside',120);notes.append(other);chars.append(glyph(other))
        lines=[(106,y,126,y,2.25) for y in (10,13.5,17)]+[(111,6,121,14,2.25)]
        text=[dict(char='3',font='Text',bbox=[121,-2,125,2])]
        before=deepcopy(notes);self.assertEqual(self.recover(notes,lines,chars,text),0)
        self.assertEqual(notes,before)

    def test_explicit_target_hook_supports_mixed_eighth_and_sixteenth_group(self):
        notes,lines,chars=fixture();anchor,target=notes
        # The right-hand neighbour has two beams; the third level terminates at
        # the target. Full ink support on the left proves the target has three.
        other=event('outside',120);other['rhythm_evidence']['beams']=2
        other['duration']=other['beats']=.25;notes.append(other);chars.append(glyph(other))
        lines=[(106,y,126,y,2.25) for y in (10,13.5)]+[(106,17,116,17,2.25),
                                                       (111,6,121,14,2.25)]
        self.assertEqual(self.recover(notes,lines,chars),1)
        self.assertEqual(target['duration'],.125)

    def test_target_dotted_glyph_uses_its_own_dot(self):
        notes,lines,chars=fixture()
        chars.append(dict(char='Ǉ',x=116.5,y=30,bbox=[116,29,118,31],size=10,font='Aloisen'))
        self.assertEqual(self.recover(notes,lines,chars),1)
        self.assertEqual(notes[1]['duration'],.1875)

    def test_same_stem_conflicting_known_beam_counts_do_not_guess(self):
        shaft=[106,10,40]
        a=event('known',100,y=40,shaft=shaft)
        b=event('unknown',107,y=35,shaft=shaft,unknown=True)
        c=event('conflict',100,y=30,shaft=shaft)
        c['rhythm_evidence']['beams']=2;c['duration']=c['beats']=.25
        notes=[a,b,c];chars=[glyph(n) for n in notes]
        before=deepcopy(notes);self.assertEqual(self.recover(notes,[],chars),0)
        self.assertEqual(notes,before)

    def test_same_stem_conflicting_dots_are_not_silently_assumed(self):
        shaft=[106,10,35];a=event('known',100,y=35,shaft=shaft);b=event('unknown',107,y=30,shaft=shaft,unknown=True)
        chars=[glyph(a),glyph(b),dict(char='Ǉ',x=113,y=30,bbox=[112,29,114,31],size=10,font='Aloisen')]
        notes=[a,b];before=deepcopy(notes)
        self.assertEqual(self.recover(notes,[],chars),0)
        self.assertEqual(notes,before)

    def test_a_recovered_note_is_not_reused_as_a_new_anchor(self):
        notes,lines,chars=fixture();other=event('other-unknown',120,unknown=True)
        notes.append(other);chars.append(glyph(other))
        lines=[(106,y,126,y,2.25) for y in (10,13.5,17)]+[(111,6,121,14,2.25)]
        self.assertEqual(self.recover(notes,lines,chars),1)
        self.assertEqual(notes[1]['duration'],.125)
        self.assertIsNone(notes[2]['duration'])

    def test_recovered_duration_reaches_right_hand_pgl_without_a_fake_finger(self):
        from score_automatic import prepare_automatic_project,export_automatic
        from score_codec import decode,encode
        notes,lines,chars=fixture();self.assertEqual(self.recover(notes,lines,chars),1)
        for i,n in enumerate(notes):
            x,y=n['origin'];n.update(page=1,system=1,bbox=[x-2,y-2,x+7,y+3],
                pitch=('C4','D4')[i],finger=(1,2)[i],duration_beats=n['duration'],
                measure_beat=None,beat=None,confirmed=False,finger_source='printed')
        p=dict(name='独立梁组',notes=notes,rests=[],staves=[dict(id='r',hand='right',page=1,system=1,
            meter_beats=4,lines=[0,5,10,15,20],measures=[dict(measure=1,meter_beats=4,
                timing_resolved=False,length_beats=None)])],selection=dict(bpm=120,start_beat=0,repeat_mode='written'))
        prepare_automatic_project(p);self.assertTrue(p['automatic']['ready'])
        packed=decode(encode(export_automatic(p)))
        self.assertEqual([(x['pitch'],x['finger'],x['t_ms']) for x in packed['notes']],[(60,1,0),(62,2,62)])
        self.assertEqual(packed['duration_ms'],125)

    def test_scale_translate_and_renamed_ids_preserve_result(self):
        for factor in (.5,1.7,3):
            notes,lines,chars=fixture()
            for i,n in enumerate(notes):
                n['id']='new-'+str(i);n['origin']=[n['origin'][0]*factor+41,n['origin'][1]*factor+27]
                s=n['rhythm_evidence']['stem'];n['rhythm_evidence']['stem']=[s[0]*factor+41,s[1]*factor+27,s[2]*factor+27]
            for c in chars:
                c['x']=c['x']*factor+41;c['y']=c['y']*factor+27;c['size']*=factor
                c['bbox']=[v*factor+(41 if i%2==0 else 27) for i,v in enumerate(c['bbox'])]
            lines=[(a*factor+41,b*factor+27,c*factor+41,d*factor+27,w*factor) for a,b,c,d,w in lines]
            self.assertEqual(_recover_beam_from_physical_stems([dict(id='r',gap=5*factor)],notes,lines,chars),1)
            self.assertEqual(notes[1]['duration'],.125)


if __name__=='__main__':unittest.main()
