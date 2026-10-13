"""Behavioral checks for scan cost, deferred evidence and restart boundaries."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import inventory_watch as inventory
import metrics


class InventoryScheduling(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        for module in (inventory,metrics):
            patcher=patch.object(module,'RUN',self.root)
            patcher.start();self.addCleanup(patcher.stop)
        self.config={'inventory_check':True,'user_id':123,'account_username':'TestAccount','place_id':456}
        patcher=patch.object(inventory,'load_config',side_effect=lambda:dict(self.config))
        patcher.start();self.addCleanup(patcher.stop)
        patcher=patch.object(inventory,'InventoryScanner')
        self.scanners=patcher.start();self.addCleanup(patcher.stop)
        self.now=10000
        metrics.write('supervisor.json',{'started':9000})
        self.events=[]

    def watcher(self):
        # Separate scanner instances make accidental reopenings observable.
        scanner=Mock()
        scanner.scan.return_value={'Coral':3,'Worm':10}
        self.scanners.return_value=scanner
        return inventory.InventoryWatcher(Mock(),lambda event,**kw:self.events.append((event,kw)),clock=lambda:self.now)

    def test_no_periodic_scans_or_empty_round_inventory_checks(self):
        watcher=self.watcher();watcher.start()
        for _ in range(100):
            self.now+=60
            watcher.begin_round();watcher.observe_unconfirmed('','empty')
            watcher.observe('Coral X1','','known')
            self.assertIsNone(watcher.check_pending());watcher.end_round()
        self.assertEqual(watcher.scanner.scan.call_count,1)
        watcher.scanner.scan.assert_called_with(max_seconds=20)

    def test_unknown_waits_ten_minutes_known_catches_are_subtracted(self):
        watcher=self.watcher();watcher.start();watcher.begin_round()
        watcher.observe('Coral X1','','known')
        watcher.observe_unconfirmed('Zebra Fish T Collect','missing')
        watcher.scanner.scan.return_value={'Coral':4,'Worm':8,'Zebra Fish':1}
        for seconds in (1,100,599):
            self.now=10000+seconds
            self.assertIsNone(watcher.check_pending())
        self.assertEqual(watcher.scanner.scan.call_count,1)
        self.now=10600
        self.assertEqual(watcher.check_pending(),{'item':'Zebra Fish','quantity':1})
        self.assertIsNone(watcher.check_pending())
        self.assertEqual(watcher.scanner.scan.call_count,2)
        self.assertEqual(sum(kind=='inventory_recovered' for kind,_ in self.events),1)

    def test_unknown_burst_does_not_overwrite_or_misallocate_catches(self):
        watcher=self.watcher();watcher.start()
        watcher.observe('??? X1','','first')
        watcher.observe('??? X2','','second')
        watcher.observe('??? X2','','second')
        self.assertEqual(len(watcher.pending),2)
        self.assertIsNone(watcher.check_pending())
        watcher.scanner.scan.return_value={'Coral':3,'Worm':8,'New Fish':3}
        self.now+=600;watcher.check_pending()
        self.assertEqual(watcher.scanner.scan.call_count,2)
        self.assertFalse(any(kind in ('inventory_resolved','inventory_recovered') for kind,_ in self.events))
        self.assertEqual(watcher.pending,[])

    def test_queue_is_bounded_and_overflow_remains_ambiguous(self):
        watcher=self.watcher();watcher.start()
        for index in range(100):watcher.observe('??? X1','',str(index))
        self.assertEqual(len(watcher.pending),32)
        self.assertTrue(watcher.overflow)
        self.now+=600;watcher.scanner.scan.return_value={'Coral':3,'Worm':8,'New Fish':1}
        watcher.check_pending()
        self.assertFalse(any(kind=='inventory_resolved' for kind,_ in self.events))

    def test_clean_restart_reuses_baseline_known_catches_and_pending(self):
        watcher=self.watcher();watcher.start();watcher.begin_round()
        watcher.observe('Coral X1','','known')
        watcher.observe_unconfirmed('Zebra Fish T Collect','missing')
        watcher.end_round();self.now+=300
        restarted=self.watcher();restarted.start()
        restarted.scanner.scan.assert_not_called()
        self.assertEqual(restarted.known,{'Coral':1})
        self.assertEqual(len(restarted.pending),1)
        self.assertIsNone(restarted.check_pending())
        self.now+=300
        restarted.scanner.scan.return_value={'Coral':4,'Zebra Fish':1,'Worm':8}
        self.assertEqual(restarted.check_pending(),{'item':'Zebra Fish','quantity':1})

    def test_interrupted_round_discards_comparison_but_keeps_cooldown(self):
        watcher=self.watcher();watcher.start();watcher.begin_round()
        watcher.observe_unconfirmed('Zebra Fish T Collect','old')
        restarted=self.watcher();restarted.start()
        restarted.scanner.scan.assert_not_called()
        self.assertIsNone(restarted.baseline)
        self.assertEqual(restarted.pending,[])
        restarted.observe_unconfirmed('Zebra Fish T Collect','new')
        self.assertIsNone(restarted.check_pending())
        self.now+=600
        restarted.scanner.scan.return_value={'Coral':3,'Worm':8,'Zebra Fish':1}
        self.assertIsNone(restarted.check_pending())
        self.assertFalse(any(kind=='inventory_recovered' for kind,_ in self.events))

    def test_new_supervisor_account_or_expired_cache_never_reuses_counts(self):
        for change in ('supervisor','account','expired'):
            with self.subTest(change=change):
                (self.root/'inventory-watch.json').unlink(missing_ok=True)
                (self.root/'inventory-baseline.json').unlink(missing_ok=True)
                watcher=self.watcher();watcher.start()
                if change=='supervisor':metrics.write('supervisor.json',{'started':self.now})
                elif change=='account':self.config['user_id']+=1
                else:self.now+=inventory.CACHE_MAX_AGE
                restarted=self.watcher();restarted.start()
                self.assertIsNone(restarted.baseline)
                restarted.scanner.scan.assert_not_called()

    def test_failures_back_off_survive_restarts_and_need_new_unknown(self):
        watcher=self.watcher();watcher.start()
        for wait in (1200,2400,3600,3600):
            self.now=watcher.next_check_at
            watcher.observe('??? X1','',str(wait))
            watcher.scanner.scan.side_effect=ValueError('Unreadable quantity')
            watcher.check_pending();watcher.end_round()
            self.assertEqual(watcher.next_check_at,self.now+wait)
            restarted=self.watcher();restarted.start()
            restarted.scanner.scan.assert_not_called()
            self.assertEqual(restarted.next_check_at,watcher.next_check_at)
            self.assertIsNone(restarted.check_pending())
            watcher=restarted

    def test_interrupted_scan_reserves_slot_before_menu_opens(self):
        watcher=self.watcher();watcher.start();watcher.begin_round()
        self.now+=600;watcher.observe('??? X1','','unknown')
        def fail(**kw):
            self.assertEqual(metrics.read('inventory-watch.json')['next_check_at'],self.now+600)
            raise RuntimeError('Roblox lost focus')
        watcher.scanner.scan.side_effect=fail
        with self.assertRaises(RuntimeError):watcher.check_pending()
        restarted=self.watcher();restarted.start()
        restarted.scanner.scan.assert_not_called()
        self.assertEqual(restarted.next_check_at,self.now+600)
        self.assertIsNone(restarted.baseline)

    def test_legacy_baseline_migration_defers_without_trusting_old_counts(self):
        metrics.write('inventory-baseline.json',{'at':self.now-100,'counts':{'Coral':3}})
        watcher=self.watcher();watcher.start()
        watcher.scanner.scan.assert_not_called()
        self.assertIsNone(watcher.baseline)
        self.assertEqual(watcher.next_check_at,self.now+500)

    def test_disabled_identification_does_no_scanning_or_checkpoint_writes(self):
        self.config['inventory_check']=False
        watcher=self.watcher();watcher.start();watcher.begin_round()
        watcher.observe('??? X1','','unknown');watcher.observe_unconfirmed('Fish T Collect','missing')
        watcher.check_pending();watcher.end_round()
        watcher.scanner.scan.assert_not_called()
        self.assertFalse((self.root/'inventory-watch.json').exists())

    def test_unsupported_inventory_is_not_reopened_and_unknown_evidence_survives(self):
        watcher=self.watcher();watcher.start();self.now+=600
        watcher.observe('??? X1','','unknown')
        def unsupported(**kw):
            metrics.write('inventory-count-evidence.json',{'at':self.now,
                'reason':'outside_first_page_limit','parsed_total':187})
            raise ValueError('Inventory is not fully visible')
        watcher.scanner.scan.side_effect=unsupported;watcher.check_pending();watcher.end_round()
        self.assertTrue(watcher.comparison_blocked)
        self.assertEqual(watcher.pending[0]['reward_id'],'unknown')
        restarted=self.watcher();self.now+=7200
        restarted.observe('??? X2','','another');restarted.check_pending();restarted.check_pending()
        restarted.scanner.scan.assert_not_called()
        self.assertEqual(len(restarted.pending),2)
        self.assertEqual(sum(kind=='inventory_comparison_deferred' for kind,_ in self.events),1)
        self.assertFalse(any(kind in ('inventory_resolved','inventory_recovered') for kind,_ in self.events))

    def test_recent_legacy_large_inventory_failure_is_scoped_to_its_run(self):
        watcher=self.watcher();watcher.failures=1;watcher.baseline=None;watcher.checkpoint()
        metrics.write('inventory-count-evidence.json',{'at':self.now-1,
            'reason':'outside_first_page_limit','parsed_total':187})
        self.assertTrue(self.watcher().comparison_blocked)
        self.config['user_id']+=1
        self.assertFalse(self.watcher().comparison_blocked)
        self.config['user_id']-=1;metrics.write('supervisor.json',{'started':self.now+1})
        self.assertFalse(self.watcher().comparison_blocked)

    def test_explicit_successful_comparison_clears_the_capacity_block(self):
        watcher=self.watcher();watcher.unsupported_total=187;watcher.unsupported_at=self.now
        self.assertEqual(watcher.snapshot('manual comparison'),{'Coral':3,'Worm':10})
        self.assertFalse(watcher.comparison_blocked)


class ScanBudget(unittest.TestCase):
    def test_expired_budget_still_closes_menu(self):
        driver=Mock(deadline=None)
        driver.capture.return_value=np.zeros((1440,2560,3),np.uint8)
        driver.text.return_value=[]
        scanner=object.__new__(inventory.InventoryScanner)
        scanner.driver=driver;scanner.progress=Mock()
        scanner.open=Mock(side_effect=ValueError('Inventory scan time budget reached'))
        scanner.inventory_count=Mock(side_effect=[66,None])
        def close(key):
            self.assertIsNone(driver.deadline)
            self.assertEqual(key,'M')
        driver.key.side_effect=close
        with self.assertRaisesRegex(ValueError,'time budget'):scanner.scan(max_seconds=20)
        driver.key.assert_called_once_with('M')
        self.assertIsNone(driver.deadline)

    def test_stop_and_focus_guards_take_priority_over_budget(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(inventory,'RUN',Path(folder)), \
                patch.object(inventory.win32gui,'IsWindow',return_value=True), \
                patch.object(inventory.win32gui,'IsIconic',return_value=False), \
                patch.object(inventory.win32gui,'GetForegroundWindow',return_value=1) as foreground, \
                patch.object(inventory.win32gui,'GetClientRect',return_value=(0,0,2560,1440)), \
                patch.object(inventory.win32gui,'ClientToScreen',return_value=(0,0)):
            user=Mock();user.GetAsyncKeyState.return_value=0
            driver=inventory.InventoryDriver(1,Mock(rect=(0,0,2560,1440)),Mock(),Mock(),Mock(),user,Mock())
            driver.deadline=0
            with self.assertRaisesRegex(ValueError,'time budget'):driver.guard()
            foreground.return_value=2
            with self.assertRaisesRegex(RuntimeError,'lost focus'):driver.guard()
            (Path(folder)/'STOP').write_text('Stopped by user')
            with self.assertRaisesRegex(RuntimeError,'Stopped by user'):driver.guard()
            driver.inp.release.assert_called()


if __name__=='__main__':unittest.main()
