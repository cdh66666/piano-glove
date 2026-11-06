"""Independent notation controls. No PDF, filename, corpus ID, or source gold."""
from copy import deepcopy
import json,sys,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent;HOST=HERE.parent.parent.parent/'repo/host'
sys.path.insert(0,str(HOST));sys.path.insert(0,str(HERE))
import score_converter_engine as E
import score_marks as M
from score_realization import realize_project

def head(x,y):return dict(char='Ŵ',font='Aloisen',size=12.,x=x,y=y,bbox=[x,y-2.4,x+7.2,y+2.4])
def crossed_heads():
    heads=[head(55.,120.),head(55.,114.)]
    lines=[(61.6,84.,61.6,119.7,.6),(61.6,84.,95.,84.,2.4),(55.3,114.3,55.3,140.4,.6)]
    flag=dict(char='ř',font='Aloisen',size=12.,x=55.,y=114.6,bbox=[55.,117.,61.5,141.])
    return heads,lines,[flag]
def recover(heads,lines,extra,force=False):
    chars=heads+extra;staff=dict(gap=6.,heads=heads)
    result={id(h):E._stem_and_duration(h,staff,lines,chars) for h in heads}
    if force:result[id(heads[0])]=(None,{'head':'filled'},['stem_not_resolved'])
    before=deepcopy(result);E._recover_explicit_physical_rhythms([staff],result,lines,chars)
    return result[id(heads[0])],before[id(heads[0])]

def staff(ident,hand,top):
    return dict(id=ident,page=1,system=1,hand=hand,left=20,right=300,top=top,bottom=top+40,gap=10,
        lines=[top+i*10 for i in range(5)],bbox=[20,top,300,top+40],measures=[dict(measure=1,meter_beats=3,
        metric_extent_evidence=dict(method='explicit_meter_shared_ordinary_barlines',quarter_beats=3,boundary_x=[20,300]))])
def note(ident,hand,x,y,duration,beat,stem=None,direction=None,kind='filled',midi=60,marks=()):
    return dict(id=ident,page=1,system=1,measure=1,staff='right' if hand=='right' else 'left',hand=hand,
        pitch='C4',midi=midi,finger=1,source_fingering_state='printed',origin=[x,y],glyph_bbox=[x,y-4,x+12,y+4],
        duration=duration,duration_beats=duration,beat=beat,measure_beat=beat-7 if beat is not None else None,
        measure_start_beat=7 if beat is not None else None,rhythm_evidence=dict(head=kind,stem=stem,stem_direction=direction),
        performance_marks=list(marks),issues=[])
def mark(gid,char='Ʋ',box=(245,40,265,50)):
    return dict(kind='fermata',group_id=gid,source=dict(font='Aloisen',char=char,bbox=list(box)),options={})
def pause_fixture():
    right=staff('right','right',50);left=staff('left','left',150)
    notes=[note('start','right',50,80,1,7,[60,45,80],'up'),note('middle','right',150,80,1,8,[160,45,80],'up'),
        note('end','right',250,80,.5,9.5,[260,45,80],'up',marks=[mark('terminal')]),
        note('lh-up','left',50,170,1,None,[61,140,170],'up',midi=48),
        note('lh-hold','left',62,170,3,None,[62.5,170,200],'down','open',48,[mark('sustained','Ƴ',(58,205,78,215))])]
    follow=note('follow','right',50,80,1,10,[60,45,80],'up');follow.update(measure=2,measure_beat=0,measure_start_beat=10);notes.append(follow)
    return dict(name='Independent notation',notes=notes,rests=[],staves=[right,left],performance_spans=[],
        selection=dict(bpm=120,start_beat=0,repeat_mode='written'),performance_policy=dict(mode='practice'))

class StemOwnershipControls(unittest.TestCase):
    def test_terminal_beam_excludes_crossing_flag_with_own_head(self):
        hs,ls,flags=crossed_heads();after,before=recover(hs,ls,flags)
        self.assertIsNone(before[0]);self.assertEqual(after[0],.5);self.assertEqual(after[1]['stem_direction'],'up')
        self.assertEqual(len(after[1]['beam_recovery']['discarded_crossing_flag_shafts']),1)
    def test_actual_second_beam_changes_to_sixteenth(self):
        hs,ls,flags=crossed_heads();ls.append((61.6,87.6,95.,87.6,2.4));self.assertEqual(recover(hs,ls,flags)[0][0],.25)
    def test_missing_flag_owner_remains_unknown(self):
        hs,ls,flags=crossed_heads();self.assertIsNone(recover(hs[:1],ls,flags)[0][0])
    def test_missing_owner_shaft_remains_unknown(self):
        hs,ls,flags=crossed_heads();self.assertIsNone(recover(hs,ls[:2],flags)[0][0])
    def test_other_font_owner_is_insufficient(self):
        hs,ls,flags=crossed_heads();hs[1]['font']='Other';self.assertIsNone(recover(hs,ls,flags)[0][0])
    def test_own_terminal_flag_does_not_trigger_foreign_shaft_recovery(self):
        hs,ls,flags=crossed_heads();ls[2]=(55.3,119.7,55.3,145.,.6);flags[0].update(y=120.,bbox=[55.,123.,61.5,146.])
        after,_=recover(hs,ls,flags,True);self.assertEqual(after[0],.5)
        self.assertNotIn('discarded_crossing_flag_shafts',after[1].get('beam_recovery',{}))
    def test_competing_beamed_voice_stays_ambiguous(self):
        hs,ls,flags=crossed_heads();ls.append((55.3,140.4,95.,140.4,2.4));self.assertIsNone(recover(hs,ls,flags)[0][0])
    def test_geometry_is_unchanged(self):
        hs,ls,flags=crossed_heads();before=deepcopy((hs,ls,flags));recover(hs,ls,flags);self.assertEqual((hs,ls,flags),before)

class FermataOwnershipControls(unittest.TestCase):
    def test_inverted_between_staves_belongs_to_upper_music(self):
        upper=staff('right','right',50);lower=staff('left','left',150)
        a=note('upper','right',80,100,1,7,[80.5,100,125],'down');b=note('lower','left',80,150,1,None,[90,115,150],'up')
        symbol=dict(char='Ƴ',font='Aloisen',x=77,y=140,size=20,bbox=[77,129,100,140])
        choices=M._staff_choices(symbol,[upper,lower],{'right':[a],'left':[b]},'fermata')
        self.assertEqual(choices[0][1]['id'],'right');self.assertEqual(M._anchor(symbol,upper,[a],'fermata'),[a])
    def test_upright_between_staves_belongs_to_lower_music(self):
        upper=staff('right','right',50);lower=staff('left','left',150)
        a=note('upper','right',80,100,1,7);b=note('lower','left',80,150,1,None)
        symbol=dict(char='Ʋ',font='Aloisen',x=77,y=126,size=20,bbox=[77,115,100,126])
        self.assertEqual(M._staff_choices(symbol,[upper,lower],{'right':[a],'left':[b]},'fermata')[0][1]['id'],'left')
    def test_whole_chord_excludes_same_column_quarter_rest_and_keeps_displaced_second(self):
        s=staff('left','left',150)
        ns=[note('h1','left',80,180,4,None,kind='whole'),note('h2','left',80,195,4,None,kind='whole'),
            note('h3','left',80,215,4,None,kind='whole'),note('shift','left',68,200,4,None,kind='whole')]
        for n in ns:n['glyph_bbox'][2]=n['origin'][0]+16
        rest=dict(id='rest',origin=[80,160],duration=1,rhythm_evidence=dict(glyph='ţ'),hand='left',measure=1)
        symbol=dict(char='Ƴ',font='Aloisen',x=75,y=240,size=20,bbox=[75,228,101,240])
        self.assertEqual({n['id'] for n in M._anchor(symbol,s,ns+[rest],'fermata')},{'h1','h2','h3','shift'})
    def test_shared_stem_does_not_include_opposed_voice(self):
        p=pause_fixture();source=p['notes'][3];other=p['notes'][4];s=p['staves'][1]
        symbol=dict(char='Ƴ',font='Aloisen',x=58,y=215,size=20,bbox=[58,205,78,215])
        self.assertEqual(M._anchor(symbol,s,[source,other],'fermata'),[other])
    def test_standard_orientations_are_explicit(self):
        for above,below in [('Ʋ','Ƴ'),('\U0001d110','\U0001d111'),('\ue4c0','\ue4c1'),('\ue4cc','\ue4cd')]:
            font='Aloisen' if above=='Ʋ' else 'Bravura'
            self.assertEqual(M._fermata_side(dict(char=above,font=font)),-1);self.assertEqual(M._fermata_side(dict(char=below,font=font)),1)
    def test_incompatible_side_preserves_detected_sign_and_blocks(self):
        p=pause_fixture();symbol=dict(char='Ƴ',font='Aloisen',x=47,y=55,size=20,bbox=[47,45,70,55])
        M.annotate_performance_page(p,1,p['staves'],[symbol],[symbol],[],[])
        unresolved=[m for n in p['notes'] for m in n['performance_marks'] if m.get('options',{}).get('source_anchor_unresolved')]
        self.assertTrue(unresolved);self.assertEqual(unresolved[0]['source']['bbox'],[47.,45.,70.,55.]);self.assertTrue(realize_project(p)['errors'])

class SharedPauseControls(unittest.TestCase):
    def paired(self,p):
        M._pair_sustained_measure_fermatas(p,1)
        return next(n for n in p['notes'] if n['id']=='lh-hold')['performance_marks'][0]['group_id']=='terminal'
    def test_complete_bar_voice_pairs_different_written_values_without_lh_clock(self):
        p=pause_fixture();before=deepcopy(p);self.assertTrue(self.paired(p));r=realize_project(p)
        self.assertFalse(r['errors']);held=next(n for n in p['notes'] if n['id']=='lh-hold')
        self.assertIsNone(held['beat']);self.assertIsNone(held['measure_beat']);self.assertEqual(held['duration_beats'],3)
        self.assertEqual(len([f for f in r['features'] if f['kind']=='fermata']),1)
        self.assertEqual(next(e['t_ms'] for e in r['audio_events'] if 'follow' in e['source_note_ids']),5125)
        self.assertFalse(any(any(i.startswith('lh-') for i in e['source_note_ids']) for e in r['audio_events']+r['motion_events']))
        for now,old in zip(p['notes'],before['notes']):
            for k in ('pitch','origin','duration','duration_beats','beat','measure_beat'):self.assertEqual(now[k],old[k])
    def test_not_a_full_measure_value_remains_unpaired_and_blocked(self):
        p=pause_fixture();p['notes'][4].update(duration=2,duration_beats=2);self.assertFalse(self.paired(p));self.assertTrue(realize_project(p)['errors'])
    def test_later_same_direction_voice_note_invalidates_complete_voice(self):
        p=pause_fixture();p['notes'].append(note('later','left',200,170,.5,None,[200,170,195],'down'))
        self.assertFalse(self.paired(p))
    def test_earlier_unrelated_column_is_not_claimed_as_onset(self):
        p=pause_fixture();p['notes'].append(note('earlier','left',25,190,.5,None,[35,160,190],'up',midi=52));self.assertFalse(self.paired(p))
    def test_bar_boundary_mismatch_is_not_paired(self):
        p=pause_fixture();p['staves'][0]['measures'][0]['metric_extent_evidence']['boundary_x'][1]=310;self.assertFalse(self.paired(p))
    def test_fermata_on_a_nonterminal_rh_event_does_not_pair(self):
        p=pause_fixture();p['notes'][1]['performance_marks']=p['notes'][2].pop('performance_marks');self.assertFalse(self.paired(p))
    def test_multiple_terminal_fermata_groups_are_ambiguous(self):
        p=pause_fixture();p['notes'][2]['performance_marks'].append(mark('competing'));self.assertFalse(self.paired(p))
    def test_explicitly_cleared_lh_clock_is_not_replaced(self):
        p=pause_fixture();p['notes'][4]['manual_fields']=['measure_beat'];self.assertFalse(self.paired(p))
    def test_whole_four_and_unfermata_quarter_rest_do_not_share_pause(self):
        p=pause_fixture();p['notes'][2]['performance_marks']=[];held=p['notes'][4]
        held.update(duration=4,duration_beats=4,origin=[50,170],glyph_bbox=[50,166,66,174],rhythm_evidence=dict(head='whole'))
        for s in p['staves']:
            s['measures'][0]['meter_beats']=4;s['measures'][0]['metric_extent_evidence']['quarter_beats']=4
        p['rests']=[dict(id='right-quarter',hand='right',staff='right',page=1,system=1,measure=1,origin=[50,70],
            beat=7,measure_beat=0,measure_start_beat=7,duration=1,duration_beats=1,rhythm_evidence=dict(glyph='ţ'))]
        self.assertFalse(self.paired(p));self.assertTrue(realize_project(p)['errors'])

if __name__=='__main__':unittest.main()
