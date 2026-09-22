import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracking_control import ReelMotion


def sample(ball,target=250,height=54):
    return {'ball':ball,'target':target,'height':height,'ball_height':31}


class ReelControl(unittest.TestCase):
    def test_brakes_before_a_fast_marker_crosses_the_target(self):
        control=ReelMotion()
        control.step(sample(300),1)
        for t,y in ((1.02,296),(1.04,288),(1.06,276)):
            held=control.step(sample(y),t)
        self.assertFalse(held)
        self.assertGreater(control.previous[1],250)

    def test_one_impossible_marker_jump_does_not_reverse_input(self):
        control=ReelMotion();control.step(sample(300),1)
        self.assertTrue(control.step(sample(100),1.016))
        self.assertEqual(control.previous[1],300)
        control.step(sample(100),1.032)
        self.assertFalse(control.held)

    def test_focus_suspend_discards_motion_and_releases(self):
        control=ReelMotion();control.step(sample(350),1)
        control.suspend()
        self.assertFalse(control.held);self.assertIsNone(control.previous)
        self.assertFalse(control.step(sample(200),2))

    def test_large_target_jump_is_not_extrapolated_into_another_jump(self):
        control=ReelMotion();control.step(sample(300,300),1)
        self.assertTrue(control.step(sample(300,120),1.016))
        self.assertEqual(control.target_velocity,0)

    def test_tracks_different_rod_response_rates_in_closed_loop(self):
        # Independent damped-motion simulation with reversals and quantization.
        for acceleration,drag in ((800,3),(1240,4.2),(1800,5.5)):
            with self.subTest(acceleration=acceleration):
                control=ReelMotion();y=300.;v=0.;inside=total=0
                for n in range(900):
                    t=n/60;target=285+90*math.sin(t*1.2)+25*math.sin(t*2.7)
                    held=control.step(sample(round(y*2)/2,target),t+1)
                    for _ in range(4):
                        v+=((-acceleration if held else acceleration)-drag*v)/240
                        y+=v/240
                    if t>1:inside+=abs(y-target)<14.5;total+=1
                self.assertGreater(inside/total,.90)
                self.assertTrue(400<=control.up_accel<=3000)
                self.assertTrue(400<=control.down_accel<=3000)
