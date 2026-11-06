"""Prerequisite path tests; no installed runtime is removed or changed."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import desktop_setup

class SetupTests(unittest.TestCase):
    def test_download_entry_is_fixed_and_only_opens_after_the_explicit_api_call(self):
        from native_window import DesktopAPI
        api=DesktopAPI.__new__(DesktopAPI)
        with patch('os.startfile',create=True) as opened, patch('webbrowser.open',return_value=True) as fallback:
            self.assertEqual(api.open_runtime_download(),{'opened':True})
        opened.assert_called_once_with(desktop_setup.RUNTIME_DOWNLOAD_URL)
        fallback.assert_not_called()

    def test_existing_runtime_never_launches_an_installer_or_window(self):
        with patch.object(desktop_setup,'installed_runtime',return_value='155.0.4283.62'), \
             patch.object(desktop_setup,'_splash') as splash,patch.object(desktop_setup.subprocess,'Popen') as launch, \
             patch.object(desktop_setup,'_sha256_file') as read_component:
            result=desktop_setup.ensure_runtime(Path('not-needed'))
        self.assertFalse(result['installed']);launch.assert_not_called();splash.assert_not_called();read_component.assert_not_called()

    def package(self,root):
        path=Path(root)/'assets/runtime'/desktop_setup.RUNTIME_FILENAME
        path.parent.mkdir(parents=True)
        path.write_bytes(b'official-installer-test-fixture')
        return path

    def test_missing_runtime_uses_verified_offline_installer_and_requires_real_detection(self):
        with tempfile.TemporaryDirectory() as root:
            package=self.package(root)
            child=Mock(returncode=0);child.poll.return_value=0
            with patch.object(desktop_setup,'installed_runtime',side_effect=[None,'155.0.4283.62']), \
                 patch.object(desktop_setup,'RUNTIME_SHA256',hashlib.sha256(package.read_bytes()).hexdigest()), \
                 patch('usb_driver_install._verify_catalog') as trust, \
                 patch.object(desktop_setup.subprocess,'Popen',return_value=child) as launch:
                result=desktop_setup.ensure_runtime(root,False)
            self.assertTrue(result['installed'])
            trust.assert_called_once_with(package)
            self.assertEqual(launch.call_args.args[0],[str(package),'/silent','/install'])

    def test_success_exit_without_runtime_is_not_success(self):
        with tempfile.TemporaryDirectory() as root:
            package=self.package(root)
            child=Mock(returncode=0);child.poll.return_value=0
            with patch.object(desktop_setup,'installed_runtime',return_value=None), \
                 patch.object(desktop_setup,'RUNTIME_SHA256',hashlib.sha256(package.read_bytes()).hexdigest()), \
                 patch('usb_driver_install._verify_catalog'),patch.object(desktop_setup.subprocess,'Popen',return_value=child):
                with self.assertRaisesRegex(RuntimeError,'未完成安装'):desktop_setup.ensure_runtime(root,False)

    def test_corrupt_installer_never_executes(self):
        with tempfile.TemporaryDirectory() as root:
            self.package(root)
            with patch.object(desktop_setup,'installed_runtime',return_value=None), \
                 patch.object(desktop_setup.subprocess,'Popen') as launch:
                with self.assertRaisesRegex(RuntimeError,'校验失败'):desktop_setup.ensure_runtime(root,False)
            launch.assert_not_called()

    def test_runtime_too_old_for_desktop_selectors_uses_the_offline_upgrade(self):
        with tempfile.TemporaryDirectory() as root:
            package=self.package(root)
            child=Mock(returncode=0);child.poll.return_value=0
            with patch.object(desktop_setup,'installed_runtime',side_effect=['94.0.992.50','155.0.4283.62']), \
                 patch.object(desktop_setup,'RUNTIME_SHA256',hashlib.sha256(package.read_bytes()).hexdigest()), \
                 patch('usb_driver_install._verify_catalog'),patch.object(desktop_setup.subprocess,'Popen',return_value=child) as launch:
                self.assertTrue(desktop_setup.ensure_runtime(root,False)['installed'])
            launch.assert_called_once()

    def test_unchanged_old_runtime_is_not_a_successful_upgrade(self):
        with tempfile.TemporaryDirectory() as root:
            package=self.package(root)
            child=Mock(returncode=0);child.poll.return_value=0
            with patch.object(desktop_setup,'installed_runtime',return_value='94.0.992.50'), \
                 patch.object(desktop_setup,'RUNTIME_SHA256',hashlib.sha256(package.read_bytes()).hexdigest()), \
                 patch('usb_driver_install._verify_catalog'),patch.object(desktop_setup.subprocess,'Popen',return_value=child):
                with self.assertRaisesRegex(RuntimeError,'未完成安装'):desktop_setup.ensure_runtime(root,False)

    def test_lightweight_missing_runtime_uses_only_the_explicit_same_folder_sidecar(self):
        with tempfile.TemporaryDirectory() as root:
            app=Path(root)/'application';app.mkdir();package=app/desktop_setup.RUNTIME_FILENAME
            payload=b'official-sidecar-fixture';package.write_bytes(payload)
            child=Mock(returncode=0);child.poll.return_value=0
            with patch.object(desktop_setup,'installed_runtime',side_effect=[None,'155.0.4283.62']), \
                 patch.object(desktop_setup,'RUNTIME_SHA256',hashlib.sha256(payload).hexdigest()), \
                 patch('usb_driver_install._verify_catalog') as trust, \
                 patch.object(desktop_setup.subprocess,'Popen',return_value=child) as launch:
                result=desktop_setup.ensure_runtime(Path(root)/'missing-bundle',False,executable_dir=app)
            self.assertTrue(result['installed']);trust.assert_called_once_with(package)
            self.assertEqual(launch.call_args.args[0],[str(package),'/silent','/install'])

    def test_missing_both_component_locations_has_an_honest_official_download_instruction(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(desktop_setup,'installed_runtime',return_value=None), \
                 patch.object(desktop_setup.subprocess,'Popen') as launch,patch.object(desktop_setup,'_splash') as splash:
                with self.assertRaises(RuntimeError) as error:
                    desktop_setup.ensure_runtime(Path(root)/'assets-root',False,executable_dir=Path(root)/'application')
            text=str(error.exception);self.assertIn(desktop_setup.RUNTIME_FILENAME,text)
            self.assertIn(desktop_setup.RUNTIME_DOWNLOAD_URL,text);self.assertIn('主程序旁',text)
            self.assertNotIn('软件会使用内置',text);launch.assert_not_called();splash.assert_not_called()

    def bootstrapper(self,root,payload=b'official-bootstrapper-fixture'):
        path=Path(root)/'assets/runtime'/desktop_setup.BOOTSTRAPPER_FILENAME
        path.parent.mkdir(parents=True);path.write_bytes(payload)
        return path

    def test_lightweight_without_offline_installer_runs_the_verified_online_bootstrapper(self):
        with tempfile.TemporaryDirectory() as root:
            package=self.bootstrapper(root);app=Path(root)/'application';app.mkdir()
            child=Mock(returncode=0);child.poll.return_value=0
            with patch.object(desktop_setup,'installed_runtime',side_effect=[None,'155.0.4283.62']), \
                 patch.object(desktop_setup,'BOOTSTRAPPER_SHA256',hashlib.sha256(package.read_bytes()).hexdigest()), \
                 patch('usb_driver_install._verify_catalog') as trust, \
                 patch('webbrowser.open') as browser, \
                 patch.object(desktop_setup.subprocess,'Popen',return_value=child) as launch:
                self.assertTrue(desktop_setup.ensure_runtime(root,False,executable_dir=app)['installed'])
            trust.assert_called_once_with(package);browser.assert_not_called()
            self.assertEqual(launch.call_args.args[0],[str(package),'/silent','/install'])

    def test_offline_sidecar_keeps_priority_over_the_online_bootstrapper(self):
        with tempfile.TemporaryDirectory() as root:
            self.bootstrapper(root);app=Path(root)/'application';app.mkdir()
            sidecar=app/desktop_setup.RUNTIME_FILENAME;sidecar.write_bytes(b'offline-sidecar')
            child=Mock(returncode=0);child.poll.return_value=0
            with patch.object(desktop_setup,'installed_runtime',side_effect=[None,'155.0.4283.62']), \
                 patch.object(desktop_setup,'RUNTIME_SHA256',hashlib.sha256(b'offline-sidecar').hexdigest()), \
                 patch('usb_driver_install._verify_catalog'), \
                 patch.object(desktop_setup.subprocess,'Popen',return_value=child) as launch:
                desktop_setup.ensure_runtime(root,False,executable_dir=app)
            self.assertEqual(launch.call_args.args[0][0],str(sidecar))

    def test_online_bootstrapper_failure_asks_for_network_and_tampered_copy_never_runs(self):
        with tempfile.TemporaryDirectory() as root:
            package=self.bootstrapper(root);app=Path(root)/'application';app.mkdir()
            child=Mock(returncode=-2147012889);child.poll.return_value=child.returncode
            with patch.object(desktop_setup,'installed_runtime',return_value=None), \
                 patch.object(desktop_setup,'BOOTSTRAPPER_SHA256',hashlib.sha256(package.read_bytes()).hexdigest()), \
                 patch('usb_driver_install._verify_catalog'),patch.object(desktop_setup.subprocess,'Popen',return_value=child):
                with self.assertRaisesRegex(RuntimeError,'连上网络'):desktop_setup.ensure_runtime(root,False,executable_dir=app)
            with patch.object(desktop_setup,'installed_runtime',return_value=None), \
                 patch.object(desktop_setup.subprocess,'Popen') as launch:
                with self.assertRaisesRegex(RuntimeError,'校验失败'):desktop_setup.ensure_runtime(root,False,executable_dir=app)
            launch.assert_not_called()

    def test_bundled_bootstrapper_matches_the_pinned_microsoft_copy(self):
        package=Path(desktop_setup.__file__).resolve().parent/'assets/runtime'/desktop_setup.BOOTSTRAPPER_FILENAME
        self.assertEqual(desktop_setup._sha256_file(package),desktop_setup.BOOTSTRAPPER_SHA256)

    def test_sidecar_must_match_hash_and_microsoft_trust_before_launch(self):
        with tempfile.TemporaryDirectory() as root:
            package=Path(root)/desktop_setup.RUNTIME_FILENAME;package.write_bytes(b'changed-sidecar')
            with patch.object(desktop_setup,'installed_runtime',return_value=None), \
                 patch.object(desktop_setup.subprocess,'Popen') as launch:
                with self.assertRaisesRegex(RuntimeError,'校验失败'):
                    desktop_setup.ensure_runtime(Path(root)/'empty-bundle',False,executable_dir=root)
            launch.assert_not_called()
            with patch.object(desktop_setup,'installed_runtime',return_value=None), \
                 patch.object(desktop_setup,'RUNTIME_SHA256',hashlib.sha256(b'changed-sidecar').hexdigest()), \
                 patch('usb_driver_install._verify_catalog',side_effect=RuntimeError('签名未验证')), \
                 patch.object(desktop_setup.subprocess,'Popen') as launch:
                with self.assertRaisesRegex(RuntimeError,'签名未验证'):
                    desktop_setup.ensure_runtime(Path(root)/'empty-bundle',False,executable_dir=root)
            launch.assert_not_called()

    def test_installer_hash_is_streamed_without_a_whole_file_read(self):
        with tempfile.TemporaryDirectory() as root:
            payload=b'bounded-hash-fixture'*100000;package=Path(root)/'component';package.write_bytes(payload)
            with patch.object(Path,'read_bytes',side_effect=AssertionError('must stream')):
                self.assertEqual(desktop_setup._sha256_file(package),hashlib.sha256(payload).hexdigest())

    def test_full_bundle_keeps_priority_over_a_same_named_sidecar(self):
        with tempfile.TemporaryDirectory() as root:
            bundled=self.package(root);app=Path(root)/'application';app.mkdir()
            (app/desktop_setup.RUNTIME_FILENAME).write_bytes(b'unused-sidecar')
            child=Mock(returncode=0);child.poll.return_value=0
            with patch.object(desktop_setup,'installed_runtime',side_effect=[None,'155.0.4283.62']), \
                 patch.object(desktop_setup,'RUNTIME_SHA256',hashlib.sha256(bundled.read_bytes()).hexdigest()), \
                 patch('usb_driver_install._verify_catalog'), \
                 patch.object(desktop_setup.subprocess,'Popen',return_value=child) as launch:
                self.assertTrue(desktop_setup.ensure_runtime(root,False,executable_dir=app)['installed'])
            self.assertEqual(launch.call_args.args[0][0],str(bundled))

if __name__=='__main__':unittest.main()
