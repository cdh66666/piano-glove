"""General header geometry, with no customer names, hashes or note IDs as rules."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import score_converter_engine as engine


def glyph(symbol,x,y,gap=5):
    return dict(char=symbol,x=x,y=y,size=2*gap,font='Aloisen',
                bbox=[x,y-1.9*gap,x+.8*gap,y+.7*gap])


def header(clef='treble',kind='flat',count=1,scale=1,dx=0,dy=0):
    gap=5*scale
    staff=dict(top=100*scale+dy,bottom=120*scale+dy,gap=gap,
               left=30*scale+dx,right=580*scale+dx,clef=clef,hand='right')
    c=glyph('ƀ' if clef=='treble' else 'Ɓ',40*scale+dx,staff['bottom']-gap,gap)
    c['bbox'][2]=53*scale+dx
    steps={('treble','sharp'):[8,5,9,6,3,7,4],('treble','flat'):[4,7,3,6,2,5,1],
           ('bass','sharp'):[6,3,7,4,1,5,2],('bass','flat'):[2,5,1,4,0,3,-1]}
    keys=[glyph('ġ' if kind=='sharp' else 'Ģ',(60+i*5)*scale+dx,
                staff['bottom']-step*gap/2,gap) for i,step in enumerate(steps[clef,kind][:count])]
    staff.update(chars=[c]+keys,clefs=[c])
    # Only 1.6 staff spaces after the last sign, below the old 2-space cutoff.
    event=glyph('Ŵ',keys[-1]['x']+1.6*gap,staff['bottom']+gap,gap)
    return staff,keys,[event]


class OpeningKeyGeometryTests(unittest.TestCase):
    def test_compact_signatures_one_to_seven_follow_order_across_clefs(self):
        for clef in ('treble','bass'):
            for kind,order,alter in [('sharp','FCGDAEB',1),('flat','BEADGCF',-1)]:
                for count in range(1,8):
                    for scale,dx,dy in [(0.7,-13,41),(1,0,0),(2.3,129,-57)]:
                        with self.subTest(clef=clef,kind=kind,count=count,scale=scale):
                            staff,expected,events=header(clef,kind,count,scale,dx,dy)
                            keys,key_map=engine._opening_key_signature(staff,events)
                            self.assertEqual(keys,expected)
                            self.assertEqual(key_map,{letter:alter for letter in order[:count]})

    def test_first_local_accidental_after_printed_meter_is_not_global_key(self):
        staff,keys,events=header()
        staff['chars'] += [glyph('Ĵ',57,105),glyph('Ĵ',57,115)]
        # Canonical B-flat height alone is insufficient after the time signature.
        self.assertEqual(engine._opening_key_signature(staff,events),([],{}))

    def test_first_local_accidental_without_meter_is_not_globalized(self):
        for clef,kind in [('treble','flat'),('treble','sharp'),('bass','flat'),('bass','sharp')]:
            staff,keys,events=header(clef,kind)
            events[0]['y']=keys[-1]['y']
            self.assertEqual(engine._opening_key_signature(staff,events),([],{}))

    def test_repeated_same_hand_signature_resolves_compact_header(self):
        staff,keys,events=header()
        events[0]['y']=keys[-1]['y']
        previous=[dict(hand='right',key_signature={'B':-1}),dict(hand='left',key_signature={})]
        self.assertEqual(engine._opening_key_signature(staff,events,previous),(keys,{'B':-1}))
        previous=[dict(hand='left',key_signature={'B':-1})]
        self.assertEqual(engine._opening_key_signature(staff,events,previous),([],{}))

    def test_noncanonical_note_accidental_ends_the_verified_key_prefix(self):
        staff,keys,events=header(kind='sharp',count=3)
        staff['chars'][2]['y']+=staff['gap']/2
        self.assertEqual(engine._opening_key_signature(staff,events),(keys[:1],{'F':1}))

    def test_opposite_accidental_keeps_verified_key_and_stays_local(self):
        staff,keys,events=header(kind='flat',count=2)
        keys[1]['char']='ġ'
        self.assertEqual(engine._opening_key_signature(staff,events),(keys[:1],{'B':-1}))

    def test_explicit_cancellation_blocks_previous_key_corroboration(self):
        staff,keys,events=header()
        events[0]['y']=keys[-1]['y']
        staff['chars'].append(glyph('ģ',57,keys[-1]['y']))
        previous=[dict(hand='right',key_signature={'B':-1})]
        self.assertEqual(engine._opening_key_signature(staff,events,previous),([],{}))

    def test_detached_note_accidental_not_attached_to_clef_header(self):
        staff,keys,events=header()
        keys[0]['x']+=80;keys[0]['bbox']=[v+80 if i%2==0 else v for i,v in enumerate(keys[0]['bbox'])]
        events[0]['x']+=80
        self.assertEqual(engine._opening_key_signature(staff,events),([],{}))

    def test_rest_is_a_real_prefix_boundary(self):
        staff,keys,events=header()
        rest=glyph('š',keys[0]['x']-1,staff['top']+2*staff['gap'])
        self.assertEqual(engine._opening_key_signature(staff,events+[rest]),([],{}))

    def test_cancel_naturals_do_not_create_a_sharp_or_flat_signature(self):
        staff,keys,events=header()
        keys[0]['char']='ģ'
        self.assertEqual(engine._opening_key_signature(staff,events),([],{}))


class SyntheticPage:
    def __init__(self,chars,lines):
        self.rect=SimpleNamespace(width=612,height=300)
        self._chars=chars;self._lines=lines
    def chars(self,music_only=True):return copy.deepcopy(self._chars)
    def geometry(self):return self._lines,[]


class SyntheticDocument:
    def __init__(self,page):self.pages=[page]
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def __iter__(self):return iter(self.pages)


def synthesize_pitch_project(has_key=True,local_natural=False,local_flat_after_meter=False,compact=False):
    gap=5
    staff,keys,_=header()
    chars=copy.deepcopy(staff['chars'] if has_key else staff['clefs'])
    if local_flat_after_meter:
        chars += [glyph('Ĵ',65,105),glyph('Ĵ',65,115),glyph('Ģ',92,110)]
    if local_natural:chars.append(glyph('ģ',92,110))
    # Two B4s in the first measure, followed by B4 in the next measure.
    positions=(68,150,340) if compact else (100,150,340)
    for x in positions:chars.append(glyph('Ŵ',x,110))
    chars.append(glyph('Ɓ',40,195))
    chars.append(glyph('š',100,190))
    lines=[(30,y,580,y,.5) for top in (100,180) for y in range(top,top+21,5)]
    lines += [(x,100,x,120,.5) for x in (30,300,580)]
    lines += [(x+5.5,95,x+5.5,110,.5) for x in positions]
    with tempfile.TemporaryDirectory() as folder:
        source=Path(folder)/'synthetic.pdf';source.write_bytes(b'synthetic coordinate fixture')
        with patch.object(engine,'open_document',return_value=SyntheticDocument(SyntheticPage(chars,lines))):
            return engine.recognize(source)


class AccidentalScopeIntegrationTests(unittest.TestCase):
    def test_verified_key_applies_to_later_notes(self):
        project=synthesize_pitch_project()
        right=[n for n in project['notes'] if n['hand']=='right']
        self.assertEqual([n['pitch'] for n in right],['Bb4','Bb4','Bb4'])
    def test_local_natural_overrides_key_only_until_barline(self):
        project=synthesize_pitch_project(local_natural=True)
        right=[n for n in project['notes'] if n['hand']=='right']
        self.assertEqual([n['pitch'] for n in right],['B4','B4','Bb4'])
    def test_local_flat_after_meter_does_not_change_next_measure_key(self):
        project=synthesize_pitch_project(has_key=False,local_flat_after_meter=True)
        right=[n for n in project['notes'] if n['hand']=='right']
        self.assertEqual([n['pitch'] for n in right],['Bb4','Bb4','B4'])
    def test_compact_first_note_flat_without_meter_stays_measure_local(self):
        project=synthesize_pitch_project(compact=True)
        right=[n for n in project['notes'] if n['hand']=='right']
        self.assertEqual([n['pitch'] for n in right],['Bb4','Bb4','B4'])


if __name__=='__main__':unittest.main()
