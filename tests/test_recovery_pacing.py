import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import recovery
from recovery_pacing import MenuPacer, private_join_target


def private_rows(y=1333):
    return [{'text':'Hold to join private server','center':(1280,1395)},
            {'text':'JOIN','center':(1280,y)}]


class RecoveryPacing(unittest.TestCase):
    def test_animation_and_single_observations_cannot_trigger_input(self):
        gate=MenuPacer()
        gate.observe('private_join',(1280,1366),0)
        self.assertFalse(gate.ready('private_join',1))
        gate.observe('private_join',(1280,1333),1)
        self.assertFalse(gate.ready('private_join',1.1))
        gate.observe('private_join',(1281,1334),1.7)
        self.assertTrue(gate.ready('private_join',1.7))

    def test_transition_does_not_inherit_old_delay_or_erase_retry_limit(self):
        gate=MenuPacer()
        gate.observe('skip_loading',(500,500),0)
        gate.observe('skip_loading',(500,500),1)
        gate.acted('skip_loading',1,8)
        gate.observe('main_menu',(600,600),1.1)
        gate.observe('main_menu',(600,600),1.8)
        self.assertTrue(gate.ready('main_menu',1.8))
        gate.observe('skip_loading',(500,500),2)
        gate.observe('skip_loading',(500,500),2.7)
        self.assertFalse(gate.ready('skip_loading',2.7))

    def test_join_grace_and_backoff_prevent_repeated_teleports(self):
        gate=MenuPacer();gate.joined(1,1)
        gate.observe('world_selection',(520,680),1.1)
        gate.observe('world_selection',(520,680),2)
        self.assertFalse(gate.ready('world_selection',2))
        self.assertTrue(gate.ready('world_selection',4.1))
        gate.joined(5,2)
        self.assertFalse(gate.ready('world_selection',10.9))
        self.assertTrue(gate.ready('world_selection',11.1))
        gate.joined(20,100)
        self.assertEqual(gate.join_grace_until,32)

    def test_world_ready_requires_continuous_world_observations(self):
        gate=MenuPacer();gate.observe('world',None,0);gate.observe('world',None,2)
        self.assertFalse(gate.ready('world_ready',2,3))
        gate.observe('loading',None,2.5);gate.observe('world',None,3)
        gate.observe('world',None,5)
        self.assertFalse(gate.ready('world_ready',5,3))
        gate.observe('world',None,6.1)
        self.assertTrue(gate.ready('world_ready',6.1,3))

    def test_friend_join_and_ambiguous_buttons_are_not_private_join(self):
        self.assertIsNone(private_join_target([{'text':'Friend Join','center':(100,200)},
            {'text':'Join','center':(1280,1366)}]))
        self.assertIsNone(private_join_target(private_rows()+[{'text':'Join','center':(300,400)}]))
        self.assertEqual(private_join_target(private_rows()),(1280,1333))

    def test_private_join_accepts_ocr_collapsed_spaces_in_crop(self):
        rows=[{'text':'Privateserverowner','center':(1278,1264)},
              {'text':'JOIN','center':(1280,1332)},
              {'text':'Holdtojoinprivateserver','center':(1281,1395)}]
        self.assertEqual(private_join_target(rows),(1280,1332))

    def driver(self):
        clock=[0.0]
        driver=recovery.Recovery.__new__(recovery.Recovery)
        driver.inp=Mock();driver.move=Mock();driver.guard=Mock();driver.event=Mock()
        driver.capture=Mock(return_value=object())
        driver.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
        return driver,clock

    def test_revalidation_refuses_stale_or_changed_target_without_pressing(self):
        for rows in ([],private_rows(1366)):
            driver,clock=self.driver();driver.text=Mock(return_value=rows)
            with patch.object(recovery.time,'monotonic',side_effect=lambda:clock[0]):
                self.assertFalse(driver.hold_private_join((1280,1333)))
            driver.inp.hold.assert_not_called()

    def test_hold_releases_as_soon_as_private_panel_changes(self):
        driver,clock=self.driver();driver.text=Mock(side_effect=[private_rows(),private_rows(),[]])
        with patch.object(recovery.time,'monotonic',side_effect=lambda:clock[0]):
            self.assertTrue(driver.hold_private_join((1280,1333)))
        self.assertEqual([call.args for call in driver.inp.hold.call_args_list],[(True,),(False,)])
        self.assertLess(clock[0],1)

    def test_hold_has_bounded_duration_if_panel_never_changes(self):
        driver,clock=self.driver();driver.text=Mock(return_value=private_rows())
        with patch.object(recovery.time,'monotonic',side_effect=lambda:clock[0]):
            driver.hold_private_join((1280,1333))
        self.assertLessEqual(clock[0],5)
        driver.inp.hold.assert_called_with(False)

    def test_stop_focus_change_or_ocr_error_always_releases_hold(self):
        for error in (recovery.UserStop('Stopped'),recovery.RecoveryError('Roblox lost focus'),
                      recovery.RecoveryError('Roblox window changed'),RuntimeError('OCR failed')):
            driver,clock=self.driver();driver.text=Mock(side_effect=[private_rows(),error])
            with patch.object(recovery.time,'monotonic',side_effect=lambda:clock[0]):
                with self.assertRaises(type(error)):driver.hold_private_join((1280,1333))
            self.assertEqual([call.args for call in driver.inp.hold.call_args_list],[(True,),(False,)])

    def test_full_rejoin_handles_animation_then_waits_for_loaded_world(self):
        driver,clock=self.driver();state={'kind':'world','since':0,'holding':False};events=[]
        def transition(kind):state.update(kind=kind,since=clock[0])
        def capture(tag=None):
            if state['kind']=='loading' and clock[0]-state['since']>2:transition('world')
            if state['kind']=='private_join' and state['holding'] and clock[0]-state['held_since']>1:
                transition('loading')
            return dict(state)
        def text(frame,box=None):
            kind=frame['kind']
            if kind=='world':return [{'text':'Mistfall Lv. 50','center':(100,100)}]
            if kind=='private_join':
                return private_rows(1366 if clock[0]-frame['since']<.8 else 1333)
            return {'game_menu':[{'text':'Back to main menu','center':(800,700)}],
                'confirm_menu':[{'text':'Go back to the main menu','center':(1000,700)}],
                'main_menu':[{'text':'Play','center':(600,700)}],
                'world_selection':[{'text':'Ouwland Last played','center':(520,680)}],
                'loading':[]}[kind]
        def click(*args):
            transition({'game_menu':'confirm_menu','confirm_menu':'main_menu',
                        'main_menu':'world_selection','world_selection':'private_join'}[state['kind']])
        def hold(pressed):
            if pressed:
                self.assertEqual(state['kind'],'private_join')
                self.assertGreaterEqual(clock[0]-state['since'],.8)
                state['held_since']=clock[0]
            state['holding']=pressed
        driver.capture=capture;driver.text=text;driver.click=click
        driver.select=Mock();driver.progress=Mock();driver.key=lambda key:transition('game_menu')
        driver.world_visible=lambda frame:frame['kind']=='world'
        driver.equip_rod=Mock();driver.event=lambda event,**kw:events.append((event,clock[0]))
        driver.inp.hold.side_effect=hold
        with patch.object(recovery.time,'monotonic',side_effect=lambda:clock[0]):driver.recover(True)
        driver.equip_rod.assert_called_once()
        self.assertEqual(sum(event=='hold_private_join' for event,_ in events),1)
        self.assertLess(clock[0],20)
        self.assertGreaterEqual(clock[0]-state['since'],3)
        self.assertFalse(state['holding'])


if __name__=='__main__':unittest.main()
