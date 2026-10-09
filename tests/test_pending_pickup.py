import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fishing_assistant as fishing
import full_pause
from faults import FishingFault
from pickup_policy import Pickup, before_cast_decision


class PendingPickupTests(unittest.TestCase):
    def drive(self, initial='collect', pause_after_cast=False, pause_in_ocr=False, active_minigame=False, pending_after_cast=False, stop_in_ocr=False, resize_after_cast=False):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name);self.test_root=root;clock=[100.];mode=[initial];held_at=[None];resized=[False]
        paused_at=[None];cast_released=[False];inputs=[];states=[]
        gui=Mock();gui.IsWindow.return_value=True;gui.IsIconic.return_value=False
        gui.GetForegroundWindow.return_value=1;gui.GetAncestor.return_value=1
        gui.GetCursorPos.return_value=(1600,800)
        user=Mock();user.GetAsyncKeyState.return_value=0;user.MapVirtualKeyW.return_value=0
        def key(vk,scan,flags,*unused):
            if vk==ord('T'):
                inputs.append(('T',flags,clock[0]))
                if flags==0:held_at[0]=clock[0]
        def mouse(flags,*unused):
            inputs.append(('mouse',flags,clock[0]))
            if flags==4:cast_released[0]=True
        user.keybd_event.side_effect=key;user.mouse_event.side_effect=mouse
        def sleep(seconds):
            clock[0]+=seconds
            if resize_after_cast and cast_released[0] and not resized[0]:
                resized[0]=True;mode[0]='collect'
            if pending_after_cast and cast_released[0] and mode[0]=='empty':mode[0]='collect'
            if pause_after_cast and cast_released[0] and paused_at[0] is None:
                paused_at[0]=clock[0];(root/'F8_PAUSE').write_text('Paused by user')
            if paused_at[0] is not None and clock[0]-paused_at[0]>1:
                (root/'F8_PAUSE').unlink(missing_ok=True)
                mode[0]='empty' if pause_in_ocr else 'collect'
                paused_at[0]=-1000;cast_released[0]=False
        def ocr(image,**unused):
            clock[0]+=.12
            if stop_in_ocr:
                (root/'STOP').write_text('Stopped by test during OCR')
                (root/'F8_PAUSE').write_text('Paused by test during OCR')
            if pause_in_ocr and paused_at[0] is None:
                paused_at[0]=clock[0];(root/'F8_PAUSE').write_text('Paused during OCR')
            if held_at[0] is not None and clock[0]-held_at[0]>.8:mode[0]='reward'
            labels={'collect':[('T',120,80),('Krathulon',240,60),('Collect',240,85)],
                    'reward':[('Krathulon',140,60),('X1',220,60)],
                    'ambiguous':[('Collect',160,80),('Purchase',180,85)],'empty':[]}[mode[0]]
            return ([[[[x-5,y-5],[x+5,y-5],[x+5,y+5],[x-5,y+5]],text,.99]
                     for text,x,y in labels],None)
        def status(name,value):
            if name=='status.json':states.append(dict(value))
            (root/name).write_text(json.dumps(value))
        def read(name):
            if name=='supervisor.json':return {'started':1}
            if name=='bait-observation.json':return {'supervisor_started':1}
            return {}
        frame=np.zeros((1440,2560,3),np.uint8)
        def rectangle(hwnd):
            return (-3440,30,0,1470) if resized[0] else (0,0,2560,1440)
        def make_screen(rect):
            from screen_space import ScreenSpace
            geometry=ScreenSpace(rect)
            screen=Mock(ui_scale=geometry.ui_scale,rect=rect)
            screen.point.side_effect=geometry.point
            screen.capture.return_value=frame
            screen.capture_ui.return_value=frame[:600,:140]
            return screen
        capture=Mock();capture.__enter__=Mock(return_value=Mock(resets=0));capture.__exit__=Mock(return_value=False)
        inventory=Mock();inventory.pending=[];inventory.check_pending.return_value=None
        ledger=Mock();ledger.base={}
        error=None
        with ExitStack() as stack:
            for target,name,value in [
                (fishing,'RUN',root),(fishing,'win32gui',gui),(full_pause,'win32gui',gui),
                (fishing,'USER',user),(fishing,'find_window',Mock(return_value=1)),
                (fishing,'rectangle',rectangle),
                (fishing,'ScreenSpace',make_screen),
                (fishing,'RapidOCR',Mock(return_value=ocr)),
                (fishing,'detect',Mock(return_value={'ball':100,'target':100,'height':50,'ball_height':10,'inside':True} if active_minigame else None)),
                (fishing,'ui_visible',Mock(return_value=active_minigame)),
                (fishing,'ReelMotion',Mock(return_value=Mock(step=Mock(return_value=False),velocity=0,target_velocity=0))),
                (fishing,'InventoryWatcher',Mock(return_value=inventory)),
                (fishing,'Ledger',Mock(return_value=ledger)),(fishing,'read_metrics',read),
                (fishing,'write_metrics',status),(fishing,'move_pointer',Mock()),
                (fishing,'locate_rod',Mock(return_value=None)),
                (fishing,'CaptureSession',Mock(return_value=capture)),(fishing,'Listener',Mock()),
                (fishing,'PhysicalActivity',Mock(return_value=Mock(last=100.,last_other_input=None))),
                (fishing,'load_config',Mock(return_value={'camera_mode':'keep','auto_rod':False,'cast_point':(1600,800),'overnight_focus_grace_seconds':30}))]:
                stack.enter_context(patch.object(target,name,value))
            stack.enter_context(patch.object(full_pause.InputGate,'start'))
            stack.enter_context(patch.object(fishing.time,'monotonic',side_effect=lambda:clock[0]))
            stack.enter_context(patch.object(fishing.time,'sleep',side_effect=sleep))
            stack.enter_context(patch.object(fishing.cv2,'imread',return_value=None))
            stack.enter_context(patch.object(fishing.landmarks,'profile',return_value=None))
            stack.enter_context(patch.object(sys,'argv',['fishing_assistant.py','--seconds','9']))
            stack.enter_context(patch('builtins.print'))
            try:fishing.main()
            except RuntimeError as caught:error=caught
        events=[json.loads(line) for line in next(root.glob('events-*.jsonl')).read_text().splitlines()]
        return events,inputs,states,error,inventory

    def test_replacement_collects_ground_loot_before_first_cast(self):
        events,inputs,states,error,inventory=self.drive()
        self.assertIsNone(error)
        names=[r['event'] for r in events]
        self.assertLess(names.index('pending_pickup_recovered'),names.index('pickup_hold'))
        self.assertLess(names.index('reward_observed'),names.index('cast'))
        self.assertEqual(sum(name=='reward_observed' for name in names),1)
        reward=next(r for r in events if r['event']=='reward_observed')
        self.assertEqual(reward['cycle'],1)
        self.assertEqual(reward['text'],'Krathulon X1')
        self.assertEqual(states[-1]['cycles'],0)
        self.assertEqual(states[-1]['recovered_pickups'],1)
        self.assertEqual(states[-1]['unknown_rounds'],0)
        first_t=next(at for kind,flags,at in inputs if kind=='T' and flags==0)
        first_cast=next(at for kind,flags,at in inputs if kind=='mouse' and flags==2)
        self.assertLess(first_t,first_cast)

    def test_waiting_worker_rechecks_ground_loot_after_f8(self):
        events,inputs,states,error,inventory=self.drive('empty',pause_after_cast=True)
        self.assertIsNone(error)
        names=[r['event'] for r in events]
        self.assertLess(names.index('cast'),names.index('input_paused'))
        self.assertLess(names.index('input_resumed'),names.index('pending_pickup_recovered'))
        first_reward=names.index('reward_observed')
        self.assertEqual(sum(name=='cast' for name in names[:first_reward]),1)
        self.assertTrue(all(not s['held_t'] and not s['held_mouse'] for s in states if s.get('stage')=='paused_manual'))

    def test_ambiguous_ground_prompt_never_casts_or_holds_t(self):
        events,inputs,states,error,inventory=self.drive('ambiguous')
        self.assertEqual(error.code,'pickup_timeout')
        self.assertFalse(any(r['event']=='cast' for r in events))
        self.assertFalse(any(flags==0 and kind=='T' for kind,flags,at in inputs))

    def test_ignored_cast_recovers_pending_collect_without_waiting_for_bite_timeout(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True)
        self.assertIsNone(error)
        names=[r['event'] for r in events]
        self.assertNotIn('input_resumed',names)
        self.assertNotIn('no_minigame',names)
        self.assertEqual(sum(name=='cast' for name in names[:names.index('reward_observed')]),1)
        cast_release=next(at for kind,flags,at in inputs if kind=='mouse' and flags==4)
        t_press=next(at for kind,flags,at in inputs if kind=='T' and flags==0)
        self.assertLess(t_press-cast_release,2)

    def test_previous_reward_toast_does_not_count_again(self):
        events,inputs,states,error,inventory=self.drive('reward')
        self.assertIsNone(error)
        self.assertTrue(any(r['event']=='cast' for r in events))
        self.assertFalse(any(r['event']=='reward_observed' for r in events))
        self.assertFalse(any(flags==0 and kind=='T' for kind,flags,at in inputs))

    def test_pause_during_scan_invalidates_pending_t_press(self):
        events,inputs,states,error,inventory=self.drive(pause_in_ocr=True)
        self.assertIsNone(error)
        self.assertTrue(any(r['event']=='input_paused' for r in events))
        self.assertFalse(any(flags==0 and kind=='T' for kind,flags,at in inputs))

    def test_active_minigame_takes_priority_over_ground_prompt(self):
        events,inputs,states,error,inventory=self.drive(active_minigame=True)
        self.assertIsNone(error)
        self.assertTrue(any(r['event']=='minigame' for r in events))
        self.assertFalse(any(r['event'] in ('cast','pending_pickup_recovered','reward_observed') for r in events))
        self.assertEqual(states[-1]['cycles'],1)
        self.assertEqual(states[-1]['recovered_pickups'],0)
        self.assertFalse(any(flags==0 and kind=='T' for kind,flags,at in inputs))

    def test_manual_stop_during_scene_scan_wins_over_f8_and_pending_loot(self):
        events,inputs,states,error,inventory=self.drive(stop_in_ocr=True)
        self.assertEqual(str(error),'Stopped by stop file')
        self.assertEqual(states[-1]['failure_code'],'manual_stop')
        self.assertTrue((self.test_root/'STOP').is_file())
        self.assertTrue((self.test_root/'F8_PAUSE').is_file())
        self.assertFalse(any(r['event'] in ('cast','pickup_hold','pending_pickup_recovered') for r in events))
        self.assertFalse(any((kind=='T' and flags==0) or (kind=='mouse' and flags==2) for kind,flags,at in inputs))
        self.assertFalse(states[-1]['held_mouse']);self.assertFalse(states[-1]['held_t'])

    def test_resize_to_negative_origin_ultrawide_collects_pending_loot_before_recast(self):
        events,inputs,states,error,inventory=self.drive('empty',resize_after_cast=True)
        self.assertIsNone(error)
        names=[row['event'] for row in events]
        self.assertLess(names.index('cast'),names.index('client_reacquired'))
        self.assertLess(names.index('client_reacquired'),names.index('pending_pickup_recovered'))
        self.assertLess(names.index('pending_pickup_recovered'),names.index('reward_observed'))
        self.assertEqual(sum(kind=='cast' for kind in names[:names.index('reward_observed')]),1)
        reacquired=next(row for row in events if row['event']=='client_reacquired')
        self.assertEqual(reacquired['rect'],[-3440,30,0,1470])
        self.assertTrue(any(row.get('stage')=='window_wait' for row in states))
        self.assertTrue(all(not row['held_mouse'] and not row['held_t'] for row in states if row.get('stage')=='window_wait'))
        self.assertEqual(states[-1]['cycles'],0)
        self.assertEqual(states[-1]['recovered_pickups'],1)
        self.assertEqual(sum(row['event']=='reward_observed' for row in events),1)

    def test_unconfirmed_empty_and_other_actions_do_not_clear_cast(self):
        self.assertEqual(before_cast_decision(Pickup('empty'),False,1),'wait')
        self.assertEqual(before_cast_decision(Pickup('empty'),True,.2),'wait')
        self.assertEqual(before_cast_decision(Pickup('empty'),True,.5),'clear')
        self.assertEqual(before_cast_decision(Pickup('other','Purchase'),True,1),'wait')
        self.assertEqual(before_cast_decision(Pickup('other','Purchase'),True,8),'timeout')


if __name__=='__main__':unittest.main()
