import ctypes
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import cv2
import numpy as np
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fishing_assistant as fishing
from client_geometry import ClientAreaChanged, ClientStability, client_rect, enable_physical_coordinates
from fishing_vision import detect, ui_visible
from full_pause import InputGate
from pickup_policy import Pickup, PickupSearch
from screen_space import ScreenSpace


class GeometryTests(unittest.TestCase):
    def test_thread_dpi_override_survives_an_existing_process_mode(self):
        user=Mock()
        user.SetProcessDpiAwarenessContext.return_value=0
        user.SetThreadDpiAwarenessContext.return_value=123
        self.assertEqual(enable_physical_coordinates(user),'per_monitor_v2')
        self.assertEqual(user.SetThreadDpiAwarenessContext.call_args.args[0].value,ctypes.c_void_p(-4).value)
        user.SetProcessDPIAware.assert_not_called()

    def test_legacy_windows_fallback_is_bounded(self):
        user=SimpleNamespace(SetProcessDPIAware=Mock())
        self.assertEqual(enable_physical_coordinates(user),'legacy')
        user.SetProcessDPIAware.assert_called_once()

    def test_physical_offset_client_is_not_scaled_a_second_time(self):
        gui=Mock()
        gui.GetClientRect.return_value=(0,0,1920,1080)
        gui.ClientToScreen.return_value=(-1920,240)
        rect=client_rect(gui,7)
        self.assertEqual(rect,(-1920,240,0,1320))
        screen=ScreenSpace(rect)
        self.assertEqual(screen.point(1280,720),(-960,780))
        self.assertEqual(screen.unpoint(-960,780),(1280,720))

    def test_repeated_resize_waits_until_the_latest_client_settles(self):
        state=ClientStability((0,0,2560,1440))
        self.assertFalse(state.observe((8,30,1928,1110),1))
        self.assertFalse(state.observe((8,30,1608,930),1.1))
        self.assertFalse(state.observe((8,30,1608,930),1.2))
        self.assertTrue(state.observe((8,30,1608,930),1.3))
        self.assertEqual(state.current,(8,30,1608,930))
        self.assertTrue(state.observe(state.current,2))

    def test_native_uniform_marker_and_real_exit_template_across_aspects(self):
        marker=np.zeros((600,140,3),np.uint8)
        cv2.rectangle(marker,(25,190),(90,290),(20,190,30),-1)
        cv2.circle(marker,(64,240),12,(245,245,245),-1)
        template=cv2.imread(str(Path(fishing.__file__).parent/'assets/exit.png'))
        sizes=((960,540),(1280,720),(1920,1080),(2560,1440),(3840,2160),
               (3440,1440),(5120,1440),(1280,1024),(1920,1200))
        for width,height in sizes:
            with self.subTest(size=(width,height)):
                offset=(-2000,120)
                screen=ScreenSpace((offset[0],offset[1],offset[0]+width,offset[1]+height))
                pixels=np.zeros((height,width,3),np.uint8)
                for image,box in ((marker,(1850,400,140,600)),(template,(1190,1360,180,70))):
                    x,y,w,h=box
                    cx,cy=screen.point(x+w/2,y+h/2)
                    left=round(cx-w*screen.ui_scale/2)-offset[0]
                    top=round(cy-h*screen.ui_scale/2)-offset[1]
                    right=round(cx+w*screen.ui_scale/2)-offset[0]
                    bottom=round(cy+h*screen.ui_scale/2)-offset[1]
                    normalized=np.zeros((h,w,3),np.uint8)
                    ih,iw=image.shape[:2]
                    normalized[(h-ih)//2:(h-ih)//2+ih,(w-iw)//2:(w-iw)//2+iw]=image
                    pixels[top:bottom,left:right]=cv2.resize(normalized,(right-left,bottom-top))
                class Replay:
                    def grab(self,region):
                        x,y=region['left']-offset[0],region['top']-offset[1]
                        return pixels[y:y+region['height'],x:x+region['width']]
                result=detect(screen.capture_ui(Replay(),(1850,400,140,600)))
                self.assertIsNotNone(result)
                self.assertTrue(result['inside'])
                self.assertAlmostEqual(result['ball'],240,delta=3)
                self.assertTrue(ui_visible(screen.capture_ui(Replay(),(1190,1360,180,70)),template))
                self.assertFalse(ui_visible(np.zeros((70,180,3),np.uint8),template))

    def test_crop_outside_client_is_rejected_before_capture(self):
        capture=Mock()
        with self.assertRaises(ValueError):ScreenSpace((0,0,1280,1024)).capture(capture,(2500,0,140,600))
        capture.grab.assert_not_called()

    def test_resize_after_ocr_blocks_a_stale_key_press(self):
        inp=fishing.Input(7);inp.client_rect=(0,0,2560,1440)
        with patch.object(fishing.win32gui,'IsWindow',return_value=True), \
             patch.object(fishing.win32gui,'IsIconic',return_value=False), \
             patch.object(fishing.win32gui,'GetForegroundWindow',return_value=7), \
             patch.object(fishing,'rectangle',return_value=(20,20,1940,1100)), \
             patch.object(fishing,'USER') as user:
            with self.assertRaises(ClientAreaChanged):inp.grab(True)
            user.keybd_event.assert_not_called()

    def test_release_attempts_t_even_if_mouse_release_fails(self):
        inp=fishing.Input()
        with patch.object(inp,'hold',side_effect=RuntimeError('mouse release failure')),patch.object(inp,'grab') as key:
            with self.assertRaises(RuntimeError):inp.release()
            key.assert_called_once_with(False)

    def test_real_activity_yields_without_clearing_manual_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);activity=SimpleNamespace(last=10,last_other_input=None)
            gate=InputGate(SimpleNamespace(hwnd=None),root,Mock(),activity=activity)
            with patch('full_pause.time.monotonic',return_value=11):self.assertIsNone(gate.reason())
            activity.last=20
            with patch('full_pause.time.monotonic',return_value=30):self.assertEqual(gate.reason(),'paused_human')
            with patch('full_pause.time.monotonic',return_value=65):self.assertIsNone(gate.reason())
            activity.last_other_input=65
            with patch('full_pause.time.monotonic',return_value=70):self.assertEqual(gate.reason(),'paused_competing_input')
            (root/'F8_PAUSE').write_text('user pause')
            with patch('full_pause.time.monotonic',return_value=200):self.assertEqual(gate.reason(),'paused_manual')
            self.assertEqual((root/'F8_PAUSE').read_text(),'user pause')

    def test_confirmed_prompt_cache_expires_and_never_supplies_evidence(self):
        search=PickupSearch()
        self.assertEqual(search.boxes(10),(search.default,search.wide))
        search.remember(Pickup('collect','Collect',(1300,700)),False,10)
        self.assertIsNone(search.center)
        search.remember(Pickup('collect','Collect',(1300,700)),True,10)
        self.assertEqual(search.boxes(20)[0],(1060,590,480,220))
        self.assertEqual(search.boxes(56)[0],search.default)
        self.assertEqual(search.boxes(5)[0],search.default)
        search.reset();self.assertIsNone(search.center)


if __name__=='__main__':unittest.main()
