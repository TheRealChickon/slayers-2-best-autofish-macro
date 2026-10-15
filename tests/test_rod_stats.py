import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app_config
import rod_stats


class CrateOptimizer(unittest.TestCase):
    def test_eight_balanced_commons_make_one_crate_b(self):
        best = rod_stats.best_crates({'ouwfish': 2, 'seahorse': 2, 'coral': 2, 'ouwfwesh': 2})
        self.assertEqual((best['crate_b'], best['crate_a'], best['gold']), (1, 0, 1580))

    def test_scarcest_common_limits_crates_and_the_rest_is_sold(self):
        best = rod_stats.best_crates({'ouwfish': 10, 'seahorse': 3, 'coral': 10, 'ouwfwesh': 10, 'crustadon': 2})
        self.assertEqual(best['crate_b'], 1)
        self.assertEqual(best['gold'], 1580+(8+1+8+8)*33+2*165)

    def test_crate_a_only_when_it_beats_crate_b(self):
        # 12 commons + 2 uncommons: one A (2,070) loses to one B plus selling the rest.
        counts = {'ouwfish': 3, 'seahorse': 3, 'coral': 3, 'ouwfwesh': 3, 'clownfish': 1, 'zebrafish': 1}
        best = rod_stats.best_crates(counts)
        self.assertEqual(best['gold'], max(2070, 1580+4*33+2*66))


class RodSessions(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        patcher = patch.object(app_config, 'CONFIG', self.root/'config.local.json'); patcher.start(); self.addCleanup(patcher.stop)

    def test_changing_rod_closes_the_open_session(self):
        rod_stats.set_rod('Legendary', at=100, root=self.root)
        rod_stats.set_rod('Legendary', at=150, root=self.root)
        rod_stats.set_rod('Rare', at=200, root=self.root)
        rows = rod_stats.sessions(self.root)
        self.assertEqual([(r['rod'], r['started'], r['ended']) for r in rows], [('Legendary', 100, 200), ('Rare', 200, None)])
        self.assertEqual(app_config.load_config()['active_rod'], 'Rare')

    def test_catches_are_attributed_by_session_and_page_renders(self):
        events = [{'at': 110+i, 'event': 'reward_observed', 'text': name+' X1', 'cycle': i} for i, name in
                  enumerate(('Crustadon', 'Coral', 'Clown Fish'), 1)]
        events += [{'at': 210, 'event': 'reward_observed', 'text': 'Sea Horse X1', 'cycle': 9}]
        (self.root/'events-20261015-010000.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        rod_stats.set_rod('Legendary', at=100, root=self.root); rod_stats.set_rod('Rare', at=200, root=self.root)
        rows = {r['rod']: r for r in rod_stats.by_rod(self.root, now=300)}
        self.assertEqual(rows['Legendary']['counts'], {'crustadon': 1, 'coral': 1, 'clownfish': 1})
        self.assertEqual(rows['Rare']['counts'], {'seahorse': 1})
        self.assertEqual(rows['Legendary']['rarity_percent']['Legendary'], 33.3)
        text = rod_stats.page(self.root, now=300).read_text(encoding='utf-8')
        self.assertIn('<title>Rod Lab</title>', text); self.assertIn('"rod": "Rare"', text); self.assertIn('http-equiv="refresh"', text)


if __name__ == '__main__':
    unittest.main()
