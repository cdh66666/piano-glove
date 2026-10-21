import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from score_converter import export_reviewed, pitch_midi
from score_codec import encode, decode

class ConverterTests(unittest.TestCase):
    def project(self):
        return dict(name='原谱右手', selection=dict(bpm=120,start_beat=0,end_beat=4,range_reviewed=True), notes=[
            dict(id=1,page=1,hand='right',pitch='F#4',finger=2,beat=0,duration_beats=.5,confirmed=True),
            dict(id=2,page=1,hand='right',pitch='A4',finger=4,beat=1,duration_beats=2,confirmed=True)])
    def test_pitch_and_rest_and_hold_roundtrip(self):
        score=decode(encode(export_reviewed(self.project())))
        self.assertEqual([n['pitch'] for n in score['notes']],[66,69])
        self.assertEqual([n['t_ms'] for n in score['notes']],[0,500])
        self.assertEqual([n['duration_ms'] for n in score['notes']],[250,1000])
    def test_unconfirmed_not_executable(self):
        p=self.project();p['notes'][0]['confirmed']=False
        with self.assertRaises(ValueError):export_reviewed(p)
    def test_unknown_hand_not_silent(self):
        p=self.project();p['notes'].append(dict(id=3,page=1,hand=None))
        with self.assertRaises(ValueError):export_reviewed(p)
    def test_left_hand_excluded(self):
        p=self.project();p['notes'].append(dict(hand='left'))
        self.assertEqual(len(export_reviewed(p)['notes']),2)
    def test_unknown_global_beat_not_measure_beat(self):
        p=self.project();p['notes'][0].update(beat=None,measure_beat=0)
        with self.assertRaises(ValueError):export_reviewed(p)
    def test_same_finger_chord_rejected(self):
        p=self.project();p['notes'][1].update(finger=2,beat=0)
        with self.assertRaises(ValueError):export_reviewed(p)
    def test_chord_different_fingers_preserved(self):
        p=self.project();p['notes'][1]['beat']=0
        self.assertEqual([n['t_ms'] for n in export_reviewed(p)['notes']],[0,0])
    def test_range_confirmation(self):
        p=self.project();p['selection']['range_reviewed']=False
        with self.assertRaises(ValueError):export_reviewed(p)
    def test_end_rest_preserved(self):
        self.assertEqual(export_reviewed(self.project())['duration_ms'],2000)
    def test_source_range_only(self):
        p=self.project();p['selection'].update(start_page=1,end_page=1)
        p['notes'].append(dict(id=3,page=2,hand=None))
        self.assertEqual(len(export_reviewed(p)['notes']),2)
    def test_invalid_pitch(self):
        for pitch in ('H4','C99','C4garbage'):
            with self.assertRaises(ValueError):pitch_midi(pitch)
    def test_double_accidental_matches_recognizer_pitch(self):
        self.assertEqual(pitch_midi('C##4'),62)
        self.assertEqual(pitch_midi('Dbb4'),60)
    def test_source_range_crosses_page_and_restarted_system_numbers(self):
        p=self.project();p['selection'].update(start_page=1,start_system=2,end_page=2,end_system=1)
        p['notes'][0].update(page=1,system=2)
        p['notes'][1].update(page=2,system=1)
        self.assertEqual(len(export_reviewed(p)['notes']),2)
    def test_missing_source_coordinate_not_silently_included(self):
        p=self.project();p['selection'].update(start_page=1,end_page=1)
        p['notes'][0].pop('page')
        with self.assertRaisesRegex(ValueError,'核对原谱'):export_reviewed(p)
    def test_reversed_source_range_rejected_without_notes(self):
        p=self.project();p['selection'].update(start_page=2,end_page=1)
        with self.assertRaisesRegex(ValueError,'结束位置早于'):export_reviewed(p)
    def test_tie_corrected_as_one_hold_not_repeated_note(self):
        p=self.project();p['notes']=[dict(id=1,page=1,hand='right',pitch='C4',finger=1,
            beat=0,duration_beats=3,confirmed=True),dict(id=2,page=1,hand='right',pitch='C4',
            finger=1,beat=2,duration_beats=1,confirmed=False,excluded=True)]
        score=decode(encode(export_reviewed(p)))
        self.assertEqual(len(score['notes']),1)
        self.assertEqual(score['notes'][0]['duration_ms'],1500)
        self.assertEqual(score['duration_ms'],2000)
    def test_scanned_manual_entry_does_not_require_vector_metadata(self):
        p=self.project();p['notes'][0].update(id='manual-1',issues=['manual_entry_requires_review'])
        p['report']={'unsupported_pages':1,'candidates':0}
        self.assertEqual(len(export_reviewed(p)['notes']),2)
    def test_source_mapping_is_aligned_after_chord_sort(self):
        p=self.project();p['notes'][0].update(beat=0,finger=4,origin=[10,20],bbox=[9,19,11,21])
        p['notes'][1].update(beat=0,finger=2,system=2,measure=3)
        score=export_reviewed(p)
        self.assertEqual([n['finger'] for n in score['notes']],[2,4])
        self.assertEqual([n['id'] for n in score['source_notes']],[2,1])
        self.assertEqual(score['source_notes'][1]['origin'],[10,20])
        self.assertNotIn('source_notes',decode(encode(score)))
    def tied_project(self):
        p=self.project();p['notes']=[dict(id=i,page=1,system=1,measure=i,hand='right',pitch='C4',
            finger=1 if i==1 else None,beat=i-1,duration_beats=1,confirmed=True) for i in (1,2,3)]
        p['notes'][0].update(tie_to=2,tie_reviewed=True)
        p['notes'][1].update(tie_to=3,tie_reviewed=True)
        return p
    def test_reviewed_tie_chain_merged_with_complete_source_provenance(self):
        score=export_reviewed(self.tied_project())
        self.assertEqual(len(score['notes']),1)
        self.assertEqual(score['notes'][0]['duration_ms'],1500)
        self.assertEqual(score['source_notes'][0]['source_note_ids'],[1,2,3])
        self.assertEqual([s['t_ms'] for s in score['source_notes'][0]['source_spans']],[0,500,1000])
    def test_tie_requires_review_and_contiguous_same_pitch(self):
        p=self.tied_project();p['notes'][0]['tie_reviewed']=False
        with self.assertRaisesRegex(ValueError,'确认延音线'):export_reviewed(p)
        for update in ({'pitch':'D4'},{'beat':1.5}):
            p=self.tied_project();p['notes'][1].update(update)
            with self.assertRaisesRegex(ValueError,'音高相同、时间连续'):export_reviewed(p)
    def test_tie_target_outside_source_selection_rejected(self):
        p=self.tied_project();p['selection'].update(start_measure=1,end_measure=1)
        with self.assertRaisesRegex(ValueError,'不在所选区间'):export_reviewed(p)
    def test_candidates_only_merged_after_reviewed_selection(self):
        p=self.tied_project()
        for note in p['notes'][:2]:note['tie_to_candidate']=note.pop('tie_to');note.pop('tie_reviewed')
        p['selection'].update(apply_tie_candidates=True)
        with self.assertRaisesRegex(ValueError,'确认延音线'):export_reviewed(p)
        p['selection']['ties_reviewed']=True
        self.assertEqual(len(export_reviewed(p)['notes']),1)
    def repeated_project(self):
        p=self.project();p['notes'][1]['duration_beats']=.5
        p['selection'].update(repeat_mode='unfold',repeats_reviewed=True)
        p['repeat_sections']=[dict(start_beat=0,end_beat=2,count=2,confirmed=False)]
        return p
    def test_repeat_expansion_preserves_gap_tail_rest_and_source_mapping(self):
        score=export_reviewed(self.repeated_project())
        self.assertEqual([n['t_ms'] for n in score['notes']],[0,500,1000,1500])
        self.assertEqual(score['duration_ms'],3000)
        self.assertEqual([n['id'] for n in score['source_notes']],[1,2,1,2])
    def test_repeat_requires_review_without_changing_written_export(self):
        p=self.repeated_project();p['selection']['repeats_reviewed']=False
        with self.assertRaisesRegex(ValueError,'确认反复段'):export_reviewed(p)
        p['selection']['repeat_mode']='written'
        self.assertEqual(len(export_reviewed(p)['notes']),2)
    def test_partial_and_nested_repeats_rejected(self):
        p=self.repeated_project();p['selection']['start_beat']=1
        with self.assertRaisesRegex(ValueError,'截断反复段'):export_reviewed(p)
        p=self.repeated_project();p['repeat_sections'].append(dict(start_beat=1,end_beat=3,count=2,confirmed=True))
        with self.assertRaisesRegex(ValueError,'嵌套反复'):export_reviewed(p)
    def test_sustain_across_repeat_boundary_rejected(self):
        p=self.repeated_project();p['notes'][1]['duration_beats']=2
        with self.assertRaisesRegex(ValueError,'跨越反复边界'):export_reviewed(p)
    def test_known_final_rest_preserved_without_explicit_end(self):
        p=self.project();p['selection']['end_beat']=None;p['written_duration_beats']=8
        self.assertEqual(export_reviewed(p)['duration_ms'],4000)
    def test_alternate_endings_play_first_once_then_second(self):
        p=self.project();p['selection'].update(end_beat=8,repeat_mode='unfold',repeats_reviewed=True)
        p['notes']=[dict(id=i,page=1,hand='right',pitch='C4',finger=1,beat=i,duration_beats=.5,confirmed=True) for i in range(5)]
        p['repeat_sections']=[dict(start_beat=0,end_beat=3,count=2,first_ending_start_beat=2,second_ending_end_beat=4,confirmed=False)]
        score=export_reviewed(p)
        self.assertEqual([n['t_ms'] for n in score['notes']],[0,500,1000,1500,2000,2500,3000])
        self.assertEqual([n['id'] for n in score['source_notes']],[0,1,2,0,1,3,4])
        self.assertEqual(score['duration_ms'],5000)
    def test_unknown_performance_navigation_not_naively_unfolded(self):
        p=self.repeated_project();p['repeat_review_issues']=['D.S. order unresolved']
        with self.assertRaisesRegex(ValueError,'导航标记'):export_reviewed(p)

if __name__=='__main__':unittest.main()
