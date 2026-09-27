import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from damage_cycle import DamageCycle, ProgressGuard
from damage_vision import SkillReady, gauntlet_selected, hotbar_visible
from damage_farmer import reset_character
from item_journal import Journal


class DamagePolicy(unittest.TestCase):
    def test_skill_precedes_exactly_five_m1s(self):
        cycle = DamageCycle()
        now = 10.
        actions = []
        while len(actions) < 7:
            action = cycle.due(now, True)
            if action:
                actions.append(action)
            now += .05
        self.assertEqual(actions, ['c', 'm1', 'm1', 'm1', 'm1', 'm1', 'cycle_end'])

    def test_stalled_combo_needs_three_plain_cycles_then_bounded_reset(self):
        guard = ProgressGuard()
        guard.observe(1)
        guard.observe(4)
        self.assertFalse(guard.finish_cycle(False))
        for _ in range(2):
            guard.observe(None)
            self.assertFalse(guard.finish_cycle(False))
        self.assertTrue(guard.finish_cycle(False))
        self.assertTrue(guard.reset_allowed(100))
        self.assertTrue(guard.reset_allowed(200))
        self.assertTrue(guard.reset_allowed(300))
        self.assertFalse(guard.reset_allowed(400))

    def test_ocr_flicker_does_not_add_false_hits(self):
        guard = ProgressGuard()
        self.assertEqual(guard.observe(32), 0)
        self.assertEqual(guard.observe(3), 0)
        self.assertEqual(guard.observe(33), 1)
        self.assertEqual(guard.observe(133), 0)
        self.assertEqual(guard.observe(34), 1)
        self.assertEqual(guard.cycle_hits, 2)

    def test_equipment_detection_uses_action_bar_and_waits_for_hud(self):
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        frame[1340:1430, 1050:1530] = 255
        self.assertTrue(hotbar_visible(frame))
        self.assertFalse(gauntlet_selected(frame))
        frame[1260:1335, 1025:1540] = 255
        self.assertTrue(gauntlet_selected(frame))

    def test_skill_ready_returns_only_after_the_icon_recovers(self):
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        frame[1290:1310, 1212:1240] = 255
        skill = SkillReady()
        self.assertTrue(skill.observe(frame))
        dark = frame.copy()
        dark[1280:1325, 1205:1250] = 0
        self.assertFalse(skill.observe(dark))
        self.assertTrue(skill.observe(frame))

    def test_respawn_does_not_confirm_original_menu(self):
        class Input:
            def guard_press(self, down): pass
            def release(self): pass

        actions, events = [], []
        menu = 'people settings respawn resume'
        with patch('damage_farmer.press', side_effect=lambda inp, key: actions.append(key)), \
             patch('damage_farmer.wait_for_scene', side_effect=lambda inp, screen, sct, ocr, predicate: predicate(menu)):
            self.assertFalse(reset_character(Input(), None, None, None,
                                             lambda kind, **fields: events.append(kind)))
        self.assertEqual(actions, ['esc', 'r'])
        self.assertIn('reset_attention', events)

    def test_respawn_requires_confirmation_then_enters(self):
        class Input:
            def guard_press(self, down): pass
            def release(self): pass

        actions, prompts = [], iter(('people settings respawn resume',
                                     'are you sure you want to respawn cancel respawn'))
        with patch('damage_farmer.press', side_effect=lambda inp, key: actions.append(key)), \
             patch('damage_farmer.wait_for_scene', side_effect=lambda inp, screen, sct, ocr, predicate: predicate(next(prompts))):
            self.assertTrue(reset_character(Input(), None, None, None, lambda *args, **kwargs: None))
        self.assertEqual(actions, ['esc', 'r', 'enter'])

    def test_damage_events_reach_cli_activity_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'events-damage-test.jsonl').write_text(json.dumps({
                'at': 2, 'event': 'damage_progress', 'message': 'Combo 20 · 25 M1'})+'\n')
            with patch('item_journal.RUN', path):
                journal = Journal()
                journal.update(1)
            self.assertEqual(journal.activity[0]['kind'], 'damage_progress')
            self.assertEqual(journal.activity[0]['group'], 'damage')


if __name__ == '__main__':
    unittest.main()
