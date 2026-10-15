import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import cv2
import numpy as np
from inventory_watch import reconcile, InventoryScanner, InventoryWatcher
import inventory_watch
from rapidocr_onnxruntime import RapidOCR
from item_journal import Journal
import item_journal
from item_names import inventory_name
from screen_space import ScreenSpace
from fishing_assistant import detect
import fishing_assistant
import recovery
import presence_watch


class InventoryReconciliation(unittest.TestCase):
    def test_prompt_without_banner_is_confirmed_by_inventory_once(self):
        watcher=object.__new__(InventoryWatcher)
        watcher.enabled=True;watcher.pending=[];watcher.baseline={'Coral':3,'Worm':10}
        watcher.overflow=False;watcher.next_check_at=0;watcher.clock=lambda:100;watcher.checkpoint=Mock()
        watcher.known={'Coral':1};watcher.snapshot=lambda reason:{'Coral':4,'Worm':8,'Zebra Fish':1}
        events=[];watcher.event=lambda kind,**kw:events.append((kind,kw))
        watcher.observe_unconfirmed('Zebra Fish T Collect','session:4:inventory')
        with patch.object(inventory_watch,'write'):
            self.assertEqual(watcher.check_pending(),{'item':'Zebra Fish','quantity':1})
            self.assertIsNone(watcher.check_pending())
        self.assertEqual(events[0][0],'inventory_recovered')
        self.assertEqual(events[0][1]['raw'],'Zebra Fish T Collect')
        with tempfile.TemporaryDirectory() as folder,patch.object(item_journal,'RUN',Path(folder)):
            row=dict(events[0][1],event=events[0][0],at=11)
            (Path(folder)/'events-test.jsonl').write_text((json.dumps(row)+'\n')*2)
            journal=Journal();journal.update(10)
            self.assertEqual(dict(journal.counts),{'Zebra Fish':1})
            self.assertEqual(journal.items[0]['source'],'inventory')

    def test_known_catches_and_consumed_bait_do_not_hide_unknown(self):
        self.assertEqual(reconcile({'Coral':12,'Fishing Bait':30},{'Coral':15,'Ore':1,'Fishing Bait':26},{'Coral':3},1),'Ore')
        self.assertEqual(reconcile({'Worm':8},{'Worm':7,'Sea Horse':1},{},1),'Sea Horse')

    def test_missing_items_extra_gains_and_wrong_quantity_remain_unknown(self):
        for before,after,known,qty in [({'Coral':3},{'Coral':2,'Ore':1},{},1),
            ({},{'Ore':1,'Coral':1},{},1),({},{'Ore':2},{},1),({'Coral':3},{'Coral':3},{},1)]:
            self.assertIsNone(reconcile(before,after,known,qty))
        self.assertIsNone(reconcile({}, {'Inventory icon abc (partial)':1}, {}, 1))

    def test_inventory_title_correction_requires_unique_known_match(self):
        self.assertEqual(inventory_name('Golden F Fish'),'Golden Fish')
        self.assertEqual(inventory_name('Zebra F Fish'),'Zebra Fish')
        self.assertEqual(inventory_name('New Unfamiliar Artifact'),'New Unfamiliar Artifact')
        self.assertEqual(inventory_name('Refinement Ore'),'Refinement Ore')

    def test_journal_correction_is_idempotent_and_preserves_original_evidence(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(item_journal,'RUN',Path(folder)):
            path=Path(folder)/'events-test.jsonl'
            reward={'event':'reward_observed','at':11,'text':'??? X2','reward_id':'test:1'}
            correction={'event':'inventory_resolved','at':12,'item':'New Fish','quantity':2,'reward_id':'test:1'}
            path.write_text(json.dumps(reward)+'\n'+json.dumps(correction)+'\n')
            journal=Journal();journal.update(10);journal.update(10)
            self.assertEqual(dict(journal.counts),{'New Fish':2})
            self.assertEqual(len(journal.items),1)
            self.assertEqual(journal.items[0]['raw'],'??? X2')
            rebuilt=Journal();rebuilt.update(10)
            self.assertEqual(rebuilt.counts,journal.counts)

    def test_quantity_requires_agreement_and_explicit_multiplication_label(self):
        class Driver:
            def __init__(self,values):self.values=iter(values)
            def text(self,*args,**kw):return [[[],next(self.values),.75]]
        icon=np.full((88,88,3),255,dtype=np.uint8)
        scanner=object.__new__(InventoryScanner)
        for words,expected in [(('X6','X6'),6),(('X6','X8'),None),(('+6','6'),None)]:
            scanner.driver=Driver(words)
            self.assertEqual(scanner.stack_count(icon),expected)

    def test_inventory_progress_prevents_false_presence_recovery(self):
        self.assertFalse(presence_watch.recovery_needed({'ok':True,'type':0},1,
            {'running':True,'stage':'fishing'}, {'stage':'inventory','updated':99,'last_game_activity':1},100))


class Resolution(unittest.TestCase):
    def test_click_is_blocked_when_cursor_is_over_another_window(self):
        with patch.object(fishing_assistant.win32gui,'IsWindow',return_value=True),patch.object(fishing_assistant.win32gui,'IsIconic',return_value=False),patch.object(fishing_assistant.win32gui,'GetForegroundWindow',return_value=1),patch.object(fishing_assistant.win32gui,'GetCursorPos',return_value=(20,20)),patch.object(fishing_assistant.win32gui,'WindowFromPoint',return_value=2),patch.object(fishing_assistant.win32gui,'GetAncestor',return_value=2),patch.object(fishing_assistant,'USER') as user:
            with self.assertRaises(RuntimeError):fishing_assistant.Input(1).hold(True)
            user.mouse_event.assert_not_called()

    def test_recovery_does_not_replace_an_existing_stop_reason(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(recovery,'USER') as user:
            user.GetAsyncKeyState.return_value=0
            driver=object.__new__(recovery.Recovery);driver.stop=Path(folder)/'STOP';driver.inp=Mock()
            driver.stop.write_text('Stopped by user')
            with self.assertRaises(recovery.UserStop):driver.check_stop()
            self.assertEqual(driver.stop.read_text(),'Stopped by user')

    def test_real_selected_border_and_count_badges_at_1080p(self):
        fixtures=Path(__file__).parent/'fixtures'
        selected=cv2.imread(str(fixtures/'selected-1080.png'))
        other=cv2.imread(str(fixtures/'unselected-1080.png'))
        self.assertTrue(InventoryScanner.selected(selected,4,4))
        self.assertFalse(InventoryScanner.selected(other,4,4))
        ocr=RapidOCR()
        class Driver:
            def text(self,image,min_confidence=.8):
                rows,_=ocr(image,use_cls=False)
                return [row for row in rows or [] if row[2]>min_confidence]
        scanner=object.__new__(InventoryScanner);scanner.driver=Driver()
        for file,amount in [('count-9-1080',9),('count-888-1080',888),('unstacked-clothing-1080',1)]:
            self.assertEqual(scanner.stack_count(cv2.imread(str(fixtures/(file+'.png')))),amount,file)

    def test_full_hd_and_offset_client_coordinates(self):
        screen=ScreenSpace((100,200,2020,1280))
        self.assertEqual(screen.point(1280,720),(1060,740))
        self.assertEqual(screen.point(0,0),(100,200))
        with self.assertRaises(ValueError):ScreenSpace((0,0,1280,1024))

    def test_minigame_survives_normalization_at_common_sizes(self):
        reference=np.zeros((1440,2560,3),np.uint8)
        cv2.rectangle(reference,(1875,590),(1940,690),(20,190,30),-1)
        cv2.circle(reference,(1914,640),12,(245,245,245),-1)
        for width,height in [(1280,720),(1920,1080),(2560,1440),(3840,2160)]:
            pixels=cv2.resize(reference,(width,height))
            class Capture:
                def grab(self,region):
                    x,y=region['left'],region['top']
                    return pixels[y:y+region['height'],x:x+region['width']]
            region=ScreenSpace((0,0,width,height)).capture(Capture(),(1850,400,140,600))
            result=detect(region)
            self.assertIsNotNone(result,(width,height))
            self.assertTrue(result['inside'])
            self.assertAlmostEqual(result['ball'],240,delta=2)


if __name__=='__main__':unittest.main()
