import collections
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app_config
import cast_point
import control_actions
import fishing_assistant
import item_journal
import live_feed
import metrics
import rod_detector
import terminal_app
import status_view
import fishing_cli
import cv2
import numpy as np


class IsolatedState(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for module in (metrics, item_journal, live_feed, control_actions, status_view):
            patcher = patch.object(module, 'RUN', self.root)
            patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(app_config, 'CONFIG', self.root/'config.local.json')
        patcher.start(); self.addCleanup(patcher.stop)
        self.addCleanup(self.temporary.cleanup)

    def append(self, name, rows, newline=True):
        with (self.root/name).open('a', encoding='utf-8') as stream:
            stream.write('\n'.join(json.dumps(row) for row in rows)+ ('\n' if newline else ''))

    def test_live_feed_waits_for_complete_line_and_does_not_duplicate(self):
        self.append('events-test.jsonl', [{'at':11, 'event':'reward_observed','text':'Coral X2'}], False)
        feed = live_feed.LiveFeed(); feed.update(10)
        self.assertEqual(feed.rows, [])
        with (self.root/'events-test.jsonl').open('a') as stream: stream.write('\n')
        feed.update(10); feed.update(10)
        self.assertEqual(len(feed.filtered('Coral', 'Catches')), 1)
        self.assertEqual(len(feed.filtered('', 'Recovery')), 0)

    def test_feed_filters_and_bounded_history(self):
        self.append('events-test.jsonl', [{'at':11+i, 'event':'cast','cast':i} for i in range(4005)])
        self.append('recovery.jsonl', [{'at':5000,'event':'recovery_retry','reason':'Window changed'}])
        feed=live_feed.LiveFeed(); feed.update(10)
        self.assertEqual(len(feed.rows),4000)
        self.assertEqual(feed.filtered('window','Warnings')[0]['text'], 'Window changed')
        feed.update(6000)
        self.assertEqual(feed.rows, [])

    def test_journal_preserves_quantities_and_rejects_partial_prompt(self):
        self.append('events-test.jsonl', [{'at':11,'event':'reward_observed','text':'Collect'},
            {'at':12,'event':'reward_observed','text':'Coral X2'}, {'at':13,'event':'reward_observed','text':'Sea Horse NEW'}])
        journal=item_journal.Journal(); journal.update(10); journal.update(10)
        self.assertEqual(journal.counts, {'Coral':2,'Sea Horse':1})
        self.assertEqual(len(journal.items),2)

    def test_account_settings_preserve_data_location(self):
        app_config.save_config({'data_dir':'saved-run','account_username':'ExampleUser','user_id':123})
        app_config.save_config({'rod_slot':7,'auto_rod':True})
        self.assertEqual(app_config.load_config()['data_dir'],'saved-run')
        self.assertEqual(app_config.load_config()['rod_slot'],7)
        with self.assertRaises(ValueError): app_config.save_config({'rod_slot':0})

    def test_cast_point_setup_saves_manual_and_captured_coordinates(self):
        app=terminal_app.Terminal();app.switch(3)
        self.assertEqual(app.config['cast_point'],[1650,800])
        app.selection=app.settings_keys.index('Cast point');app.activate()
        app.buffer='1200, 650';app.finish_edit()
        self.assertEqual(app_config.load_config()['cast_point'],[1200,650])
        app.edit('Cast point','40, 20');app.finish_edit()
        self.assertEqual(app_config.load_config()['cast_point'],[1200,650])
        app.selection=app.settings_keys.index('Capture pointer')
        with patch.object(app,'job',side_effect=lambda fn:fn()), \
             patch.object(terminal_app,'capture_pointer',return_value=[1300,700]), \
             patch.object(terminal_app.time,'sleep'):
            app.activate()
        self.assertEqual(app_config.load_config()['cast_point'],[1300,700])

    def test_pointer_capture_scales_from_roblox_client_without_input(self):
        # A 1920 x 1080 Roblox client at a nonzero desktop origin.
        with patch.object(fishing_assistant,'find_window',return_value=14), \
             patch.object(fishing_assistant,'rectangle',return_value=(100,50,2020,1130)), \
             patch('win32gui.GetCursorPos',return_value=(1075,575)), \
             patch('win32gui.WindowFromPoint',return_value=18), \
             patch('win32gui.GetAncestor',return_value=14):
            self.assertEqual(cast_point.capture_pointer(),[1300,700])

    def test_metrics_handles_transient_windows_reader(self):
        original = metrics.os.replace
        counter = [0]
        def replace(a,b):
            counter[0]+=1
            if counter[0]<3: raise PermissionError('Reader is closing')
            return original(a,b)
        with patch.object(metrics.os,'replace',side_effect=replace): metrics.write('totals.json',{'rounds':8})
        self.assertEqual(metrics.read('totals.json')['rounds'],8)
        self.assertEqual(list(self.root.glob('*.tmp')),[])

    def test_terminal_navigation_search_and_edit_cancel(self):
        app=terminal_app.Terminal()
        app.journal.counts=collections.Counter({'Coral':4,'Ore':2})
        app.key('2'); app.key('DOWN'); app.key('ENTER')
        self.assertEqual((app.page,app.query,app.category),(2,'Ore',1))
        app.key('/'); app.key('BACKSPACE'); app.key('x'); app.key('CANCEL')
        self.assertEqual(app.query,'Ore')
        app.key('TAB'); self.assertEqual(app.page,3)
        app.key('LEFT'); self.assertEqual(app.page,2)
        app.key('q'); self.assertFalse(app.alive)

    def test_terminal_history_does_not_jump_until_follow_enabled(self):
        app=terminal_app.Terminal(); app.page=2; app.height=30
        app.feed.rows=[{'text':str(i),'at':i,'level':'normal','group':'fishing'} for i in range(100)]
        app.key('UP'); self.assertFalse(app.follow)
        position=app.scroll
        app.body(18); self.assertEqual(app.scroll,position)
        app.key('END'); self.assertTrue(app.follow)

    def test_pause_in_flight_prevents_duplicate_controller(self):
        (self.root/'STOP').write_text('Paused by user')
        with patch.object(control_actions,'alive',side_effect=lambda name='supervisor-pid.json':name=='supervisor-pid.json'), patch.object(control_actions,'starting',return_value=False), patch.object(control_actions.subprocess,'Popen') as spawn:
            result=control_actions.resume()
        self.assertIn('still finishing',result)
        spawn.assert_not_called()
        self.assertTrue((self.root/'STOP').exists())

    def test_terminal_stop_remains_available_when_busy(self):
        app=terminal_app.Terminal(); app.busy=True
        with patch.object(control_actions,'stop',return_value='Stopped') as stop:
            app.key('s'); stop.assert_called_once()

    def test_run_page_launches_each_explicit_mode_without_changing_focus_itself(self):
        app=terminal_app.Terminal()
        with patch.object(app,'job',side_effect=lambda fn:fn()), patch.object(control_actions,'resume') as resume:
            for index,mode in enumerate(('assist','spot','full')):
                app.selection=index;app.key('ENTER')
                resume.assert_called_with(mode)
            app.key('END');self.assertEqual(app.selection,5)

    def test_run_modes_and_stop_reason_are_visible_with_keyboard_scrolling(self):
        (self.root/'STOP').write_text('Stopped by F12 in Roblox')
        with patch.object(control_actions,'alive',return_value=False),patch.object(control_actions,'starting',return_value=False):
            data=status_view.snapshot()
        self.assertEqual(data['reason'],'Stopped by F12 in Roblox')
        self.assertIn('Stopped by F12 in Roblox','\n'.join(fishing_cli.status_lines(data)))
        app=terminal_app.Terminal();app.data=data
        normal='\n'.join(app.render(100,32))
        for text in ('Minigame only','Fish here','Full farmer','Stopped by F12 in Roblox'):
            self.assertIn(text,normal)
        for text in ('You cast + collect', 'You pick the spot', 'Saved spawn'):
            self.assertIn(text,normal)
        for index,label in enumerate(('Minigame only','Fish here','Full farmer','Pause','Stop','Export log')):
            app.selection=index
            self.assertIn('› '+label,'\n'.join(app.render(65,22)))

    def test_live_focus_reason_replaces_stale_stop_reason(self):
        metrics.write('status.json',{'wait_reason':'Waiting for Roblox','reason':'Old error'})
        metrics.write('supervisor.json',{'mode':'assist','stage':'paused_focus'})
        with patch.object(control_actions,'alive',return_value=True),patch.object(control_actions,'starting',return_value=False):
            data=status_view.snapshot()
        self.assertEqual(data['reason'],'Waiting for Roblox')
        self.assertEqual(data['state'],'Waiting for Roblox')

    def test_bait_setting_retains_hook_counters(self):
        metrics.write('totals.json',{'rounds':17})
        app=terminal_app.Terminal(); app.edit('Bait left','50'); app.finish_edit()
        self.assertEqual(metrics.read('bait.json')['starting_stock'],67)
        self.assertEqual(metrics.read('totals.json')['rounds'],17)


class VisionAndInput(unittest.TestCase):
    def test_rod_selected_ring_and_unselected_icon(self):
        icon=cv2.imread(str(app_config.ROOT/'assets'/'rod-icon.png'))
        frame=np.full((1440,2560,3), (30,20,10),dtype=np.uint8)
        frame[1366:1366+icon.shape[0],1440:1440+icon.shape[1]]=icon
        result=rod_detector.locate_rod(frame)
        self.assertIsNotNone(result); self.assertFalse(result['equipped'])
        cv2.circle(frame,(1470,1385),39,(190,190,190),2)
        result=rod_detector.locate_rod(frame)
        self.assertTrue(result['equipped'])

    def test_no_new_press_after_focus_changes_but_release_allowed(self):
        with patch.object(fishing_assistant.win32gui,'IsWindow',return_value=True), patch.object(fishing_assistant.win32gui,'IsIconic',return_value=False), patch.object(fishing_assistant.win32gui,'GetForegroundWindow',return_value=2), patch.object(fishing_assistant,'USER') as user:
            inp=fishing_assistant.Input(1)
            with self.assertRaises(RuntimeError): inp.hold(True)
            with self.assertRaises(RuntimeError): inp.grab(True)
            user.mouse_event.assert_not_called(); user.keybd_event.assert_not_called()
            inp.mouse=True; inp.hold(False)
            user.mouse_event.assert_called_once()

    def test_reward_detection_excludes_collect_and_wall_climb(self):
        for text in ('Collect','llect','T Wall Climb','Wall Climb X1'):
            self.assertFalse(fishing_assistant.is_reward_banner(text))
        self.assertTrue(fishing_assistant.is_reward_banner('OuwFish X1'))


if __name__=='__main__': unittest.main()
