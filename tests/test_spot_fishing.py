import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import cv2
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fishing_vision import detect, ui_visible
from spot_fishing import SpotCycle
from pickup_policy import Pickup
from minigame_assist import ForegroundInput, read_scene
import minigame_assist


class TintedVision(unittest.TestCase):
    def fixture(self, background, target):
        im=np.full((600,140,3),background,np.uint8)
        cv2.rectangle(im,(35,30),(105,545),(110,110,110),1)
        cv2.rectangle(im,(32,240),(108,296),target,-1)
        cv2.rectangle(im,(55,350),(85,380),(220,220,250),-1)
        return im

    def test_tracks_transparent_bar_over_red_yellow_green_and_blue(self):
        for background,target in [((20,20,170),(30,115,180)),((15,100,180),(30,160,220)),
                                  ((150,70,15),(45,160,60)),((20,30,10),(40,130,70))]:
            with self.subTest(background=background):
                result=detect(self.fixture(background,target))
                self.assertIsNotNone(result)
                self.assertAlmostEqual(result['target'],268.5,delta=2)
                self.assertAlmostEqual(result['ball'],365.5,delta=2)

    def test_requires_both_markers_and_rejects_wrong_geometry(self):
        for color in ((0,0,220),(60,180,60),(235,235,235)):
            self.assertIsNone(detect(np.full((600,140,3),color,np.uint8)))
        im=self.fixture((20,20,170),(30,115,180));im[340:390,50:90]=(20,20,170)
        self.assertIsNone(detect(im))

    def test_target_border_crossing_marker_keeps_whole_center(self):
        im=self.fixture((20,20,170),(30,115,180))
        im[363:366,55:86]=(55,130,90)
        result=detect(im)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['ball'],365.5,delta=2)

    def test_ui_gate_does_not_accept_plain_background(self):
        template=cv2.imread(str(Path(__file__).resolve().parents[1]/'assets/exit.png'))
        for color in ((0,0,220),(200,200,200),(40,50,60)):
            self.assertFalse(ui_visible(np.full((70,180,3),color,np.uint8),template))

    def test_brown_scenery_connected_to_target_does_not_hide_it(self):
        im=np.full((600,140,3),(50,75,80),np.uint8)
        cv2.rectangle(im,(35,30),(104,545),(24,32,36),-1)
        cv2.rectangle(im,(31,415),(108,467),(20,75,85),-1)
        cv2.rectangle(im,(31,415),(108,467),(10,170,180),2)
        cv2.rectangle(im,(55,512),(85,542),(220,220,220),-1)
        result=detect(im)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['target'],441.5,delta=2)
        self.assertAlmostEqual(result['ball'],527.5,delta=2)

    def test_target_outline_wins_over_green_lily_pad(self):
        im=np.full((600,140,3),(145,75,20),np.uint8)
        cv2.rectangle(im,(35,30),(104,545),(85,42,18),-1)
        cv2.ellipse(im,(67,190),(90,39),0,0,360,(40,125,35),-1)
        cv2.rectangle(im,(31,102),(108,154),(100,120,70),-1)
        cv2.rectangle(im,(31,102),(108,154),(60,190,170),2)
        cv2.rectangle(im,(55,220),(85,250),(230,235,230),-1)
        result=detect(im)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['target'],128,delta=3)
        self.assertAlmostEqual(result['ball'],235.5,delta=2)

    def test_larger_control_bar_is_not_limited_to_common_rod_height(self):
        im=self.fixture((20,20,170),(30,115,180))
        cv2.rectangle(im,(31,160),(108,310),(30,115,180),-1)
        cv2.rectangle(im,(31,160),(108,310),(15,210,190),2)
        result=detect(im)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['height'],153,delta=5)

    def test_dim_tinted_marker_uses_local_contrast(self):
        im=self.fixture((70,30,10),(45,115,60))
        im[350:381,55:86]=(155,145,110)
        result=detect(im)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['ball'],365.5,delta=2)


class SpotState(unittest.TestCase):
    def setUp(self):
        self.events=[]
        self.spot=SpotCycle(lambda kind,**kw:self.events.append((kind,kw)))
        self.spot.arm(0)

    def step(self,t,kind='empty',world=True,equipped=True,stable=True):
        return self.spot.step(t,Pickup(kind,'Coral X1' if kind=='reward' else ''),stable,world,equipped)

    def test_player_must_arm_and_equip_before_clicking(self):
        blank=SpotCycle(Mock())
        self.assertEqual(blank.step(20,Pickup('empty'),True,True,True),'release')
        self.assertFalse(blank.armed)
        blank.arm(0)
        for t in (2,10,60):
            self.assertEqual(blank.step(t,Pickup('empty'),True,True,False),'release')
        self.assertEqual(blank.step(61,Pickup('empty'),True,True,True),'cast')

    def test_complete_cycle_collects_once_and_repeats(self):
        self.assertEqual(self.step(1.3),'cast')
        self.assertEqual(self.step(1.4),'hold')
        self.assertEqual(self.step(1.5),'release');self.assertEqual(self.spot.casts,1)
        self.spot.tracking(4);self.spot.ended(12)
        self.assertEqual(self.step(12.5,'collect'),'collect')
        self.assertEqual(self.step(13,'reward'),'collect')
        self.assertEqual(self.step(14.4,'reward'),'release')
        self.step(15,'reward');self.assertEqual(self.spot.rewards,1)
        self.step(16);self.assertEqual(self.step(17.3),'cast')

    def test_f8_starts_then_pauses_and_resumes_without_duplicate_cast(self):
        blank=SpotCycle(Mock())
        self.assertTrue(blank.toggle(0))
        self.assertEqual(blank.step(2,Pickup('empty'),True,True,True),'cast')
        blank.step(2.2,Pickup('empty'),True,True,True)
        self.assertFalse(blank.toggle(3))
        self.assertEqual(blank.step(50,Pickup('collect'),True,True,True),'release')
        self.assertTrue(blank.toggle(3))  # Paused wall time is excluded.
        self.assertEqual(blank.step(4,Pickup('empty'),True,True,True),'release')
        self.assertEqual(blank.casts,1)

    def test_f8_can_pause_during_tracking_or_pickup(self):
        for stage in ('tracking','pickup'):
            self.setUp();self.spot.stage=stage;self.spot.since=1
            self.assertFalse(self.spot.toggle(2))
            self.assertEqual(self.step(3,'collect'),'release')
            self.assertTrue(self.spot.toggle(2))
            self.assertEqual(self.step(2.1,stable=False),'release')

    def test_focus_return_reobserves_instead_of_reusing_hold(self):
        self.spot.tracking(1);self.spot.ended(5)
        self.assertEqual(self.step(5.5,'collect'),'collect')
        self.spot.resume(6)
        self.assertEqual(self.step(6.1,stable=False),'release')
        self.assertEqual(self.step(7),'release')
        self.assertEqual(self.step(10.2),'release')
        self.assertEqual(self.step(13.1),'cast')

    def test_round_without_reward_continues_without_t(self):
        self.spot.tracking(1);self.spot.ended(5)
        self.assertEqual(self.step(6),'release')
        self.assertEqual(self.step(9.1),'release')
        self.assertEqual(self.step(12.1),'cast')
        self.assertEqual(self.spot.rewards,0)

    def test_focus_return_preserves_pending_bite_wait(self):
        self.assertEqual(self.step(1.3),'cast')
        self.step(1.5)
        self.spot.resume(4)
        self.assertEqual(self.step(6),'release')
        self.spot.resume(7)
        self.assertEqual(self.step(10),'release')
        self.assertEqual(self.step(25),'release')
        self.assertEqual(self.step(32),'cast')

    def test_blocked_press_is_not_counted_as_a_cast_or_bite_wait(self):
        self.assertEqual(self.step(1.3),'cast')
        self.spot.cancel_unstarted_press(1.4)
        self.spot.resume(1.5)
        self.assertEqual(self.step(2.8),'cast')
        self.assertEqual(self.spot.casts,0)

    def test_brief_loss_of_hotbar_cannot_cancel_pending_bite(self):
        self.assertEqual(self.step(2),'cast');self.step(2.2)
        self.step(5,world=False);self.step(6)
        for t in (8,15,25,31):self.assertEqual(self.step(t),'release')
        self.assertEqual(self.step(32.1),'cast')

    def test_late_pickup_resets_clear_scene_wait_and_is_collected(self):
        self.spot.tracking(1);self.spot.ended(5)
        self.step(6)
        self.assertEqual(self.step(10.5,'collect'),'collect')
        self.assertEqual(self.step(11),'collect')
        self.assertEqual(self.step(11.5),'release')
        self.assertEqual(self.step(13),'release')
        self.assertEqual(self.step(14,'collect'),'collect')

    def test_pickup_does_not_need_equipped_rod_and_conflicts_release_t(self):
        self.spot.tracking(1);self.spot.ended(5)
        self.assertEqual(self.step(6,'collect',equipped=False),'collect')
        self.assertEqual(self.step(6.3,'other',equipped=False),'release')

    def test_stale_selected_rod_and_hotbar_cursor_cannot_authorize_cast(self):
        from rod_detector import RodReady
        from screen_space import ScreenSpace
        gate=RodReady();rod={'equipped':True,'score':.95,'ring':.5,'x':1470,'y':1385}
        self.assertFalse(gate.observe(rod,1))
        self.assertFalse(gate.observe(rod,1.4))
        self.assertTrue(gate.observe(rod,1.8))
        self.assertFalse(gate.matches({**rod,'equipped':False}))
        self.assertFalse(gate.observe(None,2))
        self.assertFalse(gate.observe(rod,2.4))
        with patch.object(minigame_assist.win32gui,'GetCursorPos',return_value=(1470,1385)):
            self.assertFalse(minigame_assist.safe_cast_pointer(ScreenSpace((0,0,2560,1440))))
        with patch.object(minigame_assist.win32gui,'GetCursorPos',return_value=(1280,720)):
            self.assertTrue(minigame_assist.safe_cast_pointer(ScreenSpace((0,0,2560,1440))))

    def test_manual_input_forbids_pointer_movement(self):
        import fishing_assistant
        with patch.object(fishing_assistant,'move_pointer') as move:
            with self.assertRaises(RuntimeError):ForegroundInput().aim(850,800)
            move.assert_not_called()

    def test_f8_releases_once_per_press_and_only_in_roblox(self):
        for focused in (True,False):
            inp=Mock(toggle_enabled=True,hwnd=1)
            done=Mock();done.wait.side_effect=[False,False,True]
            with patch.object(minigame_assist,'USER') as user,patch.object(minigame_assist,'foreground',return_value=focused),patch.object(minigame_assist,'window_foreground',return_value=focused),patch.object(minigame_assist,'RUN',Path('nonexistent-test-state')):
                user.GetAsyncKeyState.side_effect=lambda k:0x8000 if k==119 else 0
                minigame_assist.watch_focus(inp,done)
            self.assertEqual(inp.toggle_requested.set.call_count,1 if focused else 0)
            if focused:inp.suspend_input.assert_called_once()

    def test_manual_input_emits_only_left_click_and_t(self):
        import fishing_assistant
        from unittest.mock import call
        with patch.object(fishing_assistant,'USER') as user,patch.object(minigame_assist,'RUN',Path('nonexistent-test-state')):
            user.MapVirtualKeyW.return_value=20
            inp=ForegroundInput()
            inp.hold(True);inp.hold(False);inp.grab(True);inp.release()
            self.assertEqual(user.mouse_event.call_args_list,[call(2,0,0,0,0),call(4,0,0,0,0)])
            self.assertEqual(user.keybd_event.call_args_list,[call(ord('T'),20,0,0),call(ord('T'),20,2,0)])
            user.SetCursorPos.assert_not_called();user.ClipCursor.assert_not_called()
            user.SetForegroundWindow.assert_not_called()

    def test_pickup_and_no_bite_retries_are_bounded(self):
        self.spot.tracking(1);self.spot.ended(2)
        for t in (3,8,13):
            self.assertEqual(self.step(t,'collect'),'collect')
            self.assertEqual(self.step(t+4.1,'collect'),'release')
        self.assertEqual(self.step(18,'collect'),'release')
        self.assertEqual(self.spot.stage,'spot_attention')
        self.setUp()
        for t in (2,35,68):
            self.step(t);self.step(t+.2);self.step(t+31)
        self.assertEqual(self.spot.stage,'spot_attention')

    def test_nonfishing_scene_and_interactions_never_press(self):
        self.assertEqual(self.step(2,world=False),'release')
        self.assertEqual(self.spot.stage,'spot_blocked')
        self.assertEqual(self.step(3),'release')
        for t in (5,7,9):self.assertEqual(self.step(t,'other'),'release')

    def test_focus_loss_during_ocr_blocks_new_down_but_allows_release(self):
        inp=ForegroundInput();inp.interrupted.set()
        with patch.object(minigame_assist,'RUN',Path('nonexistent-test-state')):
            with self.assertRaises(RuntimeError):inp.hold(True)
            with self.assertRaises(RuntimeError):inp.grab(True)
            inp.release()

    def test_disconnect_even_with_visible_rod_blocks_world(self):
        frame=np.zeros((1440,2560,3),np.uint8)
        ocr=Mock(return_value=([[[[0,0],[100,0],[100,25],[0,25]],'Disconnected',.98]],None))
        with patch.object(minigame_assist,'locate_rod',return_value={'equipped':True}):
            evidence,world,rod=read_scene(frame,ocr)
        self.assertFalse(world)


if __name__=='__main__':unittest.main()
