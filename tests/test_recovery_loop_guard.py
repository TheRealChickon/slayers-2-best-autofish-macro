import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from faults import RecoveryPolicy, reason_code
from fishing_assistant import MISSED_CASTS_BEFORE_REJOIN


class RecoveryLoopGuard(unittest.TestCase):
    def test_two_empty_casts_do_not_force_rejoin(self):
        self.assertGreater(MISSED_CASTS_BEFORE_REJOIN, 2)
        code = reason_code('Three casts without a recognized minigame')
        self.assertEqual(code, 'no_minigame')
        self.assertEqual(RecoveryPolicy().choose(code, 0, False), 'rejoin')

    def test_repeated_no_minigame_rejoins_stop_but_old_failures_expire(self):
        policy = RecoveryPolicy()
        self.assertEqual(policy.choose('no_minigame', 0, False), 'rejoin')
        self.assertEqual(policy.choose('no_minigame', 1700, False), 'rejoin')
        self.assertEqual(policy.choose('no_minigame', 3600, False), 'stop_unstable_position')
        self.assertEqual(policy.choose('no_minigame', 10000, False), 'rejoin')
        self.assertEqual(policy.choose('manual_stop', 10001, False), 'stop')

    def test_health_flags_recovery_pattern_even_when_user_has_paused(self):
        script = Path(__file__).resolve().parents[1] / 'health_check.py'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            now = time.time()
            rows = [
                {'at': now - 3500, 'event': 'recovery_decision', 'code': 'no_minigame', 'action': 'rejoin'},
                {'at': now - 200, 'event': 'recovery_decision', 'code': 'no_minigame', 'action': 'rejoin'},
            ]
            (root / 'recovery.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            (root / 'F8_PAUSE').write_text('paused')
            (root / 'supervisor.json').write_text(json.dumps({'running': True, 'pid': os.getpid(), 'stage': 'paused_manual'}))
            (root / 'status.json').write_text(json.dumps({'running': True, 'pid': os.getpid(), 'stage': 'paused_manual'}))
            env = dict(os.environ, FISHING_DATA_DIR=str(root))
            report = json.loads(subprocess.check_output([sys.executable, str(script)], env=env, text=True))
            self.assertTrue(report['pause_requested'])
            self.assertEqual(report['recent_90min']['no_minigame_recoveries'], 2)
            self.assertTrue(any('2 no-minigame recovery decisions' in issue for issue in report['issues']))
            (root / 'supervisor.json').write_text(json.dumps({'running': True, 'pid': os.getpid(),
                                                             'stage': 'paused_manual', 'started': now - 100}))
            restarted = json.loads(subprocess.check_output([sys.executable, str(script)], env=env, text=True))
            self.assertEqual(restarted['recent_90min']['no_minigame_recoveries'], 2)
            self.assertEqual(restarted['recent_90min']['current_supervisor_no_minigame_recoveries'], 0)
            self.assertEqual(restarted['issues'], [])


if __name__ == '__main__':
    unittest.main()
