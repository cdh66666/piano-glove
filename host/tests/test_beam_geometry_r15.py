"""Synthetic vector ink; no user scores used as fixtures."""
from copy import deepcopy
import unittest
from score_converter_engine import _stem_beams,_stem_and_duration,_recover_beam_from_physical_stems
from test_beam_physical_stems_r13 import fixture

class StrokeIntersectionTests(unittest.TestCase):
 def test_non_touching_cross_voice_is_excluded_in_both_stem_directions(self):
  for sign in (1,-1):
   # A parallel remote beam lies beyond the shaft endpoint; despite its
   # close center it is separated from the shaft by a gap in the actual ink.
   tip=40; head=80 if sign==1 else 0; stem=[100,min(tip,head),max(tip,head)]
   lines=[(90,tip,110,tip,4),(90,tip+sign*8,110,tip+sign*8,4),
          (90,tip-sign*2.5,110,tip-sign*2.5,4)]
   self.assertEqual(_stem_beams(stem,head,10,lines,physical_only=True)[0],2)
 def test_touching_slanted_competitor_remains_ambiguous(self):
  stem=[100,0,40]; head=0
  lines=[(90,40,110,40,4),(90,32,110,32,4),(90,36,110,44,4)]
  self.assertIsNone(_stem_beams(stem,head,10,lines,physical_only=True)[0])
 def test_oblique_stroke_thickness_uses_perpendicular_width(self):
  # At the stem x the oblique stroke is 2.2 outside the tip. Its actual
  # vertical ink extent is 2.5, so it still touches; ambiguity must survive.
  stem=[100,0,40];lines=[(90,40,110,40,4),(90,32,110,32,4),(95,38.45,105,45.95,4)]
  self.assertIsNone(_stem_beams(stem,0,10,lines,physical_only=True)[0])
 def test_short_segment_near_shaft_is_not_extrapolated(self):
  for sign in (1,-1):
   tip=40;head=80 if sign==1 else 0;stem=[100,min(tip,head),max(tip,head)]
   # Neither cap style nor the short segment's ink is available; the line
   # ends before the shaft and its extrapolation would appear to cross it.
   lines=[(90,tip,110,tip,4),(90,tip+sign*8,110,tip+sign*8,4),
          (90,tip-sign*5,99,tip-sign*.5,4)]
   self.assertIsNone(_stem_beams(stem,head,10,lines,physical_only=True)[0])
 def test_non_touching_exclusion_scales_and_translates(self):
  for factor in (.5,1.7,3):
   stem=[100*factor+12,0*factor+71,40*factor+71]
   lines=[(x1*factor+12,y1*factor+71,x2*factor+12,y2*factor+71,w*factor) for x1,y1,x2,y2,w in [(90,40,110,40,4),(90,32,110,32,4),(90,42.5,110,42.5,4)]]
   self.assertEqual(_stem_beams(stem,71,10*factor,lines,physical_only=True)[0],2)
 def test_ambiguity_fallback_reads_only_ordinary_heads_and_marks_evidence(self):
  head=dict(char='Ŵ',x=100,y=0,size=20,bbox=[100,-2,106,2]); stem=(100,0,100,40,.3)
  lines=[stem,(90,40,110,40,4),(90,32,110,32,4),(90,42.5,110,42.5,4)]
  duration,evidence,issues=_stem_and_duration(head,dict(gap=10),lines,[head]);self.assertEqual(duration,.25);self.assertEqual(evidence['beam_recovery']['method'],'unique_intersecting_strokes_at_stem_tip')
  small=dict(head,size=14);duration,evidence,issues=_stem_and_duration(small,dict(gap=10),lines,[small]);self.assertIsNone(duration);self.assertIn('beam_spacing_conflict',issues)
 def test_small_anchor_unique_same_size_recovers_but_keeps_warning(self):
  notes,lines,chars=fixture();notes[0]['issues'].append('small_notated_note_requires_review');notes[1]['issues'].append('small_notated_note_requires_review');chars[0]['size']=chars[1]['size']=8.5
  self.assertEqual(_recover_beam_from_physical_stems([dict(id='r',gap=5)],notes,lines,chars),1)
  self.assertEqual(notes[1]['duration'],.125);self.assertIn('small_notated_note_requires_review',notes[1]['issues'])
 def test_small_anchor_never_licenses_normal_or_different_size(self):
  for kind in ('normal_target','mismatch','slashed_anchor','different_voice'):
   notes,lines,chars=fixture();notes[0]['issues'].append('small_notated_note_requires_review');chars[0]['size']=8.5;chars[1]['size']=8.5
   if kind!='normal_target':notes[1]['issues'].append('small_notated_note_requires_review')
   if kind=='mismatch':chars[1]['size']=6
   if kind=='slashed_anchor':notes[0]['issues'].append('grace_or_cue_note_requires_review')
   if kind=='different_voice':notes[0]['voice']='one';notes[1]['voice']='two'
   before=deepcopy(notes);self.assertEqual(_recover_beam_from_physical_stems([dict(id='r',gap=5)],notes,lines,chars),0,kind);self.assertEqual(notes,before)
if __name__=='__main__':unittest.main()
