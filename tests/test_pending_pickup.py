import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fishing_assistant as fishing
import full_pause
from faults import FishingFault
from pickup_policy import Pickup, before_cast_decision


class PendingPickupTests(unittest.TestCase):
    def drive(self, initial='collect', pause_after_cast=False, pause_in_ocr=False, active_minigame=False, pending_after_cast=False,
              post_reward=None, pause_after_reward=False, menu_after_reward=False, minigame_after_reward=False,
              pause_in_post_reward_ocr=False, auto_rod=False, rod_changed_after_reward=False,
              tracking_seconds=0, timing=False, disconnect_after_reward=False, minigame_in_recast_ocr=False,
              reward_after=.8, stationary_prompt=False, duration=None):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name);clock=[100.];mode=[initial];held_at=[None]
        paused_at=[None];cast_released=[False];inputs=[];states=[]
        accepted_at=[None];region=[None];self.scene_scans=[];self.reward_time=None
        first_cast_at=[None];minigame_after_ocr=[False]
        self.rod_reads=[];self.rod_rechecks=[]
        rod={'name':'rare','x':1586,'y':1385,'equipped':True,'score':.99,'ring':.85}
        def read_rod(unused):
            self.rod_reads.append(clock[0])
            return {**rod,'name':'common'} if rod_changed_after_reward and accepted_at[0] is not None else dict(rod)
        def recheck_rod(unused,previous):
            self.rod_rechecks.append((clock[0],previous))
            return None if rod_changed_after_reward and accepted_at[0] is not None else previous
        gui=Mock();gui.IsWindow.return_value=True;gui.IsIconic.return_value=False
        gui.GetForegroundWindow.return_value=1;gui.GetAncestor.return_value=1
        gui.GetCursorPos.return_value=(1600,800)
        user=Mock();user.GetAsyncKeyState.return_value=0;user.MapVirtualKeyW.return_value=0
        def key(vk,scan,flags,*unused):
            if vk==ord('T'):
                inputs.append(('T',flags,clock[0]))
                if flags==0:held_at[0]=clock[0]
        def mouse(flags,*unused):
            inputs.append(('mouse',flags,clock[0]))
            if flags==4:
                cast_released[0]=True
                if first_cast_at[0] is None:first_cast_at[0]=clock[0]
        user.keybd_event.side_effect=key;user.mouse_event.side_effect=mouse
        def sleep(seconds):
            clock[0]+=seconds
            if pending_after_cast and cast_released[0] and mode[0]=='empty':mode[0]='collect'
            if pause_after_cast and cast_released[0] and paused_at[0] is None:
                paused_at[0]=clock[0];(root/'F8_PAUSE').write_text('Paused by user')
            if pause_after_reward and accepted_at[0] is not None and paused_at[0] is None:
                paused_at[0]=clock[0];(root/'F8_PAUSE').write_text('Paused after reward')
            if paused_at[0] is not None and clock[0]-paused_at[0]>1:
                (root/'F8_PAUSE').unlink(missing_ok=True)
                mode[0]='reward' if pause_after_reward or pause_in_post_reward_ocr else 'empty' if pause_in_ocr else 'collect'
                paused_at[0]=-1000;cast_released[0]=False
        def ocr(image,**unused):
            clock[0]+=(.20 if region[0]==(760,410,1040,580) else .17 if region[0]==(480,150,1630,1110) else .12) if timing else .12
            if pause_in_ocr and paused_at[0] is None:
                paused_at[0]=clock[0];(root/'F8_PAUSE').write_text('Paused during OCR')
            if held_at[0] is not None and clock[0]-held_at[0]>reward_after:mode[0]='reward'
            reading=mode[0]
            if accepted_at[0] is not None:
                self.scene_scans.append((clock[0],region[0]))
                if disconnect_after_reward and region[0] in ((480,150,1630,1110),(760,410,1040,580)):
                    reading='disconnect'
                if minigame_in_recast_ocr and region[0]==(480,150,1630,1110):minigame_after_ocr[0]=True
                if pause_in_post_reward_ocr and paused_at[0] is None:
                    paused_at[0]=clock[0];(root/'F8_PAUSE').write_text('Paused during recast OCR')
                if post_reward and region[0]==(480,150,1630,1110):reading=post_reward
            labels={'collect':[('T',120,80),('Krathulon',240,60),('Collect',240,85)],
                    'reward':[('Krathulon',140,60),('X1',220,60)],
                    'ambiguous':[('Collect',160,80),('Purchase',180,85)],'empty':[],
                    'disconnect':[('Disconnected',500,280),('Krathulon',140,60),('X1',220,60)]}[reading]
            if reading=='disconnect' and disconnect_after_reward=='outside':labels[0]=('Disconnected',500,80)
            if stationary_prompt and reading in ('collect','reward'):
                labels=([('T',1250,700),('Krathulon',1350,675),('Collect',1350,700)] if reading=='collect'
                        else [('Krathulon',1400,740),('X1',1490,740)])
                x0,y0,w,h=region[0]
                scale=1.5 if region[0]==(1240,670,310,180) else .75 if w>=1000 else 1
                labels=[(text,(x-x0)*scale,(y-y0)*scale) for text,x,y in labels]
            return ([[[[x-5,y-5],[x+5,y-5],[x+5,y+5],[x-5,y+5]],text,
                       .79 if text=='Disconnected' and disconnect_after_reward=='low' else .99]
                     for text,x,y in labels],None)
        def status(name,value):
            if name=='status.json':states.append(dict(value))
            (root/name).write_text(json.dumps(value))
        def read(name):
            if name=='supervisor.json':return {'started':1}
            if name=='bait-observation.json':return {'supervisor_started':1}
            return {}
        screen=Mock();screen.point.return_value=(1600,800)
        frame=np.zeros((1440,2560,3),np.uint8)
        def capture_frame(unused,box=None):
            region[0]=box
            if timing:clock[0]+=.01
            return frame
        screen.capture.side_effect=capture_frame
        capture=Mock();capture.__enter__=Mock(return_value=Mock(resets=0));capture.__exit__=Mock(return_value=False)
        inventory=Mock();inventory.pending=[];inventory.check_pending.return_value=None
        def observed(*unused):
            accepted_at[0]=clock[0];self.reward_time=clock[0]
            if menu_after_reward:
                inventory.pending=[{'reward_id':'unknown'}]
                inventory.clock.return_value=1000;inventory.next_check_at=0
        inventory.observe.side_effect=observed
        ledger=Mock();ledger.base={}
        def tracking_now():
            return (active_minigame or minigame_after_reward and accepted_at[0] is not None
                    or minigame_after_ocr[0] or tracking_seconds and first_cast_at[0] is not None
                    and .3<clock[0]-first_cast_at[0]<tracking_seconds)
        error=None
        with ExitStack() as stack:
            for target,name,value in [
                (fishing,'RUN',root),(fishing,'win32gui',gui),(full_pause,'win32gui',gui),
                (fishing,'USER',user),(fishing,'find_window',Mock(return_value=1)),
                (fishing,'rectangle',Mock(return_value=(0,0,2560,1440))),
                (fishing,'ScreenSpace',Mock(return_value=screen)),
                (fishing,'RapidOCR',Mock(return_value=ocr)),
                (fishing,'detect',Mock(side_effect=lambda unused:{'ball':100,'target':100,'height':50,'ball_height':10,'inside':True}
                                     if tracking_now() else None)),
                (fishing,'ui_visible',Mock(side_effect=lambda *unused:tracking_now())),
                (fishing,'ReelMotion',Mock(return_value=Mock(step=Mock(return_value=False),velocity=0,target_velocity=0))),
                (fishing,'InventoryWatcher',Mock(return_value=inventory)),
                (fishing,'Ledger',Mock(return_value=ledger)),(fishing,'read_metrics',read),
                (fishing,'write_metrics',status),(fishing,'move_pointer',Mock()),
                (fishing,'locate_rod',Mock(side_effect=read_rod)),
                (fishing,'recheck_selected_rod',Mock(side_effect=recheck_rod)),
                (fishing,'CaptureSession',Mock(return_value=capture)),(fishing,'Listener',Mock()),
                (fishing,'load_config',Mock(return_value={'camera_mode':'keep','auto_rod':auto_rod,'cast_point':(1600,800)}))]:
                stack.enter_context(patch.object(target,name,value))
            stack.enter_context(patch.object(full_pause.InputGate,'start'))
            stack.enter_context(patch.object(fishing.time,'monotonic',side_effect=lambda:clock[0]))
            stack.enter_context(patch.object(fishing.time,'sleep',side_effect=sleep))
            stack.enter_context(patch.object(fishing.cv2,'imread',return_value=None))
            stack.enter_context(patch.object(fishing.landmarks,'profile',return_value=None))
            if timing:
                recorder=Mock();recorder.observe.side_effect=lambda *unused:clock.__setitem__(0,clock[0]+.03)
                recorder.save.return_value={'sequence':1}
                stack.enter_context(patch.object(fishing,'FaultRecorder',return_value=recorder))
                stack.enter_context(patch.object(fishing.cv2,'imwrite',side_effect=lambda *unused:clock.__setitem__(0,clock[0]+.04)))
                if hasattr(fishing,'SnapshotWriter'):
                    writer=Mock();writer.__enter__=Mock(return_value=Mock());writer.__exit__=Mock(return_value=False)
                    stack.enter_context(patch.object(fishing,'SnapshotWriter',return_value=writer))
            stack.enter_context(patch.object(sys,'argv',['fishing_assistant.py','--seconds',str(duration or (24 if auto_rod or tracking_seconds else 9))]))
            stack.enter_context(patch('builtins.print'))
            try:fishing.main()
            except RuntimeError as caught:error=caught
        events=[json.loads(line) for line in next(root.glob('events-*.jsonl')).read_text().splitlines()]
        return events,inputs,states,error,inventory

    def test_replacement_collects_ground_loot_before_first_cast(self):
        events,inputs,states,error,inventory=self.drive()
        self.assertIsNone(error)
        names=[r['event'] for r in events]
        self.assertLess(names.index('pending_pickup_recovered'),names.index('pickup_hold'))
        self.assertLess(names.index('reward_observed'),names.index('cast'))
        self.assertEqual(sum(name=='reward_observed' for name in names),1)
        reward=next(r for r in events if r['event']=='reward_observed')
        self.assertEqual(reward['cycle'],1)
        self.assertEqual(reward['text'],'Krathulon X1')
        self.assertEqual(states[-1]['cycles'],0)
        self.assertEqual(states[-1]['recovered_pickups'],1)
        self.assertEqual(states[-1]['unknown_rounds'],0)
        first_t=next(at for kind,flags,at in inputs if kind=='T' and flags==0)
        first_cast=next(at for kind,flags,at in inputs if kind=='mouse' and flags==2)
        self.assertLess(first_t,first_cast)

    def test_waiting_worker_rechecks_ground_loot_after_f8(self):
        events,inputs,states,error,inventory=self.drive('empty',pause_after_cast=True)
        self.assertIsNone(error)
        names=[r['event'] for r in events]
        self.assertLess(names.index('cast'),names.index('input_paused'))
        self.assertLess(names.index('input_resumed'),names.index('pending_pickup_recovered'))
        first_reward=names.index('reward_observed')
        self.assertEqual(sum(name=='cast' for name in names[:first_reward]),1)
        self.assertTrue(all(not s['held_t'] and not s['held_mouse'] for s in states if s.get('stage')=='paused_manual'))

    def test_ambiguous_ground_prompt_never_casts_or_holds_t(self):
        events,inputs,states,error,inventory=self.drive('ambiguous')
        self.assertEqual(error.code,'pickup_timeout')
        self.assertFalse(any(r['event']=='cast' for r in events))
        self.assertFalse(any(flags==0 and kind=='T' for kind,flags,at in inputs))

    def test_ignored_cast_recovers_pending_collect_without_waiting_for_bite_timeout(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True)
        self.assertIsNone(error)
        names=[r['event'] for r in events]
        self.assertNotIn('input_resumed',names)
        self.assertNotIn('no_minigame',names)
        self.assertEqual(sum(name=='cast' for name in names[:names.index('reward_observed')]),1)
        cast_release=next(at for kind,flags,at in inputs if kind=='mouse' and flags==4)
        t_press=next(at for kind,flags,at in inputs if kind=='T' and flags==0)
        self.assertLess(t_press-cast_release,2)

    def test_previous_reward_toast_does_not_count_again(self):
        events,inputs,states,error,inventory=self.drive('reward')
        self.assertIsNone(error)
        self.assertTrue(any(r['event']=='cast' for r in events))
        self.assertFalse(any(r['event']=='reward_observed' for r in events))
        self.assertFalse(any(flags==0 and kind=='T' for kind,flags,at in inputs))

    def test_pause_during_scan_invalidates_pending_t_press(self):
        events,inputs,states,error,inventory=self.drive(pause_in_ocr=True)
        self.assertIsNone(error)
        self.assertTrue(any(r['event']=='input_paused' for r in events))
        self.assertFalse(any(flags==0 and kind=='T' for kind,flags,at in inputs))

    def test_active_minigame_takes_priority_over_ground_prompt(self):
        events,inputs,states,error,inventory=self.drive(active_minigame=True)
        self.assertIsNone(error)
        self.assertTrue(any(r['event']=='minigame' for r in events))
        self.assertFalse(any(r['event'] in ('cast','pending_pickup_recovered','reward_observed') for r in events))
        self.assertEqual(states[-1]['cycles'],1)
        self.assertEqual(states[-1]['recovered_pickups'],0)
        self.assertFalse(any(flags==0 and kind=='T' for kind,flags,at in inputs))

    def test_unconfirmed_empty_and_other_actions_do_not_clear_cast(self):
        self.assertEqual(before_cast_decision(Pickup('empty'),False,1),'wait')
        self.assertEqual(before_cast_decision(Pickup('empty'),True,.2),'wait')
        self.assertEqual(before_cast_decision(Pickup('empty'),True,.5),'clear')
        self.assertEqual(before_cast_decision(Pickup('other','Purchase'),True,1),'wait')
        self.assertEqual(before_cast_decision(Pickup('other','Purchase'),True,8),'timeout')

    def test_confirmed_receipt_recasts_quickly_after_fresh_full_scene(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True)
        self.assertIsNone(error)
        recasts=[at for kind,flags,at in inputs if kind=='mouse' and flags==2 and at>self.reward_time]
        self.assertTrue(recasts)
        self.assertLess(recasts[0]-self.reward_time,.6)
        ready=next(event for event in events if event['event']=='recast_ready')
        self.assertTrue(ready['matching_receipt'])
        self.assertEqual(self.scene_scans[0][1],(480,150,1630,1110))
        self.assertEqual(sum(event['event']=='reward_observed' for event in events),1)
        self.assertFalse(states[-1]['held_t'])

    def test_other_prompt_outside_toast_crop_blocks_fast_recast(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True,post_reward='ambiguous')
        self.assertFalse(any(kind=='mouse' and flags==2 and at>self.reward_time for kind,flags,at in inputs))
        self.assertFalse(any(event['event']=='recast_ready' for event in events))

    def test_new_collect_outside_toast_crop_takes_priority(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True,post_reward='collect')
        names=[event['event'] for event in events]
        reward=names.index('reward_observed')
        self.assertIn('pending_pickup_recovered',names[reward+1:])
        self.assertNotIn('cast',names[reward+1:])

    def test_pause_after_reward_discards_fast_recast_receipt(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True,pause_after_reward=True)
        self.assertIsNone(error)
        self.assertTrue(any(event['event']=='input_resumed' for event in events))
        self.assertFalse(any(event['event']=='recast_ready' for event in events))
        self.assertTrue(any(kind=='mouse' and flags==2 and at>self.reward_time for kind,flags,at in inputs))
        self.assertTrue(all(not state['held_t'] and not state['held_mouse'] for state in states if state['stage']=='paused_manual'))

    def test_inventory_menu_discards_fast_recast_receipt(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True,menu_after_reward=True)
        self.assertIsNone(error)
        self.assertTrue(inventory.check_pending.called)
        self.assertFalse(any(event['event']=='recast_ready' for event in events))
        self.assertTrue(any(kind=='mouse' and flags==2 and at>self.reward_time for kind,flags,at in inputs))

    def test_pause_during_fast_scan_invalidates_receipt_before_click(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True,pause_in_post_reward_ocr=True)
        self.assertIsNone(error)
        names=[event['event'] for event in events]
        reward=names.index('reward_observed')
        resumed=names.index('input_resumed',reward)
        self.assertNotIn('cast',names[reward+1:resumed])
        self.assertNotIn('recast_ready',names)
        self.assertTrue(any(kind=='mouse' and flags==2 and at>self.reward_time for kind,flags,at in inputs))

    def test_active_minigame_after_reward_blocks_fast_recast(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True,minigame_after_reward=True)
        self.assertIsNone(error)
        self.assertFalse(any(event['event']=='recast_ready' for event in events))
        self.assertFalse(any(kind=='mouse' and flags==2 and at>self.reward_time for kind,flags,at in inputs))

    def test_fast_receipt_requires_exact_confirmed_reward_and_full_scene(self):
        receipt=Pickup('reward','Krathulon X1')
        self.assertEqual(before_cast_decision(receipt,False,.1,receipt,True),'clear')
        self.assertEqual(before_cast_decision(receipt,False,.1,receipt,False),'wait')
        self.assertEqual(before_cast_decision(receipt,False,.1,Pickup('reward','Zebra Fish X1'),True),'wait')
        self.assertEqual(before_cast_decision(Pickup('empty'),False,.1,receipt,True),'wait')
        self.assertEqual(before_cast_decision(Pickup('ambiguous'),True,.1,receipt,True),'wait')
        self.assertEqual(before_cast_decision(Pickup('collect','T Collect'),True,.1,receipt,True),'collect')

    def test_periodic_rod_check_reuses_location_with_fresh_verification(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True,auto_rod=True)
        self.assertIsNone(error)
        self.assertGreaterEqual(len(self.rod_rechecks),2)
        self.assertEqual(len(self.rod_reads),1)
        self.assertIsNone(self.rod_rechecks[0][1])
        self.assertEqual(self.rod_rechecks[1][1]['name'],'rare')
        self.assertTrue(any(event['event']=='cast' for event in events))

    def test_changed_rod_recheck_falls_back_to_full_hotbar(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True,auto_rod=True,rod_changed_after_reward=True)
        self.assertIsNone(error)
        self.assertGreaterEqual(len(self.rod_reads),2)
        self.assertGreater(self.rod_reads[1],self.reward_time)

    def test_recast_critical_path_stays_under_half_second_with_due_gui_scan(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True,tracking_seconds=7,timing=True)
        self.assertIsNone(error)
        presses=[at for kind,flags,at in inputs if kind=='mouse' and flags==2 and at>self.reward_time]
        releases=[at for kind,flags,at in inputs if kind=='mouse' and flags==4 and at>presses[0]]
        self.assertTrue(releases)
        self.assertLess(releases[0]-self.reward_time,.5)
        self.assertGreaterEqual(releases[0]-presses[0],.16)
        ready=next(event for event in events if event['event']=='recast_ready')
        self.assertTrue(ready['matching_receipt'])
        self.assertEqual(self.scene_scans[0][1],(480,150,1630,1110))

    def test_combined_scan_disconnect_wins_over_matching_receipt(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True,disconnect_after_reward=True)
        self.assertIn('Disconnect GUI detected',str(error))
        self.assertFalse(any(kind=='mouse' and flags==2 and at>self.reward_time for kind,flags,at in inputs))
        self.assertTrue(any(event['event']=='disconnect_gui' for event in events))
        self.assertFalse(states[-1]['held_mouse'])
        self.assertFalse(states[-1]['held_t'])

    def test_due_inventory_menu_checks_disconnect_before_opening(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True,tracking_seconds=7,
                                                      menu_after_reward=True,disconnect_after_reward=True)
        self.assertIn('Disconnect GUI detected',str(error))
        inventory.check_pending.assert_not_called()

    def test_combined_disconnect_check_preserves_old_gui_bounds_and_confidence(self):
        for kind in ('outside','low'):
            with self.subTest(kind=kind):
                events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True,disconnect_after_reward=kind)
                self.assertIsNone(error)
                self.assertTrue(any(kind=='mouse' and flags==2 and at>self.reward_time for kind,flags,at in inputs))
                self.assertFalse(any(event['event']=='disconnect_gui' for event in events))

    def test_minigame_arriving_during_recast_ocr_owns_input(self):
        events,inputs,states,error,inventory=self.drive('empty',pending_after_cast=True,minigame_in_recast_ocr=True)
        self.assertIsNone(error)
        self.assertFalse(any(kind=='mouse' and flags==2 and at>self.reward_time for kind,flags,at in inputs))
        self.assertTrue(any(event['event'] in ('minigame','tracking_reacquired') for event in events))
        self.assertTrue(any(state['stage']=='tracking' for state in states))

    def test_first_hold_collects_late_reward_without_releasing_and_retrying(self):
        events,inputs,states,error,inventory=self.drive(reward_after=4.4,stationary_prompt=True)
        self.assertIsNone(error)
        t_down=[at for kind,flags,at in inputs if kind=='T' and flags==0]
        self.assertEqual(len(t_down),1)
        t_up=next(at for kind,flags,at in inputs if kind=='T' and flags==2)
        self.assertGreaterEqual(t_up-t_down[0],4.4)
        self.assertEqual(sum(event['event']=='reward_observed' for event in events),1)
        self.assertFalse(states[-1]['held_t'])

    def test_first_timeout_gets_extra_grace_but_second_hold_stays_four_seconds(self):
        events,inputs,states,error,inventory=self.drive(reward_after=100,stationary_prompt=True,duration=16)
        holds=[];down=None
        for kind,flags,at in inputs:
            if kind!='T':continue
            if flags==0:down=at
            elif down is not None:holds.append(at-down);down=None
        self.assertGreaterEqual(len(holds),2)
        self.assertGreaterEqual(holds[0],4.75)
        self.assertLess(holds[0],5.15)
        self.assertGreaterEqual(holds[1],4.0)
        self.assertLess(holds[1],4.4)


if __name__=='__main__':unittest.main()
