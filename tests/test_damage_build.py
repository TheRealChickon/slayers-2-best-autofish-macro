"""Personal build display uses saved evidence without controlling the game."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import damage_build
import fishing_cli
import terminal_app
import app_config


class DamageBuild(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        site = self.root/'wiki-snapshot'/'site'
        site.mkdir(parents=True)
        items = [{'name': name, 'stats': ['+2 (Additional Damage)'], 'equipped': True,
                  'refinement': 10 if name == 'Nightfall Gauntlet' else 0}
                 for name in ('Stone Haori', 'Demonic Lantern', 'Bamboo Muzzle',
                              'Demonic Horns II', 'Nichirin Lantern', 'Nightfall Gauntlet')]
        (site/'items.json').write_text(json.dumps({'captured_at': 'test', 'inventory': items}), encoding='utf-8')
        self.profile = {'mastery': 186, 'weapon': 'Nightfall Gauntlet',
                        'stat_items': [item['name'] for item in items[:5]],
                        'calibration': {'mastery': 186, 'm1': 64.15,
                                        'base_per_mastery': 0.025, 'damage_factor': 1.461}}
        (self.root/damage_build.PROFILE_NAME).write_text(json.dumps(self.profile), encoding='utf-8')

    def test_mastery_projection_is_only_for_saved_owned_loadout(self):
        measured = damage_build.report(self.root)
        self.assertEqual(measured['projected_m1'], 64.15)
        self.assertEqual(damage_build.report(self.root, 200)['projected_m1'], 64.66)
        self.assertEqual(len(measured['stat_items']), 5)
        self.assertEqual(measured['weapon']['refinement'], 10)
        self.profile['stat_items'][0] = 'Not owned'
        (self.root/damage_build.PROFILE_NAME).write_text(json.dumps(self.profile), encoding='utf-8')
        self.assertIsNone(damage_build.report(self.root)['projected_m1'])

    def test_haori_swap_uses_flat_damage_and_additive_displayed_factor(self):
        owned = {
            'Stone Haori': {'stats': ['+2 (Additional Damage)', '1.02x (Additional Damage Factor)']},
            'Serpent Haori': {'stats': ['1.07x (Additional Damage Factor)']},
            'Flame Haori Style 1': {'stats': ['1.07x (Additional Damage Factor)']},
        }
        result = damage_build.haori_comparison(self.profile, owned)
        self.assertEqual(len(result['swaps']), 2)
        self.assertEqual(result['swaps'][0]['damage_factor'], 1.511)
        self.assertEqual(result['swaps'][0]['projected_m1'], 63.32)
        self.assertEqual(result['swaps'][0]['difference'], -0.83)
        self.assertEqual(result['swaps'][1]['projected_m1'], 63.32)

    def test_save_mastery_preserves_calibration(self):
        damage_build.save_mastery(190, self.root)
        self.assertEqual(damage_build.load_profile(self.root)['calibration']['mastery'], 186)
        self.assertEqual(damage_build.report(mastery=200, root=self.root)['projected_m1'], 64.66)
        self.assertEqual(damage_build.load_profile(self.root)['mastery'], 190)

    def test_fishing_pages_have_no_combat_build(self):
        app = terminal_app.Terminal()
        app.switch(4)
        self.assertEqual(app.pages[app.page], 'Predictions')
        self.assertNotIn('Build', app.pages)

    def test_hosted_wiki_command_uses_local_url_without_rebuilding(self):
        (self.root/'wiki-hosted-url.txt').write_text('https://private.example.test\n', encoding='utf-8')
        with patch.object(app_config, 'data_directory', return_value=self.root), \
             patch('webbrowser.open') as open_page, \
             patch.object(fishing_cli.actions, 'resume') as resume, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(fishing_cli.main(['wiki', '--site']), 0)
        open_page.assert_called_once_with('https://private.example.test')
        resume.assert_not_called()


if __name__ == '__main__':
    unittest.main()
