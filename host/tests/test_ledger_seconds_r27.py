"""Independent synthetic engraving controls; no source-PDF answer keys."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import sys
import unittest

HERE=Path(__file__).resolve().parent
HOST=HERE.parents[2]/'repo/host'
sys.path.insert(0,str(HOST))
import score_converter_engine as engine


def fixture(side='left',kind='open',below=False,scale=1,offset=(0,0)):
    staff=dict(top=100.,bottom=140.,left=0.,right=400.,gap=10.)
    target_x,peer_x=(120.,132.) if side=='left' else (132.,120.)
    glyph='ż' if kind=='open' else 'Ŵ';height=10.4 if kind=='open' else 9.8
    def head(x,y):
        return dict(char=glyph,font='Aloisen',size=20.,x=x,y=y,
                    bbox=[x,y-height/2,x+12,y+height/2])
    target=head(target_x,85.);peer=head(peer_x,80.)
    lines=[(peer_x-2,y,peer_x+15,y,1.) for y in (80.,90.)]
    lines.append((132.6,80.5,132.6,155.,1.))
    if below:
        for item in (target,peer):
            item['y']=240-item['y'];b=item['bbox'];item['bbox']=[b[0],240-b[3],b[2],240-b[1]]
        lines=[(x1,240-y1,x2,240-y2,w) for x1,y1,x2,y2,w in lines]
    dx,dy=offset
    for key in ('top','bottom'):staff[key]=staff[key]*scale+dy
    for key in ('left','right'):staff[key]=staff[key]*scale+dx
    staff['gap']*=scale
    for item in (target,peer):
        item['x']=item['x']*scale+dx;item['y']=item['y']*scale+dy;item['size']*=scale
        item['bbox']=[v*scale+(dx if i%2==0 else dy) for i,v in enumerate(item['bbox'])]
    lines=[(x1*scale+dx,y1*scale+dy,x2*scale+dx,y2*scale+dy,w*scale) for x1,y1,x2,y2,w in lines]
    return staff,target,peer,lines


class DisplacedSecondControls(unittest.TestCase):
    def test_both_sides_filled_open_above_below_scale_and_translation(self):
        for side in ('left','right'):
            for kind in ('filled','open'):
                for below in (False,True):
                    for scale,offset in ((.4,(720,-310)),(1,(0,0)),(3.2,(-450,890))):
                        with self.subTest(side=side,kind=kind,below=below,scale=scale):
                            staff,target,peer,lines=fixture(side,kind,below,scale,offset)
                            chars=[target,peer]
                            evidence=engine._displaced_second_ledger_evidence(target,staff,lines,chars,[staff])
                            self.assertIsNotNone(evidence)
                            self.assertEqual(evidence['method'],'displaced_second_shared_stem_ledger_chain')
                            self.assertTrue(engine._is_score_head(target,staff,lines,chars))
                            owner,ownership=engine._head_staff(target,[staff],lines,chars)
                            self.assertIs(owner,staff)
                            self.assertIsNotNone(ownership)
                            if side=='left':
                                self.assertFalse(engine._is_score_head(target,staff,lines))
                                self.assertEqual(ownership['method'],evidence['method'])

    def test_missing_or_conflicting_evidence_is_not_recovered(self):
        controls=('no_peer','no_shaft','short_shaft','shaft_misses_target','different_font',
                  'both_wrong_font','different_size','mixed_heads','whole_head','not_second',
                  'far_label','incomplete_chain','no_ink_contact','different_staff','two_peers','two_shafts')
        for mode in controls:
            with self.subTest(mode=mode):
                staff,target,peer,lines=fixture();chars=[target,peer];staves=[staff]
                if mode=='no_peer':chars=[target]
                elif mode=='no_shaft':lines=lines[:-1]
                elif mode=='short_shaft':lines[-1]=(132.6,80.5,132.6,89.,1.)
                elif mode=='shaft_misses_target':lines[-1]=(140.,80.5,140.,155.,1.)
                elif mode=='different_font':peer['font']='Text'
                elif mode=='both_wrong_font':target['font']=peer['font']='Text'
                elif mode=='different_size':peer['size']=12.
                elif mode=='mixed_heads':peer['char']='Ŵ'
                elif mode=='whole_head':target['char']=peer['char']='Ł'
                elif mode=='not_second':peer['y']=70.
                elif mode=='far_label':peer['x']+=30;peer['bbox']=[v+(30 if i%2==0 else 0) for i,v in enumerate(peer['bbox'])]
                elif mode=='incomplete_chain':lines.pop(0)
                elif mode=='no_ink_contact':lines[1]=(132.5,90.,149.5,90.,1.)
                elif mode=='different_staff':staves.append(dict(top=75.,bottom=115.,left=0.,right=400.,gap=10.))
                elif mode=='two_peers':
                    chars.append(deepcopy(peer))
                elif mode=='two_shafts':lines.append((131.8,80.5,131.8,155.,1.))
                self.assertIsNone(engine._displaced_second_ledger_evidence(target,staff,lines,chars,staves))
                if mode not in ('different_staff',):
                    self.assertFalse(engine._is_score_head(target,staff,lines,chars))

    def test_tempo_head_and_nearby_text_are_not_score_heads(self):
        staff,target,peer,lines=fixture(kind='filled')
        text=[dict(char='=',font='Text',size=14.,x=140.,y=85.,bbox=[140.,79.,148.,88.]),
              dict(char='8',font='Text',size=14.,x=152.,y=85.,bbox=[152.,79.,160.,88.])]
        self.assertFalse(engine._is_score_head(target,staff,lines[:-1],[target]+text))
        self.assertIsNone(engine._head_staff(target,[staff],lines[:-1],[target]+text)[1])

    def test_source_geometry_is_unchanged(self):
        staff,target,peer,lines=fixture();chars=[target,peer]
        before=deepcopy((staff,chars,lines))
        engine._head_staff(target,[staff],lines,chars)
        engine._is_score_head(target,staff,lines,chars)
        self.assertEqual((staff,chars,lines),before)


if __name__=='__main__':unittest.main(verbosity=2)
