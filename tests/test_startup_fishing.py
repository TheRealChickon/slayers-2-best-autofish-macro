import sys
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import recovery
from full_pause import InputPaused


class CurrentFishingStartup(unittest.TestCase):
    def driver(self,state='world'):
        driver=recovery.Recovery.__new__(recovery.Recovery)
        clock=[0.];scene=[state];frame=np.zeros((1440,2560,3),np.uint8)
        driver.inp=Mock();driver.guard=Mock();driver.progress=Mock();driver.select=Mock();driver.launch=Mock()
        driver.restarts=0;driver.exit_template=frame[:1,:1];driver.capture=Mock(return_value=frame)
        driver.event=Mock();driver.equip_rod=Mock();driver.backstep_after_join=Mock();driver.move=Mock()
        driver.key=Mock(side_effect=lambda *args:scene.__setitem__(0,'world'))
        driver.click=Mock(side_effect=lambda *args:scene.__setitem__(0,'world'))
        driver.world_visible=lambda unused:scene[0]=='world'
        driver.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
        labels={'world':[{'text':'Mistfall Lv. 225','center':(100,100)}],
                'minigame':[],
                'game_menu':[{'text':'Back to main menu','center':(100,100)}],
                'disconnect':[{'text':'Disconnected','center':(1000,700)},
                              {'text':'Reconnect','center':(1280,800)}],
                'challenge':[{'text':'Verify you are human','center':(1280,800)}]}
        driver.text=lambda *unused:labels[scene[0]]
        return driver,clock,scene

    def run_recovery(self,driver,clock,scene,**kwargs):
        with patch.object(recovery.time,'monotonic',side_effect=lambda:clock[0]),\
             patch.object(recovery,'confirm_menu_target',return_value=None),\
             patch.object(recovery,'ui_visible',side_effect=lambda *unused:scene[0] in ('minigame','disconnect','challenge')):
            return driver.recover(**kwargs)

    def test_startup_hands_visible_minigame_to_worker_without_exit_or_menu_input(self):
        driver,clock,scene=self.driver('minigame')
        result=self.run_recovery(driver,clock,scene,force_menu=True,prefer_current=True)
        self.assertEqual(result,'current_minigame')
        driver.click.assert_not_called();driver.key.assert_not_called();driver.launch.assert_not_called()
        driver.equip_rod.assert_not_called();driver.backstep_after_join.assert_not_called()

    def test_existing_world_ignores_startup_rejoin_and_keeps_its_position(self):
        driver,clock,scene=self.driver()
        result=self.run_recovery(driver,clock,scene,force_menu=True,prefer_current=True)
        self.assertEqual(result,'current_world');self.assertGreaterEqual(clock[0],3)
        driver.click.assert_not_called();driver.key.assert_not_called();driver.equip_rod.assert_not_called()
        driver.backstep_after_join.assert_not_called();driver.launch.assert_not_called()

    def test_minigame_appearing_during_world_confirmation_takes_over_immediately(self):
        driver,clock,scene=self.driver()
        def sleep(seconds):
            clock[0]+=seconds
            if clock[0]>=.5:scene[0]='minigame'
        driver.sleep=sleep
        result=self.run_recovery(driver,clock,scene,force_menu=True,prefer_current=True)
        self.assertEqual(result,'current_minigame');self.assertLess(clock[0],1)
        driver.key.assert_not_called();driver.click.assert_not_called()

    def test_startup_closes_existing_inventory_menu_without_selecting_rejoin(self):
        driver,clock,scene=self.driver('game_menu')
        result=self.run_recovery(driver,clock,scene,force_menu=True,prefer_current=True)
        self.assertEqual(result,'current_world');driver.key.assert_called_once_with('M')
        driver.click.assert_not_called();driver.equip_rod.assert_not_called()

    def test_disconnect_overrides_stale_minigame_and_keeps_normal_reconnect(self):
        driver,clock,scene=self.driver('disconnect')
        result=self.run_recovery(driver,clock,scene,force_menu=False,prefer_current=True)
        self.assertEqual(result,'joined_world');driver.click.assert_called_once_with(1280,800)
        driver.event.assert_any_call('disconnect_observed',text='disconnected reconnect')
        driver.equip_rod.assert_called_once()
        self.assertNotIn('startup_current_minigame',[call.args[0] for call in driver.event.call_args_list])

    def test_starting_at_main_menu_still_joins_then_prepares_saved_world(self):
        driver,clock,scene=self.driver();scene[0]='main_menu'
        labels={'main_menu':[{'text':'PLAY','score':.99,'center':(96,629)},
                             {'text':'CUSTOMIZE','center':(138,690)},
                             {'text':'SLOTS','center':(95,812)}],
                'world_selection':[{'text':'Ouwland Last played','center':(520,680)}],
                'private_join':[{'text':'Private Server','center':(1000,1250)},
                                {'text':'Join','center':(1280,1333)}],
                'world':[{'text':'Mistfall Lv. 225','center':(100,100)}]}
        driver.text=lambda *unused:labels[scene[0]]
        def click(*unused):
            scene[0]={'main_menu':'world_selection','world_selection':'private_join'}[scene[0]]
        def join(*unused):scene[0]='world';return True
        driver.click=Mock(side_effect=click);driver.hold_private_join=Mock(side_effect=join)
        result=self.run_recovery(driver,clock,scene,force_menu=True,prefer_current=True)
        self.assertEqual(result,'joined_world');driver.hold_private_join.assert_called_once_with((1280,1333))
        driver.equip_rod.assert_called_once();driver.backstep_after_join.assert_called_once_with(True)
        self.assertNotIn('startup_current_world',[call.args[0] for call in driver.event.call_args_list])

    def test_focus_pause_prevents_startup_handoff(self):
        driver,clock,scene=self.driver('minigame');driver.guard.side_effect=InputPaused('paused_focus')
        with self.assertRaises(InputPaused):self.run_recovery(driver,clock,scene,prefer_current=True)
        driver.capture.assert_not_called();driver.click.assert_not_called()

    def test_challenge_blocks_handoff_even_with_stale_fishing_ui(self):
        driver,clock,scene=self.driver('challenge')
        with self.assertRaisesRegex(recovery.FishingFault,'requires user action'):
            self.run_recovery(driver,clock,scene,prefer_current=True)
        driver.click.assert_not_called();driver.equip_rod.assert_not_called()

    def test_adopted_minigame_skips_saved_alignment_heading_and_title_menus(self):
        driver=Mock();driver.recover.return_value='current_minigame'
        with patch.object(recovery,'load_config',return_value={'camera_heading':270,'auto_fishing_titles':True}),\
             patch.object(recovery.landmarks,'align') as align,\
             patch.object(recovery.landmarks,'restore_heading') as heading,\
             patch.object(recovery,'TitleManager') as titles:
            position,checked=recovery.prepare_worker(driver,True,True,True,False,False,False)
        self.assertTrue(position);self.assertFalse(checked)
        align.assert_not_called();heading.assert_not_called();titles.assert_not_called()

    def test_local_repair_keeps_adopted_position_but_actual_rejoin_restores_saved_setup(self):
        driver=Mock();driver.recover.side_effect=[None,'joined_world']
        with patch.object(recovery,'load_config',return_value={'camera_heading':None,'auto_fishing_titles':True}),\
             patch.object(recovery.landmarks,'align') as align,patch.object(recovery,'TitleManager') as titles:
            self.assertEqual(recovery.prepare_worker(driver,False,True,False,True,False,False),(True,False))
            align.assert_not_called();titles.assert_not_called()
            self.assertEqual(recovery.prepare_worker(driver,True,True,False,True,False,False),(False,True))
        align.assert_called_once_with(driver);titles.return_value.run.assert_called_once()


if __name__=='__main__':unittest.main()
