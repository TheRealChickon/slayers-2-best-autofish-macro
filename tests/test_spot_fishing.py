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


class SpotState(unittest.TestCase):
    def setUp(self):
        self.events=[]
        self.spot=SpotCycle(lambda kind,**kw:self.events.append((kind,kw)))
        self.spot.select((1500,700),0)

    def step(self,t,kind='empty',world=True,equipped=True,stable=True):
        return self.spot.step(t,Pickup(kind,'Coral X1' if kind=='reward' else ''),stable,world,equipped)

    def test_point_required_and_hud_rejected(self):
        blank=SpotCycle(Mock())
        self.assertEqual(blank.step(20,Pickup('empty'),True,True,True),'release')
        self.assertFalse(blank.select((100,1400),0));self.assertIsNone(blank.point)

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

    def test_focus_return_reobserves_instead_of_reusing_hold(self):
        self.spot.tracking(1);self.spot.ended(5)
        self.assertEqual(self.step(5.5,'collect'),'collect')
        self.spot.resume(6)
        self.assertEqual(self.step(6.1,stable=False),'release')
        self.assertEqual(self.step(7),'release')
        self.assertEqual(self.step(10.2),'cast')

    def test_round_without_reward_continues_without_t(self):
        self.spot.tracking(1);self.spot.ended(5)
        self.assertEqual(self.step(6),'release')
        self.assertEqual(self.step(9.1),'cast')
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
