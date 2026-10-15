import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import fishing_assistant as fishing


class ClickSettling(unittest.TestCase):
    def test_primary_screen_input_uses_primary_coordinates_on_two_monitors(self):
        with patch.object(fishing.win32api,'EnumDisplayMonitors',return_value=[(None,None,(0,0,2560,1440)),(None,None,(2560,0,5120,1440))]), \
                patch.object(fishing.win32gui,'GetCursorPos',return_value=(1280,1332)),patch.object(fishing,'USER') as user:
            user.GetSystemMetrics.side_effect=lambda key:{0:2560,1:1440}[key]
            fishing.move_pointer(1280,1332)
            flags,x,y,_,_=user.mouse_event.call_args.args
            self.assertEqual(flags,0x8001)
            self.assertLess(abs(x/65535*2559-1280),1)
            user.SetCursorPos.assert_not_called()

    def test_secondary_screen_keeps_virtual_mapping_and_verifies_position(self):
        with patch.object(fishing.win32api,'EnumDisplayMonitors',return_value=[(None,None,(-1920,0,0,1080)),(None,None,(0,0,2560,1440))]), \
                patch.object(fishing.win32gui,'GetCursorPos',side_effect=[(-999,100),(-1000,100)]),patch.object(fishing,'USER') as user:
            user.GetSystemMetrics.side_effect=lambda key:{0:2560,1:1440}[key]
            fishing.move_pointer(-1000,100)
            flags,x,y,_,_=user.mouse_event.call_args.args
            self.assertEqual(flags,0xC001)
            self.assertLess(abs(x/65535*4479-920),1)

    def test_first_cast_after_menu_waits_for_slower_game_hover(self):
        now=[100.0];hover_ready=[0]
        def move(*args):hover_ready[0]=now[0]+.22
        def press(*args):self.assertGreaterEqual(now[0],hover_ready[0])
        with tempfile.TemporaryDirectory() as folder,patch.object(fishing,'RUN',Path(folder)), \
                patch.object(fishing,'move_pointer',side_effect=move),patch.object(fishing,'USER') as user, \
                patch.object(fishing.time,'monotonic',side_effect=lambda:now[0]), \
                patch.object(fishing.time,'sleep',side_effect=lambda duration:now.__setitem__(0,now[0]+duration)):
            user.GetAsyncKeyState.return_value=0;user.mouse_event.side_effect=press
            inp=fishing.Input();inp.aim(1650,800,after_menu=True);inp.hold(True)
            user.mouse_event.assert_called_once()

    def test_click_waits_for_game_hover_at_final_position(self):
        now=[100.0];hover_ready=[0];point=[None]
        def move(x,y):
            point[0]=(x,y);hover_ready[0]=now[0]+.05
        def press(*args):
            self.assertEqual(point[0],(1650,800))
            self.assertGreaterEqual(now[0],hover_ready[0])
        with tempfile.TemporaryDirectory() as folder,patch.object(fishing,'RUN',Path(folder)), \
                patch.object(fishing,'move_pointer',side_effect=move),patch.object(fishing,'USER') as user, \
                patch.object(fishing.time,'monotonic',side_effect=lambda:now[0]), \
                patch.object(fishing.time,'sleep',side_effect=lambda duration:now.__setitem__(0,now[0]+duration)):
            user.GetAsyncKeyState.return_value=0
            user.mouse_event.side_effect=press
            inp=fishing.Input();inp.aim(1650,800);inp.hold(True)
            user.mouse_event.assert_called_once()

    def test_repeat_cast_skips_settle_only_while_known_pointer_is_unchanged(self):
        inp=fishing.Input()
        with patch.object(fishing.win32gui,'GetCursorPos',side_effect=[(1650,800)]*2+[(1640,800),(1650,800)]), \
             patch.object(inp,'aim') as settle:
            inp.aim_cast(1650,800,after_menu=True)
            self.assertEqual(settle.call_count,1)
            inp.aim_cast(1650,800)
            self.assertEqual(settle.call_count,1)
            inp.aim_cast(1650,800)
            self.assertEqual(settle.call_count,2)
            inp.cast_target=None  # A menu or focus pause invalidates hover state.
            inp.aim_cast(1650,800)
            self.assertEqual(settle.call_count,3)

    def test_manual_stop_or_focus_loss_during_aim_blocks_click(self):
        for reason in ('stop','focus'):
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as folder, \
                    patch.object(fishing,'RUN',Path(folder)),patch.object(fishing,'move_pointer'), \
                    patch.object(fishing,'USER') as user,patch.object(fishing.Input,'guard_press') as guard:
                user.GetAsyncKeyState.return_value=0
                def interrupt(*args):
                    if reason=='stop':(Path(folder)/'STOP').write_text('Stopped by user')
                    else:guard.side_effect=RuntimeError('Roblox lost focus')
                with patch.object(fishing.time,'sleep',side_effect=interrupt):
                    inp=fishing.Input()
                    with self.assertRaises(RuntimeError):
                        inp.aim(1650,800);inp.hold(True)
                user.mouse_event.assert_not_called()


if __name__=='__main__':unittest.main()
