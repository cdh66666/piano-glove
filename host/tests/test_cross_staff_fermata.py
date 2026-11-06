from pathlib import Path
from copy import deepcopy
import sys,unittest
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from score_marks import _pair_cross_staff_fermatas
def fixture():
    def event(nid,staff,hand,gid,x,y):
        source=dict(method='printed_music_glyph',page=1,staff=staff,bbox=[x,y,x+12,y+8])
        return dict(id=nid,page=1,system=1,measure=2,staff=staff,hand=hand,duration=2.,measure_beat=None,
            performance_marks=[dict(kind='fermata',group_id=gid,source=source,options={})])
    notes=[event('rh','upper','right','right-pause',100,70),event('lh','lower','left','left-pause',104,170)]
    spans=[dict(id=n['performance_marks'][0]['group_id'],kind='fermata',source=deepcopy(n['performance_marks'][0]['source']),options={'anchor_note_id':n['id']},source_note_ids=['rh']) for n in notes]
    return dict(notes=notes,rests=[],performance_spans=spans)
class CrossStaffFermataTests(unittest.TestCase):
    def test_one_shifted_printed_pause_coalesces_without_guessing_time(self):
        p=fixture();original=[deepcopy(n['performance_marks'][0]['source']) for n in p['notes']]
        self.assertEqual(_pair_cross_staff_fermatas(p,1),1);self.assertEqual(len(p['performance_spans']),1)
        self.assertEqual({n['performance_marks'][0]['group_id'] for n in p['notes']},{'right-pause'})
        self.assertEqual([n['performance_marks'][0]['source'] for n in p['notes']],original)
        self.assertEqual(len(p['performance_spans'][0]['sources']),2);self.assertTrue(all(n['measure_beat'] is None for n in p['notes']))
    def test_known_equal_end_can_pair(self):
        p=fixture()
        for n in p['notes']:n['measure_beat']=1.
        self.assertEqual(_pair_cross_staff_fermatas(p,1),1)
    def test_known_different_end_is_not_paired(self):
        p=fixture();p['notes'][0]['measure_beat']=0.;p['notes'][1]['measure_beat']=2.
        self.assertEqual(_pair_cross_staff_fermatas(p,1),0)
    def test_different_duration_is_not_paired(self):
        p=fixture();p['notes'][1]['duration']=1.;self.assertEqual(_pair_cross_staff_fermatas(p,1),0)
    def test_nearby_separate_pause_with_no_actual_ink_overlap_is_not_paired(self):
        p=fixture();p['notes'][1]['performance_marks'][0]['source']['bbox']=[113,170,125,178]
        self.assertEqual(_pair_cross_staff_fermatas(p,1),0)
    def test_multiple_overlapping_candidates_remain_ambiguous(self):
        p=fixture();extra=deepcopy(p['notes'][1]);extra.update(id='lh2');extra['performance_marks'][0]['group_id']='other-left-pause';p['notes'].append(extra)
        self.assertEqual(_pair_cross_staff_fermatas(p,1),0)
    def test_different_measure_not_paired(self):
        p=fixture();p['notes'][1]['measure']=3;self.assertEqual(_pair_cross_staff_fermatas(p,1),0)
    def test_same_staff_not_paired(self):
        p=fixture();p['notes'][1]['staff']='upper';self.assertEqual(_pair_cross_staff_fermatas(p,1),0)
    def test_rest_mark_can_pair_with_other_staff_note(self):
        p=fixture();rest=p['notes'].pop();p['rests'].append(rest);self.assertEqual(_pair_cross_staff_fermatas(p,1),1)
        self.assertEqual(p['performance_spans'][0]['options']['paired_anchor_rest_ids'],['lh'])
    def test_chord_heads_are_one_source_pause(self):
        p=fixture();extra=deepcopy(p['notes'][0]);extra['id']='rh2';p['notes'].append(extra)
        self.assertEqual(_pair_cross_staff_fermatas(p,1),1);self.assertEqual(len(p['performance_spans']),1)
if __name__=='__main__':unittest.main()
