"""Synthetic source-absence, editable gray notes and action export semantics."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_automatic import prepare_automatic_project,check_project,export_automatic


def note(identity,beat=0,finger=1,pitch='C4',duration=1,state='printed',**values):
    return dict(id=identity,hand='right',pitch=pitch,finger=finger,beat=beat,
                duration_beats=duration,confirmed=False,source_fingering_state=state,**values)


def project(notes,**values):
    return dict(name='Synthetic unmarked source',notes=notes,
                selection=dict(bpm=120,start_beat=0,repeat_mode='written',range_reviewed=False),**values)


class UnmarkedScoreTests(unittest.TestCase):
    def test_unmarked_is_ready_and_editable_but_not_an_invented_action(self):
        gray=note('unmarked',beat=1,finger=None,pitch='E4',state='unmarked')
        p=project([note('first'),gray,note('later',beat=3,finger=2,pitch='D4')])
        prepared=prepare_automatic_project(p)
        self.assertTrue(gray['unfingered'])
        self.assertTrue(gray['automatic_ready'])
        self.assertFalse(gray.get('excluded',False))
        self.assertIsNone(gray['finger'])
        self.assertEqual(prepared['automatic']['attention_notes'],0)
        self.assertEqual(prepared['automatic']['unfingered_notes'],1)
        self.assertEqual(prepared['automatic']['action_notes'],2)
        self.assertTrue(prepared['automatic']['recognition_ready'])
        before=deepcopy(p)
        score=export_automatic(p)
        self.assertEqual([(n['t_ms'],n['finger']) for n in score['notes']],[(0,1),(1500,2)])
        self.assertEqual(len(p['notes']),3)
        self.assertEqual(p,before)

    def test_unmarked_tail_and_original_rest_do_not_shorten_score(self):
        p=project([note('attack'),note('gray-tail',beat=4,finger=None,state='unmarked')],
                  rests=[dict(hand='right',beat=5,duration_beats=3)])
        score=export_automatic(p)
        self.assertEqual(len(score['notes']),1)
        self.assertEqual(score['notes'][0]['duration_ms'],500)
        self.assertEqual(score['duration_ms'],4000)

    def test_unmarked_lead_does_not_shift_later_attack_earlier(self):
        p=project([note('gray-lead',finger=None,state='unmarked',duration=2),
                   note('attack',beat=3)])
        score=export_automatic(p)
        self.assertEqual(score['notes'][0]['t_ms'],1500)
        self.assertEqual(score['duration_ms'],2000)

    def test_all_unmarked_is_recognition_ready_without_empty_pgl(self):
        p=project([note('one',finger=None,state='unmarked'),
                   note('two',beat=2,finger=None,state='unmarked')])
        prepare_automatic_project(p)
        self.assertTrue(p['automatic']['recognition_ready'])
        self.assertFalse(p['automatic']['ready'])
        self.assertFalse(p['automatic']['unsupported'])
        self.assertEqual(p['automatic']['notes'],2)
        self.assertEqual(p['automatic']['unfingered_notes'],2)
        self.assertEqual(p['automatic']['action_notes'],0)
        self.assertEqual(p['automatic']['attention_notes'],0)
        self.assertFalse(p['report']['requires_review'])
        with self.assertRaisesRegex(ValueError,'没有已设置指法的手指动作'):
            export_automatic(p)

    def test_missing_without_source_evidence_is_not_marked_unprinted(self):
        for state in (None,'unresolved','printed'):
            with self.subTest(state=state):
                p=project([note('missing',finger=None,state=state)])
                prepare_automatic_project(p)
                self.assertFalse(p['notes'][0]['unfingered'])
                self.assertFalse(p['automatic']['recognition_ready'])
                self.assertIn('选择指法',p['notes'][0]['automatic_reasons'])

    def test_filling_gray_activates_action_and_clearing_returns_to_gray(self):
        p=project([note('gray',finger=None,state='unmarked')])
        prepare_automatic_project(p)
        n=p['notes'][0]
        n.update(finger=4,finger_source='manual',manual_fields=['finger'])
        prepare_automatic_project(p)
        self.assertFalse(n['unfingered'])
        self.assertTrue(p['automatic']['ready'])
        self.assertEqual(export_automatic(p)['notes'][0]['finger'],4)
        n['finger']=None
        prepare_automatic_project(p)
        self.assertTrue(n['unfingered'])
        self.assertTrue(p['automatic']['recognition_ready'])
        self.assertEqual(p['automatic']['action_notes'],0)

    def test_unmarked_other_missing_fields_still_need_review(self):
        for field,bad,reason in [('pitch',None,'选择音高'),('beat',None,'确定小节内开始位置'),
                                 ('duration_beats',None,'选择音值'),('hand',None,'确认左右手')]:
            with self.subTest(field=field):
                n=note('gray',finger=None,state='unmarked');n[field]=bad
                p=prepare_automatic_project(project([n]))
                self.assertTrue(n['unfingered'])
                self.assertIn(reason,n['automatic_reasons'])
                self.assertFalse(n['automatic_ready'])
                self.assertFalse(p['automatic']['recognition_ready'])

    def test_invalid_explicit_finger_is_not_treated_as_source_blank(self):
        for value in (0,6,True,'2'):
            with self.subTest(value=value):
                n=note('invalid',finger=value,state='unmarked')
                prepare_automatic_project(project([n]))
                self.assertFalse(n['unfingered'])
                self.assertIn('选择指法',n['automatic_reasons'])

    def test_gray_tie_continuations_extend_the_fingered_attack(self):
        first=note('attack',tie_to_candidate='middle')
        middle=note('middle',beat=1,finger=None,state='unmarked',tie_to_candidate='end')
        last=note('end',beat=2,finger=None,state='unmarked')
        p=project([first,middle,last]);p['selection']['apply_tie_candidates']=True
        before=deepcopy(p)
        score=export_automatic(p)
        self.assertEqual(len(score['notes']),1)
        self.assertEqual(score['notes'][0]['duration_ms'],1500)
        self.assertEqual(score['source_notes'][0]['source_note_ids'],['attack','middle','end'])
        self.assertEqual(p,before)

    def test_gray_notes_keep_their_time_inside_repeated_segments(self):
        p=project([note('attack'),note('gray',beat=1,finger=None,state='unmarked')],
                  repeat_sections=[dict(start_beat=0,end_beat=2,count=2)])
        score=export_automatic(p)
        self.assertEqual([n['t_ms'] for n in score['notes']],[0,1000])
        self.assertEqual(score['duration_ms'],2000)

    def test_source_range_end_uses_gray_tail_not_the_whole_document(self):
        p=project([note('outside',beat=0,page=1,system=1,measure=1),
                   note('selected',beat=4,page=2,system=1,measure=1),
                   note('gray',beat=6,duration=2,finger=None,state='unmarked',page=2,system=1,measure=1)],
                  written_duration_beats=12)
        p['selection'].update(start_page=2,end_page=2)
        score=export_automatic(p)
        self.assertEqual(score['notes'][0]['t_ms'],0)
        self.assertEqual(score['duration_ms'],2000)

    def test_unmarked_tremolo_pulses_are_gaps_not_shortened_time(self):
        settings=dict(duration=2,tremolo_group='synthetic',tremolo_step_beats=.25,tremolo_span_beats=2)
        p=project([note('active',tremolo_side=0,**settings),
                   note('gray',finger=None,state='unmarked',pitch='G4',tremolo_side=1,**settings)])
        score=export_automatic(p)
        self.assertEqual([n['t_ms'] for n in score['notes']],[0,250,500,750])
        self.assertEqual(score['duration_ms'],1000)

    def test_same_finger_conflicts_stay_pending_after_gray_acceptance(self):
        p=prepare_automatic_project(project([note('one',duration=2),note('two',beat=1,pitch='D4'),
                    note('gray',beat=4,finger=None,state='unmarked')]))
        self.assertEqual(p['automatic']['attention_notes'],2)
        self.assertTrue(p['notes'][2]['automatic_ready'])
        self.assertFalse(p['automatic']['recognition_ready'])
        self.assertFalse(p['automatic']['ready'])

    def test_validation_returns_gray_state_without_mutating_source(self):
        p=project([note('gray',finger=None,state='unmarked')]);before=deepcopy(p)
        checked=check_project(p)
        self.assertEqual(p,before)
        self.assertTrue(checked['notes'][0]['unfingered'])
        self.assertEqual(checked['notes'][0]['source_fingering_state'],'unmarked')
        self.assertTrue(checked['notes'][0]['automatic_ready'])


if __name__=='__main__':unittest.main()
