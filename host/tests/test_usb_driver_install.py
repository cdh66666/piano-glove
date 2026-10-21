"""Driver installation is fully mocked: no UAC, PnPUtil, COM or network calls."""
import io
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import usb_driver_install as install

MISSING = dict(state='missing_driver', port_available=False, ports=[], message='missing')
READY = dict(state='ready', port_available=True, ports=[dict(device='COM7', desc='CP210x')])


class InstallerTests(unittest.TestCase):
    def run_worker(self, diagnostics=(MISSING, READY), exit_code=0, exception=None):
        manager = install.USBDriverInstaller()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(install.sys, 'platform', 'win32'), \
             patch.dict(install.os.environ, {'LOCALAPPDATA': directory}), \
             patch.object(install, '_diagnose', side_effect=diagnostics) as diagnose, \
             patch.object(install, '_download_package', return_value=Path(directory)/'driver.zip') as download, \
             patch.object(install, '_extract_package', return_value=(Path(directory)/'silabser.inf', Path(directory)/'silabser.cat')) as extract, \
             patch.object(install, '_verify_catalog') as verify, \
             patch.object(install, '_install_inf', side_effect=exception, return_value=exit_code) as apply, \
             patch.object(install, '_rescan_devices') as rescan, \
             patch.object(install.time, 'monotonic', side_effect=[100, 121]), \
             patch.object(install.time, 'sleep'):
            (Path(directory)/'driver.zip').write_bytes(b'official-test-package')
            manager._worker()
            return manager.status(), dict(diagnose=diagnose, download=download, extract=extract, verify=verify, apply=apply, rescan=rescan)

    def test_installed_driver_does_not_download_or_elevate(self):
        state, calls = self.run_worker((READY,))
        self.assertTrue(state['verified'])
        self.assertEqual(state['state'], 'ready')
        calls['apply'].assert_not_called()
        calls['download'].assert_not_called()

    def test_absent_or_unknown_device_is_not_installed_blindly(self):
        for diagnostic in (dict(state='unplugged', message='接上 USB'), dict(state='unavailable', message='未知'),
                           dict(state='ready', port_available=False, message='等待 COM')):
            with self.subTest(state=diagnostic['state']):
                state, calls = self.run_worker((diagnostic,))
                self.assertFalse(state['verified'])
                calls['apply'].assert_not_called()

    def test_install_verifies_package_before_invoking_windows_and_requires_com(self):
        state, calls = self.run_worker()
        self.assertEqual(state['state'], 'ready')
        self.assertTrue(state['verified'])
        self.assertEqual(state['ports'][0]['device'], 'COM7')
        calls['verify'].assert_called_once()
        calls['apply'].assert_called_once()
        calls['rescan'].assert_called_once()
        self.assertFalse(state['busy'])

    def test_success_exit_without_com_is_not_a_verified_install(self):
        state, calls = self.run_worker((MISSING, MISSING), 0)
        self.assertEqual(state['state'], 'waiting_port')
        self.assertFalse(state['verified'])

    def test_restart_needed_is_reported_without_restarting(self):
        state, calls = self.run_worker((MISSING, MISSING), 3010)
        self.assertEqual(state['state'], 'restart_required')
        self.assertTrue(state['restart_required'])
        self.assertFalse(state['verified'])

    def test_restart_exit_with_usable_com_is_ready(self):
        state, _ = self.run_worker(exit_code=3010)
        self.assertTrue(state['verified'])

    def test_cancelled_admin_prompt_is_retriable_and_not_success(self):
        state, calls = self.run_worker(exception=install.InstallationCancelled())
        self.assertEqual(state['state'], 'cancelled')
        self.assertFalse(state['verified'])
        self.assertFalse(state['busy'])
        calls['rescan'].assert_not_called()

    def test_nonzero_windows_result_does_not_claim_install_success(self):
        state, calls = self.run_worker(exit_code=5)
        self.assertEqual(state['error'], 'windows_install_failed')
        self.assertFalse(state['verified'])
        calls['rescan'].assert_not_called()

    def test_start_is_single_flight_and_takes_no_input(self):
        manager = install.USBDriverInstaller()
        with patch.object(install.threading, 'Thread') as thread:
            first = manager.start()
            second = manager.start()
            self.assertTrue(first['busy'] and second['busy'])
            self.assertEqual(thread.call_count, 1)
            with self.assertRaises(TypeError):
                manager.start(url='https://untrusted.invalid/driver.zip')

    def test_status_returns_independent_public_port_records(self):
        manager = install.USBDriverInstaller()
        manager._update(ports=[dict(device='COM7')])
        manager.status()['ports'][0]['device'] = 'changed'
        self.assertEqual(manager.status()['ports'][0]['device'], 'COM7')

    def test_native_handoff_requests_windows_uac_for_only_system_pnputil(self):
        shell,kernel=Mock(),Mock()
        captured={}
        def execute(pointer):
            value=pointer._obj
            captured.update(verb=value.lpVerb,file=value.lpFile,parameters=value.lpParameters,show=value.nShow)
            value.hProcess=123
            return True
        def exit_code(handle,pointer):pointer._obj.value=0;return True
        shell.ShellExecuteExW.side_effect=execute
        kernel.WaitForSingleObject.return_value=0
        kernel.GetExitCodeProcess.side_effect=exit_code
        update=Mock()
        with patch.object(install.sys,'platform','win32'),patch.dict(install.os.environ,{'SystemRoot':'C:/Windows'}), \
             patch.object(Path,'exists',return_value=False),patch.object(Path,'is_file',return_value=True), \
             patch.object(install.ctypes,'WinDLL',side_effect=lambda name,**kw:{'shell32':shell,'kernel32':kernel}[name]):
            self.assertEqual(install._install_inf(Path('C:/driver/silabser.inf'),update),0)
        self.assertEqual(captured['verb'],'runas')
        self.assertTrue(captured['file'].replace('\\','/').endswith('/System32/pnputil.exe'))
        self.assertEqual(captured['parameters'],'/add-driver "C:\\driver\\silabser.inf" /install' if sys.platform=='win32' else '/add-driver "C:/driver/silabser.inf" /install')
        self.assertEqual(captured['show'],0)
        kernel.CloseHandle.assert_called_once_with(123)

    def test_native_cancel_is_a_cancelled_result_not_an_install(self):
        shell,kernel=Mock(),Mock()
        shell.ShellExecuteExW.return_value=False
        with patch.object(install.sys,'platform','win32'),patch.dict(install.os.environ,{'SystemRoot':'C:/Windows'}), \
             patch.object(Path,'exists',return_value=False),patch.object(Path,'is_file',return_value=True), \
             patch.object(install.ctypes,'get_last_error',return_value=1223), \
             patch.object(install.ctypes,'WinDLL',side_effect=lambda name,**kw:{'shell32':shell,'kernel32':kernel}[name]):
            with self.assertRaises(install.InstallationCancelled):install._install_inf(Path('C:/driver/silabser.inf'),Mock())
        kernel.WaitForSingleObject.assert_not_called()

    def archive(self, directory, files):
        path = Path(directory)/'driver.zip'
        with zipfile.ZipFile(path, 'w') as target:
            for name, data in files.items():target.writestr(name, data)
        return path

    def test_official_inf_catalog_and_hardware_id_required(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.archive(directory, {'silabser.inf': '[Models]\nUSB\\VID_10C4&PID_EA60', 'silabser.cat': b'catalog'})
            inf, cat = install._extract_package(archive, Path(directory))
            self.assertEqual(inf.name, 'silabser.inf')
            self.assertEqual(cat.name, 'silabser.cat')

    def test_foreign_driver_or_missing_catalog_rejected(self):
        for files in ({'silabser.inf': 'USB\\VID_1234&PID_5678', 'silabser.cat': b'x'}, {'silabser.inf': 'USB\\VID_10C4&PID_EA60'}):
            with tempfile.TemporaryDirectory() as directory:
                archive = self.archive(directory, files)
                with self.assertRaises(ValueError):install._extract_package(archive, Path(directory))

    def test_archive_path_escape_rejected_before_extraction(self):
        for name in ('../outside.sys', '/outside.sys', 'C:/outside.sys', '..\\outside.sys'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                archive = self.archive(directory, {name:b'bad'})
                with self.assertRaises(ValueError):install._extract_package(archive, Path(directory))

    def test_redirect_to_non_vendor_host_is_not_downloaded(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = 'https://untrusted.invalid/package.zip'
        with tempfile.TemporaryDirectory() as directory, patch.object(install, 'urlopen', return_value=response):
            with self.assertRaises(ValueError):install._download_package(Path(directory))
        response.read.assert_not_called()

    def test_vendor_download_failure_uses_only_fixed_official_microsoft_fallback(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(install,'_native_architecture',return_value='AMD64'),patch.object(install, '_download_from', side_effect=[OSError('403'),Path(directory)/'driver.cab']) as download:
            result=install._download_package(Path(directory))
        self.assertEqual(result.suffix,'.cab')
        self.assertEqual(download.call_args_list[0].args[0],install.DRIVER_DOWNLOAD_URL)
        self.assertEqual(download.call_args_list[1].args[0],install.MICROSOFT_DRIVER_URL)
        self.assertTrue(download.call_args_list[1].kwargs['microsoft'])

    def test_microsoft_catalog_fallback_does_not_apply_to_other_native_architectures(self):
        for architecture in ('ARM64','X86','UNKNOWN'):
            with self.subTest(architecture=architecture),tempfile.TemporaryDirectory() as directory, \
                 patch.object(install,'_native_architecture',return_value=architecture), \
                 patch.object(install,'_download_from',side_effect=OSError('403')) as download:
                with self.assertRaises(OSError):install._download_package(Path(directory))
                self.assertEqual(download.call_count,1)

    def test_microsoft_cab_hash_must_match_before_system_expansion(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(install,'_expand_cab') as expand:
            archive=Path(directory)/'driver.cab';archive.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'hash_mismatch'):
                install._extract_package(archive,Path(directory))
            expand.assert_not_called()

    def test_verified_cab_uses_system_expansion_and_same_inf_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'driver.cab';archive.write_bytes(b'official-cab-fixture')
            def expand(source,destination):
                (destination/'silabser.inf').write_text('USB\\VID_10C4&PID_EA60',encoding='utf-8')
                (destination/'silabser.cat').write_bytes(b'catalog')
            with patch.object(install,'MICROSOFT_DRIVER_SHA256',hashlib.sha256(archive.read_bytes()).hexdigest()),patch.object(install,'_expand_cab',side_effect=expand):
                inf,cat=install._extract_package(archive,Path(directory))
            self.assertEqual(inf.name,'silabser.inf');self.assertEqual(cat.name,'silabser.cat')

    def test_untrusted_catalog_never_reaches_install(self):
        with patch.object(install, '_verify_catalog', side_effect=ValueError('invalid')):
            # Keep this separate from run_worker's trusted-catalog patch.
            manager = install.USBDriverInstaller()
            with tempfile.TemporaryDirectory() as directory, patch.object(install.sys, 'platform', 'win32'), \
                 patch.dict(install.os.environ, {'LOCALAPPDATA':directory}), \
                 patch.object(install, '_diagnose', return_value=MISSING), \
                 patch.object(install, '_download_package', return_value=Path(directory)/'driver.zip'), \
                 patch.object(install, '_extract_package', return_value=(Path(directory)/'silabser.inf', Path(directory)/'silabser.cat')), \
                 patch.object(install, '_install_inf') as apply:
                manager._worker()
            self.assertEqual(manager.status()['error'], 'verify_failed')
            apply.assert_not_called()


if __name__ == '__main__':unittest.main()
