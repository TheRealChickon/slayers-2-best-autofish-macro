import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fishing_assistant as fishing


class ClickSettling(unittest.TestCase):
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
