"""Chunk protocol guards and exact device bytes using the protocol fake."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_software_console import FakeBridge, SCORE
from bridge import SoftwareConsole
from score_codec import encode


class Tests(unittest.TestCase):
    def setUp(self):
        self.bridge=FakeBridge();self.console=SoftwareConsole(self.bridge);self.blob=encode(SCORE)
    def test_chunks_commit_exact_original_wire_file(self):
        self.console.begin_upload(3,len(self.blob),'one')
        for offset in range(0,len(self.blob),64):self.console.upload_chunk(self.blob[offset:offset+64],'one')
        result=self.console.commit_upload('one')
        raw=b''.join(bytes.fromhex(c.split()[2]) for c in self.bridge.commands if c.startswith('LIB CHUNK'))
        self.assertEqual(raw,self.blob);self.assertEqual(result['slot'],3)
        self.assertEqual(self.bridge.commands[-1],'LIB COMMIT');self.assertIsNone(self.console.upload_session)
    def test_other_tab_cannot_append_commit_or_abort(self):
        self.console.begin_upload(1,len(self.blob),'one')
        before=list(self.bridge.commands)
        for action in [lambda:self.console.upload_chunk(self.blob[:64],'two'),lambda:self.console.commit_upload('two'),lambda:self.console.abort_upload('two')]:
            with self.assertRaisesRegex(RuntimeError,'controller_mismatch'):action()
        self.assertEqual(self.bridge.commands,before)
    def test_incomplete_commit_preserves_session_for_remaining_chunks(self):
        self.console.begin_upload(1,len(self.blob));self.console.upload_chunk(self.blob[:64])
        with self.assertRaisesRegex(ValueError,'upload_incomplete'):self.console.commit_upload()
        self.assertNotIn('LIB COMMIT',self.bridge.commands)
        self.console.upload_chunk(self.blob[64:128]);self.console.upload_chunk(self.blob[128:]);self.console.commit_upload()
    def test_crc_failure_aborts_without_commit(self):
        self.console.begin_upload(1,len(self.blob));bad=bytearray(self.blob);bad[-1]^=1
        for offset in range(0,len(bad),64):self.console.upload_chunk(bad[offset:offset+64])
        with self.assertRaises(ValueError):self.console.commit_upload()
        self.assertNotIn('LIB COMMIT',self.bridge.commands);self.assertEqual(self.bridge.commands[-1],'LIB ABORT')
    def test_timeout_aborts_without_new_chunk(self):
        with patch('bridge.time.monotonic',return_value=10):self.console.begin_upload(1,len(self.blob),'one')
        with patch('bridge.time.monotonic',return_value=41):
            with self.assertRaisesRegex(RuntimeError,'upload_timeout'):self.console.upload_chunk(self.blob[:64],'one')
        self.assertEqual(self.bridge.commands[-1],'LIB ABORT')
    def test_oversized_or_extra_chunk_does_not_reach_device(self):
        self.console.begin_upload(1,len(self.blob));before=list(self.bridge.commands)
        with self.assertRaises(ValueError):self.console.upload_chunk(b'x'*97)
        self.assertEqual(self.bridge.commands,before)
        self.console.upload_chunk(self.blob[:96]);self.console.upload_chunk(self.blob[96:])
        before=list(self.bridge.commands)
        with self.assertRaises(ValueError):self.console.upload_chunk(b'x')
        self.assertEqual(self.bridge.commands,before)
    def test_invalid_begin_no_device_command(self):
        for size in [128,145,960144]:
            with self.assertRaises(ValueError):self.console.begin_upload(1,size)
        with self.assertRaises(ValueError):self.console.begin_upload(1,144,'../bad')
        self.assertEqual(self.bridge.commands,[])


if __name__=='__main__':unittest.main()
