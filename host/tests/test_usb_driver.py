"""Read-only driver state cases. No serial ports, installers, or elevation."""
import ctypes
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import usb_driver


class DriverDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        usb_driver._cache = None
        usb_driver._cache_at = 0

    def state(self, code, **extra):
        return usb_driver.classify_driver_status([dict(name='CP2102', problem_code=code, **extra)], [])

    def test_missing_driver_is_visible_without_a_com_port(self):
        value = self.state(28)
        self.assertEqual(value['state'], 'missing_driver')
        self.assertEqual(value['problem_code'], 28)
        self.assertFalse(value['port_available'])
        self.assertIn('Silicon Labs', value['message'])

    def test_other_problem_codes_are_not_called_missing_driver(self):
        for code in (10, 22, 31, 43, 52):
            with self.subTest(code=code):
                value = self.state(code)
                self.assertEqual(value['state'], 'device_error')
                self.assertEqual(value['problem_code'], code)
                self.assertIn('不一定是缺少驱动', value['message'])

    def test_healthy_device_waiting_for_com_is_not_a_missing_driver(self):
        value = self.state(0)
        self.assertEqual(value['state'], 'ready')
        self.assertFalse(value['port_available'])
        self.assertIn('等待 COM', value['message'])

    def test_unknown_device_status_stays_unknown(self):
        self.assertEqual(self.state(None)['state'], 'unavailable')

    def test_no_present_hardware_is_unplugged_not_missing_driver(self):
        value = usb_driver.classify_driver_status([], [])
        self.assertEqual(value['state'], 'unplugged')
        self.assertIsNone(value['problem_code'])

    def test_enumeration_failure_cannot_claim_usb_is_unplugged(self):
        with patch.object(usb_driver, '_scan_windows_devices', side_effect=OSError('private device instance path')):
            value = usb_driver.get_driver_status([], refresh=True)
        self.assertEqual(value['state'], 'unavailable')
        self.assertEqual(value['diagnostic_error'], 'OSError')
        self.assertNotIn('private', str(value))

    def test_exact_cp210x_com_port_is_ready_even_if_pnp_is_unavailable(self):
        value = usb_driver.classify_driver_status([], [dict(device='COM7', desc='CP210x', hwid='USB VID:PID=10C4:EA60 SER=SECRET')], 'OSError')
        self.assertEqual(value['state'], 'ready')
        self.assertTrue(value['port_available'])
        self.assertEqual(value['ports'], [{'device': 'COM7', 'desc': 'CP210x'}])
        self.assertNotIn('SECRET', str(value))

    def test_unrelated_serial_ports_do_not_make_the_driver_ready(self):
        for hwid in ('USB VID:PID=1A86:7523', 'USB VID:PID=10C4:EA61', 'ACPI\\PNP0501'):
            value = usb_driver.classify_driver_status([], [dict(device='COM1', hwid=hwid)])
            self.assertEqual(value['state'], 'unplugged')
            self.assertEqual(value['ports'], [])

    def test_hardware_id_matching_accepts_revision_suffix(self):
        self.assertTrue(usb_driver._is_target('USB\\VID_10C4&PID_EA60&REV_0100'))
        self.assertFalse(usb_driver._is_target('USB\\VID_10C4&PID_EA61'))
        self.assertFalse(usb_driver._is_target('USB\\VID_10C4&PID_EA600'))

    def test_device_instance_ids_are_not_in_public_response(self):
        value = self.state(28, instance_id='USB\\VID_10C4&PID_EA60\\PRIVATE_SERIAL')
        self.assertNotIn('PRIVATE_SERIAL', str(value))
        self.assertEqual(set(value['devices'][0]), {'name', 'problem_code'})

    def test_pnp_scan_is_cached_but_new_com_port_is_immediately_seen(self):
        with patch.object(usb_driver, '_scan_windows_devices', return_value=[dict(name='CP2102', problem_code=28)]) as scan, \
             patch.object(usb_driver.time, 'monotonic', return_value=100):
            first = usb_driver.get_driver_status([])
            second = usb_driver.get_driver_status([dict(device='COM3', hwid='USB VID:PID=10C4:EA60')])
        self.assertEqual(first['state'], 'missing_driver')
        self.assertEqual(second['state'], 'ready')
        self.assertEqual(scan.call_count, 1)

    def test_refresh_and_expiry_each_rescan(self):
        with patch.object(usb_driver, '_scan_windows_devices', return_value=[]) as scan, \
             patch.object(usb_driver.time, 'monotonic', side_effect=[100, 101, 102, 108]):
            usb_driver.get_driver_status([])
            usb_driver.get_driver_status([])
            usb_driver.get_driver_status([], refresh=True)
            usb_driver.get_driver_status([])
        self.assertEqual(scan.call_count, 3)

    def test_each_response_is_a_fresh_copy(self):
        with patch.object(usb_driver, '_scan_windows_devices', return_value=[dict(name='CP2102', problem_code=28)]):
            first = usb_driver.get_driver_status([])
            first['devices'][0]['problem_code'] = 0
            second = usb_driver.get_driver_status([])
        self.assertEqual(second['state'], 'missing_driver')

    def test_official_links_are_fixed_https_silabs_urls(self):
        value = self.state(28)
        self.assertTrue(value['driver_download_url'].startswith('https://www.silabs.com/'))
        self.assertTrue(value['driver_download_url'].endswith('CP210x_Universal_Windows_Driver.zip'))
        self.assertTrue(value['driver_page_url'].startswith('https://www.silabs.com/'))

    def test_installed_version_is_optional_and_only_numeric_label_is_published(self):
        value = self.state(0, driver_version='11.5.0.417')
        self.assertEqual(value['devices'][0]['driver_version'], '11.5.0.417')
        private = self.state(0, driver_version='C:\\private\\some-driver.inf')
        self.assertNotIn('driver_version', private['devices'][0])
        self.assertNotIn('private', str(private))

    def test_driver_registry_version_lookup_is_read_only_and_optional(self):
        key = MagicMock()
        registry = SimpleNamespace(HKEY_LOCAL_MACHINE=123, OpenKey=Mock(return_value=key),
                                   QueryValueEx=Mock(return_value=('11.5.0.417', 1)))
        driver_key = '{4d36e978-e325-11ce-bfc1-08002be10318}\\0002'
        with patch.dict(sys.modules, {'winreg': registry}):
            self.assertEqual(usb_driver._read_driver_version(driver_key), '11.5.0.417')
            registry.OpenKey.assert_called_once_with(123, 'SYSTEM\\CurrentControlSet\\Control\\Class\\'+driver_key)
            registry.OpenKey.side_effect = OSError('unavailable')
            self.assertIsNone(usb_driver._read_driver_version(driver_key))
            self.assertIsNone(usb_driver._read_driver_version('unexpected\\registry\\path'))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows SetupAPI harness')
    def test_optional_display_properties_do_not_hide_a_driverless_device(self):
        hardware = 'USB\\VID_10C4&PID_EA60\0\0'.encode('utf-16-le')
        def enumerate_device(handle, index, info):
            if index == 0:
                info._obj.DevInst = 23
                return True
            ctypes.set_last_error(259)
            return False
        def get_property(handle, info, prop, kind, buffer, size, needed):
            if prop != 1:  # Optional labels and registry key denied by OS.
                needed._obj.value = 0
                ctypes.set_last_error(5)
                return False
            needed._obj.value = len(hardware)
            if buffer is None:
                ctypes.set_last_error(122)
                return False
            ctypes.memmove(buffer, hardware, len(hardware))
            return True
        def status(flags, problem, instance, reserved):
            problem._obj.value = 28
            return 0
        setup = SimpleNamespace(SetupDiGetClassDevsW=Mock(return_value=1),
            SetupDiEnumDeviceInfo=Mock(side_effect=enumerate_device),
            SetupDiGetDeviceRegistryPropertyW=Mock(side_effect=get_property),
            SetupDiDestroyDeviceInfoList=Mock(return_value=True))
        config = SimpleNamespace(CM_Get_DevNode_Status=Mock(side_effect=status))
        with patch.object(usb_driver.sys, 'platform', 'win32'), \
             patch.object(usb_driver.ctypes, 'WinDLL', side_effect=[setup, config]):
            devices = usb_driver._scan_windows_devices()
        self.assertEqual(devices, [{'name': 'CP2102 USB to UART Bridge Controller', 'problem_code': 28}])
        setup.SetupDiDestroyDeviceInfoList.assert_called_once_with(1)

    def test_working_com_does_not_erase_another_devices_problem_code(self):
        value = usb_driver.classify_driver_status([dict(name='first', problem_code=0),
            dict(name='second', problem_code=28)], [dict(device='COM3', hwid='USB VID:PID=10C4:EA60')])
        self.assertEqual(value['state'], 'ready')
        self.assertEqual(value['devices'][1]['problem_code'], 28)


if __name__ == '__main__':
    unittest.main()
