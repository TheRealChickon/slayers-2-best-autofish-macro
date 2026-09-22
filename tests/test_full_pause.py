import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, call
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import full_pause
import fishing_assistant as fishing
import presence_watch
from full_pause import F8Toggle, InputGate, InputPaused, resumed_stage


class FullPauseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.user=Mock();self.user.GetAsyncKeyState.return_value=0
        self.gui=patch.object(full_pause,'win32gui').start();self.addCleanup(patch.stopall)
        self.gui.IsWindow.return_value=True;self.gui.IsIconic.return_value=False
        self.gui.GetForegroundWindow.return_value=1;self.gui.GetAncestor.return_value=1
        patch.object(fishing,'win32gui',self.gui).start()
        patch.object(fishing,'USER',self.user).start()
        self.inp=fishing.Input(1);self.gate=InputGate(self.inp,self.root,self.user,pointer=True);self.inp.gate=self.gate

    def test_held_f8_toggles_once_and_other_apps_do_not_toggle(self):
        changed=Mock();toggle=F8Toggle(self.root,lambda:1,changed)
        toggle.press();toggle.press();self.assertTrue((self.root/'F8_PAUSE').exists())
        changed.assert_called_once_with(True)
        toggle.release();self.gui.GetForegroundWindow.return_value=2;toggle.press();toggle.release()
        self.assertTrue((self.root/'F8_PAUSE').exists())
        self.gui.GetForegroundWindow.return_value=1;toggle.press()
        self.assertFalse((self.root/'F8_PAUSE').exists())
        self.assertEqual(changed.call_args_list,[call(True),call(False)])

    def test_f8_never_clears_manual_stop(self):
        (self.root/'STOP').write_text('Stopped by user')
        (self.root/'F8_PAUSE').write_text('Paused')
        F8Toggle(self.root,lambda:1).press()
        self.assertTrue((self.root/'F8_PAUSE').exists())
        self.assertEqual((self.root/'STOP').read_text(),'Stopped by user')

    def test_pause_releases_mouse_and_t_and_blocks_stale_ocr_decision(self):
        self.inp.hold(True);self.inp.grab(True)
        (self.root/'F8_PAUSE').write_text('Paused');self.gate.poll()
        self.assertFalse(self.inp.mouse);self.assertFalse(self.inp.t)
        self.assertEqual(self.user.mouse_event.call_args.args[0],4)
        self.assertEqual(self.user.keybd_event.call_args.args[2],2)
        (self.root/'F8_PAUSE').unlink()
        with self.assertRaises(InputPaused):self.inp.hold(True)
        with self.assertRaises(InputPaused):self.inp.grab(True)
        self.assertTrue(self.gate.acknowledge())
        self.inp.hold(True);self.assertTrue(self.inp.mouse)

    def test_manual_pause_survives_focus_return_and_blocks_recovery_movement(self):
        (self.root/'F8_PAUSE').write_text('Paused')
        self.gui.GetForegroundWindow.return_value=2;self.gate.poll()
        self.gui.GetForegroundWindow.return_value=1
        self.assertFalse(self.gate.acknowledge())
        with patch.object(fishing,'move_pointer') as move:
            with self.assertRaises(InputPaused):self.inp.aim(1200,800)
            move.assert_not_called()

    def test_pointer_or_navigation_keys_suspend_without_injecting_keys(self):
        for pointer,nav in ((2,False),(1,True)):
            self.gui.GetAncestor.return_value=pointer
            self.user.GetAsyncKeyState.side_effect=lambda key:0x8000 if nav and key==18 else 0
            with self.assertRaises(InputPaused):self.inp.hold(True)
        self.user.keybd_event.assert_not_called();self.user.mouse_event.assert_not_called()

    def test_resume_waits_for_interrupted_cast_and_rechecks_pickup(self):
        self.assertEqual(resumed_stage('casting',True),'waiting')
        self.assertEqual(resumed_stage('casting',False),'casting')
        self.assertEqual(resumed_stage('pickup',False),'pickup_wait')
        self.assertEqual(resumed_stage('tracking',False),'tracking')

    def test_closed_window_releases_and_escalates_instead_of_focus_pause_loop(self):
        self.inp.hold(True);self.gui.IsWindow.return_value=False;self.gate.poll()
        self.assertFalse(self.inp.mouse)
        with self.assertRaisesRegex(RuntimeError,'window closed'):self.gate.check()
        (self.root/'F8_PAUSE').write_text('Paused')
        with self.assertRaises(InputPaused):self.gate.check()

    def test_paused_worker_cannot_trigger_presence_recovery(self):
        present={'ok':True,'type':0};sup={'running':True,'stage':'fishing'}
        worker={'last_game_activity':0}
        self.assertTrue(presence_watch.recovery_needed(present,0,sup,worker,200))
        for state in ('paused_manual','paused_focus'):
            self.assertFalse(presence_watch.recovery_needed(present,0,sup,{**worker,'stage':state},200))
        self.assertFalse(presence_watch.recovery_needed(present,0,{**sup,'manual_paused':True},worker,200))

    def test_actual_worker_keeps_session_on_f8_and_focus_pause(self):
        # Drive the real full-mode loop with a fake screen/clock. No live input.
        now=[100.0];phase=[0];seen=[];ledger=Mock();gate_ref=[]
        def sleep(seconds):
            now[0]+=seconds
            if phase[0]==0 and now[0]>101:
                (self.root/'F8_PAUSE').write_text('Paused');phase[0]=1
            elif phase[0]==1 and now[0]>103:
                (self.root/'F8_PAUSE').unlink();phase[0]=2
            elif phase[0]==2 and now[0]>104:
                self.gui.GetForegroundWindow.return_value=2;phase[0]=3
            elif phase[0]==3 and now[0]>106:
                self.gui.GetForegroundWindow.return_value=1;phase[0]=4
        def status(name,value):
            if name=='status.json':seen.append(dict(value));(self.root/name).write_text(json.dumps(value))
        screen=Mock();screen.capture.return_value=np.zeros((1440,2560,3),np.uint8);screen.point.return_value=(1600,800)
        inventory=Mock();inventory.check_pending.return_value=None
        with patch.object(fishing,'RUN',self.root),patch.object(fishing,'find_window',return_value=1), \
                patch.object(fishing,'rectangle',return_value=(0,0,2560,1440)),patch.object(fishing,'ScreenSpace',return_value=screen), \
                patch.object(fishing,'RapidOCR',return_value=Mock(return_value=([],None))),patch.object(fishing,'detect',return_value=None), \
                patch.object(fishing,'InventoryWatcher',return_value=inventory),patch.object(fishing,'Ledger',return_value=ledger), \
                patch.object(fishing,'write_metrics',side_effect=status),patch.object(fishing,'move_pointer'), \
                patch.object(fishing,'locate_rod',return_value=None),patch.object(fishing.mss,'MSS'), \
                patch.object(fishing.time,'monotonic',side_effect=lambda:now[0]),patch.object(fishing.time,'sleep',side_effect=sleep), \
                patch.object(InputGate,'start'),patch.object(fishing.cv2,'imread',return_value=None), \
                patch.object(sys,'argv',['fishing_assistant.py','--seconds','7']),patch('builtins.print'):
            fishing.main()
        paused=[s for s in seen if s.get('stage') in ('paused_manual','paused_focus')]
        self.assertEqual({s['stage'] for s in paused},{'paused_manual','paused_focus'})
        self.assertTrue(all(not s['held_mouse'] and not s['held_t'] for s in paused))
        events=[json.loads(row) for row in next(self.root.glob('events-*.jsonl')).read_text().splitlines()]
        self.assertEqual(sum(r['event']=='cast' for r in events),1)
        self.assertEqual(sum(r['event']=='input_resumed' for r in events),2)
        self.assertEqual(events[-1]['event'],'session_limit')
        self.assertEqual(seen[-1]['casts'],1)
        self.assertLess(ledger.update.call_args.args[0],8)


if __name__=='__main__':unittest.main()
