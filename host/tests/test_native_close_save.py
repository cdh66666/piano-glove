"""Close/save handshake without a window, device, or user workspace."""
from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_window import DesktopAPI


class Window:
    def __init__(self):
        loaded = threading.Event()
        loaded.set()
        self.events = SimpleNamespace(loaded=loaded)
        self.evaluated = threading.Event()
        self.calls = []
        self.callback = None
        self.destroyed = 0
        self.failure = None

    def evaluate_js(self, script, callback=None):
        self.calls.append((script, callback, threading.get_ident()))
        if callback:
            self.callback = callback
            self.evaluated.set()
        if self.failure:raise self.failure
        return 'true'  # Dispatch success is deliberately not save completion.

    def destroy(self):
        self.destroyed += 1


class CloseSaveTests(unittest.TestCase):
    def setUp(self):
        # Isolate just the close protocol: no constructors that open stores,
        # device transports, original files, or browser windows.
        self.api = DesktopAPI.__new__(DesktopAPI)
        self.api._window = self.window = Window()
        self.api._close_lock = threading.Lock()
        self.api._close_pending = False
        self.api._close_approved = False
        self.api._close_error = None
        self.api._confirm_discard_close = Mock(return_value=False)

    def begin_close(self):
        ui_thread = threading.get_ident()
        self.assertIs(self.api._before_close(), False)
        self.assertTrue(self.window.evaluated.wait(2), 'background close worker did not dispatch')
        self.assertNotEqual(self.window.calls[0][2], ui_thread)

    def test_ui_thread_close_is_cancelled_until_save_promise_callback(self):
        self.begin_close()
        self.assertEqual(self.window.destroyed, 0)
        self.assertTrue(self.api._close_pending)
        self.window.callback({'saved': True})
        self.assertEqual(self.window.destroyed, 1)
        self.assertIsNone(self.api._before_close())

    def test_repeated_close_while_saving_does_not_duplicate_save(self):
        self.begin_close()
        self.assertIs(self.api._before_close(), False)
        self.assertEqual(len(self.window.calls), 1)

    def test_failed_save_preserves_window_and_allows_retry(self):
        self.begin_close()
        self.window.callback({'saved': False, 'error': '磁盘空间不足'})
        self.assertEqual(self.window.destroyed, 0)
        self.assertFalse(self.api._close_pending)
        self.assertEqual(self.api._close_error, '磁盘空间不足')
        self.window.evaluated.clear()
        self.begin_close()
        self.assertEqual(len(self.window.calls), 2)
        self.window.callback({'saved': True})
        self.assertEqual(self.window.destroyed, 1)
        self.api._confirm_discard_close.assert_not_called()

    def repeat_failure(self, answer):
        self.begin_close()
        self.window.callback({'saved': False})
        self.api._confirm_discard_close.assert_not_called()
        self.window.evaluated.clear()
        self.begin_close()
        done=threading.Event()
        real_offer=self.api._offer_discard_close
        def offered():
            try:real_offer()
            finally:done.set()
        self.api._offer_discard_close=offered
        self.api._confirm_discard_close.return_value=answer
        self.window.callback({'saved': False})
        self.assertTrue(done.wait(2))

    def test_repeated_save_failure_cancel_preserves_window(self):
        self.repeat_failure(False)
        self.api._confirm_discard_close.assert_called_once()
        self.assertEqual(self.window.destroyed,0)
        self.assertFalse(self.api._close_approved)
        self.assertFalse(self.api._close_pending)

    def test_repeated_save_failure_explicit_yes_closes(self):
        self.repeat_failure(True)
        self.api._confirm_discard_close.assert_called_once()
        self.assertEqual(self.window.destroyed,1)
        self.assertTrue(self.api._close_approved)

    def test_discard_confirmation_runs_off_calling_thread_and_needs_exact_true(self):
        caller=threading.get_ident()
        dialog_threads=[]
        self.api._confirm_discard_close.side_effect=lambda:dialog_threads.append(threading.get_ident()) or 'yes'
        self.repeat_failure(None)
        self.assertNotEqual(dialog_threads,[caller])
        self.assertEqual(len(dialog_threads),1)
        self.assertEqual(self.window.destroyed,0)

    def test_dialog_failure_does_not_close_or_get_stuck_pending(self):
        self.api._confirm_discard_close.side_effect=RuntimeError('dialog unavailable')
        self.api._close_pending=True
        self.api._offer_discard_close()
        self.assertEqual(self.window.destroyed,0)
        self.assertFalse(self.api._close_pending)
        self.assertIn('dialog unavailable',self.api._close_error)

    def test_native_dialog_is_owned_defaults_no_and_only_idyes_discards(self):
        self.window.native=SimpleNamespace(Handle=SimpleNamespace(ToInt64=lambda:1234))
        box=Mock(return_value=7)
        with patch('ctypes.WinDLL',return_value=SimpleNamespace(MessageBoxW=box)):
            self.assertFalse(DesktopAPI._confirm_discard_close(self.api))
            args=box.call_args.args
            self.assertEqual(args[0],1234)
            self.assertIn('放弃本次未保存',args[1])
            self.assertEqual(args[3],0x4|0x30|0x100)
            for answer in (0,2,7):
                box.return_value=answer
                self.assertFalse(DesktopAPI._confirm_discard_close(self.api))
            box.return_value=6
            self.assertTrue(DesktopAPI._confirm_discard_close(self.api))

    def test_truthy_or_unknown_callback_is_not_saved(self):
        for value in (None, True, 'true', {}, {'saved': 'true'}, {'message': 'failed'}):
            with self.subTest(value=value):
                self.api._close_pending = True
                self.api._finish_close_save(value)
                self.assertEqual(self.window.destroyed, 0)
                self.assertFalse(self.api._close_pending)

    def test_unloaded_window_closes_without_waiting_for_a_js_bridge(self):
        self.window.events.loaded.clear()
        self.api.close_app()
        self.assertEqual(self.window.destroyed, 1)
        self.assertEqual(self.window.calls, [])

    def test_close_button_uses_same_save_handshake(self):
        self.api.close_app()
        self.assertTrue(self.window.evaluated.wait(2))
        self.assertEqual(self.window.destroyed, 0)
        self.window.callback({'saved': True})
        self.assertEqual(self.window.destroyed, 1)

    def test_evaluation_failure_does_not_approve_close(self):
        self.window.failure = RuntimeError('JS bridge unavailable')
        self.api._close_pending = True
        self.api._flush_before_close()
        self.assertEqual(self.window.destroyed, 0)
        self.assertFalse(self.api._close_pending)
        self.assertFalse(self.api._close_approved)
        self.assertIn('JS bridge unavailable', self.api._close_error)

    def test_flush_owns_edit_commit_and_other_pages_need_no_save(self):
        self.begin_close()
        script = self.window.calls[0][0]
        self.assertIn('if(!workspace?.flush)return {saved:true}', script)
        self.assertIn('const operation=workspace.flush()', script)
        self.assertIn('await operation===true', script)
        self.assertLess(script.index('await workspace.prepareClose?.()'), script.index('workspace.flush()'))
        self.assertLess(script.index('workspace.flush()'), script.index('node.inert=true'))
        self.assertIn("document.querySelectorAll('main, nav')", script)
        self.assertNotIn('body.inert=true', script)
        self.assertIn('workspace.cancelClose?.()', script)


if __name__ == '__main__':unittest.main()
