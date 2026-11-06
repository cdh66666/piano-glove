"""Independent common-shaft evidence; never copy merely by x or arpeggio."""
from pathlib import Path
from copy import deepcopy
import sys,unittest
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parents[2]/'repo/host'));sys.path.insert(0,str(HERE/'candidate'))
from score_converter_engine import _stem_and_duration,_recover_shared_beamed_chord_heads
from score_marks import _merge_arpeggio_segments,annotate_performance_page

def fixture(dots=0):
    heads=[dict(char='Ŵ',font='Aloisen',x=100.,y=float(y),size=10.,bbox=[100.,y-2.,106.,y+2.]) for y in (80,100,120)]
    staff=dict(gap=5.,heads=heads)
    lines=[(100.2,80.,100.2,150.,.5),(100.2,150.,140.,150.,2.)]
    chars=list(heads)
    for head in heads:
        for i in range(dots):chars.append(dict(char='Ǉ',font='Aloisen',x=108.+i*3,y=head['y'],size=10.,bbox=[108.+i*3,head['y']-1,109.+i*3,head['y']+1]))
    rhythms={id(h):_stem_and_duration(h,staff,lines,chars) for h in heads}
    return staff,heads,lines,chars,rhythms

class SharedChordShaftTests(unittest.TestCase):
    def test_direct_shared_beamed_shaft_recovers_only_interior_heads(self):
        s,h,l,c,r=fixture();self.assertEqual(r[id(h[0])][0],.5);self.assertIsNone(r[id(h[1])][0]);self.assertIsNone(r[id(h[2])][0])
        before=deepcopy(r[id(h[0])]);self.assertEqual(_recover_shared_beamed_chord_heads([s],r,l,c),2)
        self.assertEqual([r[id(x)][0] for x in h],[.5,.5,.5]);self.assertEqual(r[id(h[0])],before)
        self.assertEqual(r[id(h[1])][1]['beam_recovery']['method'],'unique_direct_shared_beamed_chord_shaft')

    def test_dotted_beam_value_requires_individual_matching_dots(self):
        s,h,l,c,r=fixture(1);self.assertEqual(r[id(h[0])][0],.75)
        self.assertEqual(_recover_shared_beamed_chord_heads([s],r,l,c),2);self.assertEqual([r[id(x)][0] for x in h],[.75]*3)

    def test_dot_mismatch_remains_unknown(self):
        s,h,l,c,r=fixture(1);c=[v for v in c if v['char']!='Ǉ' or v['y']==80]
        self.assertEqual(_recover_shared_beamed_chord_heads([s],r,l,c),0);self.assertIsNone(r[id(h[1])][0])

    def test_same_x_without_actual_shaft_is_not_enough(self):
        s,h,l,c,r=fixture();self.assertEqual(_recover_shared_beamed_chord_heads([s],r,l[1:],c),0)

    def test_cached_beam_value_without_actual_beam_is_not_enough(self):
        s,h,l,c,r=fixture();self.assertEqual(_recover_shared_beamed_chord_heads([s],r,l[:1],c),0)

    def test_shaft_not_touching_ink_does_not_recover(self):
        s,h,l,c,r=fixture();h[1]['bbox']=[102.,98.,108.,102.];h[2]['bbox']=[102.,118.,108.,122.]
        self.assertEqual(_recover_shared_beamed_chord_heads([s],r,l,c),0)

    def test_other_physical_shaft_means_ambiguous_voice(self):
        s,h,l,c,r=fixture();l.append((106.,90.,106.,125.,.5))
        self.assertEqual(_recover_shared_beamed_chord_heads([s],r,l,c),0)

    def test_conflicting_anchor_directions_not_one_voice(self):
        s,h,l,c,r=fixture();bottom=dict(h[0],y=150.,bbox=[100.,148.,106.,152.]);h.append(bottom);l.append((100.2,80.,140.,80.,2.))
        r[id(bottom)]=(.5,dict(head='filled',stem=[100.2,80.,150.],beams=1,dots=0,stem_direction='up'),[])
        self.assertEqual(_recover_shared_beamed_chord_heads([s],r,l,c),0)

    def test_small_cue_head_not_promoted(self):
        s,h,l,c,r=fixture();h[1]['size']=6.;h[2]['size']=6.
        self.assertEqual(_recover_shared_beamed_chord_heads([s],r,l,c),0)

    def test_different_font_or_head_type_not_promoted(self):
        s,h,l,c,r=fixture();h[1]['font']='Other';r[id(h[2])]=(None,{'head':'open'},['stem_not_resolved'])
        self.assertEqual(_recover_shared_beamed_chord_heads([s],r,l,c),0)

    def test_different_size_same_font_not_promoted(self):
        s,h,l,c,r=fixture();h[1]['size']=12.;h[2]['size']=12.
        self.assertEqual(_recover_shared_beamed_chord_heads([s],r,l,c),0)

    def test_unrelated_decoder_error_not_hidden(self):
        s,h,l,c,r=fixture();r[id(h[1])]=(None,{'head':'filled'},['stem_not_resolved','rhythm_geometry_conflict']);r[id(h[2])]=(None,{'head':'filled'},['flag_anchor_unresolved'])
        self.assertEqual(_recover_shared_beamed_chord_heads([s],r,l,c),0)

    def test_conflicting_flag_not_copied_from_beam(self):
        s,h,l,c,r=fixture();c.extend(dict(char='Ŋ',font='Aloisen',x=t['x'],y=t['y'],size=10.,bbox=[100,t['y']-10,105,t['y']]) for t in h[1:])
        self.assertEqual(_recover_shared_beamed_chord_heads([s],r,l,c),0)

    def test_slash_grace_context_not_promoted(self):
        s,h,l,c,r=fixture();l.append((97.,115.,104.,110.,.4))
        self.assertEqual(_recover_shared_beamed_chord_heads([s],r,l,c),0)

    def test_no_input_geometry_or_chars_mutation(self):
        s,h,l,c,r=fixture();before=deepcopy((s,h,l,c));_recover_shared_beamed_chord_heads([s],r,l,c)
        self.assertEqual((s,h,l,c),before)


class ContinuousWaveTests(unittest.TestCase):
    def setup(self):
        staff=dict(id='s',page=1,system=1,hand='right',gap=10.,top=100.,bottom=140.,left=20.,right=400.,bbox=[20,100,400,140])
        notes=[dict(id='n'+str(i),page=1,system=1,staff='s',hand='right',measure=1,origin=[100.,float(y)],pitch=pitch,midi=midi,duration=.5,measure_beat=0.,
                    rhythm_evidence={'head':'filled','stem':[101.,80.,165.],'beams':1,'dots':0,'stem_direction':'down'},issues=['arpeggio_requires_review'])
               for i,(y,pitch,midi) in enumerate([(100,'C6',84),(120,'F5',77),(140,'C5',72)])]
        wave=lambda top,bottom:dict(char='Ƭ',font='Aloisen',kind='arpeggio',x=78.,y=bottom,size=20.,bbox=[78.,top,86.,bottom])
        return staff,notes,[wave(88,104),wave(106,122),wave(124,140)]

    def test_continuous_vertical_pieces_make_one_whole_chord_group(self):
        s,notes,waves=self.setup();p=dict(notes=notes,rests=[],staves=[s]);raw=[{k:v for k,v in w.items() if k!='kind'} for w in waves]
        annotate_performance_page(p,1,[s],raw,raw,[],[])
        marks=[next(m for m in n['performance_marks'] if m['kind']=='arpeggio') for n in notes]
        self.assertEqual(len({m['group_id'] for m in marks}),1)
        self.assertTrue(all(m['source']['component_count']==3 for m in marks));self.assertEqual(marks[0]['source']['bbox'],[78.,88.,86.,140.])

    def test_same_x_but_disjoint_ink_does_not_join(self):
        s,ns,ws=self.setup();ws[1]['bbox']=[78,150,86,166];ws=ws[:2]
        self.assertEqual(len(_merge_arpeggio_segments(ws,[s],{'s':ns})),2)

    def test_small_horizontal_jitter_cannot_break_transitive_vertical_chain(self):
        s,ns,ws=self.setup()
        for wave,dx in zip(ws,(1,-1,0)):
            wave['bbox']=[wave['bbox'][0]+dx,wave['bbox'][1],wave['bbox'][2]+dx,wave['bbox'][3]];wave['x']+=dx
        merged=_merge_arpeggio_segments(ws,[s],{'s':ns});self.assertEqual(len(merged),1);self.assertEqual(len(merged[0]['glyph_bboxes']),3)

    def test_different_font_does_not_join(self):
        s,ns,ws=self.setup();ws[1]['font']='OtherMusic';self.assertEqual(len(_merge_arpeggio_segments(ws[:2],[s],{'s':ns})),2)

    def test_horizontal_alignment_alone_without_ink_overlap_does_not_join(self):
        s,ns,ws=self.setup();ws[1]['bbox']=[88,106,96,122];ws[1]['x']=88
        self.assertEqual(len(_merge_arpeggio_segments(ws[:2],[s],{'s':ns})),2)

    def test_separate_staffs_do_not_join(self):
        s,ns,ws=self.setup();lower=dict(s,id='lower',top=220.,bottom=260.,bbox=[20,220,400,260],hand='left')
        ls=[dict(n,id=n['id']+'L',staff='lower',hand='left',origin=[100,n['origin'][1]+120]) for n in ns]
        other=dict(ws[0],y=224,bbox=[78.,208.,86.,224.]);merged=_merge_arpeggio_segments([ws[0],other],[s,lower],{'s':ns,'lower':ls})
        self.assertEqual(len(merged),2)

if __name__=='__main__':unittest.main()
