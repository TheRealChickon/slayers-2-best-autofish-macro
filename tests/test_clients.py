import collections
import datetime
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
    def session_fixture(self):
        metrics.write('totals.json',{'started':1,'casts':100,'rounds':99,'rewards':90,'active_seconds':500})
        metrics.write('current-run.json',{'id':'current-session','started':100,'ended':200})
        self.append('events-20261011-010000.jsonl',[
            {'at':50,'event':'reward_observed','text':'Ore X3','cycle':1},
            {'at':105,'event':'started'},
            {'at':106,'event':'cast','cast':1},
            {'at':106.5,'event':'cast','cast':1},
            {'at':107,'event':'minigame','cycle':1},
            {'at':107.5,'event':'minigame','cycle':1},
            {'at':108,'event':'reward_observed','text':'Coral X2','cycle':2},
            {'at':108.5,'event':'reward_observed','text':'Coral X2','cycle':2},
            {'at':110,'event':'input_paused'},
            {'at':120,'event':'input_resumed'},
            {'at':130,'event':'stopped'},
            {'at':250,'event':'reward_observed','text':'ClownFish X9','cycle':3}])
        self.append('events-20261011-020000.jsonl',[
            {'at':140,'event':'started'},
            {'at':141,'event':'cast','cast':1},
            {'at':142,'event':'minigame','cycle':1},
            {'at':143,'event':'reward_observed','text':'GoldenFish X1','cycle':1},
            {'at':145,'event':'stopped'}])

    def test_t_toggles_only_catches_without_changing_run_logs_or_game_controls(self):
        self.session_fixture()
        before={p:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        app=terminal_app.Terminal();app.refresh()
        self.assertFalse(app.show_total)
        self.assertEqual(sum(qty for _,qty in app.item_rows()),3)
        self.assertTrue(all(100<=r['at']<=200 for r in app.feed.rows))
        original_stats={k:app.data[k] for k in ('hooks','casts','collections','active_seconds')}
        original_logs=list(app.feed.rows)
        with patch.object(control_actions,'resume') as resume,patch.object(control_actions,'pause') as pause,patch.object(control_actions,'stop') as stop:
            for page in (0,2):
                app.switch(page);app.key('t')
                self.assertFalse(app.show_total)
            app.switch(1);app.key('T')
            self.assertTrue(app.show_total)
            self.assertEqual(sum(qty for _,qty in app.item_rows()),15)
            self.assertIn('TOTAL','\n'.join(app.body(20)))
            self.assertEqual(original_stats,{k:app.data[k] for k in original_stats})
            self.assertEqual(original_logs,app.feed.rows)
            app.key('t')
            self.assertFalse(app.show_total)
            self.assertEqual(sum(qty for _,qty in app.item_rows()),3)
            self.assertEqual(original_logs,app.feed.rows)
            resume.assert_not_called();pause.assert_not_called();stop.assert_not_called()
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertFalse(terminal_app.Terminal().show_total)

    def test_session_journal_stops_at_end_and_can_switch_back_to_total(self):
        self.session_fixture()
        journal=item_journal.Journal();journal.update(100,200);journal.update(100,200)
        self.assertEqual(len(journal.items),2)
        journal.update(1)
        self.assertEqual(len(journal.items),4)
        journal.update(100,200)
        self.assertEqual(len(journal.items),2)

    def test_overnight_defaults_on_and_preserves_a_saved_off(self):
        self.assertTrue(app_config.load_config()['overnight_enabled'])
        self.assertTrue(app_config.load_config()['overnight_auto_enable_idle'])
        app_config.save_config({'overnight_enabled':False,'overnight_auto_enable_idle':False})
        self.assertFalse(app_config.load_config()['overnight_enabled'])
        self.assertFalse(app_config.load_config()['overnight_auto_enable_idle'])

    def test_overnight_switches_back_on_once_for_an_older_saved_off(self):
        app_config.CONFIG.write_text(json.dumps({'overnight_enabled':False,'overnight_auto_enable_idle':False}))
        config=app_config.load_config()
        self.assertTrue(config['overnight_enabled']);self.assertTrue(config['overnight_auto_enable_idle'])
        app_config.save_config({'overnight_enabled':False})
        self.assertFalse(app_config.load_config()['overnight_enabled'])

    def test_log_navigation_reaches_last_row_without_enabling_follow(self):
        app=terminal_app.Terminal();app.page=2;app.height=22;app.follow=False
        app.feed.rows=[{'text':f'entry-{i}','at':i,'level':'normal','group':'fishing'} for i in range(100)]
        for _ in range(120):app.key('DOWN')
        lines=[terminal_app.ANSI.sub('',line) for line in app.body(10)]
        self.assertIn('entry-99',lines[-1]);self.assertEqual(app.scroll,92)
        self.assertFalse(app.follow);self.assertIn('Rows 93–100 of 100',lines[1])
        app.key('PGUP');self.assertEqual(app.scroll,84)
        lines=[terminal_app.ANSI.sub('',line) for line in app.body(10)]
        self.assertIn('8 newer',lines[1])
        app.key('PGDN');self.assertEqual(app.scroll,92)

    def test_finished_run_keeps_browsing_anchor_when_full_archive_is_loaded(self):
        metrics.write('totals.json',{'started':10})
        metrics.write('current-run.json',{'id':'run-1','started':10,'ended':None})
        self.append('events-test.jsonl',[{'at':11+i,'event':'cast','cast':i} for i in range(4005)])
        app=terminal_app.Terminal();app.page=2;app.refresh();app.follow=False;app.scroll=100
        anchor=app.feed.rows[app.scroll]['id']
        metrics.write('current-run.json',{'id':'run-1','started':10,'ended':5000})
        app.refresh()
        self.assertEqual(len(app.feed.rows),4005)
        self.assertEqual(app.feed.rows[app.scroll]['id'],anchor)
        self.assertFalse(app.follow)
        self.assertTrue(all(10<=r['at']<=5000 for r in app.feed.rows))
        self.assertIn('Finished',terminal_app.ANSI.sub('',app.body(18)[1]))

    def test_new_current_run_returns_to_follow_and_excludes_previous_logs(self):
        metrics.write('totals.json',{'started':10})
        metrics.write('current-run.json',{'id':'old','started':10,'ended':None})
        self.append('events-test.jsonl',[{'at':11+i,'event':'cast','cast':i} for i in range(30)])
        app=terminal_app.Terminal();app.refresh();app.follow=False;app.scroll=12
        metrics.write('totals.json',{'started':100})
        metrics.write('current-run.json',{'id':'new','started':100,'ended':None})
        self.append('events-test.jsonl',[{'at':101,'event':'cast','cast':1}])
        app.refresh()
        self.assertTrue(app.follow);self.assertEqual(app.scroll,0)
        self.assertTrue(all(r['at']>=100 for r in app.feed.rows))

    def test_previous_run_selector_skips_duplicate_current_run(self):
        from discord_hourly import atomic_json
        for run_id,at in [('old',10),('new',20)]:
            atomic_json(self.root/'runs'/run_id/'run.json',{'id':run_id,'started':at,'ended':at+5})
        metrics.write('current-run.json',{'id':'new','started':20,'ended':25})
        app=terminal_app.Terminal();app.page=2;app.data={'log_run':{'id':'new'}}
        app.key('r');self.assertEqual(app.log_run_id,'old')
        app.key('r');self.assertEqual(app.log_run_id,'current')

    def test_inventory_quantity_is_a_warning_without_inflating_journal(self):
        self.append('events-test.jsonl',[{'at':11,'event':'reward_observed','text':'X2964 Bait'},
                    {'at':12,'event':'reward_observed','text':'Coral X2'}])
        before=(self.root/'events-test.jsonl').read_bytes()
        journal=item_journal.Journal();journal.update(10)
        self.assertEqual(journal.counts,{'Coral':2})
        feed=live_feed.LiveFeed();feed.update(10)
        self.assertEqual(len(feed.filtered('','Catches')),1)
        warnings=feed.filtered('','Warnings')
        self.assertEqual(len(warnings),1)
        self.assertIn('Ignored unconfirmed reward read',warnings[0]['text'])
        self.assertEqual((self.root/'events-test.jsonl').read_bytes(),before)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for module in (metrics, item_journal, live_feed, control_actions, status_view):
            patcher = patch.object(module, 'RUN', self.root)
            patcher.start(); self.addCleanup(patcher.stop)
        patcher=patch.object(terminal_app,'data_directory',return_value=self.root)
        patcher.start();self.addCleanup(patcher.stop)
        patcher = patch.object(app_config, 'CONFIG', self.root/'config.local.json')
        patcher.start(); self.addCleanup(patcher.stop)
        # Answer the first-run gamepass question so Terminal() opens on its pages.
        patcher = patch.dict(app_config.DEFAULTS, {'spawn_gamepass': True})
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
        app.catch_journal.counts=collections.Counter({'Coral':4,'Ore':2})
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

    def test_prediction_page_scrolls_to_values_and_duration_is_read_only(self):
        import catch_predictions
        rows=[{'at':0,'event':'started','source':'events-20261009-010000.jsonl'},
              {'at':900,'event':'stopped','source':'events-20261009-010000.jsonl'}]
        rows.extend({'at':i,'event':'reward_observed','source':'events-20261009-010000.jsonl',
                     'cycle':i,'text':'Item '+str(i)+' X1'} for i in range(1,26))
        app=terminal_app.Terminal();app.switch(4);app.height=22
        app.predictions=catch_predictions.calculate(rows,{'id':'test','started':0,'ended':900})
        app.key('END');self.assertGreater(app.scroll,0)
        self.assertIn('Actual sold proceeds','\n'.join(app.body(10)))
        app.key('HOME');self.assertEqual(app.scroll,0)
        with patch.object(control_actions,'resume') as resume,patch.object(terminal_app,'save_config') as save:
            app.key('h');app.buffer='12';app.finish_edit()
            self.assertEqual(app.prediction_hours,12);resume.assert_not_called();save.assert_not_called()

    def test_pause_in_flight_prevents_duplicate_controller(self):
        (self.root/'STOP').write_text('Paused by user')
        with patch.object(control_actions,'alive',side_effect=lambda name='supervisor-pid.json':name=='supervisor-pid.json'), patch.object(control_actions,'starting',return_value=False), patch.object(control_actions.subprocess,'Popen') as spawn:
            result=control_actions.resume()
        self.assertIn('still finishing',result)
        spawn.assert_not_called()
        self.assertTrue((self.root/'STOP').exists())

    def test_combat_modes_are_rejected_before_starting_input(self):
        with patch.object(control_actions.subprocess, 'Popen') as spawn:
            for mode in ('damage', 'boss'):
                with self.assertRaisesRegex(ValueError, 'Unknown controller mode'):
                    control_actions.resume(mode)
            spawn.assert_not_called()

    def test_old_boss_settings_migrate_to_fishing_without_resetting_data_or_titles(self):
        app_config.CONFIG.write_text(json.dumps({'mode': 'boss', 'boss': {'invalid': True},
            'data_dir': 'saved-run', 'auto_fishing_titles': True}))
        values = app_config.load_config()
        self.assertEqual(values['mode'], 'full')
        self.assertEqual(values['data_dir'], 'saved-run')
        self.assertTrue(values['auto_fishing_titles'])
        self.assertNotIn('boss', values)

    def test_running_peer_blocks_start_without_clearing_manual_stop(self):
        (self.root/'STOP').write_text('Stopped by user')
        peer = self.root/'sanemi'; peer.mkdir()
        (peer/'supervisor-pid.json').write_text(json.dumps({'pid': 555, 'created': 123}))
        app_config.save_config({'peer_data_dir': str(peer)})
        with patch.object(control_actions.psutil, 'Process') as process, \
             patch.object(control_actions.subprocess, 'Popen') as spawn:
            process.return_value.create_time.return_value = 123
            with self.assertRaisesRegex(RuntimeError, 'other Slayers 2 macro'):
                control_actions.resume('full')
            spawn.assert_not_called()
        self.assertEqual((self.root/'STOP').read_text(), 'Stopped by user')

    def test_timed_full_farmer_stops_at_local_clock_today(self):
        fixed=datetime.datetime(2026,9,27,3,50,tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
        class Clock(datetime.datetime):
            @classmethod
            def now(cls,tz=None):return fixed
        with patch.object(control_actions.datetime,'datetime',Clock):
            self.assertEqual(control_actions.seconds_until_local_clock('22:00'),18*3600+10*60)
            with self.assertRaisesRegex(ValueError,'later today'):
                control_actions.seconds_until_local_clock('03:00')
            with self.assertRaisesRegex(ValueError,'HH:MM'):
                control_actions.seconds_until_local_clock('tomorrow')
        parsed=fishing_cli.parser().parse_args(['continue','--mode','full','--until','22:00'])
        self.assertEqual(parsed.until,'22:00')
        with self.assertRaisesRegex(ValueError,'Full farmer only'):
            control_actions.resume('assist','22:00')

    def test_terminal_stop_remains_available_when_busy(self):
        app=terminal_app.Terminal(); app.busy=True
        with patch.object(control_actions,'stop',return_value='Stopped') as stop:
            app.key('s'); stop.assert_called_once()

    def test_first_run_gamepass_prompt_answers_and_still_allows_stop(self):
        with patch.dict(app_config.DEFAULTS, {'spawn_gamepass': None}):
            app=terminal_app.Terminal()
            self.assertIn('FIRST-TIME SETUP', '\n'.join(app.gamepass_question()))
            with patch.object(control_actions,'stop',return_value='Stopped') as stop:
                app.key('s'); stop.assert_called_once()
            app.key('x'); self.assertIsNone(app.config['spawn_gamepass'])
            app.key('n'); self.assertFalse(app.config['spawn_gamepass'])
            self.assertEqual(app_config.load_config()['mode'], 'here')

    def test_gamepass_yes_asks_for_the_roblox_username_and_saves_it_locally(self):
        with patch.dict(app_config.DEFAULTS, {'spawn_gamepass': None}):
            app=terminal_app.Terminal()
            app.key('y')
            self.assertTrue(app.ask_username)
            screen='\n'.join(terminal_app.ANSI.sub('',line) for line in app.render(120,35))
            self.assertIn('Roblox username', screen)
            for letter in 'Builder_1': app.key(letter)
            with patch.object(app,'job',side_effect=lambda fn:fn()),\
                    patch.object(terminal_app,'resolve_account',return_value={'account_username':'Builder_1','user_id':42}) as resolve:
                app.key('ENTER')
            resolve.assert_called_once_with('Builder_1')
            self.assertFalse(app.ask_username)
            saved=app_config.load_config()
            self.assertEqual((saved['account_username'],saved['user_id'],saved['mode']),('Builder_1',42,'full'))

    def test_username_step_can_be_skipped_and_is_not_asked_without_the_gamepass(self):
        with patch.dict(app_config.DEFAULTS, {'spawn_gamepass': None}):
            app=terminal_app.Terminal()
            app.key('y'); app.key('CANCEL')
            self.assertFalse(app.ask_username); self.assertIsNone(app.editing)
            self.assertEqual(app_config.load_config()['account_username'],'')
            other=terminal_app.Terminal(); other.config['spawn_gamepass']=None
            other.key('n')
            self.assertFalse(other.ask_username); self.assertIsNone(other.editing)

    def test_run_page_leads_with_full_farmer_and_keeps_other_modes_one_level_down(self):
        app=terminal_app.Terminal()
        with patch.object(app,'job',side_effect=lambda fn:fn()), patch.object(control_actions,'resume') as resume,\
                patch.object(control_actions,'restart_full') as restart,patch.object(control_actions,'focus_game') as focus:
            app.selection=0;app.key('ENTER');resume.assert_called_with('full')
            app.selection=3;app.key('ENTER');restart.assert_called_once_with()
            app.key('END');self.assertEqual(app.selection,5)
            app.key('ENTER');self.assertTrue(app.show_other_modes)
            for offset,mode in enumerate(('here','spot','assist','rejoin')):
                app.selection=6+offset;app.key('ENTER');resume.assert_called_with(mode)
            app.key('END');self.assertEqual(app.selection,10)
            self.assertEqual(resume.call_count,5);focus.assert_not_called()

    def test_buy_bait_now_pauses_a_running_farmer_before_launching(self):
        app=terminal_app.Terminal()
        live=[True,True,False]
        with patch.object(control_actions,'alive',side_effect=lambda *a:live.pop(0) if live else False),\
                patch.object(control_actions,'starting',return_value=False),\
                patch.object(control_actions,'pause') as pause,patch('bait_buy.launch',return_value='launched') as launch:
            self.assertEqual(app.buy_bait_now(),'launched')
        pause.assert_called_once();launch.assert_called_once()

    def test_run_modes_and_stop_reason_are_visible_with_keyboard_scrolling(self):
        (self.root/'STOP').write_text('Stopped by F12 in Roblox')
        with patch.object(control_actions,'alive',return_value=False),patch.object(control_actions,'starting',return_value=False):
            data=status_view.snapshot()
        self.assertEqual(data['reason'],'Stopped by F12 in Roblox')
        self.assertIn('Stopped by F12 in Roblox','\n'.join(fishing_cli.status_lines(data)))
        app=terminal_app.Terminal();app.data=data
        normal='\n'.join(app.render(100,32))
        for text in ('Start Full farmer','Other modes','Full farmer','Stopped by F12 in Roblox','RECENT'):
            self.assertIn(text,normal)
        app.show_other_modes=True
        for index,(label,_,_,_) in enumerate(app.run_actions()):
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
