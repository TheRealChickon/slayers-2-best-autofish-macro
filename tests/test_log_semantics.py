import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fishing_cli
import item_journal
import live_feed


class LogSemantics(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        for module in (item_journal,live_feed):
            patcher=patch.object(module,'RUN',self.root)
            patcher.start();self.addCleanup(patcher.stop)
        self.at=10

    def append(self,*kinds):
        with (self.root/'recovery.jsonl').open('a') as stream:
            for kind in kinds:
                self.at+=1
                stream.write(json.dumps({'at':self.at,'event':kind})+'\n')

    def test_five_join_holds_count_once_and_rod_only_resume_does_not(self):
        journal=item_journal.Journal()
        self.append('recovery_started','equipped_rod')
        journal.update(10)
        self.assertEqual(journal.joins-1,0)
        self.append('recovery_started',*(['hold_private_join']*5))
        journal.update(10)
        self.assertEqual(journal.joins-1,0)
        self.append('equipped_rod','recovery_started','rod_already_equipped','equipped_rod')
        journal.update(10);journal.update(10)
        self.assertEqual(journal.joins-1,1)
        rebuilt=item_journal.Journal();rebuilt.update(10)
        self.assertEqual(rebuilt.joins,journal.joins)
        self.assertEqual(journal.launches,0)

    def test_restart_then_ready_counts_once_and_aborted_join_is_not_carried(self):
        journal=item_journal.Journal()
        self.append('hold_private_join','equipped_rod','launching_game','recovery_started','equipped_rod')
        journal.update(10)
        self.assertEqual(journal.joins-1,1)
        self.assertEqual(journal.launches,1)
        self.append('hold_private_join','supervisor_stopped','recovery_started','equipped_rod')
        journal.update(10)
        self.assertEqual(journal.joins-1,1)

    def test_live_feed_keeps_actions_without_repeating_screen_observations(self):
        self.append('recovery_started',*(['screen']*30),'play','hold_private_join','equipped_rod')
        raw=(self.root/'recovery.jsonl').read_bytes()
        feed=live_feed.LiveFeed();feed.update(10);feed.update(10)
        self.assertEqual([r['kind'] for r in feed.rows],['recovery_started','play','hold_private_join','equipped_rod'])
        self.assertEqual((self.root/'recovery.jsonl').read_bytes(),raw)

    def test_semantic_colors_work_for_recovery_retries_failures_and_catches(self):
        for kind,message,expected in (
                ('play','Play','cyan'),('hold_private_join','Hold Join','cyan'),
                ('recovery_retry','Window changed','gold'),
                ('worker_exit','Non-fishing interaction replaced pickup','red'),
                ('worker_exit','Stopped by stop file','gold'),
                ('equipped_rod','Game ready','green'),('reward_observed','Coral X1','green')):
            with self.subTest(kind=kind,message=message):
                row={'at':11,'kind':kind,'message':message,'group':'recovery'}
                self.assertEqual(live_feed.event_tone(row),expected)
                self.assertIn(f'\033[{fishing_cli.COLORS[expected]}m',fishing_cli.log_line(row,activity=True,colors=True))
                self.assertNotIn('\033',fishing_cli.log_line(row,activity=True,colors=False))
        self.assertEqual(live_feed.state_tone('Recovering'),'cyan')
        self.assertEqual(live_feed.state_tone('Fishing'),'green')
        self.assertEqual(live_feed.state_tone('Waiting for Roblox'),'gold')


if __name__=='__main__':unittest.main()
