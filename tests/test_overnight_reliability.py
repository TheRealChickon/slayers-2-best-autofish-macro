import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import discord_hourly as discord
import live_feed
import run_log
from screen_space import ScreenSpace
from pickup_policy import PickupGate,Pickup,clear_collect
from tracking_watchdog import TrackingWatchdog
from overnight_watch import Watcher
from unattended_focus import allowed,PhysicalActivity
from pickup_policy import RewardGate
from farm_policy import HereRecovery,startup_rejoin
from overnight_guard import can_restart
import capture_session
import numpy as np
from display_repair import DisplayRepair


class Reliability(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)

    def rows(self,name,rows):
        (self.root/name).write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')

    def test_1440p_fullscreen_and_window_borders(self):
        for rect in ((0,0,2560,1440),(8,31,2552,1400),(8,31,1912,1020)):
            s=ScreenSpace(rect)
            self.assertEqual(s.point(1280,720),(round((rect[0]+rect[2])/2),round((rect[1]+rect[3])/2)))
        with self.assertRaises(ValueError):ScreenSpace((0,0,1280,1024))

    def test_two_observations_even_when_ocr_is_slow(self):
        gate=PickupGate();evidence=Pickup('collect','Collect',(1320,700))
        self.assertFalse(gate.observe(evidence,10,2))
        self.assertTrue(gate.observe(evidence,13,2.5))
        self.assertFalse(gate.observe(Pickup('collect','Collect',(1700,700)),14,.2))

    def test_explicit_t_and_collect_cannot_authorize_wall_or_faraway_key(self):
        rows=[{'text':'T','score':.99,'center':(1300,700)},
              {'text':'Collect','score':.99,'center':(1380,700)}]
        self.assertTrue(clear_collect(rows))
        self.assertFalse(clear_collect(rows[1:]))
        self.assertFalse(clear_collect([{**rows[0],'center':(100,100)},rows[1]]))
        self.assertFalse(clear_collect(rows+[{'text':'Wall Climb','score':.99,'center':(1350,710)}]))

    def test_frozen_recorded_markers_recover_without_waiting_75_seconds(self):
        watch=TrackingWatchdog();d={'ball':453,'target':444.5,'height':53,'ball_height':32}
        self.assertFalse(watch.observe(d,100));self.assertFalse(watch.observe(d,111.9))
        self.assertTrue(watch.observe(d,112))
        self.assertFalse(watch.observe({**d,'ball':455},113))

    def test_long_moving_round_and_focus_reset_are_not_stalls(self):
        watch=TrackingWatchdog()
        for now in range(200):
            self.assertFalse(watch.observe({'ball':200+now%2*5,'target':250,'height':54,'ball_height':31},now))
        watch.reset();self.assertFalse(watch.observe({'ball':200,'target':250,'height':54,'ball_height':31},500))

    def test_run_archive_excludes_previous_and_future_events(self):
        self.rows('events-test.jsonl',[{'at':9,'event':'cast'},{'at':11,'event':'cast'},{'at':31,'event':'cast'}])
        with patch('run_log.time.time',return_value=10):run=run_log.begin(self.root)
        run_log.finish(self.root,'Stopped by user',30)
        path=self.root/'runs'/run['id']/'events.jsonl'
        self.assertEqual([r['at'] for r in map(json.loads,path.read_text().splitlines())],[11])
        self.assertEqual(run_log.list_runs(self.root)[0]['ended'],30)
        with patch('run_log.time.time',return_value=40):resumed=run_log.begin(self.root,resume=True)
        self.assertEqual(resumed['id'],run['id']);self.assertIsNone(resumed['ended'])

    def test_archived_feed_has_all_rows_and_an_upper_bound(self):
        self.rows('events-test.jsonl',[{'at':11+i,'event':'cast'} for i in range(5000)]+[{'at':9000,'event':'cast'}])
        with patch.object(live_feed,'RUN',self.root):
            feed=live_feed.LiveFeed();feed.update(10,ended=6000)
        self.assertEqual(len(feed.rows),5000)

    def test_discord_current_run_never_includes_prior_session(self):
        discord.atomic_json(self.root/'current-run.json',{'id':'run-new','started':100,'ended':None})
        self.rows('events-test.jsonl',[{'at':50,'event':'reward_observed','text':'Ore X9'},
                    {'at':110,'event':'reward_observed','text':'Coral X1'}])
        result=discord.summarize(self.root,0,200,now=200)
        self.assertEqual(result['start'],100);self.assertEqual(result['items'],{'Coral':1})
        self.assertEqual(result['totals']['rewards'],1)

    def test_multiple_webhook_attachments_and_empty_204(self):
        class Response(io.BytesIO):
            status=204
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        with patch.object(discord.urllib.request,'urlopen',return_value=Response(b'')) as send:
            self.assertEqual(discord.request_webhook('https://discord.com/api/webhooks/123/test',
                {'embeds':[]},b'jpeg',attachments=[('run-events.jsonl','application/x-ndjson',b'{"event":"cast"}\n')]),(204,None))
        data=send.call_args.args[0].data
        self.assertIn(b'files[1]',data);self.assertIn(b'run-events.jsonl',data)

    def test_discord_retry_after_is_retained(self):
        error=discord.urllib.error.HTTPError('redacted',429,'Too many',{},io.BytesIO(b'{"retry_after":75}'))
        with patch.object(discord.urllib.request,'urlopen',side_effect=error):
            with self.assertRaises(discord.WebhookError) as result:
                discord.request_webhook('https://discord.com/api/webhooks/123/test',{'embeds':[]})
        self.assertEqual(result.exception.retry_after,75)

    def test_watcher_flags_error_once_and_respects_manual_stop(self):
        discord.atomic_json(self.root/'current-run.json',{'id':'test','started':100})
        self.rows('events-test.jsonl',[{'at':90,'event':'stopped','reason':'Old error'},
                    {'at':101,'event':'stopped','reason':'Minigame markers frozen'},
                    {'at':102,'event':'stopped','reason':'Stopped by F12 in Roblox'}])
        watcher=Watcher(self.root,{})
        watcher.poll(now=200);watcher.poll(now=201)
        self.assertEqual(len(watcher.pending),1)
        self.assertIn('frozen',watcher.pending[0]['message'])

    def test_error_delivery_failure_retries_without_losing_alerts(self):
        watcher=Watcher(self.root,{})
        watcher.alert('test','test')
        with patch('overnight_watch.safe_notify',side_effect=RuntimeError('unavailable')):watcher.deliver()
        self.assertEqual(len(watcher.pending),1)
        self.assertFalse(discord.read_json(self.root/'monitor-delivery.json')['ok'])

    def test_failed_and_empty_rounds_alert_once_but_unread_percent_does_not(self):
        discord.atomic_json(self.root/'current-run.json',{'id':'test','started':100})
        self.rows('events-test.jsonl',[{'at':101,'event':'minigame_ended','cycle':1,'percent':75},
                    {'at':102,'event':'minigame_ended','cycle':2,'percent':None},
                    {'at':103,'event':'empty_round','cycle':3,'message':'No pickup prompt'}])
        watcher=Watcher(self.root,{})
        watcher.poll(now=200);watcher.poll(now=201)
        self.assertEqual(len(watcher.pending),2)
        self.assertIn('75%',watcher.pending[0]['message'])

    def test_late_loot_after_success_is_not_recast_before_prompt_appears(self):
        from pickup_policy import Pickup,waiting_decision
        absent=Pickup('empty');prompt=Pickup('collect','Golden Fish T Collect')
        # 99.5% of logged prompts are readable within 1.36 s; later drops are
        # collected by the pre-cast and waiting-stage scene checks.
        self.assertEqual(waiting_decision(absent,True,1.4,True,100),'wait')
        self.assertEqual(waiting_decision(absent,True,1.9,True,100),'wait')
        self.assertEqual(waiting_decision(prompt,True,1.95,True,100),'collect')
        self.assertEqual(waiting_decision(absent,True,2.1,True,100),'empty')
        self.assertEqual(waiting_decision(absent,False,2.1,True,100),'wait')
        self.assertEqual(waiting_decision(absent,True,1.6,False,100),'empty')
        self.assertEqual(waiting_decision(absent,True,1.6,True,0),'empty')
        self.assertEqual(waiting_decision(prompt,False,1,True,100),'wait')

    def test_prompt_occlusion_does_not_abort_a_verified_hold_before_reward(self):
        from pickup_policy import Pickup,retain_collect_hold
        evidence=[(0,Pickup('collect')),(1.25,Pickup('empty')),(1.45,Pickup('empty')),
                  (1.9,Pickup('collect')),(2.7,Pickup('reward'))]
        self.assertTrue(all(retain_collect_hold(frame,elapsed) for elapsed,frame in evidence))
        self.assertFalse(retain_collect_hold(evidence[-1][1],2.7,confirmed_reward=True))

    def test_occluded_hold_still_releases_for_other_interactions_or_deadline(self):
        from pickup_policy import Pickup,retain_collect_hold
        for kind in ('other','ambiguous'):
            self.assertFalse(retain_collect_hold(Pickup(kind),.7))
        self.assertFalse(retain_collect_hold(Pickup('empty'),4))

    def test_airborne_target_retries_once_only_after_two_settled_scans(self):
        from pickup_policy import Pickup,CollectHoldMotion
        motion=CollectHoldMotion();motion.start(Pickup('collect',center=(1370,285)),0)
        self.assertFalse(motion.observe(Pickup('collect',center=(1380,610)),True,1,1))
        self.assertFalse(motion.observe(Pickup('collect',center=(1382,625)),True,1.4,1))
        self.assertFalse(motion.observe(Pickup('collect',center=(1380,629)),True,1.6,1))
        self.assertTrue(motion.observe(Pickup('collect',center=(1380,629)),True,1.65,1))
        self.assertFalse(motion.observe(Pickup('collect',center=(1380,629)),True,2.2,2))

    def test_stationary_or_still_moving_target_does_not_reset_a_valid_hold(self):
        from pickup_policy import Pickup,CollectHoldMotion
        motion=CollectHoldMotion();motion.start(Pickup('collect',center=(1370,680)),0)
        for at,center in ((1,(1380,686)),(1.4,(1379,692))):
            self.assertFalse(motion.observe(Pickup('collect',center=center),True,at,1))
        motion.start(Pickup('collect',center=(1370,285)),0)
        self.assertFalse(motion.observe(Pickup('collect',center=(1380,480)),True,1,1))
        self.assertFalse(motion.observe(Pickup('collect',center=(1380,650)),True,1.4,1))

    def test_movement_retry_requires_fresh_collect_evidence_after_occlusion(self):
        from pickup_policy import Pickup,CollectHoldMotion
        motion=CollectHoldMotion();motion.start(Pickup('collect',center=(1370,285)),0)
        motion.observe(Pickup('collect',center=(1380,610)),True,1,1)
        self.assertFalse(motion.observe(Pickup('other',center=(1380,610)),True,1.2,1))
        self.assertFalse(motion.observe(Pickup('collect',center=(1380,615)),True,1.5,1))
        self.assertFalse(motion.observe(Pickup('collect',center=(1380,617)),False,1.8,1))
        self.assertFalse(motion.observe(Pickup('collect',center=(1380,619)),True,4,1))

    def test_failed_native_alert_survives_watcher_restart_until_acknowledged(self):
        watcher=Watcher(self.root,{})
        watcher.alert('test-native-failure','Minigame stalled')
        with patch('overnight_watch.safe_notify',side_effect=RuntimeError('app pipe unavailable')):watcher.deliver()
        restarted=Watcher(self.root,{})
        self.assertEqual([r['id'] for r in restarted.pending],['test-native-failure'])
        with patch('overnight_watch.safe_notify',return_value={'ok':True}):restarted.deliver()
        self.assertEqual(Watcher(self.root,{}).pending,[])

    def test_unattended_focus_cannot_override_activity_manual_pause_or_expiry(self):
        self.assertTrue(allowed(200,10,100,1000,500))
        self.assertFalse(allowed(200,10,190,1000,500))
        self.assertFalse(allowed(100,10,0,1000,500))
        self.assertFalse(allowed(200,10,100,500,500))
        self.assertFalse(allowed(200,10,100,1000,500,manual=True))

    def test_bot_injected_events_do_not_hide_physical_inactivity(self):
        from types import SimpleNamespace
        activity=PhysicalActivity();previous=activity.last
        with patch('unattended_focus.time.monotonic',return_value=previous+10):
            activity.keyboard_event(0,SimpleNamespace(flags=0x10))
            activity.mouse_event(0,SimpleNamespace(flags=1))
            self.assertEqual(activity.last,previous)
            activity.mouse_event(0,SimpleNamespace(flags=0))
            self.assertEqual(activity.last,previous+10)

    def test_status_replace_retries_a_windows_reader_lock(self):
        replace=discord.os.replace
        calls=[0]
        def locked(source,target):
            calls[0]+=1
            if calls[0]<3:raise PermissionError('reader has the file open')
            return replace(source,target)
        with patch.object(discord.os,'replace',side_effect=locked),patch.object(discord.time,'sleep'):
            discord.atomic_json(self.root/'monitor-status.json',{'running':True})
        self.assertTrue(discord.read_json(self.root/'monitor-status.json')['running'])
        self.assertEqual(calls[0],3)

    def test_capture_replaces_and_closes_bad_gdi_source_once(self):
        from unittest.mock import Mock
        bad=Mock();bad.grab.side_effect=capture_session.ScreenShotError('BitBlt: Cannot create a file when that file already exists')
        good=Mock();good.grab.return_value=np.full((40,40,4),80,dtype=np.uint8)
        with patch.object(capture_session.mss,'MSS',side_effect=[bad,good]) as factory,patch.object(capture_session.time,'sleep'):
            with capture_session.CaptureSession() as session:
                for _ in range(4):session.grab({'left':0,'top':0,'width':40,'height':40})
                self.assertEqual(session.resets,1)
        self.assertEqual(factory.call_count,2);bad.close.assert_called_once();good.close.assert_called_once()

    def test_solid_white_game_frame_is_unavailable_not_disconnect(self):
        from unittest.mock import Mock
        from faults import FishingFault
        source=Mock();source.grab.return_value=np.full((540,960,4),255,dtype=np.uint8)
        with patch.object(capture_session.mss,'MSS',return_value=source),patch.object(capture_session.time,'sleep'):
            with capture_session.CaptureSession() as session:
                with self.assertRaises(FishingFault) as result:session.grab({'left':0,'top':0,'width':960,'height':540})
        self.assertEqual(result.exception.code,'capture_unavailable')
        self.assertEqual(result.exception.details['blank_color'],'white')

    def test_display_refresh_requires_persistent_white_safe_ownership_and_is_bounded(self):
        repair=DisplayRepair()
        flags=dict(white=True,enabled=True,physical_idle=100,foreground=True,manual=False,ownership_idle=True)
        self.assertFalse(repair.allowed(0,**flags));self.assertFalse(repair.allowed(9,**flags))
        self.assertTrue(repair.allowed(10,**flags))
        for changes in ({'white':False},{'enabled':False},{'physical_idle':5},{'foreground':False},{'manual':True},{'ownership_idle':False}):
            self.assertFalse(repair.allowed(11,**{**flags,**changes}))
        self.assertFalse(repair.allowed(12,**flags));self.assertTrue(repair.allowed(22,**flags))
        repair.attempted(22);self.assertFalse(repair.allowed(81,**flags));self.assertTrue(repair.allowed(82,**flags))
        repair.attempted(82);self.assertFalse(repair.allowed(1000,**flags))
        self.assertTrue(repair.allowed(5483,**flags))

    def test_display_refresh_releases_key_when_interrupted_and_reacquires_geometry(self):
        import recovery
        from unittest.mock import Mock
        driver=recovery.Recovery.__new__(recovery.Recovery)
        driver.hwnd=123;driver.inp=Mock();driver.guard=Mock();driver.check_stop=Mock();driver.sct=Mock();driver.select=Mock();driver.event=Mock()
        driver.screen=Mock(actual_width=2560,actual_height=1440)
        driver.sleep=Mock(side_effect=recovery.UserStop('Stopped by user'))
        # A live farmer's PAUSE file must not leak into this test.
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        with patch.object(recovery,'RUN',Path(temporary.name)),patch.object(recovery,'find_window',return_value=123),patch.object(recovery,'USER') as user:
            with self.assertRaises(recovery.UserStop):driver.refresh_display()
            self.assertEqual(user.keybd_event.call_args_list[-1].args[2],2)
        driver.sct.reset.assert_not_called();driver.inp.release.assert_called_once()
        driver.sleep=Mock()
        with patch.object(recovery,'RUN',Path(temporary.name)),patch.object(recovery,'find_window',return_value=123),patch.object(recovery,'USER'):
            driver.refresh_display()
        driver.sct.reset.assert_called_once();driver.select.assert_called_once()

    def test_local_window_failure_cannot_launch_another_client(self):
        import recovery
        from faults import FishingFault
        from unittest.mock import Mock
        driver=recovery.Recovery.__new__(recovery.Recovery)
        driver.inp=Mock();driver.event=Mock();driver.launch=Mock()
        driver.select=Mock(side_effect=FishingFault('window','Roblox client is still changing'))
        with self.assertRaises(FishingFault):driver.recover(allow_rejoin=False)
        driver.launch.assert_not_called()

    def test_square_transition_maximizes_exact_player_then_validates_1440p(self):
        import recovery
        from unittest.mock import Mock
        driver=recovery.Recovery.__new__(recovery.Recovery)
        driver.check_stop=Mock();driver.inp=Mock();driver.event=Mock();driver.progress=Mock();driver.sleep=Mock()
        with patch.object(recovery,'find_window',return_value=123),patch.object(recovery.win32gui,'IsIconic',return_value=False),\
             patch.object(recovery.win32gui,'GetForegroundWindow',return_value=123),\
             patch.object(recovery.win32gui,'ShowWindow') as show,\
             patch.object(recovery,'rectangle',side_effect=[(0,23,1024,720)]*5+[(0,23,2560,1400)]*3),\
             patch.object(recovery,'RUN',self.root):
            driver.select()
        show.assert_called_once_with(123,3)
        self.assertEqual(driver.screen.actual_width,2560)

    def test_farm_here_never_rejoins_for_local_faults(self):
        self.assertFalse(startup_rejoin('here',True));self.assertTrue(startup_rejoin('full',True))
        for code in ('focus','window','tracking_frozen','pickup_timeout','capture_unavailable','no_minigame'):
            self.assertNotEqual(HereRecovery().choose(code),'rejoin')
        self.assertEqual(HereRecovery().choose('disconnect'),'rejoin')
        self.assertEqual(HereRecovery().choose('client_lost'),'rejoin')
        policy=HereRecovery()
        self.assertEqual([policy.choose('pickup_timeout') for _ in range(4)],['local','local','local','attention'])

    def test_overnight_stop_off_user_activity_and_challenges_block_restart(self):
        c={'overnight_enabled':True,'overnight_autofocus':True}
        self.assertTrue(can_restart(c,500,True))
        self.assertFalse(can_restart(c,10,True))
        self.assertFalse(can_restart({**c,'overnight_enabled':False},500,True))
        self.assertFalse(can_restart(c,500,True,manual=True))
        self.assertFalse(can_restart(c,500,True,failure_code='user_required'))
        self.assertFalse(can_restart(c,500,False))
        self.assertTrue(can_restart(c,500,False,failure_code='client_lost'))

    def test_same_round_cannot_count_a_second_case_variant_banner(self):
        gate=RewardGate()
        self.assertTrue(gate.accept(11));self.assertFalse(gate.accept(11));self.assertTrue(gate.accept(12))

    def test_farm_here_world_start_and_verified_disconnect_take_distinct_paths(self):
        import recovery
        from unittest.mock import Mock
        for disconnected in (False,True):
            clock=[0.];scene=['disconnect' if disconnected else 'world'];events=[]
            driver=recovery.Recovery.__new__(recovery.Recovery)
            driver.inp=Mock();driver.guard=Mock();driver.select=Mock();driver.progress=Mock();driver.restarts=0
            driver.capture=lambda *args:{'scene':scene[0]}
            driver.text=lambda frame,*args:([{'text':'Disconnected'},{'text':'Reconnect','center':(100,100)}] if frame['scene']=='disconnect' else [{'text':'Mistfall Lv. 225'}])
            driver.world_visible=lambda frame:frame['scene']=='world'
            driver.click=Mock(side_effect=lambda *args:scene.__setitem__(0,'world'))
            driver.key=Mock();driver.launch=Mock();driver.equip_rod=Mock();driver.backstep_after_join=Mock()
            driver.event=lambda event,**kw:events.append(event)
            driver.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
            with patch.object(recovery.time,'monotonic',side_effect=lambda:clock[0]):
                driver.recover(force_menu=False,allow_rejoin=False)
            driver.launch.assert_not_called();driver.key.assert_not_called();driver.equip_rod.assert_called_once()
            self.assertEqual(driver.click.call_count,int(disconnected))
            self.assertEqual('disconnect_observed' in events,disconnected)

    def test_config_legacy_defaults_and_overnight_off_disarm_future_activation(self):
        import app_config,fishing_cli
        from contextlib import redirect_stdout
        config=self.root/'config.local.json'
        config.write_text(json.dumps({'data_dir':str(self.root),'mode':'full'}))
        with patch.object(app_config,'CONFIG',config),redirect_stdout(io.StringIO()):
            self.assertTrue(app_config.load_config()['overnight_enabled'])
            self.assertTrue(app_config.load_config()['overnight_auto_enable_idle'])
            app_config.save_config({'overnight_enabled':True,'overnight_auto_enable_idle':True})
            fishing_cli.execute(fishing_cli.parser().parse_args(['overnight','off']))
            saved=app_config.load_config()
        self.assertFalse(saved['overnight_enabled']);self.assertFalse(saved['overnight_auto_enable_idle'])

    def test_certain_collect_is_immediate_only_after_a_fresh_minigame(self):
        rows=[{'text':'Collect','score':.99,'center':(1350,650)}]
        self.assertTrue(clear_collect(rows,after_minigame=True))
        self.assertFalse(clear_collect(rows,after_minigame=False))
        self.assertFalse(clear_collect([{**rows[0],'score':.85}],after_minigame=True))

    def test_recorded_diamond_play_menu_requires_scene_and_button_location(self):
        from recovery_pacing import main_menu_target
        rows=[{'text':'·PLAY','score':.855,'center':(96,629)},
              {'text':'CUSTOMIZE','score':.98,'center':(138,690)},
              {'text':'SLOTS','score':.96,'center':(95,812)}]
        self.assertEqual(main_menu_target(rows),(96,629))
        self.assertIsNone(main_menu_target(rows[:1]))
        self.assertIsNone(main_menu_target([{**rows[0],'center':(1400,650)},*rows[1:]]))
        self.assertIsNone(main_menu_target([{**rows[0],'text':'Gameplay'},*rows[1:]]))
        self.assertIsNone(main_menu_target([*rows,rows[0]]))

    def test_menu_cursor_warp_during_hover_does_not_redirect_click(self):
        import recovery
        from unittest.mock import Mock
        driver=recovery.Recovery.__new__(recovery.Recovery);position=[None];pressed=[]
        driver.move=lambda x,y:position.__setitem__(0,(x,y))
        driver.sleep=lambda seconds:position.__setitem__(0,(1280,720))
        driver.inp=Mock();driver.inp.hold.side_effect=lambda down:pressed.append(position[0]) if down else None
        driver.click(96,629)
        self.assertEqual(pressed,[(96,629)])
        driver.inp.hold.assert_called_with(False)

    def test_rod_fallback_cannot_leave_previously_selected_rod_toggled_off(self):
        import recovery
        from unittest.mock import Mock
        driver=recovery.Recovery.__new__(recovery.Recovery)
        driver.move=Mock();driver.sleep=Mock();driver.key=Mock();driver.capture=Mock();driver.event=Mock()
        off={'score':.95,'ring':0.,'equipped':False,'x':1300,'y':1370}
        on={**off,'ring':.9,'equipped':True}
        with patch.object(recovery,'load_config',return_value={'cast_point':(1332,508),'auto_rod':True,'rod_slot':5}),\
             patch.object(recovery,'locate_rod',side_effect=[None,off,on]):
            driver.equip_rod()
        self.assertEqual([c.args for c in driver.key.call_args_list],[('5',),('5',)])
        self.assertIn('rod_selection_verified',[c.args[0] for c in driver.event.call_args_list])

    def test_inventory_tab_location_comes_from_its_current_label(self):
        import inventory_watch
        from unittest.mock import Mock
        scanner=inventory_watch.InventoryScanner.__new__(inventory_watch.InventoryScanner)
        scanner.driver=Mock();scanner.driver.text.return_value=[([[160,40],[250,40],[250,80],[160,80]],'All (187)',.99)]
        self.assertEqual(scanner.tab_target(np.zeros((1440,2560,3),np.uint8),'All'),(825,160))
        scanner.driver.text.return_value=[]
        with self.assertRaises(ValueError):scanner.tab_target(np.zeros((1440,2560,3),np.uint8),'All')


if __name__=='__main__':unittest.main()
