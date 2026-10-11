import sys
import tempfile
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from minigame_assist import TrackingAssist
import minigame_assist as assist
import fishing_assistant
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

    def test_focus_return_reacquires_two_frames_without_old_motion(self):
        tracker=TrackingAssist()
        tracker.step(marker(),True,1);tracker.step(marker(),True,1.02)
        tracker.suspend()
        self.assertFalse(tracker.step(marker(180,250),True,3))
        self.assertFalse(tracker.step(marker(180,250),True,3.02))
        self.assertEqual(tracker.velocity,0)
        self.assertEqual(tracker.count,1)
        self.assertTrue(tracker.step(marker(200,150),True,3.04))


class FocusInput(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        patches=[patch.object(assist,'RUN',self.root),patch.object(fishing_assistant,'USER'),
                 patch.object(assist,'USER'),patch.object(assist,'foreground',return_value=True),
                 patch.object(fishing_assistant.Input,'guard_press')]
        self.mocks=[p.start() for p in patches]
        for p in patches:self.addCleanup(p.stop)
        self.user=self.mocks[2];self.user.GetAsyncKeyState.return_value=0
        self.inp=assist.ForegroundInput();self.inp.hwnd=123

    def test_return_sends_real_release_even_when_local_button_is_already_up(self):
        self.inp.mouse=True;self.inp.suspend_input()
        self.assertFalse(self.inp.mouse)
        self.inp.interrupted.clear()
        self.inp.sync_game_input()
        self.user.mouse_event.assert_called_once_with(4,0,0,0,0)
        self.user.keybd_event.assert_not_called()
        self.inp.sync_game_input()
        self.assertEqual(self.user.mouse_event.call_count,1)

    def test_sync_cannot_send_to_background_app_or_while_alt_is_held(self):
        self.inp.suspend_input();self.inp.interrupted.clear()
        self.mocks[3].return_value=False
        with self.assertRaises(RuntimeError):self.inp.sync_game_input()
        self.mocks[3].return_value=True
        self.user.GetAsyncKeyState.side_effect=lambda key:0x8000 if key==18 else 0
        with self.assertRaises(RuntimeError):self.inp.sync_game_input()
        self.user.mouse_event.assert_not_called()
        self.user.keybd_event.assert_not_called()

    def test_sync_preserves_stop_and_only_releases_t_if_it_was_owned(self):
        self.inp.t=True;self.inp.suspend_input();self.inp.interrupted.clear()
        (self.root/'STOP').write_text('Stopped by user')
        with self.assertRaises(RuntimeError):self.inp.sync_game_input()
        self.user.mouse_event.assert_not_called();self.user.keybd_event.assert_not_called()


class ManualStopKeys(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        for target, name, value in ((assist,'RUN',self.root),(assist,'USER',Mock())):
            p=patch.object(target,name,value);p.start();self.addCleanup(p.stop)
        self.keys=set()
        assist.USER.GetAsyncKeyState.side_effect=lambda key:0x8000 if key in self.keys else 0

    def test_escape_never_stops_manual_modes(self):
        self.keys={27}
        with patch.object(assist,'window_foreground',return_value=True):
            self.assertIsNone(assist.request_hotkey_stop(123))
        self.assertFalse((self.root/'STOP').exists())

    def test_other_app_function_keys_do_not_stop_but_roblox_key_records_name(self):
        for key,name in ((120,'F9'),(123,'F12')):
            self.keys={key}
            with patch.object(assist,'window_foreground',return_value=False):
                self.assertIsNone(assist.request_hotkey_stop(123))
            self.assertFalse((self.root/'STOP').exists())
            with patch.object(assist,'window_foreground',return_value=True):
                self.assertEqual(assist.request_hotkey_stop(123),f'Stopped by {name} in Roblox')
            self.assertEqual(assist.stop_reason(),f'Stopped by {name} in Roblox')
            (self.root/'STOP').unlink()

    def test_hotkey_does_not_overwrite_an_existing_user_stop_or_pause(self):
        self.keys={120}
        (self.root/'STOP').write_text('Stopped by user')
        with patch.object(assist,'window_foreground',return_value=True):
            assist.request_hotkey_stop(123)
        self.assertEqual(assist.stop_reason(),'Stopped by user')
        (self.root/'PAUSE').write_text('Paused by user')
        self.assertEqual(assist.stop_reason(),'Paused by user')

    def test_focus_watcher_ignores_escape_then_stops_on_named_game_key(self):
        inp=Mock(hwnd=123,toggle_enabled=True);done=Mock()
        states=iter([({120},False),({27},True),({123},True)])
        current={'foreground':False}
        def wait(_):
            try:self.keys,current['foreground']=next(states)
            except StopIteration:return True
            if self.keys=={123}:self.assertFalse((self.root/'STOP').exists())
            return False
        done.wait.side_effect=wait
        with patch.object(assist,'window_foreground',side_effect=lambda h:current['foreground']), \
             patch.object(assist,'foreground',side_effect=lambda h:current['foreground']):
            assist.watch_focus(inp,done)
        self.assertEqual(assist.stop_reason(),'Stopped by F12 in Roblox')
        inp.suspend_input.assert_called()
        inp.toggle_requested.set.assert_not_called()


class AssistControls(unittest.TestCase):
    def setUp(self):
        # Overnight now defaults on; isolate its separately managed background process.
        p=patch('overnight_guard.ensure_guard');self.guard=p.start();self.addCleanup(p.stop)
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
            self.guard.assert_called_once()
        self.assertEqual(metrics.read('totals.json'),{'started':1,'rounds':7,'rewards':4})
        self.assertFalse((self.root/'STOP').exists())

    def test_spot_mode_starts_local_controller_without_focus_or_rejoin(self):
        with patch.object(control_actions,'alive',return_value=False),patch.object(control_actions,'starting',return_value=False),patch.object(control_actions.subprocess,'Popen',return_value=Mock(pid=123)) as spawn,patch.object(control_actions.psutil,'Process',return_value=Mock(create_time=lambda:10)),patch.object(control_actions,'focus_game') as focus:
            self.assertIn('F8',control_actions.resume('spot'))
            args=spawn.call_args.args[0]
            self.assertEqual(args[-2:],['--mode','spot'])
            self.assertNotIn('--focus',args);self.assertNotIn('--rejoin',args)
            focus.assert_not_called()
            self.guard.assert_called_once()
        self.assertEqual(app_config.load_config()['mode'],'spot')

    def test_running_assist_f8_and_focus_round_trip_without_real_input(self):
        import json
        import numpy as np
        # Exercise main(), including its pause branch and input application.
        # The clock, screen, Windows APIs and input sink are all offline fakes.
        clock={'at':0.,'focus':True};presses=[];states=[];fired=set()
        inp=assist.ForegroundInput()
        def tick(delay):
            clock['at']+=max(.01,delay)
            t=clock['at']
            for threshold in (.2,1.25):
                if t>=threshold and threshold not in fired:
                    fired.add(threshold);inp.suspend_input();inp.toggle_requested.set()
            clock['focus']=not (.4<=t<.6 or 1.6<=t<1.8)
        def mouse(flags,*args):
            presses.append((clock['at'],flags,clock['focus']))
        screen=Mock(rect=(0,0,2560,1440))
        screen.capture.return_value=np.zeros((600,140,3),np.uint8)
        writes=lambda name,data:states.append((name,dict(data)))
        with ExitStack() as stack:
            replacements=[(assist,'RUN',self.root),(assist,'ForegroundInput',lambda:inp),
                (assist,'foreground',lambda hwnd:clock['focus']),(assist,'navigation_keys_down',lambda:False),
                (assist,'find_window',lambda:123),(assist,'rectangle',lambda hwnd:screen.rect),
                (assist,'ScreenSpace',lambda rect:screen),(assist,'Ledger',Mock(return_value=Mock(base={}))),
                (assist,'PerformanceRecorder',Mock()),(assist,'write',writes),(assist,'read',lambda name:{}),
                (assist,'detect',lambda roi:{**marker(),'inside':False,'height':54,'ball_height':31}),
                (assist,'ui_visible',lambda *args:True),
                (control_actions,'guard',nullcontext),(control_actions,'alive',lambda *args:False),
                (assist.time,'monotonic',lambda:clock['at']),(assist.time,'time',lambda:clock['at']+1000),
                (assist.time,'sleep',tick),(assist.threading,'Thread',Mock()),
                (fishing_assistant.Input,'guard_press',lambda *args:None),
                (assist.win32gui,'IsWindow',lambda h:True),
                (assist.win32gui,'GetCursorPos',lambda:(1280,720)),
                (assist.win32gui,'WindowFromPoint',lambda p:123),
                (assist.win32gui,'GetAncestor',lambda *args:123),
                (assist.cv2,'imwrite',lambda *args:True)]
            for obj,key,value in replacements:stack.enter_context(patch.object(obj,key,value))
            user=Mock();user.GetAsyncKeyState.return_value=0;user.mouse_event.side_effect=mouse
            stack.enter_context(patch.object(assist,'USER',user))
            stack.enter_context(patch.object(fishing_assistant,'USER',user))
            stack.enter_context(patch.object(assist.mss,'MSS',lambda:nullcontext(None)))
            self.assertEqual(assist.main(['--mode','assist','--seconds','2.1']),0)
        downs=[t for t,flag,focus in presses if flag==2]
        self.assertTrue(any(t<.2 for t in downs))
        self.assertFalse(any(.2<=t<1.25 for t in downs))
        self.assertTrue(any(1.25<t<1.6 for t in downs))
        self.assertTrue(any(t>1.8 for t in downs))
        self.assertFalse(any(flag==2 and not focus for _,flag,focus in presses))
        self.assertTrue(any(s.get('stage')=='assist_paused' and s.get('manual_paused') for _,s in states))
        events=[json.loads(line) for p in self.root.glob('events-*.jsonl') for line in p.read_text().splitlines()]
        self.assertEqual(sum(e['event']=='assist_paused' for e in events),1)
        self.assertEqual(sum(e['event']=='assist_resumed' for e in events),1)
        user.keybd_event.assert_not_called()


if __name__=='__main__':unittest.main()
