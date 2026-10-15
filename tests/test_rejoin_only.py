"""Offline safety checks for the connection-only controller."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import control_actions
import fishing_cli
import recovery
from rejoin_only import scene_kind
from rejoin_policy import RejoinPolicy


class RejoinSignals(unittest.TestCase):
    def test_presence_errors_and_live_game_never_rejoin(self):
        policy = RejoinPolicy()
        policy.presence({'ok': False}, 0)
        self.assertIsNone(policy.decide('other', True, 1000))
        policy.presence({'ok': True, 'type': 0}, 1001)
        self.assertIsNone(policy.decide('world', True, 1200))
        policy.presence({'ok': True, 'type': 2}, 1201)
        self.assertIsNone(policy.decide('other', True, 1400))

    def test_visible_disconnect_and_lobby_recover_immediately(self):
        for scene in ('disconnect', 'lobby'):
            policy = RejoinPolicy()
            self.assertEqual(policy.decide(scene, True, 0), 'recover')

    def test_presence_absence_needs_bad_scene_and_duration(self):
        policy = RejoinPolicy()
        policy.presence({'ok': True, 'type': 1}, 0)
        self.assertIsNone(policy.decide('other', True, 89))
        self.assertEqual(policy.decide('other', True, 90), 'recover')
        policy.presence({'ok': False}, 91)
        self.assertIsNone(policy.decide('other', True, 200))

    def test_missing_client_and_backoff_are_bounded(self):
        policy = RejoinPolicy()
        self.assertIsNone(policy.decide('missing', False, 0))
        self.assertIsNone(policy.decide('missing', False, 44))
        self.assertEqual(policy.decide('missing', False, 45), 'launch')
        self.assertEqual(policy.failed(45), 15)
        self.assertIsNone(policy.decide('missing', False, 59))
        self.assertEqual(policy.decide('missing', False, 60), 'launch')
        for step in range(8):
            delay = policy.failed(60 + step * 200)
        self.assertEqual(delay, 180)
        policy.succeeded()
        self.assertEqual(policy.failures, 0)

    def test_scene_recognition(self):
        rows = lambda *labels: [{'text': label} for label in labels]
        self.assertEqual(scene_kind(rows('Disconnected', 'Reconnect'), False), 'disconnect')
        self.assertEqual(scene_kind(rows('Last played', 'Ouwland'), False), 'lobby')
        self.assertEqual(scene_kind(rows('Mistfall', 'Lv. 51'), True), 'world')
        self.assertEqual(scene_kind(rows('Mistfall', 'Lv. 51'), False), 'other')


class RejoinControls(unittest.TestCase):
    def test_cli_command_starts_only_rejoin_mode(self):
        output = io.StringIO()
        with patch.object(control_actions, 'resume', return_value='Watching') as resume, redirect_stdout(output):
            self.assertEqual(fishing_cli.main(['rejoin']), 0)
        resume.assert_called_once_with('rejoin')
        self.assertIn('Watching', output.getvalue())

    def test_status_only_shows_connection_counters(self):
        data = {'state': 'Watching connection', 'running': True, 'stop_requested': False,
                'mode': 'rejoin', 'reason': '', 'presence': 'In game',
                'rejoin': {'account': 'ExamplePlayer', 'detail': 'Roblox world connected',
                           'rejoins': 2, 'attempts': 3, 'launches': 1}}
        result = '\n'.join(fishing_cli.status_lines(data))
        self.assertIn('ExamplePlayer', result)
        self.assertIn('Rejoins', result)
        self.assertNotIn('Bait', result)

    def test_recovery_skips_rod_and_spawn_movement(self):
        driver = recovery.Recovery.__new__(recovery.Recovery)
        tick = [0.0]
        driver.inp = Mock()
        driver.restarts = 0
        driver.guard = Mock()
        driver.progress = Mock()
        driver.select = Mock()
        driver.capture = Mock(return_value=object())
        driver.text = Mock(return_value=[{'text': 'Mistfall Lv. 51'}])
        driver.world_visible = Mock(return_value=True)
        driver.event = Mock()
        driver.backstep_after_join = Mock()
        driver.equip_rod = Mock()
        driver.sleep = lambda seconds: tick.__setitem__(0, tick[0] + seconds)
        with patch.object(recovery.time, 'monotonic', side_effect=lambda: tick[0]):
            driver.recover(equip_rod=False)
        driver.equip_rod.assert_not_called()
        driver.backstep_after_join.assert_not_called()
        driver.event.assert_any_call('world_ready')


if __name__ == '__main__':
    unittest.main()
