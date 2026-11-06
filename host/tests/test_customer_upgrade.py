"""Offline image / region regressions. All esptool and HTTP actions are mocked."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('customer_firmware_upgrade', REPO / 'tools' / 'customer_firmware_upgrade.py')
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


def table():
    blob = bytearray(b'\xff' * 4096)
    for index, (name, kind, subtype, address, size) in enumerate([
        ('nvs', 1, 2, 0x9000, 0x5000), ('app0', 0, 0, 0x10000, 0x140000),
        ('spiffs', 1, 0x82, 0x290000, 0x160000)]):
        struct.pack_into('<HBBII16sI', blob, index * 32, 0x50aa, kind, subtype, address, size, name.encode(), 0)
    return blob


class UpgradeTest(unittest.TestCase):
    def test_mismatching_app_partition_refused(self):
        self.assertEqual(upgrade.validate_partitions(table())['app0'][2], 0x10000)
        bad = table()
        struct.pack_into('<I', bad, 32 + 8, 0x180000)
        with self.assertRaisesRegex(ValueError, '不同'):
            upgrade.validate_partitions(bad)

    def test_default_ota_layout_accepted_only_when_booting_ota0(self):
        ota = bytearray(b'\xff' * 4096)
        for index, (name, kind, subtype, address, size) in enumerate([
            ('nvs', 1, 2, 0x9000, 0x5000), ('otadata', 1, 0, 0xe000, 0x2000),
            ('app0', 0, 0x10, 0x10000, 0x140000), ('app1', 0, 0x11, 0x150000, 0x140000),
            ('spiffs', 1, 0x82, 0x290000, 0x160000)]):
            struct.pack_into('<HBBII16sI', ota, index * 32, 0x50aa, kind, subtype, address, size, name.encode(), 0)
        self.assertEqual(upgrade.validate_partitions(ota)['app0'][1], 0x10)
        def otadata(seq):
            blob = bytearray(b'\xff' * 0x2000)
            struct.pack_into('<I', blob, 0, seq)
            struct.pack_into('<I', blob, 28, __import__('zlib').crc32(struct.pack('<I', seq), 0xffffffff))
            return bytes(blob)
        self.assertIsNone(upgrade.ota_boot_slot(b'\xff' * 0x2000))
        self.assertEqual(upgrade.ota_boot_slot(otadata(1)), 0)  # boot_app0.bin as written by the Arduino upload
        self.assertEqual(upgrade.ota_boot_slot(otadata(2)), 1)

    def test_gui_progress_and_plain_errors(self):
        events = []
        progress = upgrade.Progress(events.append, [])
        progress.span = (10, 70)
        progress.write('Writing at 0x0004a000 [=====>     ] 50.0% 491520/978592 bytes...')
        self.assertEqual(events[-1], ('progress', 40.0))
        self.assertIn('关掉「钢琴手套」软件', upgrade.friendly_error(Exception('could not open port COM9: PermissionError(13)')))
        self.assertIn('拔下来', upgrade.friendly_error(Exception('Failed to connect to ESP32: No serial data received.')))
        for text in [upgrade.friendly_error(Exception('x')), upgrade.friendly_error(ValueError('未找到CP210x主控'))]:
            self.assertNotIn('YES', text)

    def test_corrupted_image_refused_before_esptool(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = b'\xe9' + b'\x00' * 31
            (root / 'firmware.bin').write_bytes(image)
            manifest = dict(chip='esp32', address=0x10000, max_size=0x140000, bytes=len(image),
                            sha256=hashlib.sha256(image).hexdigest())
            (root / 'firmware-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            self.assertEqual(upgrade.load_image(root)[1]['bytes'], 32)
            (root / 'firmware.bin').write_bytes(image[:-1] + b'\x01')
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                upgrade.load_image(root)

    def test_only_application_is_written_and_nvs_matches(self):
        commands = []
        with tempfile.TemporaryDirectory() as temporary:
            def fake_tool(port, command, after='no-reset'):
                commands.append(command)
                if command[0] == 'read-flash':
                    Path(command[-1]).write_bytes(table() if command[1] == '0x8000' else b'calibration-data')
            with patch.dict('os.environ', {'LOCALAPPDATA': temporary}), \
                 patch.object(upgrade, 'release_local_console'), \
                 patch.object(upgrade, 'tool_command', side_effect=fake_tool):
                upgrade.upgrade('COM3', Path(temporary) / 'image.bin', {'sha256': 'test', 'bytes': 913232})
            writes = [command for command in commands if command[0] == 'write-flash']
            self.assertEqual(len(writes), 1)
            self.assertEqual(writes[0][1], '0x10000')
            self.assertFalse(any(command[0] == 'erase-flash' for command in commands))
            report = json.loads(next(Path(temporary).rglob('upgrade-report.json')).read_text(encoding='utf-8'))
            self.assertTrue(report['calibration_nvs_preserved'])
            self.assertFalse(report['ids_written'])
            self.assertFalse(report['filesystem_written'])

    def test_bad_partition_stops_before_any_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            def fake_tool(port, command, after='no-reset'):
                Path(command[-1]).write_bytes(b'\xff' * 4096)
            with patch.dict('os.environ', {'LOCALAPPDATA': temporary}), \
                 patch.object(upgrade, 'release_local_console'), \
                 patch.object(upgrade, 'tool_command', side_effect=fake_tool) as calls:
                with self.assertRaisesRegex(ValueError, '不同'):
                    upgrade.upgrade('COM3', Path(temporary) / 'image.bin', {'sha256': 'test', 'bytes': 913232})
            self.assertEqual(calls.call_count, 1)


if __name__ == '__main__':
    unittest.main()
