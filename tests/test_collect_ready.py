import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pickup_policy import Pickup,CollectReadyGate,CollectHoldMotion,classify


class CollectReadyTests(unittest.TestCase):
    def prompt(self,x=1280,y=650):
        return Pickup('collect','Fish T Collect',(x+100,y+15),(x,y))

    def test_airborne_prompt_must_land_before_the_first_press(self):
        gate=CollectReadyGate()
        self.assertFalse(gate.observe(self.prompt(1500,300),True,1))
        self.assertFalse(gate.observe(self.prompt(1340,550),True,1.15))
        self.assertFalse(gate.observe(self.prompt(1280,650),True,1.25))
        self.assertTrue(gate.observe(self.prompt(1282,651),True,1.4))

    def test_animated_prompt_cannot_delay_the_first_hold_for_seconds(self):
        gate=CollectReadyGate();gate.observe(self.prompt(1550,300),True,1)
        self.assertFalse(gate.observe(self.prompt(1490,430),True,1.15))
        self.assertTrue(gate.observe(self.prompt(1420,560),True,1.31))

    def test_newly_visible_t_rebinds_the_occluded_first_hold_promptly(self):
        motion=CollectHoldMotion();motion.start(Pickup('collect','Fish Collect',(1380,650)),1)
        self.assertFalse(motion.observe(self.prompt(),True,1.8,1))
        self.assertFalse(motion.observe(self.prompt(),True,2,1))
        self.assertTrue(motion.observe(self.prompt(),True,2.13,1))

    def test_missing_or_stale_or_ambiguous_prompt_cannot_press(self):
        for evidence,stable,at in ((Pickup('empty'),True,1.2),
                (Pickup('ambiguous','Purchase Collect'),True,1.2),
                (self.prompt(),False,1.2),(self.prompt(),True,3)):
            gate=CollectReadyGate();gate.observe(self.prompt(),True,1)
            self.assertFalse(gate.observe(evidence,stable,at))

    def test_occluded_t_has_a_bounded_repeated_label_fallback(self):
        gate=CollectReadyGate();label=Pickup('collect','Fish Collect',(1380,650))
        self.assertFalse(gate.observe(label,True,1))
        self.assertFalse(gate.observe(label,True,1.2))
        self.assertTrue(gate.observe(label,True,1.7))

    def test_key_position_ignores_item_name_and_title_ocr_changes(self):
        gate=CollectReadyGate();gate.observe(self.prompt(),True,1)
        changed=Pickup('collect','Living Legend Golden Fish T Collect',(1460,640),(1281,650))
        self.assertTrue(gate.observe(changed,True,1.15))
        motion=CollectHoldMotion();motion.start(self.prompt(),1)
        self.assertFalse(motion.observe(changed,True,1.8,1))
        self.assertFalse(motion.observe(changed,True,2,1))

    def test_moved_key_retries_promptly_only_after_it_settles(self):
        motion=CollectHoldMotion();motion.start(self.prompt(1400,600),1)
        self.assertFalse(motion.observe(self.prompt(1280,650),True,1.8,1))
        self.assertFalse(motion.observe(self.prompt(1281,650),True,2,1))
        self.assertTrue(motion.observe(self.prompt(1281,650),True,2.13,1))
        self.assertFalse(motion.observe(self.prompt(1281,650),True,2.2,2))

    def test_only_nearby_confident_t_is_the_collect_anchor(self):
        rows=[{'text':'Collect','score':.99,'center':(1380,650)},
              {'text':'T','score':.95,'center':(1280,650)}]
        self.assertEqual(classify(rows).key_center,(1280,650))
        self.assertIsNone(classify([rows[0],{**rows[1],'center':(800,650)}]).key_center)


if __name__=='__main__':unittest.main()
