"""Native/direct equivalence on independent synthetic scores, no user originals."""
from pathlib import Path
from copy import deepcopy
import os,sys,tempfile,unittest,json
from unittest.mock import patch
HOST=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HOST))
import native_api as module
NativeAPI=module.NativeAPI

def fixture():
    return dict(name='独立合成原生校验',source_sha256='a'*64,automatic_mode=True,source_has_printed_fingering=True,
        selection=dict(bpm=120,start_beat=0),notes=[
            dict(id='good',hand='right',pitch='C4',finger=1,beat=2,duration_beats=1,confirmed=False,manual_fields=['finger'],metadata={'arbitrary':['retain',None,False]}),
            dict(id='ignored',hand='right',pitch='D4',finger=None,beat=None,duration_beats=None,excluded=True),
            dict(id='left',hand='left',pitch='C3',finger=1,beat=0,duration_beats=1,confirmed=False)])

class DirectCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='piano-direct-validation-test-');self.addCleanup(self.tmp.cleanup)
        self.environment=patch.dict(os.environ,LOCALAPPDATA=self.tmp.name);self.environment.start();self.addCleanup(self.environment.stop)
        for name in ('serial.Serial','serial.serial_for_url','socket.socket','webbrowser.open'):
            blocked=patch(name,side_effect=AssertionError('No external I/O: '+name));blocked.start();self.addCleanup(blocked.stop)
        self.api=NativeAPI(None)

    def test_direct_and_existing_route_have_identical_values_and_do_not_mutate_source(self):
        original=fixture();before=deepcopy(original)
        legacy=self.api.request('/api/software/check','POST',{'project':original})
        direct=self.api.check_project(original)
        self.assertEqual(legacy['status'],200);self.assertEqual(direct,legacy['body']);self.assertEqual(original,before)
        self.assertEqual(original['notes'][0]['manual_fields'],['finger'])

    def test_direct_calls_exact_shared_validator_without_request_json_or_http_handler(self):
        original=fixture();expected={'automatic':{'ready':True},'notes':[]};api=NativeAPI.__new__(NativeAPI)
        with patch('score_automatic.check_project',return_value=expected) as validator:
            with patch.object(module.json,'dumps',side_effect=AssertionError('No synthetic HTTP serialization')):
                self.assertEqual(api.check_project(original),dict(ok=True,**expected))
            self.assertIs(validator.call_args.args[0],original)

    def test_invalid_input_propagates_shared_validator_error_and_legacy_error_contract_stays(self):
        for project in (None,[],{},dict(notes='invalid')):
            with self.assertRaisesRegex(ValueError,'曲谱项目不正确'):self.api.check_project(project)
            route=self.api.request('/api/software/check','POST',{'project':project})
            self.assertEqual(route['status'],400);self.assertEqual(route['body']['error'],'曲谱项目不正确')

    def test_independent_large_metadata_is_retained_and_result_matches_route(self):
        original=fixture();original['notes']=[dict(original['notes'][0],id=f'synthetic-{i}',beat=2*i,finger=i%5+1,
            metadata={'retained':'independent synthetic detail '*120,'points':list(range(32))}) for i in range(1600)]
        before=json.dumps(original,sort_keys=True)
        route=self.api.request('/api/software/check','POST',{'project':original})['body']
        self.assertEqual(self.api.check_project(original),route)
        self.assertEqual(json.dumps(original,sort_keys=True),before)

if __name__=='__main__':unittest.main(verbosity=2)
