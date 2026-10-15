import sys
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import cv2
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from app_config import ROOT
from rod_detector import locate_rod,selected_rod,unselected_rod
from rod_recovery import RodRecovery
from live_feed import describe
from faults import FishingFault
from overnight_guard import can_restart


class RodRecoveryTests(unittest.TestCase):
    def test_translucent_unselected_rod_over_daylight_scenery(self):
        # Same rod foreground over a changing background, without a disk.
        yy,xx=np.indices((1440,2560))
        gray=(95+35*np.sin(xx*.29+yy*.17)).astype(np.uint8)
        frame=np.repeat(gray[:,:,None],3,axis=2)
        icon=cv2.imread(str(ROOT/'assets/legendary-rod-unequipped.png'))
        crop=frame[1352:1426,1436:1512]
        foreground=icon.max(axis=2)>65
        crop[foreground]=icon[foreground]
        rod=locate_rod(frame)
        self.assertEqual(rod['name'],'legendary')
        self.assertAlmostEqual(rod['x'],1472,delta=2)
        self.assertFalse(selected_rod(rod))
        self.assertTrue(unselected_rod(rod))

    def test_textured_scenery_alone_does_not_authorize_a_rod_click(self):
        rng=np.random.default_rng(123)
        frame=rng.integers(40,180,(1440,2560,3),dtype=np.uint8)
        self.assertFalse(unselected_rod(locate_rod(frame)))
        self.assertFalse(selected_rod(locate_rod(frame)))

    def test_persistent_full_farmer_fault_rejoins_before_idle_timeout(self):
        policy=RodRecovery()
        self.assertEqual(policy.choose(0),('local',3))
        self.assertEqual(policy.choose(8),('local',3))
        self.assertEqual(policy.choose(16),('rejoin',3))
        for now in range(20,616,30):
            action,delay=policy.choose(now)
            self.assertEqual(action,'wait')
            self.assertLessEqual(delay,60)
        self.assertEqual(policy.choose(616),('rejoin',3))

    def test_farm_here_never_rejoins_for_a_rod_vision_fault(self):
        policy=RodRecovery()
        for now in range(0,3600,60):
            action,delay=policy.choose(now,here=True)
            self.assertIn(action,('local','wait'))

    def test_success_clears_retries_but_preserves_rejoin_rate_limit(self):
        policy=RodRecovery()
        for now in (0,10,20):policy.choose(now)
        policy.progress()
        self.assertEqual(policy.choose(30),('local',3))
        self.assertEqual(policy.choose(40),('local',3))
        self.assertEqual(policy.choose(50),('wait',30))

    def test_unverified_selection_never_logs_equipped_or_casts(self):
        import recovery
        driver=recovery.Recovery.__new__(recovery.Recovery)
        driver.move=Mock();driver.sleep=Mock();driver.key=Mock();driver.click=Mock()
        driver.capture=Mock();driver.event=Mock()
        with patch.object(recovery,'load_config',return_value={'cast_point':(1650,800),'auto_rod':True,'rod_slot':5}),\
             patch.object(recovery,'locate_rod',return_value=None):
            with self.assertRaises(FishingFault) as fault:driver.equip_rod()
        self.assertEqual(fault.exception.code,'rod_unreadable')
        events=[call.args[0] for call in driver.event.call_args_list]
        self.assertIn('rod_selection_attempt',events)
        self.assertNotIn('rod_equipped',events)
        self.assertNotIn('rod_selection_verified',events)
        driver.click.assert_not_called()

    def test_manual_hold_and_real_user_attention_still_block_restart(self):
        config={'overnight_enabled':True,'overnight_autofocus':True}
        self.assertTrue(can_restart(config,500,True,failure_code='rod_unreadable'))
        self.assertFalse(can_restart(config,500,True,manual=True,failure_code='rod_unreadable'))
        self.assertFalse(can_restart(config,500,True,failure_code='user_required'))

    def test_log_describes_selection_attempt_separately_from_verification(self):
        self.assertEqual(describe({'event':'rod_selection_attempt'}),'Selecting rod · awaiting verification')
        self.assertEqual(describe({'event':'rod_selection_verified'}),'Rod equipped · verified')


if __name__=='__main__':unittest.main()
