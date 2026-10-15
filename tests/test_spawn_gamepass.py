import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app_config
from farm_policy import HereRecovery


class SpawnGamepass(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.config = Path(folder.name)/'config.local.json'
        patcher = patch.object(app_config, 'CONFIG', self.config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unanswered_keeps_full_farmer_for_existing_installs(self):
        config = app_config.load_config()
        self.assertIsNone(config['spawn_gamepass'])
        self.assertTrue(app_config.full_farmer_available(config))
        self.assertEqual(app_config.main_mode(config), 'full')

    def test_no_gamepass_switches_to_farm_here_and_back(self):
        app_config.save_config({'mode': 'full'})
        config = app_config.set_spawn_gamepass(False)
        self.assertEqual(config['mode'], 'here')
        self.assertFalse(app_config.full_farmer_available(config))
        self.assertEqual(json.loads(self.config.read_text())['spawn_gamepass'], False)
        self.assertEqual(app_config.set_spawn_gamepass(True)['mode'], 'full')

    def test_other_modes_are_kept(self):
        app_config.save_config({'mode': 'assist'})
        self.assertEqual(app_config.set_spawn_gamepass(False)['mode'], 'assist')
        self.assertEqual(app_config.set_spawn_gamepass(True)['mode'], 'assist')

    def test_invalid_answer_is_rejected(self):
        with self.assertRaises(ValueError):
            app_config.save_config({'spawn_gamepass': 'maybe'})


class FarmHereRecovery(unittest.TestCase):
    def test_disconnect_rejoins_only_with_the_gamepass(self):
        self.assertEqual(HereRecovery().choose('disconnect'), 'rejoin')
        self.assertEqual(HereRecovery(rejoin=True).choose('client_lost'), 'rejoin')
        self.assertEqual(HereRecovery(rejoin=False).choose('disconnect'), 'stop_disconnected')
        self.assertEqual(HereRecovery(rejoin=False).choose('client_lost'), 'stop_disconnected')

    def test_local_faults_still_repair_without_the_gamepass(self):
        policy = HereRecovery(rejoin=False)
        self.assertEqual([policy.choose('capture') for _ in range(4)], ['local', 'local', 'local', 'attention'])
        self.assertEqual(policy.choose('focus'), 'wait_focus')


if __name__ == '__main__':
    unittest.main()
