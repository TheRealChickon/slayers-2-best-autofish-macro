import contextlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import overlay
import status_view
import control_actions

SAMPLE = {'state':'Waiting for a bite', 'mode':'full', 'running':True, 'activity_running':True,
          'active_seconds':9250, 'pace':4.5, 'gold_per_hour':24600, 'bait_remaining_estimate':21452,
          'bait_hours_remaining_estimate':79, 'events':[
              {'at':1792080300+n*60,'text':name,'group':'catches'} for n,name in enumerate(
                  ['Refinement Ore','Zebra Fish','Coral','Krathulon','Refinement Guard'])]}
GEAR = {'rod':'Legendary','enchant':10,'titles':[
    {'name':'Salvager','luck':1.08},{'name':'Legendary Fisherman','luck':1.07,'bite':1.05},
    {'name':'Leviathan Hunter','luck':1.03}]}


class OverlayRender(unittest.TestCase):
    def test_native_surface_keeps_translucency_and_opaque_colored_text(self):
        image=overlay.render(SAMPLE,GEAR)
        self.assertEqual(image.size,(284,436))
        self.assertEqual(image.getpixel((0,0))[3],0)
        self.assertTrue(165 <= image.getpixel((5,200))[3] <= 185)
        pixels=list(image.get_flattened_data())
        self.assertTrue(any(a>245 and g>170 and g>r*1.4 for r,g,b,a in pixels))
        self.assertTrue(any(a>245 and r>220 and g>155 and b<120 for r,g,b,a in pixels))
        self.assertEqual(overlay.render(SAMPLE,GEAR,1.5).size,(426,654))

    @unittest.skipUnless(os.name=='nt','Native Windows window')
    def test_real_hidden_window_is_click_through_and_never_activates(self):
        import win32gui, win32con
        before=win32gui.GetForegroundWindow()
        item=overlay.Overlay()
        with patch.object(overlay,'roblox_window',return_value=None):
            try:
                item.start('http://127.0.0.1:12345/overlay?t=fixture')
                self.assertTrue(item.running,item.error)
                hwnd=item.hwnd
                style=win32gui.GetWindowLong(hwnd,win32con.GWL_EXSTYLE)
                for flag in (win32con.WS_EX_LAYERED,win32con.WS_EX_TRANSPARENT,win32con.WS_EX_NOACTIVATE):
                    self.assertTrue(style & flag)
                self.assertEqual(win32gui.SendMessage(hwnd,win32con.WM_NCHITTEST,0,0),win32con.HTTRANSPARENT)
                self.assertFalse(win32gui.IsWindowVisible(hwnd))
                self.assertEqual(win32gui.GetForegroundWindow(),before)
            finally: item.stop()
        self.assertFalse(item.running)
        self.assertFalse(win32gui.IsWindow(hwnd))


class ActivityClock(unittest.TestCase):
    def test_clock_needs_fresh_fishing_and_actual_roblox_focus(self):
        import win32gui,win32process,psutil
        supervisor={'stage':'fishing'}
        worker={'stage':'waiting','updated':100,'running':True}
        with patch.object(win32gui,'GetForegroundWindow',return_value=42),patch.object(win32gui,'IsIconic',return_value=False), \
             patch.object(win32process,'GetWindowThreadProcessId',return_value=(1,2)),patch.object(psutil,'Process') as process:
            process.return_value.name.return_value='RobloxPlayerBeta.exe'
            self.assertTrue(status_view.activity_running(supervisor,worker,True,now=101))
            for stage in ('paused_focus','paused_manual','assist_waiting','inventory','select_spot','waiting_game'):
                self.assertFalse(status_view.activity_running(supervisor,{**worker,'stage':stage},True,now=101))
            self.assertFalse(status_view.activity_running(supervisor,worker,True,held=True,now=101))
            self.assertFalse(status_view.activity_running(supervisor,worker,True,now=110))
            self.assertFalse(status_view.activity_running(supervisor,worker,False,now=101))
            self.assertFalse(status_view.activity_running({'stage':'rejoining'},worker,True,now=101))
            process.return_value.name.return_value='msedge.exe'
            self.assertFalse(status_view.activity_running(supervisor,worker,True,now=101))


class ModeSwitch(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        for item in (patch.object(control_actions,'RUN',self.root),
                     patch.object(control_actions,'guard',side_effect=contextlib.nullcontext),
                     patch.object(control_actions,'refuse_peer_controller'),
                     patch.object(control_actions,'starting',return_value=False)):
            item.start();self.addCleanup(item.stop)

    def test_switch_waits_for_exit_and_keeps_the_pause_for_resume(self):
        active=[True]
        def alive(name='supervisor-pid.json'):return active[0] if name in ('supervisor-pid.json','pid.json') else False
        def pause(): (self.root/'PAUSE').write_text('switch'); (self.root/'STOP').write_text('switch')
        def wait(_): active[0]=False
        def resume(mode):
            self.assertFalse(active[0]); self.assertTrue((self.root/'PAUSE').exists());return 'Started'
        with patch.object(control_actions,'alive',side_effect=alive),patch.object(control_actions,'pause',side_effect=pause), \
             patch.object(control_actions.time,'sleep',side_effect=wait),patch.object(control_actions,'resume',side_effect=resume) as start:
            self.assertEqual(control_actions.switch_mode('assist'),'Started');start.assert_called_once_with('assist')

    def test_new_manual_stop_cancels_switch_without_resuming(self):
        def alive(name='supervisor-pid.json'):return name=='supervisor-pid.json'
        def pause(): (self.root/'PAUSE').write_text('switch')
        def wait(_): (self.root/'STOP').write_text('user stopped')
        with patch.object(control_actions,'alive',side_effect=alive),patch.object(control_actions,'pause',side_effect=pause), \
             patch.object(control_actions.time,'sleep',side_effect=wait),patch.object(control_actions,'resume') as start:
            with self.assertRaisesRegex(RuntimeError,'manual hold'):control_actions.switch_mode('assist')
            start.assert_not_called();self.assertEqual((self.root/'STOP').read_text(),'user stopped')

    def test_other_controller_blocks_switch(self):
        with patch.object(control_actions,'alive',return_value=True),patch.object(control_actions,'pause') as pause:
            with self.assertRaisesRegex(RuntimeError,'other controller'):control_actions.switch_mode('assist')
            pause.assert_not_called()

if __name__=='__main__':unittest.main()
