"""Customer import/export behavior, without per-note checkbox work or devices."""
from copy import deepcopy
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from score_automatic import prepare_automatic_project,export_automatic
from score_converter import export_reviewed

def note(identity='a',**values):
    return dict(id=identity,hand='right',pitch='C4',finger=1,beat=0,duration_beats=1,
                confirmed=False,**values)
def project(notes):
    return dict(name='客户新谱',notes=notes,selection=dict(bpm=120,start_beat=0,
                repeat_mode='written',range_reviewed=False))

class AutomaticScoreTests(unittest.TestCase):
    def test_complete_import_exports_without_per_note_or_range_approval(self):
        source=project([note()]);before=deepcopy(source)
        prepared=prepare_automatic_project(source)
        self.assertTrue(prepared['automatic']['ready'])
        self.assertFalse(source['notes'][0]['confirmed'])
        result=export_automatic(source)
        self.assertEqual(result['notes'][0]['t_ms'],0)
        self.assertEqual(result['notes'][0]['duration_ms'],500)
        self.assertFalse(source['selection']['range_reviewed'])
        self.assertEqual(source['notes'][0]['beat'],before['notes'][0]['beat'])

    def test_legacy_missing_digits_stay_pending_without_guessing_absence(self):
        notes=[dict(id=str(i),hand='right',pitch=p,finger=None,beat=i,duration_beats=1)
               for i,p in enumerate(('C4','D4','E4','F4','G4'))]
        source=prepare_automatic_project(project(notes))
        self.assertFalse(source['automatic']['ready'])
        self.assertFalse(source['automatic']['unsupported'])
        self.assertFalse(source['automatic']['recognition_ready'])
        self.assertFalse(any(n['unfingered'] for n in notes))
        self.assertTrue(all(n['finger'] is None for n in notes))
        with self.assertRaisesRegex(ValueError,'还有 5 处'):
            export_automatic(source)

    def test_missing_time_is_not_guessed_from_neighbors_or_page_position(self):
        source=project([dict(note(),beat=None)])
        prepare_automatic_project(source)
        self.assertFalse(source['automatic']['ready'])
        self.assertIsNone(source['notes'][0]['beat'])
        with self.assertRaisesRegex(ValueError,'还有 1 处'):
            export_automatic(source)

    def test_independently_resolved_written_position_is_usable(self):
        source=project([dict(note(),beat=None,written_beat=4)])
        prepare_automatic_project(source)
        self.assertEqual(source['notes'][0]['beat'],4)
        self.assertTrue(source['automatic']['ready'])

    def test_unknown_hand_is_attention_not_silently_discarded(self):
        source=project([dict(note(),hand=None)])
        prepare_automatic_project(source)
        self.assertFalse(source['automatic']['ready'])
        self.assertEqual(source['automatic']['attention_notes'],1)

    def test_ambiguous_rhythm_candidate_does_not_become_accepted_time(self):
        source=project([dict(note(),beat=None,written_beat=4,issues=['beam_spacing_conflict'])])
        prepare_automatic_project(source)
        self.assertIsNone(source['notes'][0]['beat'])
        self.assertFalse(source['automatic']['ready'])

    def test_identical_contiguous_tie_is_merged_without_manual_dialog(self):
        a=note();a['tie_to_candidate']='b'
        b=note('b');b['beat']=1
        source=project([a,b]);source['selection']['apply_tie_candidates']=True
        result=export_automatic(source)
        self.assertEqual(len(result['notes']),1)
        self.assertEqual(result['notes'][0]['duration_ms'],1000)
        self.assertEqual(result['source_notes'][0]['source_note_ids'],['a','b'])

    def test_conflicting_original_fingers_are_preserved_and_reported(self):
        a=note();b=note('b');b['pitch']='E4'
        source=prepare_automatic_project(project([a,b]))
        self.assertFalse(source['automatic']['ready'])
        self.assertEqual([n['finger'] for n in source['notes']],[1,1])
        self.assertEqual(source['automatic']['attention_notes'],2)
        with self.assertRaises(ValueError):export_automatic(source)

    def test_missing_digits_are_not_filled_or_notes_dropped_to_pass(self):
        source=project([dict(id=str(i),hand='right',pitch=p,finger=None,beat=0,duration_beats=1)
                        for i,p in enumerate(('C4','D4','E4','F4','G4','A4'))])
        prepare_automatic_project(source)
        self.assertFalse(source['automatic']['ready'])
        self.assertEqual(len(source['notes']),6)
        with self.assertRaises(ValueError):export_automatic(source)

    def test_original_manual_export_contract_is_unchanged(self):
        with self.assertRaisesRegex(ValueError,'请对照原谱'):
            export_reviewed(project([note()]))

    def test_explicit_resolved_repeat_plays_without_an_extra_approval_step(self):
        a=note();b=dict(note('b'),beat=1,pitch='D4',finger=2)
        source=project([a,b]);source['repeat_sections']=[dict(start_beat=0,end_beat=2,count=2)]
        result=export_automatic(source)
        self.assertEqual([n['pitch'] for n in result['notes']],[60,62,60,62])
        self.assertEqual(result['duration_ms'],2000)

    def test_user_can_keep_written_order_after_automatic_repeat_detection(self):
        source=project([note()]);source['repeat_sections']=[dict(start_beat=0,end_beat=1,count=2)]
        prepare_automatic_project(source)
        self.assertEqual(source['selection']['repeat_mode'],'unfold')
        source['selection']['repeat_mode']='written'
        self.assertEqual(len(export_automatic(source)['notes']),1)

    def test_notated_tremolo_expands_alternating_chords_and_retains_source_ids(self):
        members=[]
        for identity,pitch,finger,side in [('a','C4',1,0),('b','E4',3,0),('c','C5',5,1)]:
            members.append(dict(id=identity,hand='right',pitch=pitch,finger=finger,beat=0,duration_beats=4,
                tremolo_group='group',tremolo_side=side,tremolo_step_beats=.25,tremolo_span_beats=4))
        source=project(members);before=deepcopy(source)
        result=export_automatic(source)
        self.assertEqual(len(result['notes']),24)
        self.assertEqual([(n['t_ms'],n['pitch']) for n in result['notes'][:3]],[(0,60),(0,64),(125,72)])
        self.assertEqual({i for n in result['source_notes'] for i in n['source_note_ids']},{'a','b','c'})
        self.assertEqual(source,before)

    def test_incomplete_tremolo_group_does_not_silently_become_held_whole_notes(self):
        a=dict(note(),duration_beats=4,tremolo_group='x',tremolo_side=0,
               tremolo_step_beats=.25,tremolo_span_beats=4)
        with self.assertRaisesRegex(ValueError,'震音'):
            export_automatic(project([a]))

if __name__=='__main__':unittest.main()
