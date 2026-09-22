import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from minigame_assist import TrackingAssist
import control_actions
import app_config
import metrics


def marker(ball=300,target=250):return {'ball':ball,'target':target}


class AssistTracking(unittest.TestCase):
    def test_requires_ui_and_repeated_marker_before_holding(self):
        tracker=TrackingAssist()
        self.assertFalse(tracker.step(marker(),False,1))
        self.assertFalse(tracker.step(marker(),True,1.03))
        self.assertTrue(tracker.step(marker(),True,1.06))
        self.assertEqual(tracker.count,1)

    def test_releases_when_ui_disappears_and_deduplicates_flicker(self):
        tracker=TrackingAssist()
        tracker.step(marker(),True,1);tracker.step(marker(),True,1.03)
        self.assertFalse(tracker.step(None,False,1.1))
        tracker.step(marker(),True,1.2)
        self.assertEqual(tracker.count,1)
        tracker.step(None,False,2);tracker.step(None,False,2.6)
        self.assertFalse(tracker.step(marker(),True,3))
        tracker.step(marker(),True,3.03)
        self.assertEqual(tracker.count,2)

    def test_no_marker_releases_after_short_gap_even_if_ui_remains(self):
        tracker=TrackingAssist()
        tracker.step(marker(),True,1);tracker.step(marker(),True,1.03)
        self.assertFalse(tracker.step(None,True,1.17))
        tracker.suspend()
        self.assertFalse(tracker.held)
        self.assertIsNone(tracker.previous)


class AssistControls(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        for module,key,value in ((control_actions,'RUN',self.root),(metrics,'RUN',self.root),
                                  (app_config,'CONFIG',self.root/'config.local.json')):
            p=patch.object(module,key,value);p.start();self.addCleanup(p.stop)

    def test_mode_change_never_starts_parallel_controller_or_focuses(self):
        metrics.write('supervisor.json',{'mode':'full'})
        with patch.object(control_actions,'alive',side_effect=lambda name='supervisor-pid.json':name=='supervisor-pid.json'),patch.object(control_actions,'starting',return_value=False),patch.object(control_actions,'focus_game') as focus,patch.object(control_actions.subprocess,'Popen') as spawn:
            self.assertIn('Pause',control_actions.resume('assist'))
            focus.assert_not_called();spawn.assert_not_called()

    def test_start_assist_uses_only_assist_entrypoint_and_preserves_totals(self):
        metrics.write('totals.json',{'started':1,'rounds':7,'rewards':4})
        (self.root/'STOP').write_text('Stopped by user')
        with patch.object(control_actions,'alive',return_value=False),patch.object(control_actions,'starting',return_value=False),patch.object(control_actions.subprocess,'Popen',return_value=Mock(pid=123)) as spawn,patch.object(control_actions.psutil,'Process',return_value=Mock(create_time=lambda:10)),patch.object(control_actions,'focus_game') as focus:
            self.assertIn('Minigame only',control_actions.resume('assist'))
            args=spawn.call_args.args[0]
            self.assertTrue(args[1].endswith('minigame_assist.py'))
            self.assertNotIn('--focus',args);self.assertNotIn('--rejoin',args)
            focus.assert_not_called()
        self.assertEqual(metrics.read('totals.json'),{'started':1,'rounds':7,'rewards':4})
        self.assertFalse((self.root/'STOP').exists())

    def test_spot_mode_starts_local_controller_without_focus_or_rejoin(self):
        with patch.object(control_actions,'alive',return_value=False),patch.object(control_actions,'starting',return_value=False),patch.object(control_actions.subprocess,'Popen',return_value=Mock(pid=123)) as spawn,patch.object(control_actions.psutil,'Process',return_value=Mock(create_time=lambda:10)),patch.object(control_actions,'focus_game') as focus:
            self.assertIn('F8',control_actions.resume('spot'))
            args=spawn.call_args.args[0]
            self.assertEqual(args[-2:],['--mode','spot'])
            self.assertNotIn('--focus',args);self.assertNotIn('--rejoin',args)
            focus.assert_not_called()
        self.assertEqual(app_config.load_config()['mode'],'spot')


if __name__=='__main__':unittest.main()
