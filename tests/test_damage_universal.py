import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from damage_plan import DEFAULT_ROTATION, DamageRotation, validate_rotation
from damage_measure import DamageMeasurements
from damage_title import DamageTitleReader, progress_from_rows


class UniversalDamageTests(unittest.TestCase):
    def test_title_reader_retries_swallowed_menu_key_and_closes_verified_menu(self):
        import numpy as np
        class Driver:
            keys = 0
            menu = False
            def key(self, key):
                self.keys += 1
                if self.keys > 1:
                    self.menu = not self.menu
            def sleep(self, seconds): pass
            def move(self, x, y): pass
            def capture(self):
                frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
                frame[1345:1360, 1060:1100] = 255
                return frame
        driver = Driver()
        reader = DamageTitleReader(driver, 'Annihilator', 10_000_000)
        detail = [{'text': text, 'score': .99, 'center': (2200, y)} for text, y in
                  [('Annihilator', 365), ('Requirements', 469),
                   ('Deal 10,000,000 total damage.', 508), ('5,251,113 left', 582)]]
        def rows(box):
            if box[0] == 0:
                return [{'text': 'Titles'}] if driver.menu else []
            return detail
        with patch.object(reader, 'rows', side_effect=rows), patch.object(reader, 'click_named'):
            self.assertEqual(reader.inspect(), 4_748_887)
        self.assertEqual(driver.keys, 3)
        self.assertFalse(driver.menu)

    def test_cooling_skills_are_skipped_after_five_m1(self):
        cycle = DamageRotation(DEFAULT_ROTATION)
        now, actions = 0., []
        while len(actions) < 9:
            due = cycle.due(now, False, False, False)
            if due:
                actions.append(due[0])
            now += .05
        self.assertEqual(actions, ['m1']*5 + ['skip_shock_wave', 'skip_followup',
                                             'skip_ultimate', 'cycle_end'])

    def test_live_remaining_damage_format_requires_matching_requirement(self):
        rows = [{'text': text, 'score': .94, 'center': (2200, y)} for text, y in
                [('Annihilator', 365), ('Requirements', 469),
                 ('Deal 10,000,000 total', 508), ('damage.', 545),
                 ('5,251,113 left', 582)]]
        self.assertEqual(progress_from_rows(rows, 'Annihilator', 10_000_000), 4_748_887)
        with self.assertRaises(ValueError):
            progress_from_rows(rows, 'Annihilator', 5_000_000)
        rows.append({'text': '5,200,000 left', 'score': .94, 'center': (2200, 600)})
        with self.assertRaises(ValueError):
            progress_from_rows(rows, 'Annihilator', 10_000_000)

    def test_default_rotation_never_uses_v_or_x_alone(self):
        cycle = DamageRotation(DEFAULT_ROTATION)
        self.assertNotIn('V', DEFAULT_ROTATION['keys'].values())
        now, actions = 0., []
        while len(actions) < 10:
            due = cycle.due(now, ultimate_ready=True)
            if due:
                actions.append(due[0])
            now += .05
        self.assertEqual(actions, ['m1']*5+['shock_wave', 'followup',
                                           'ultimate_pair', 'cycle_end', 'm1'])

    def test_unready_ultimate_skips_prep_tap_and_hold_together(self):
        cycle = DamageRotation(DEFAULT_ROTATION)
        now, actions = 0., []
        while len(actions) < 9:
            due = cycle.due(now, ultimate_ready=False)
            if due:
                actions.append(due[0])
            now += .05
        self.assertEqual(actions[-2:], ['skip_ultimate', 'cycle_end'])
        self.assertNotIn('ultimate_pair', actions)

    def test_selected_moves_skip_others_without_sending_prep_alone(self):
        cycle = DamageRotation({'enabled': ['followup']})
        now, actions = 0., []
        while len(actions) < 10:
            due = cycle.due(now, ultimate_ready=True)
            if due:
                actions.append(due[0])
            now += .05
        self.assertIn('followup', actions)
        self.assertNotIn('shock_wave', actions)
        self.assertNotIn('ultimate_pair', actions)

    def test_arbitrary_keys_and_timing_validate(self):
        settings = validate_rotation({'keys': {'shock_wave': 'Q', 'followup': 'E',
            'ultimate_prep': 'R', 'ultimate': 'T'}, 'post_m1_wait': .5,
            'ultimate_prep_tap_seconds': .02})
        self.assertEqual(settings['keys']['ultimate'], 'T')
        with self.assertRaises(ValueError):
            validate_rotation({'keys': {'ultimate_prep': 'E', 'ultimate': 'E'}})
        with self.assertRaises(ValueError):
            validate_rotation({'post_m1_wait': .2})

    def test_title_progress_requires_verified_detail_and_exact_target(self):
        rows = [{'text': text, 'score': .94, 'center': (2200, y)} for text, y in
                [('Annihilator', 390), ('Requirements', 480),
                 ('Deal damage 12,345 / 5,000,000', 540)]]
        self.assertEqual(progress_from_rows(rows, 'Annihilator', 5_000_000), 12_345)
        with self.assertRaises(ValueError):
            progress_from_rows(rows, 'Other', 5_000_000)
        with self.assertRaises(ValueError):
            progress_from_rows(rows, 'Annihilator', 4_000_000)

    def test_first_and_fifth_are_separate_observed_differences(self):
        sample = DamageMeasurements(5_000_000, 1000, 60)
        sample.calibrate_m1(70, 280, 400)
        sample.calibrate_move('Shock Wave', 38)
        sample.observe(1600, 123)
        summary = sample.summary()
        self.assertEqual((summary['first_m1_damage'], summary['fifth_m1_damage']), (70, 120))
        self.assertEqual(summary['estimated_damage'], 600)
        self.assertEqual(summary['remaining_damage'], 4_998_400)
        self.assertEqual(summary['estimated_dps'], 10)

    def test_fishing_cli_rejects_combat_commands_without_starting(self):
        import fishing_cli
        from contextlib import redirect_stderr
        with patch.object(fishing_cli.actions, 'resume') as resume, redirect_stderr(StringIO()):
            for command in ('boss', 'damage', 'build'):
                with self.assertRaises(SystemExit) as error:
                    fishing_cli.main([command])
                self.assertEqual(error.exception.code, 2)
            resume.assert_not_called()


if __name__ == '__main__':
    unittest.main()
