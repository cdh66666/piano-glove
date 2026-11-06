"""Current edit validation and reversible omission, without PDF tuning or devices."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_automatic import check_project,export_automatic,prepare_automatic_project

def note(identity,**values):
    data=dict(id=identity,page=1,system=1,hand='right',pitch='C4',finger=1,beat=0,
              duration_beats=1,confirmed=False,finger_source='printed')
    data.update(values);return data
def project(notes):
    return dict(name='开发验证',automatic_mode=True,source_has_printed_fingering=True,
                notes=notes,selection=dict(bpm=120,start_beat=0,repeat_mode='written'))

class ReviewValidationTests(unittest.TestCase):
    def test_stale_unconfirmed_or_edited_flag_does_not_block_valid_data(self):
        p=project([note('a',automatic_ready=False,automatic_reasons=['旧检查'],manual_fields=['finger'])])
        before=deepcopy(p);result=check_project(p)
        self.assertTrue(result['automatic']['ready'])
        self.assertEqual(result['notes'][0]['automatic_reasons'],[])
        self.assertEqual(p,before)

    def test_ignore_and_restore_incomplete_note_preserves_other_onsets_and_rest(self):
        bad=note('bad',finger=None,beat=None,duration_beats=None)
        good=note('good',beat=4,pitch='E4',finger=3)
        p=project([bad,good]);p['written_duration_beats']=8
        self.assertFalse(check_project(p)['automatic']['ready'])
        original=deepcopy(bad);bad.update(excluded=True,excluded_manual=True)
        result=check_project(p);self.assertTrue(result['automatic']['ready']);self.assertEqual(result['automatic']['ignored_notes'],1)
        score=export_automatic(p)
        self.assertEqual(len(score['notes']),1);self.assertEqual(score['notes'][0]['t_ms'],2000)
        self.assertEqual(score['duration_ms'],4000)
        bad['excluded']=False
        self.assertFalse(check_project(p)['automatic']['ready'])
        self.assertEqual({k:bad[k] for k in original},original)

    def test_overlap_is_detected_even_while_another_note_has_missing_data(self):
        a=note('a',duration_beats=4);b=note('b',beat=1,pitch='E4');c=note('c',beat=8,finger=None)
        p=project([a,b,c]);result=check_project(p)
        issues={n['id']:n['automatic_reasons'] for n in result['notes']}
        self.assertTrue(any('重叠' in x for x in issues['a']))
        self.assertTrue(any('重叠' in x for x in issues['b']))
        b['excluded']=True
        result=check_project(p);issues={n['id']:n['automatic_reasons'] for n in result['notes']}
        self.assertEqual(issues['a'],[]);self.assertEqual(issues['b'],[])
        self.assertEqual(result['automatic']['attention_note_ids'],['c'])

    def test_long_sustain_conflicts_are_not_hidden_by_short_intermediate_note(self):
        p=project([note('long',duration_beats=8),note('short',beat=1),note('later',beat=4)])
        self.assertEqual(set(check_project(p)['automatic']['attention_note_ids']),{'long','short','later'})

    def test_user_cleared_time_is_not_silently_refilled_from_old_candidate(self):
        p=project([note('a',beat=None,written_beat=0,duration_beats=None,duration=1,
                           manual_fields=['beat','duration_beats'])])
        result=prepare_automatic_project(deepcopy(p))
        self.assertIsNone(result['notes'][0]['beat']);self.assertIsNone(result['notes'][0]['duration_beats'])
        self.assertFalse(result['automatic']['ready'])

    def test_ignoring_all_notes_can_be_restored_without_misclassifying_the_source(self):
        p=project([note('a',excluded=True,excluded_manual=True)])
        result=check_project(p)
        self.assertFalse(result['automatic']['ready']);self.assertFalse(result['automatic']['unsupported'])
        self.assertIn('右键恢复',result['automatic']['messages'][0])
        p['notes'][0]['excluded']=False
        self.assertTrue(check_project(p)['automatic']['ready'])

    def test_ignored_tremolo_side_leaves_its_pulse_slots_silent(self):
        common=dict(tremolo_group='t',tremolo_step_beats=.25,tremolo_span_beats=4,duration_beats=4)
        p=project([note('a',tremolo_side=0,**common),note('b',pitch='G4',finger=5,tremolo_side=1,excluded=True,**common)])
        p['written_duration_beats']=4
        score=export_automatic(p)
        self.assertEqual(len(score['notes']),8)
        self.assertEqual([n['t_ms'] for n in score['notes']],list(range(0,2000,250)))
        self.assertEqual(score['duration_ms'],2000)
        self.assertEqual({i for n in score['source_notes'] for i in n['source_note_ids']},{'a'})

    def test_explicit_manual_review_file_uses_supplied_digits_not_inference(self):
        p=project([note('a',finger_source='manual')]);p.update(source_has_printed_fingering=False,manual_review_import=True)
        self.assertTrue(check_project(p)['automatic']['ready'])
        self.assertEqual(export_automatic(p)['notes'][0]['finger'],1)
        p['notes'][0]['finger']=None
        self.assertFalse(check_project(p)['automatic']['ready'])

if __name__=='__main__':unittest.main()
