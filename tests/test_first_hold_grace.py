import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pickup_policy import Pickup,CollectHoldMotion,collect_hold_timeout,retain_collect_hold


class FirstHoldGrace(unittest.TestCase):
    def test_first_attempt_keeps_a_short_grace_beyond_the_later_deadline(self):
        self.assertEqual(collect_hold_timeout(1),3.75)
        for attempt in (0,2,3):self.assertEqual(collect_hold_timeout(attempt),3.5)
        self.assertTrue(retain_collect_hold(Pickup('empty'),3.6,attempt=1))
        self.assertFalse(retain_collect_hold(Pickup('empty'),3.75,attempt=1))
        self.assertFalse(retain_collect_hold(Pickup('empty'),3.5,attempt=2))

    def test_reward_and_other_interactions_do_not_wait_for_extra_grace(self):
        self.assertFalse(retain_collect_hold(Pickup('reward'),.7,confirmed_reward=True,attempt=1))
        for kind in ('other','ambiguous'):
            self.assertFalse(retain_collect_hold(Pickup(kind),.7,attempt=1))

    def test_first_moving_label_keeps_a_short_grace_after_settling(self):
        motion=CollectHoldMotion();motion.start(Pickup('collect',center=(1370,285)),0)
        motion.observe(Pickup('collect',center=(1380,610)),True,1,1)
        self.assertFalse(motion.observe(Pickup('collect',center=(1382,625)),True,1.4,1))
        self.assertFalse(motion.observe(Pickup('collect',center=(1381,624)),True,1.64,1))
        self.assertTrue(motion.observe(Pickup('collect',center=(1381,624)),True,1.65,1))

    def test_ambiguous_or_stale_evidence_discards_pending_movement_retry(self):
        for interrupted,stable,at in ((Pickup('empty'),True,1.6),(Pickup('other'),True,1.6),
                                       (Pickup('collect',center=(1380,620)),False,1.6),
                                       (Pickup('collect',center=(1380,620)),True,3.1)):
            motion=CollectHoldMotion();motion.start(Pickup('collect',center=(1370,285)),0)
            motion.observe(Pickup('collect',center=(1380,610)),True,1,1)
            motion.observe(Pickup('collect',center=(1380,620)),True,1.4,1)
            self.assertFalse(motion.observe(interrupted,stable,at,1))
            self.assertIsNone(motion.retry_ready_at)

    def test_new_hold_resets_pending_grace_and_later_attempts_never_motion_retry(self):
        motion=CollectHoldMotion();motion.start(Pickup('collect',center=(1370,285)),0)
        motion.observe(Pickup('collect',center=(1380,610)),True,1,1)
        motion.observe(Pickup('collect',center=(1380,620)),True,1.4,1)
        motion.start(Pickup('collect',center=(1370,285)),2)
        self.assertIsNone(motion.retry_ready_at)
        motion.observe(Pickup('collect',center=(1380,610)),True,3,2)
        self.assertFalse(motion.observe(Pickup('collect',center=(1380,620)),True,3.4,2))


if __name__=='__main__':unittest.main()
