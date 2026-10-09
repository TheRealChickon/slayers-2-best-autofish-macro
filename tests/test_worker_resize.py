"""Replay the real worker loop with mocked capture, clock, window and input."""
import json
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fishing_assistant as fishing
from full_pause import InputGate
from screen_space import ScreenSpace


class WorkerResizeTests(unittest.TestCase):
    def test_resize_and_unreadable_transition_keep_worker_session_and_counters(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);now=[100.];saved=[];ledger=Mock()
            def rectangle(hwnd):
                if now[0]<101:return (0,0,2560,1440)
                if now[0]<101.3:return (20,30,520,330)  # unreadable transient size
                if now[0]<101.6:return (20,30,2020+int((now[0]-101.3)*100),1230)
                return (-3440,30,0,1470)  # stable ultrawide on a negative-origin monitor
            screens=[]
            def make_screen(rect):
                real=ScreenSpace(rect)
                screen=Mock(ui_scale=real.ui_scale,rect=rect)
                screen.capture.return_value=np.zeros((1440,2560,3),np.uint8)
                screen.capture_ui.return_value=np.zeros((600,140,3),np.uint8)
                screen.point.side_effect=real.point;screens.append(screen)
                return screen
            def write(name,value):
                if name=='status.json':
                    saved.append(dict(value));(root/name).write_text(json.dumps(value))
            inventory=Mock();inventory.check_pending.return_value=None
            user=Mock()
            with ExitStack() as stack:
                contexts=(patch.object(fishing,'RUN',root),patch.object(fishing,'USER',user),
                 patch.object(fishing,'find_window',return_value=7),patch.object(fishing,'rectangle',side_effect=rectangle), \
                 patch.object(fishing,'ScreenSpace',side_effect=make_screen), \
                 patch.object(fishing.win32gui,'IsWindow',return_value=True), \
                 patch.object(fishing.win32gui,'IsIconic',return_value=False), \
                 patch.object(fishing.win32gui,'GetForegroundWindow',return_value=7), \
                 patch.object(fishing.win32gui,'WindowFromPoint',return_value=7), \
                 patch.object(fishing.win32gui,'GetAncestor',return_value=7), \
                 patch.object(fishing.win32gui,'GetCursorPos',return_value=(1650,800)), \
                 patch.object(fishing,'RapidOCR',return_value=Mock(return_value=([],None))), \
                 patch.object(fishing,'detect',return_value=None),patch.object(fishing,'locate_rod',return_value=None), \
                 patch.object(fishing,'InventoryWatcher',return_value=inventory),patch.object(fishing,'Ledger',return_value=ledger), \
                 patch.object(fishing,'write_metrics',side_effect=write),patch.object(fishing,'read_metrics',return_value={}), \
                 patch.object(fishing,'move_pointer'),patch.object(fishing,'Listener'), \
                 patch.object(fishing,'PhysicalActivity',return_value=Mock(last=100.,last_other_input=None)), \
                 patch.object(fishing.mss,'MSS'),patch.object(InputGate,'start'), \
                 patch.object(fishing.time,'monotonic',side_effect=lambda:now[0]), \
                 patch.object(fishing.time,'sleep',side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)), \
                 patch.object(sys,'argv',['fishing_assistant.py','--seconds','4']),patch('builtins.print'))
                for context in contexts:stack.enter_context(context)
                user.GetAsyncKeyState.return_value=0
                fishing.main()
            events=[json.loads(line) for line in next(root.glob('events-*.jsonl')).read_text().splitlines()]
            self.assertEqual(sum(row['event']=='started' for row in events),1)
            reacquired=[row for row in events if row['event']=='client_reacquired']
            self.assertEqual(len(reacquired),1)
            self.assertEqual(reacquired[0]['rect'],[-3440,30,0,1470])
            self.assertEqual(len(screens),2)
            self.assertIs(inventory.scanner.screen,screens[-1])
            self.assertEqual(saved[-1]['casts'],1)
            self.assertEqual(len({row['session'] for row in saved}),1)
            waits=[row for row in saved if row.get('stage')=='window_wait']
            self.assertTrue(waits)
            self.assertTrue(all(not row['held_mouse'] and not row['held_t'] for row in waits))
            self.assertEqual(events[-1]['event'],'session_limit')
            self.assertFalse(saved[-1]['held_mouse']);self.assertFalse(saved[-1]['held_t'])


if __name__=='__main__':unittest.main()
