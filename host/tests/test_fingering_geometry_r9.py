"""General typography/ownership cases: synthetic geometry, no source-PDF answers."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_converter_engine import _printed_finger_candidates, _assign_page_fingerings


def event(key,x,y,hand='right',direction='down',beams=0,gap=5):
    low,high=(y,y+3.5*gap) if direction=='down' else (y-3.5*gap,y)
    return dict(id=key,origin=[x,y],hand=hand,finger=None,issues=[],
                rhythm_evidence={'stem':[x,low,high],'stem_direction':direction,'beams':beams})


def digit(value,x,y,gap):
    return dict(char=chr(0x130+value),x=x,y=y,size=1.2*gap,bbox=[x,y-.6*gap,x+.8*gap,y+.6*gap])


class PrintedFingeringGeometryR9(unittest.TestCase):
    def assign_single(self,geometry):
        note,label,head,staff,other,rhythms=geometry
        _assign_page_fingerings([(staff,[note],[[note]])],[staff,other],[label],rhythms)
        return note['finger']

    def geometry(self,scale=1,shift=(0,0),up=False,beams=0,other_reaches=False,offset=0):
        gap=5*scale;x=100*scale+shift[0];y=100*scale+shift[1]
        sign=-1 if up else 1
        note=event('target',x,y,direction='up' if up else 'down',beams=beams,gap=gap)
        label=digit(3,x+offset*gap,y+sign*6*gap,gap)
        head=dict(x=label['x'],y=y+sign*10.5*gap)
        rhythm={'stem':[head['x'],min(head['y'],label['y']-.1*gap),max(head['y'],label['y']+.1*gap)]} if other_reaches else {}
        staff=dict(gap=gap,heads=[]);other=dict(gap=gap,heads=[head])
        return note,label,head,staff,other,{id(head):(.5,rhythm,[])}

    def test_unbeamed_free_stem_label_survives_nearer_other_head(self):
        for scale,shift,up in [(1,(0,0),False),(.6,(27,-8),False),(2,(91,300),True),(1.3,(-50,7),True)]:
            with self.subTest(scale=scale,shift=shift,up=up):
                self.assertEqual(self.assign_single(self.geometry(scale,shift,up)),3)

    def test_label_glyph_edge_not_font_origin_anchors_beamed_note(self):
        for beams in [1,2,3]:
            # The glyph edge is 1.9 spaces beyond the free end; its origin is
            # 2.5 spaces away. Font baseline is not the visible attachment edge.
            self.assertEqual(self.assign_single(self.geometry(beams=beams)),3)

    def test_competing_actual_stem_still_wins(self):
        for up in [False,True]:
            self.assertIsNone(self.assign_single(self.geometry(up=up,other_reaches=True)))

    def test_unaligned_label_does_not_gain_stem_attachment(self):
        self.assertIsNone(self.assign_single(self.geometry(offset=.7)))

    def test_complete_chord_column_is_not_replaced_by_opposite_side_single(self):
        for scale,shift in [(1,(0,0)),(.65,(31,120)),(2.1,(-55,-18))]:
            with self.subTest(scale=scale,shift=shift):
                gap=5*scale;x=100*scale+shift[0];base=200*scale+shift[1]
                rh=event('single',x,base,gap=gap)
                rh_label=digit(3,x,base+5.87*gap,gap)
                chord=[];raw=[];rhythms={}
                for index,step in enumerate([8.1,10.6]):
                    y=base+step*gap
                    n=event('chord-'+str(index),x,y,hand='left',gap=gap)
                    n['rhythm_evidence']['stem']=[x,base+8.15*gap,base+14.1*gap]
                    chord.append(n);head=dict(x=x,y=y);raw.append(head)
                    rhythms[id(head)]=(.5,n['rhythm_evidence'],[])
                rh_head=dict(x=x,y=base)
                rhythms[id(rh_head)]=(.5,rh['rhythm_evidence'],[])
                upper=dict(gap=gap,heads=[rh_head]);lower=dict(gap=gap,heads=raw)
                labels=[rh_label,digit(1,x,base+15.267*gap,gap),digit(5,x,base+16.467*gap,gap)]
                _assign_page_fingerings([(upper,[rh],[[rh]]),(lower,chord,[chord])],[upper,lower],labels,rhythms)
                self.assertEqual(rh['finger'],3)
                self.assertEqual([n['finger'] for n in chord],[1,5])

    def test_neighboring_horizontal_column_keeps_its_label(self):
        gap=5
        first=event('first',100,100,gap=gap)
        second=event('second',106,100,gap=gap)
        label=digit(4,106,145,gap)
        staff=dict(gap=gap,heads=[])
        self.assertEqual(_printed_finger_candidates([first],[[first],[second]],staff,[staff],[label],set(),{}),[])

    def test_mixed_chord_sides_cannot_consume_other_hands_free_stem_label(self):
        for scale,shift,extra_spacing in [(1,(0,0),0),(.7,(32,19),0),(1.8,(-70,320),.4)]:
            with self.subTest(scale=scale,shift=shift,extra_spacing=extra_spacing):
                gap=5*scale;x=100*scale+shift[0];base=200*scale+shift[1]
                chord=[event('rh-'+str(i),x,base+s*gap,gap=gap,beams=1) for i,s in enumerate([0,1.5])]
                for n in chord:n['rhythm_evidence']['stem']=[x,base,base+5.35*gap]
                bass=event('lh',x,base+12*gap,hand='left',direction='up',gap=gap)
                bass['rhythm_evidence']['stem']=[x+1.15*gap,base+(8.5+extra_spacing)*gap,base+12*gap]
                raw_chord=[dict(x=x,y=n['origin'][1]) for n in chord]
                bass_head=dict(x=x,y=bass['origin'][1])
                upper=dict(gap=gap,heads=raw_chord);lower=dict(gap=gap,heads=[bass_head])
                rhythms={id(h):(.5,n['rhythm_evidence'],[]) for h,n in zip(raw_chord,chord)}
                rhythms[id(bass_head)]=(.5,bass['rhythm_evidence'],[])
                labels=[digit(4,x,base-1.2*gap,gap),digit(1,x,base+6.6*gap,gap),
                        digit(5,x,base+(7.5+extra_spacing)*gap,gap)]
                _assign_page_fingerings([(upper,chord,[chord]),(lower,[bass],[[bass]])],[upper,lower],labels,rhythms)
                self.assertEqual([n['finger'] for n in chord],[4,1])
                self.assertEqual(bass['finger'],5)

    def test_neighbor_hollow_head_keeps_already_allocated_finger(self):
        for scale,shift in [(1,(0,0)),(.65,(31,-15)),(2.2,(-44,93))]:
            with self.subTest(scale=scale,shift=shift):
                gap=5*scale;x=100*scale+shift[0];base=200*scale+shift[1]
                rh=event('rh-repeat',x,base,gap=gap)
                lh=dict(id='lh-hollow',origin=[x,base+6*gap],hand='left',finger=None,
                        rhythm_evidence={'head':'whole'},issues=[])
                rh_head=dict(x=x,y=base);lh_head=dict(x=x,y=lh['origin'][1])
                staff=dict(gap=gap,heads=[rh_head]);lower=dict(gap=gap,heads=[lh_head])
                rhythms={id(rh_head):(.5,rh['rhythm_evidence'],[]),id(lh_head):(4,lh['rhythm_evidence'],[])}
                label=digit(1,x,base+4.5*gap,gap)
                _assign_page_fingerings([(staff,[rh],[[rh]]),(lower,[lh],[[lh]])],[staff,lower],[label],rhythms)
                self.assertIsNone(rh['finger'])
                self.assertEqual(lh['finger'],1)

    def test_hollow_head_ink_edge_blocks_unclaimed_digit_recovery(self):
        gap=5;x=100;base=200
        note=event('unassigned-rh',x,base,gap=gap)
        head=dict(x=x,y=base+6.05*gap,bbox=[x,base+5.5*gap,x+1.2*gap,base+6.6*gap])
        staff=dict(gap=gap,heads=[]);other=dict(gap=gap,heads=[head])
        label=digit(1,x,base+4.5*gap,gap)
        # Neither a head center nor a font origin represents the visible gap.
        # The hollow note's ink is nearer than a center-only test suggests.
        rhythms={id(head):(4,{'head':'whole'},[])}
        _assign_page_fingerings([(staff,[note],[[note]])],[staff,other],[label],rhythms)
        self.assertIsNone(note['finger'])


if __name__=='__main__':unittest.main()
