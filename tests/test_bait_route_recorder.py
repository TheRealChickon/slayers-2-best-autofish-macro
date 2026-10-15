"""Recording boundaries, camera evidence and controller exclusion. No game input."""
import ctypes
import json
import queue
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import app_config
import bait_route_recorder as recorder
import control_actions as actions
import fishing_cli
import route_recording
import terminal_app


class Timeline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 100.0
        self.frame = np.full((240, 320, 3), 90, dtype=np.uint8)
        self.session = route_recording.RouteSession(self.root, {'hwnd': 1, 'pid': 2},
            (500, 100, 820, 340), self.frame, clock=lambda: self.now)
        self.addCleanup(lambda: self.session.finish(False))

    def rows(self):
        self.session.events.flush()
        return [json.loads(line) for line in (self.session.path / 'events.jsonl').read_text().splitlines()]

    def test_holds_are_balanced_and_pause_time_is_excluded(self):
        self.now = 102
        self.session.add_input('key', vk=87, scan_code=17, down=True)
        self.session.add_input('mouse_button', button='right', down=True,
                               desktop_x=660, desktop_y=220)
        self.now = 104
        self.session.pause('focus lost')
        self.now = 204
        self.assertFalse(self.session.add_input('key', vk=65, down=True))
        self.session.resume((500, 100, 820, 340))
        self.now = 205
        self.session.add_input('key', vk=69, down=True)
        rows = self.rows()
        releases = [r for r in rows if r.get('synthetic')]
        self.assertEqual(len(releases), 2)
        self.assertTrue(all(r['down'] is False and r['t'] == 4 for r in releases))
        self.assertEqual((rows[-1]['t'], rows[-1]['wall_t']), (5, 105))
        self.assertEqual(self.session.keys.keys(), {69})

    def test_auto_repeat_and_stale_events_do_not_create_extra_actions(self):
        self.assertTrue(self.session.add_input('key', vk=87, down=True))
        self.assertFalse(self.session.add_input('key', vk=87, down=True))
        self.assertTrue(self.session.add_input('key', vk=87, down=False))
        self.assertFalse(self.session.add_input('key', vk=87, down=False))
        self.session.pause('pause')
        self.now = 200
        self.session.resume(self.session.rect)
        self.assertFalse(self.session.add_input('key', at=150, vk=65, down=True))
        self.assertEqual(self.session.metadata['input_count'], 2)

    def test_native_checkpoint_video_and_mouse_coordinate_mapping(self):
        self.now = 101
        self.session.add_input('mouse_move', desktop_x=660, desktop_y=160)
        row = self.rows()[-1]
        self.assertEqual((row['client_x'], row['client_y']), (160, 60))
        self.assertEqual((row['normalized_x'], row['normalized_y']), (.5, .25))
        mark = self.session.checkpoint(self.frame)
        image = cv2.imread(str(self.session.path / mark['image']))
        self.assertEqual(image.shape, self.frame.shape)
        self.session.capture(self.frame)
        path = self.session.finish()
        video = cv2.VideoCapture(str(path / 'video.mp4'))
        try:
            success, frame = video.read()
            self.assertTrue(success)
            self.assertEqual(frame.shape[:2], (720, 1280))
        finally:
            video.release()
        frames = [json.loads(line) for line in (path / 'frames.jsonl').read_text().splitlines()]
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0]['video_viewport'], [160, 0, 960, 720])
        metadata = json.loads((path / 'route.json').read_text())
        self.assertTrue(metadata['complete'])
        self.assertFalse(metadata['automation_ready'])
        self.assertEqual(metadata['return_method'], 'manual_reset_to_saved_spawn')

    def test_partial_finish_is_idempotent_and_preserves_other_run_files(self):
        existing = self.root / 'current-run.json'
        existing.write_text('{"id":"unchanged"}')
        self.session.add_input('key', vk=87, down=True)
        self.session.finish(False, 'Stop')
        self.assertEqual(self.session.finish(), self.session.path)
        metadata = json.loads((self.session.path / 'route.json').read_text())
        self.assertFalse(metadata['complete'])
        self.assertEqual(metadata['finish_reason'], 'Stop')
        self.assertEqual(existing.read_text(), '{"id":"unchanged"}')


class InputBoundaries(unittest.TestCase):
    def setUp(self):
        self.hooks = recorder.InputCapture(foreground=lambda: self.foreground)
        self.foreground = 10
        self.hooks.target = {'hwnd': 10}
        self.hooks.recording = True

    def key(self, vk=87, flags=0):
        return SimpleNamespace(vkCode=vk, scanCode=17, flags=flags)

    def mouse(self, flags=0):
        return SimpleNamespace(pt=SimpleNamespace(x=500, y=250), flags=flags, mouseData=0)

    def test_injected_and_other_application_input_is_not_recorded(self):
        self.hooks.keyboard_event(0x100, self.key(flags=0x10))
        self.hooks.mouse_event(0x201, self.mouse(flags=1))
        self.foreground = 20
        self.hooks.keyboard_event(0x100, self.key())
        self.hooks.mouse_event(0x201, self.mouse())
        self.hooks.keyboard_event(0x100, self.key(117))
        self.assertTrue(self.hooks.events.empty())

    def test_control_key_repeat_has_one_action_and_is_not_a_route_input(self):
        for _ in range(3):
            self.assertFalse(self.hooks.keyboard_event(0x100, self.key(117)))
        self.hooks.keyboard_event(0x101, self.key(117))
        self.hooks.keyboard_event(0x100, self.key(117))
        events = [self.hooks.events.get_nowait() for _ in range(2)]
        self.assertTrue(all(kind == 'control' and data['action'] == 'checkpoint' for _, kind, data in events))
        self.assertTrue(self.hooks.events.empty())

    def test_system_navigation_pauses_before_other_keys_can_be_recorded(self):
        self.hooks.keyboard_event(0x104, self.key(18))
        self.hooks.keyboard_event(0x100, self.key(9))
        _, kind, details = self.hooks.events.get_nowait()
        self.assertEqual((kind, details['action']), ('control', 'pause'))
        self.assertFalse(self.hooks.recording)
        self.assertTrue(self.hooks.events.empty())

    def test_reset_menu_keys_are_preserved(self):
        for vk in (27, 82, 13):
            self.hooks.keyboard_event(0x100, self.key(vk))
            self.hooks.keyboard_event(0x101, self.key(vk))
        events = [self.hooks.events.get_nowait()[2] for _ in range(6)]
        self.assertEqual([r['vk'] for r in events], [27, 27, 82, 82, 13, 13])

    def test_click_outside_game_pauses_without_recording_it(self):
        with patch.object(recorder, 'client_rect', return_value=(0, 0, 300, 200)):
            self.hooks.mouse_event(0x201, self.mouse())
        _, kind, details = self.hooks.events.get_nowait()
        self.assertEqual((kind, details['action']), ('control', 'pause'))
        self.assertFalse(self.hooks.recording)

    def test_queue_overflow_is_reported_instead_of_silent_input_loss(self):
        self.hooks.events = queue.Queue(maxsize=1)
        self.hooks.put('key', vk=87)
        self.hooks.put('key', vk=65)
        self.assertTrue(self.hooks.failed.is_set())

    def test_raw_relative_mouse_and_malformed_packets(self):
        pointer = ctypes.sizeof(ctypes.c_void_p)
        header_size = 8 + 2 * pointer
        packet = struct.pack('<II', 0, header_size + 24)
        packet += (123).to_bytes(pointer, 'little') + (0).to_bytes(pointer, 'little')
        packet += struct.pack('<H2xIIiiI', 0, 0, 0, -42, 19, 0)
        self.assertEqual(recorder.parse_raw_mouse(packet)['dx'], -42)
        self.assertEqual(recorder.parse_raw_mouse(packet)['dy'], 19)
        self.assertFalse(recorder.parse_raw_mouse(packet)['absolute'])
        self.assertIsNone(recorder.parse_raw_mouse(packet[:20]))
        self.assertIsNone(recorder.parse_raw_mouse(packet[:4] + struct.pack('<I', 8) + packet[8:]))
        no_device = packet[:8] + bytes(pointer) + packet[8 + pointer:]
        self.assertIsNone(recorder.parse_raw_mouse(no_device))


class ControllerBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for module, name, value in ((actions, 'RUN', self.root), (app_config, 'CONFIG', self.root / 'config.local.json'),
                                    (recorder, 'data_directory', lambda: self.root)):
            p = patch.object(module, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_resume_does_not_clear_manual_holds_or_start_during_recording(self):
        for name in ('STOP', 'PAUSE', 'F8_PAUSE'):
            (self.root / name).write_text('retain')
        with patch.object(actions, 'alive', side_effect=lambda name='supervisor-pid.json': name == recorder.LEASE), \
             patch.object(actions.subprocess, 'Popen') as spawn:
            result = actions.resume('full')
        self.assertIn('recorder is open', result)
        spawn.assert_not_called()
        self.assertTrue(all((self.root / name).read_text() == 'retain' for name in ('STOP', 'PAUSE', 'F8_PAUSE')))

    def test_launch_refuses_paused_but_live_supervisor_without_touching_holds(self):
        (self.root / 'F8_PAUSE').write_text('retain')
        with patch.object(actions, 'alive', side_effect=lambda name='supervisor-pid.json': name == 'supervisor-pid.json'), \
             patch.object(actions.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError, 'Use Pause'):
                recorder.launch()
        spawn.assert_not_called()
        self.assertEqual((self.root / 'F8_PAUSE').read_text(), 'retain')

    def test_pause_cancels_recorder_without_changing_saved_run(self):
        (self.root / 'current-run.json').write_text('retain')
        with patch.object(actions, 'alive', side_effect=lambda name='supervisor-pid.json': name == recorder.LEASE), \
             patch.object(actions, 'starting', return_value=False):
            result = actions.pause()
        self.assertIn('partial demonstration', result)
        self.assertTrue((self.root / recorder.STOP).exists())
        self.assertEqual((self.root / 'current-run.json').read_text(), 'retain')

    def test_repeated_stop_write_changes_marker_even_with_equal_contents(self):
        stop = self.root / 'STOP'
        stop.write_text('same')
        initial = recorder.marker_state(self.root)
        stat = stop.stat()
        import os
        os.utime(stop, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
        self.assertNotEqual(initial, recorder.marker_state(self.root))

    def test_controller_entry_points_refuse_recording_before_touching_run_state(self):
        import recovery
        import minigame_assist
        import rejoin_only
        for name in ('STOP', 'PAUSE', 'F8_PAUSE', 'totals.json'):
            (self.root / name).write_text('retain')
        with patch.object(actions, 'alive', side_effect=lambda name='supervisor-pid.json': name == recorder.LEASE), \
             patch.object(recovery, 'RUN', self.root), patch.object(minigame_assist, 'RUN', self.root), \
             patch.object(rejoin_only, 'RUN', self.root), patch.object(recovery, 'Recovery') as driver, \
             patch.object(rejoin_only, 'load_config', return_value={'account_username': 'test', 'user_id': 1}), \
             patch.object(sys, 'argv', ['recovery.py']):
            for entry in (recovery.main, lambda: minigame_assist.main([]), lambda: rejoin_only.main([])):
                with self.assertRaisesRegex((RuntimeError, recovery.UserStop), 'recorder is open'):
                    entry()
            driver.assert_not_called()
        self.assertFalse((self.root / 'supervisor-pid.json').exists())
        self.assertTrue(all((self.root / name).read_text() == 'retain' for name in ('STOP', 'PAUSE', 'F8_PAUSE', 'totals.json')))

    def test_cli_and_terminal_route_controls_dispatch_explicit_recording(self):
        args = fishing_cli.parser().parse_args(['route', 'record'])
        with patch.object(recorder, 'launch', return_value='ready') as launch:
            fishing_cli.execute(args)
            launch.assert_called_once()
        terminal = terminal_app.Terminal.__new__(terminal_app.Terminal)
        terminal.page = 3
        terminal.selection = terminal.settings_keys.index('Record bait route')
        with patch.object(terminal, 'job', side_effect=lambda fn: fn()), patch.object(recorder, 'launch') as launch:
            terminal.activate()
            launch.assert_called_once()


if __name__ == '__main__':
    unittest.main()
