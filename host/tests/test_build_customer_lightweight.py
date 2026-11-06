"""Small synthetic packaging fixtures; no PyInstaller build or installer execution."""
from pathlib import Path
import hashlib
import importlib.util
import tempfile
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('lightweight_build_under_test',REPO/'tools/build_customer_runtime.py')
build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)

class LightweightBuildTests(unittest.TestCase):
    def fixture(self,root):
        host=Path(root)/'host';host.mkdir()
        for source in build.HOST.iterdir():
            if source.is_file() and source.suffix in {'.html','.css','.js'}:
                (host/source.name).write_text('<!-- desktop-runtime-edition -->' if source.name=='guide.html' else 'synthetic-ui',encoding='utf8')
        assets={'runtime/MicrosoftEdgeWebView2RuntimeInstallerX64.exe':b'fixed-component',
                'drivers/CP210x_Windows_Update.cab':b'driver', 'app-icon.ico':b'icon',
                'score-library/manifest.json':b'{}','score-library/projects/raw.json':b'{"notes":[]}',
                'score-library/original.pdf':b'%PDF-synthetic-packaging-fixture',
                'score-library/ready/song/score.pglpack':b'pack','score-library/ready/song/score.pgl':b'PGL'}
        for name,data in assets.items():
            path=host/'assets'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        return host,assets

    def test_default_preparation_keeps_full_installer_and_light_only_removes_that_runtime_entry(self):
        with tempfile.TemporaryDirectory() as root:
            host,assets=self.fixture(root)
            with patch.object(build,'HOST',host),patch.object(build,'source_modules',return_value=[]):
                full,full_snapshot=build.prepare(Path(root)/'full')
                light,light_snapshot=build.prepare(Path(root)/'light',include_webview_installer=False)
            files=lambda stage:{p.relative_to(stage/'web').as_posix() for p in (stage/'web').rglob('*') if p.is_file()}
            self.assertEqual(files(full)-files(light),{'assets/runtime/MicrosoftEdgeWebView2RuntimeInstallerX64.exe'})
            self.assertEqual(files(light)-files(full),set())
            for name,data in assets.items():
                if name.startswith('runtime/'):continue
                self.assertEqual((light/'web/assets'/name).read_bytes(),data)
            source_key='host/assets/runtime/MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
            self.assertEqual(full_snapshot[source_key],light_snapshot[source_key],'optional offline provenance retained')
            self.assertIn('完整离线首装版',(full/'web/guide.html').read_text(encoding='utf8'))
            self.assertIn('自动联网安装',(light/'web/guide.html').read_text(encoding='utf8'))

    def test_lightweight_cli_is_explicit_and_cannot_silently_affect_old_zip_builds(self):
        with tempfile.TemporaryDirectory() as root:
            args=['build','--work',str(Path(root)/'work'),'--output',str(Path(root)/'out.exe'),'--single-exe','--lightweight']
            with patch.object(build.sys,'argv',args),patch.object(build,'build_single_exe') as run:
                build.main()
            self.assertTrue(run.call_args.kwargs['lightweight'])
            with patch.object(build.sys,'argv',args[:-1]),patch.object(build,'build_single_exe') as run:
                build.main()
            self.assertFalse(run.call_args.kwargs['lightweight'])
            bad=['build','--work',str(Path(root)/'work'),'--output',str(Path(root)/'out.zip'),'--lightweight']
            with patch.object(build.sys,'argv',bad):
                with self.assertRaises(SystemExit) as error:build.main()
            self.assertEqual(error.exception.code,2)

    def test_build_hash_stream_preserves_the_exact_digest(self):
        with tempfile.TemporaryDirectory() as root:
            payload=b'asset-provenance'*100000;path=Path(root)/'asset';path.write_bytes(payload)
            with patch.object(Path,'read_bytes',side_effect=AssertionError('whole file read')):
                self.assertEqual(build.sha256(path),hashlib.sha256(payload).hexdigest())

if __name__=='__main__':unittest.main()
