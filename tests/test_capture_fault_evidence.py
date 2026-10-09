"""Capture fault replay uses fake pixels/resources and never captures the PC."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import capture_session
import fishing_assistant as fishing
from faults import FishingFault
from full_pause import InputGate


class CaptureFaultEvidenceTests(unittest.TestCase):
    def test_closed_session_does_not_grab_reset_or_reopen(self):
        source = Mock()
        with patch.object(capture_session.mss, 'MSS', return_value=source) as factory:
            session = capture_session.CaptureSession()
            session.close()
            session.close()
            for action in (lambda: session.grab({'left': 0, 'top': 0, 'width': 40, 'height': 40}), session.reset):
                with self.assertRaises(FishingFault) as fault:
                    action()
                self.assertTrue(fault.exception.details['capture_closed'])
            source.grab.assert_not_called()
            source.close.assert_called_once()
            self.assertEqual(factory.call_count, 1)

    def test_mixed_blank_and_gdi_failures_preserve_each_attempt(self):
        sources = [Mock() for _ in range(3)]
        sources[0].grab.return_value = np.zeros((540, 960, 4), np.uint8)
        sources[1].grab.side_effect = capture_session.ScreenShotError(
            'Windows graphics function failed (no error provided): SelectObject',
            details={'func': 'SelectObject', 'error_code': 0, 'args': (123, 456)})
        sources[2].grab.return_value = np.full((540, 960, 4), 255, np.uint8)
        region = {'left': -960, 'top': 30, 'width': 960, 'height': 540}
        events = Mock()
        with patch.object(capture_session.mss, 'MSS', side_effect=sources) as factory, patch.object(capture_session.time, 'sleep'):
            with capture_session.CaptureSession(events) as session:
                with self.assertRaises(FishingFault) as fault:
                    session.grab(region)
        attempts = fault.exception.details['capture_attempts']
        self.assertEqual([row['blank_color'] for row in attempts], ['black', None, 'white'])
        self.assertEqual(attempts[1]['capture_api'], 'SelectObject')
        self.assertEqual(attempts[1]['capture_error_code'], 0)
        self.assertTrue(all(row['region'] == region for row in attempts))
        self.assertNotIn('args', attempts[1])
        self.assertEqual(fault.exception.details['blank_color'], 'white')
        self.assertEqual(fault.exception.code, 'capture_unavailable')
        self.assertEqual(factory.call_count, 3)
        self.assertEqual(events.call_count, 2)
        for source in sources:
            source.close.assert_called_once()

    def replay_worker(self, root, manual=False):
        now = [100.]
        user = Mock(); user.GetAsyncKeyState.return_value = 0
        ledger = Mock(); inventory = Mock()
        inventory.check_pending.return_value = None
        source = Mock(); source.resets = 2
        source.__enter__ = Mock(return_value=source)
        source.__exit__ = Mock(return_value=False)
        original = FishingFault('capture_unavailable', 'Original blank capture',
                                capture_error='Blank game capture; no reliable visual state',
                                blank_color='black', resets=2)
        screen = Mock(ui_scale=1., rect=(0, 0, 2560, 1440))
        screen.capture_ui.side_effect = original
        # The old handler makes this second capture after context exit and
        # loses the original manifest. No fresh pixels are needed for evidence.
        screen.capture.side_effect = FishingFault('capture_unavailable', 'Closed diagnostic capture')
        def write(name, value):
            (root/name).write_text(json.dumps(value))
        def sleep(seconds):
            now[0] += seconds
            if manual and now[0] > 100.3:
                (root/'STOP').write_text('Stopped by test')
        if manual:
            (root/'F8_PAUSE').write_text('Paused by F8')
        with ExitStack() as stack:
            contexts = (
                patch.object(fishing, 'RUN', root), patch.object(fishing, 'USER', user),
                patch.object(fishing, 'find_window', return_value=7),
                patch.object(fishing, 'rectangle', return_value=(0, 0, 2560, 1440)),
                patch.object(fishing, 'ScreenSpace', return_value=screen),
                patch.object(fishing.win32gui, 'IsWindow', return_value=True),
                patch.object(fishing.win32gui, 'IsIconic', return_value=False),
                patch.object(fishing.win32gui, 'GetForegroundWindow', return_value=7),
                patch.object(fishing.win32gui, 'WindowFromPoint', return_value=7),
                patch.object(fishing.win32gui, 'GetAncestor', return_value=7),
                patch.object(fishing, 'RapidOCR'), patch.object(fishing.cv2, 'imread', return_value=None),
                patch.object(fishing, 'InventoryWatcher', return_value=inventory),
                patch.object(fishing, 'Ledger', return_value=ledger),
                patch.object(fishing, 'write_metrics', side_effect=write),
                patch.object(fishing, 'read_metrics', return_value={}),
                patch.object(fishing, 'move_pointer'), patch.object(fishing, 'Listener'),
                patch.object(fishing, 'CaptureSession', return_value=source),
                patch.object(fishing, 'PhysicalActivity', return_value=Mock(last=100., last_other_input=None)),
                patch.object(InputGate, 'start'),
                patch.object(fishing.time, 'monotonic', side_effect=lambda: now[0]),
                patch.object(fishing.time, 'sleep', side_effect=sleep),
                patch.object(sys, 'argv', ['fishing_assistant.py', '--seconds', '2']),
                patch('builtins.print'))
            for context in contexts:
                stack.enter_context(context)
            with self.assertRaises(RuntimeError) as error:
                fishing.main()
        return original, error.exception, screen, user, source

    def test_worker_saves_original_capture_fault_without_recapture(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original, error, screen, user, source = self.replay_worker(root)
            self.assertIs(error, original)
            screen.capture_ui.assert_called_once()
            screen.capture.assert_not_called()
            source.__exit__.assert_called_once()
            manifest = json.loads((root/'diagnostics/index.json').read_text())
            self.assertEqual(len(manifest), 1)
            self.assertEqual(manifest[0]['code'], 'capture_unavailable')
            self.assertEqual(manifest[0]['details']['blank_color'], 'black')
            self.assertEqual(manifest[0]['details']['capture_error'], original.details['capture_error'])
            self.assertEqual(manifest[0]['frames'], [])
            status = json.loads((root/'status.json').read_text())
            self.assertFalse(status['running']); self.assertFalse(status['held_mouse']); self.assertFalse(status['held_t'])
            self.assertEqual(status['failure_code'], 'capture_unavailable')
            # Nothing was pressed before this failure; final releases remain mocked.
            self.assertFalse(any(call.args[0] == 2 for call in user.mouse_event.call_args_list))

    def test_manual_f8_pause_prevents_capture_and_remains_set(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, error, screen, _, _ = self.replay_worker(root, manual=True)
            self.assertEqual(str(error), 'Stopped by stop file')
            self.assertEqual((root/'F8_PAUSE').read_text(), 'Paused by F8')
            screen.capture_ui.assert_not_called(); screen.capture.assert_not_called()
            status = json.loads((root/'status.json').read_text())
            self.assertTrue(status['manual_paused'])
            self.assertFalse(status['held_mouse']); self.assertFalse(status['held_t'])


if __name__ == '__main__':
    unittest.main()
