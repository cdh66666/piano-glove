"""Real JS reset -> existing Python reflow, using independent musical fixtures."""
from pathlib import Path
from copy import deepcopy
import json,subprocess,unittest
from score_timing import reflow_right_hand_timing
from test_score_timing_r11 import event,score

HOST=Path(__file__).resolve().parents[1]
NODE=(__import__('shutil').which('node') or 'node')

class AutomaticStartWorkflowTests(unittest.TestCase):
    def reset(self,p):
        script="const R=require('./software-review.js');let s='';process.stdin.on('data',v=>s+=v);process.stdin.on('end',()=>{const p=JSON.parse(s),result=R.restoreMeasureAutomaticStart(p,p.notes[0]);process.stdout.write(JSON.stringify({project:p,result}));});"
        result=subprocess.run([str(NODE),'-e',script],input=json.dumps(p),text=True,capture_output=True,cwd=HOST,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        return json.loads(result.stdout)
    def test_conflicting_user_chord_onsets_return_to_source_rhythm_and_following_notes_reflow(self):
        stem=[26,0,40]
        p=score([event('a',20,0,rhythm_evidence=dict(stem=stem),finger=1),event('b',29,0,rhythm_evidence=dict(stem=stem),finger=2),event('c',50,1,finger=3)],length=4)
        reflow_right_hand_timing(p)
        p['notes'][0].update(beat=2,manual_fields=['beat']);p['notes'][1].update(beat=3,manual_fields=['beat'])
        reflow_right_hand_timing(p);self.assertIn('手动起拍不同',p['notes'][0]['timing_warning'])
        before=[(n['id'],n['pitch'],n['finger'],n['duration_beats'],n.get('bbox'),n.get('origin')) for n in p['notes']]
        result=self.reset(p);self.assertEqual(result['result']['restored'],2)
        p=result['project'];reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,0,1])
        self.assertEqual(before,[(n['id'],n['pitch'],n['finger'],n['duration_beats'],n.get('bbox'),n.get('origin')) for n in p['notes']])
        self.assertFalse(any('手动起拍不同' in (n.get('timing_warning') or '') for n in p['notes']))
        self.assertFalse(any('beat' in n.get('manual_fields',[]) for n in p['notes']))
    def test_duration_manual_edit_is_kept_and_its_followers_still_follow_after_reset(self):
        p=score([event('a',20,0),event('b',40,1),event('c',60,2)],length=4);reflow_right_hand_timing(p)
        p['notes'][0].update(beat=2,duration_beats=.5,manual_fields=['beat','duration_beats']);reflow_right_hand_timing(p)
        p=self.reset(p)['project'];reflow_right_hand_timing(p)
        self.assertEqual([n['beat'] for n in p['notes']],[0,.5,1.5]);self.assertEqual(p['notes'][0]['manual_fields'],['duration_beats'])
        stable=deepcopy(p);reflow_right_hand_timing(p);self.assertEqual(p,stable)
