import io
import tempfile
import unittest
import cv2
import numpy as np
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, Mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import boss_farmer
import fishing_cli
from boss_plan import BossObservation, FightLedger, can_attack, validate_boss
from boss_vision import boss_from_rows, health_pair, respawn_timer, player_bar_fraction, world_name, combat_hud_visible, chat_send_button
from boss_tracking import BossTracker, Target
from boss_loot import prompt_from_rows,reward_from_rows


def reading(hp=3000, **values):
    return BossObservation(**{'name': 'Saneri', 'hp': hp, 'maximum': 3000,
                              'target': (1300, 700), 'player_fraction': 1., **values})


class BossEvidence(unittest.TestCase):
    def test_world_name_handles_waypoint_overlap_without_accepting_other_people(self):
        for name in ('Saneri Shinazugawa','SaneriShinazugawa','1721mSaneri Shinazugawa','172*maneri Shinazugawa'):
            self.assertTrue(world_name(name),name)
        for name in ('Datai','Grofheyse3729','SaneriFan','Wind Hashira'):
            self.assertFalse(world_name(name),name)

    def test_cutscene_flash_is_not_a_returned_combat_hud(self):
        for value in (0,255):
            frame=np.full((1440,2560,3),value,dtype=np.uint8)
            self.assertFalse(combat_hud_visible(frame))
        frame=np.zeros((1440,2560,3),dtype=np.uint8)
        frame[1404:1418,50:305,2]=200
        self.assertFalse(combat_hud_visible(frame))
        frame[1280:1310,1100:1400]=240
        self.assertTrue(combat_hud_visible(frame))

    def test_spawn_send_requires_one_blue_button_in_the_chat_field(self):
        frame=np.zeros((1440,2560,3),dtype=np.uint8)
        self.assertIsNone(chat_send_button(frame,410))
        frame[395:425,440:470,0]=230
        self.assertEqual(chat_send_button(frame,410),(454.5,409.5))
        frame[395:425,380:410,0]=230
        self.assertIsNone(chat_send_button(frame,410))

    def test_missing_header_does_not_mean_kill_or_reset(self):
        ledger = FightLedger()
        ledger.observe(reading(), 1)
        ledger.observe(reading(), 2)
        for now in range(3, 20):
            self.assertIsNone(ledger.observe(BossObservation(), now))
        self.assertEqual(ledger.kills, 0)
        self.assertEqual(ledger.retention, 'untested')
        self.assertEqual(ledger.hp, 3000)

    def test_two_zero_readings_confirm_exactly_one_kill(self):
        ledger = FightLedger()
        for hp, now in ((3000, 1), (3000, 2), (1, 3), (1, 4)):
            ledger.observe(reading(hp), now)
        self.assertIsNone(ledger.observe(reading(0), 5))
        self.assertEqual(ledger.kills, 0)
        self.assertEqual(ledger.observe(reading(0), 6), 'kill')
        for now in range(7, 15):
            ledger.observe(reading(0), now)
        self.assertEqual(ledger.kills, 1)
        self.assertEqual(ledger.damage, 3000)

    def test_other_boss_and_blocked_scenes_cannot_change_totals(self):
        ledger = FightLedger()
        for _ in range(3):
            ledger.observe(reading(0, name='Gyutai'), 1)
            ledger.observe(reading(0, blocked=True), 2)
        self.assertIsNone(ledger.hp)
        self.assertEqual(ledger.kills, 0)

    def test_reset_retention_is_unknown_until_stable_reacquisition(self):
        for after, expected in ((1800, 'retained'), (3000, 'healed')):
            ledger = FightLedger()
            ledger.observe(reading(1800), 1)
            ledger.observe(reading(1800), 2)
            ledger.before_reset()
            ledger.observe(BossObservation(), 3)
            self.assertEqual(ledger.retention, 'checking')
            ledger.observe(reading(after), 4)
            self.assertEqual(ledger.retention, 'checking')
            ledger.observe(reading(after), 5)
            self.assertEqual(ledger.retention, expected)

    def test_attack_requires_identity_health_target_and_clear_scene(self):
        self.assertTrue(can_attack(reading()))
        for fields in ({'name': 'Datai'}, {'hp': None}, {'hp': 0}, {'target': None},
                       {'player_fraction': None}, {'player_fraction': .2}, {'blocked': True},
                       {'respawn_seconds': 299}):
            self.assertFalse(can_attack(reading(**fields)))

    def test_visible_timer_overrides_stale_hp_and_target(self):
        row=lambda text,x=1000,y=220:dict(text=text,x=x,y=y,score=.99)
        result=boss_from_rows([row('Saneri'),row('3000 / 3000'),row('Spawns in 4:59')],
                              [row('Saneri',1100,600)],[])
        self.assertEqual(result.respawn_seconds,299)
        self.assertIsNone(result.hp)
        self.assertIsNone(result.target)
        self.assertFalse(can_attack(result))
        self.assertEqual(respawn_timer('Spawns in 0:02'),2)
        self.assertEqual(respawn_timer('Spawns in 55s'),55)
        for text in ('Spawns in 4:99','Cooldown 4:59','Spawns in 99:00'):
            self.assertIsNone(respawn_timer(text))

    def test_loot_requires_a_named_prompt_action_and_nearby_t(self):
        row=lambda text,x,y:dict(text=text,x=x,y=y,score=.99,height=25)
        valid=[row('T',900,800),row('World Events Chest',1100,775),row('Open',1080,810)]
        self.assertEqual(prompt_from_rows(valid).action,'open')
        self.assertIsNone(prompt_from_rows(valid[1:]))
        self.assertIsNone(prompt_from_rows([row('T',900,800),row('Wall',1100,775),row('Climb',1100,810)]))
        reward=[row('Coin Pouch',1400,720),row('x4',1400,745)]
        self.assertIsNone(prompt_from_rows(reward))
        self.assertEqual(reward_from_rows(reward),[('Coin Pouch',4)])
        reward[1]['x']=1800
        self.assertEqual(reward_from_rows(reward),[])
        silk=[row('T',900,800),row('Silk Thread',1100,775),row('Claim',1080,810)]
        self.assertEqual(prompt_from_rows(silk).name,'Silk Thread')

    def test_timer_confirms_defeat_once_without_inventing_a_zero_frame(self):
        ledger=FightLedger()
        ledger.observe(reading(200),1);ledger.observe(reading(200),2)
        timer=lambda seconds:BossObservation(name='Saneri',respawn_seconds=seconds)
        self.assertIsNone(ledger.observe(timer(300),3))
        self.assertEqual(ledger.observe(timer(299),4),'kill')
        for now in range(5,20):ledger.observe(timer(303-now),now)
        self.assertEqual(ledger.kills,1)
        self.assertEqual(ledger.hp,0)
        self.assertEqual(ledger.damage,200)

    def test_initial_or_inconsistent_timer_does_not_claim_a_kill(self):
        ledger=FightLedger()
        for now in (1,2,3):ledger.observe(BossObservation(name='Saneri',respawn_seconds=200-now),now)
        self.assertEqual(ledger.kills,0)
        ledger.observe(reading(),4);ledger.observe(reading(),5)
        ledger.observe(BossObservation(name='Saneri',respawn_seconds=100),6)
        ledger.observe(BossObservation(name='Saneri',respawn_seconds=299),7)
        self.assertEqual(ledger.kills,0)

    def test_health_bar_fallback_rejects_disjoint_red_pixels(self):
        frame=np.zeros((1440,2560,3),dtype=np.uint8)
        self.assertIsNone(player_bar_fraction(frame))
        frame[1404:1418,50:305,2]=200
        self.assertEqual(player_bar_fraction(frame),1.)
        frame[1404:1418,180:305]=0
        self.assertAlmostEqual(player_bar_fraction(frame),130/255)
        frame[1404:1418,280:295,2]=200
        self.assertIsNone(player_bar_fraction(frame))

    def test_duplicate_appearance_matches_are_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            texture=np.random.default_rng(4).integers(0,255,(30,35),dtype=np.uint8)
            cv2.imwrite(str(Path(directory)/'head-test.png'),texture)
            frame=np.zeros((720,1280,3),dtype=np.uint8)
            patch_image=cv2.cvtColor(texture,cv2.COLOR_GRAY2BGR)
            frame[300:330,300:335]=patch_image
            tracker=BossTracker(directory,threshold=.9)
            full=cv2.resize(frame,(2560,1440),interpolation=cv2.INTER_NEAREST)
            self.assertIsNotNone(tracker.acquire(full,1))
            frame[300:330,850:885]=patch_image
            full=cv2.resize(frame,(2560,1440),interpolation=cv2.INTER_NEAREST)
            self.assertIsNone(tracker.acquire(full,2))
            self.assertIsNone(tracker.update(full,3,False))

    def test_foggy_grass_does_not_merge_into_the_named_head(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker=BossTracker(directory)
            frame=np.full((1440,2560,3),(100,140,95),dtype=np.uint8)
            self.assertIsNone(tracker.from_label(frame,(1280,500),1,32))
            texture=np.random.default_rng(8).integers(115,230,(110,180),dtype=np.uint8)
            frame[580:690,1190:1370]=cv2.cvtColor(texture,cv2.COLOR_GRAY2BGR)
            target=tracker.from_label(frame,(1280,500),2,32)
            self.assertIsNotNone(target)
            self.assertLess(abs(target.center[0]-1280),10)
            self.assertLess(target.box[2],220)

    def test_configuration_rejects_forbidden_moves_and_unverified_reset(self):
        for key in ('v', 'n', 'k', 'l', 'esc', 'm'):
            with self.assertRaises(ValueError):
                validate_boss({'block_breaker': key})
        with self.assertRaises(ValueError):
            validate_boss({'reset_after_combo': True})
        with self.assertRaises(ValueError):
            validate_boss({'m1_interval': float('nan')})

    def test_fixed_health_header_is_not_a_world_target(self):
        def row(text, x, y):
            return {'text': text, 'x': x, 'y': y, 'score': .99}
        header = [row('Saneri', 1300, 205), row('1,670.38 / 3000', 970, 255)]
        player = [row('1980 / 1980', 250, 1385)]
        result = boss_from_rows(header, header, player)
        self.assertEqual(result.hp, 1670.38)
        self.assertIsNone(result.target)
        result = boss_from_rows(header, [row('Saneri', 1100, 650)], player)
        self.assertEqual(result.target, (1100, 650))
        result = boss_from_rows(header, [row('Saneri', 1100, 650), row('Sanemi', 1500, 800)], player)
        self.assertIsNone(result.target)

    def test_health_parser_rejects_ambiguous_and_impossible_pairs(self):
        self.assertEqual(health_pair('1820.32 / 3000'), (1820.32, 3000))
        for value in ('3000', '4000 / 3000', '0 / 0', 'Saneri'):
            self.assertIsNone(health_pair(value))


class BossInputRelease(unittest.TestCase):
    def test_last_allowed_combo_can_collect_loot_without_an_extra_attack(self):
        session=boss_farmer.BossSession.__new__(boss_farmer.BossSession)
        session.config=validate_boss({'spawn_verified':True,'reset_after_combo':True,'max_cycles':1})
        session.cycles=1;session.loot_attempted=False
        session.scan=Mock(return_value=(BossObservation(name='Saneri',respawn_seconds=299),None))
        session.collect_loot=Mock();session.cycle=Mock()
        session.farm(Mock())
        session.collect_loot.assert_called_once()
        session.cycle.assert_not_called()

    def test_final_range_check_rejects_a_target_that_moved_away(self):
        session=boss_farmer.BossSession.__new__(boss_farmer.BossSession)
        session.config=validate_boss({'target_timeout':2})
        session.target=Target((1200,550,180,140),.95,'test')
        session.track_step=Mock(return_value=(reading(),None))
        session.tap=session.wait=Mock()
        def moved(*args):
            session.target=Target((1200,450,65,50),.95,'test')
            return reading(),None
        session.scan=Mock(side_effect=moved)
        with patch.object(boss_farmer.time,'monotonic',side_effect=[0,0,3]), \
             patch.object(boss_farmer,'gauntlet_selected',return_value=True):
            with self.assertRaisesRegex(RuntimeError,'reacquisition'):
                session.acquire(Mock())
        session.scan.assert_called_once()

    def test_spawn_command_uses_wide_characters_and_verifies_send(self):
        session=boss_farmer.BossSession.__new__(boss_farmer.BossSession)
        session.click=session.wait=session.event=Mock()
        session.inp=Mock();session.screen=Mock();session.ocr=Mock()
        session.spawn_updates=0
        row=lambda text:dict(text=text,x=180,y=410,score=.99)
        def scan(character):
            self.assertIsInstance(character,boss_farmer.ctypes.c_wchar)
            return 0x0137 if character.value=='/' else ord(character.value.upper())
        with patch.object(boss_farmer,'USER') as user, \
             patch.object(boss_farmer,'rows_in',side_effect=[[row('Click here to chat')],[row('/set')],[],[row('SpawnSet')]]), \
             patch.object(boss_farmer,'chat_send_button',return_value=(455,410)):
            user.VkKeyScanW.side_effect=scan
            session.set_spawn(Mock())
        self.assertEqual(session.spawn_updates,1)
        self.assertEqual([call.args[0].value for call in user.VkKeyScanW.call_args_list],list('/set'))
        session.inp.key_code.assert_any_call(16,True)
        session.inp.key_code.assert_any_call(16,False)
        session.click.assert_any_call(455,410)

    def test_short_tracking_step_cannot_confirm_cached_health(self):
        session=boss_farmer.BossSession.__new__(boss_farmer.BossSession)
        session.guard=Mock();session.scan=Mock();session.ledger=Mock()
        session.last_identity_at=boss_farmer.time.monotonic()
        session.target=Target((1100,600,220,180),.95,'test')
        session.observation=reading(2500)
        session.screen=Mock();session.tracker=Mock()
        session.tracker.update.return_value=session.target
        with patch.object(boss_farmer,'player_bar_fraction',return_value=1.), \
             patch.object(boss_farmer,'combat_hud_visible',return_value=True):
            result,_=session.track_step(Mock())
        self.assertEqual(result.hp,2500)
        self.assertEqual(result.target,session.target.center)
        session.ledger.observe.assert_not_called()
        session.scan.assert_not_called()
        session.last_identity_at=0.
        session.scan.return_value=(reading(2490),None)
        self.assertEqual(session.track_step(Mock())[0].hp,2490)
        session.scan.assert_called_once()

    def test_normal_b_returns_only_when_combat_hud_has_returned(self):
        session=boss_farmer.BossSession.__new__(boss_farmer.BossSession)
        session.tap=session.guard=session.wait=session.evidence=Mock()
        session.actions=0
        session.screen=Mock()
        frames=[object(),object(),object()]
        session.screen.capture.side_effect=frames
        with patch.object(boss_farmer,'cutscene_visible',side_effect=[True,False,False]), \
             patch.object(boss_farmer,'combat_hud_visible',side_effect=[False,False,True]):
            result=session.normal_b(Mock(),3000)
        self.assertIs(result,frames[-1])
        self.assertEqual(session.screen.capture.call_count,3)

    def test_focus_loss_releases_camera_drag(self):
        with patch.object(boss_farmer,'USER') as user, patch.object(boss_farmer.ForegroundInput,'guard_press'), \
             patch.object(boss_farmer.ForegroundInput,'release'):
            inp=boss_farmer.BossInput();inp.right(True);inp.suspend_input()
            self.assertFalse(inp.right_mouse)
            self.assertEqual(user.mouse_event.call_args.args[0],16)

    def test_fast_skill_is_sent_before_damage_ocr(self):
        session=boss_farmer.BossSession.__new__(boss_farmer.BossSession)
        session.config=validate_boss({'strategy':'m1_c_reset'})
        session.ledger=FightLedger()
        session.inp,session.guard,session.wait=Mock(),Mock(),Mock()
        session.cycles=session.actions=session.empty_cycles=0
        session.target=Target((1100,600,220,180),.95,'test')
        frame=np.zeros((1440,2560,3),dtype=np.uint8)
        session.acquire=Mock(return_value=(reading(),frame))
        session.screen=Mock();session.screen.point.side_effect=lambda x,y:(x,y)
        session.screen.capture.return_value=frame
        session.visions={'c':Mock()};session.visions['c'].observe.return_value=True
        order=[]
        session.tap=Mock(side_effect=lambda *a:order.append('tap'))
        session.ocr=Mock();session.evidence=Mock();session.measure=Mock()
        session.scan=Mock(return_value=(reading(2100),frame))
        with patch.object(boss_farmer,'move_pointer'), \
             patch.object(boss_farmer,'fast_health',side_effect=lambda *a:order.append('ocr') or 2700):
            session.cycle(Mock())
        self.assertEqual(order,['tap','ocr'])
        self.assertEqual(session.actions,5)

    def test_focus_suspend_releases_all_owned_movement_and_skill_keys(self):
        with patch.object(boss_farmer, 'USER') as user, \
             patch.object(boss_farmer.ForegroundInput, 'guard_press'), \
             patch.object(boss_farmer.ForegroundInput, 'release'):
            inp = boss_farmer.BossInput()
            inp.key('w', True)
            inp.key('b', True)
            inp.suspend_input()
            self.assertFalse(inp.keys)
            self.assertEqual(inp.released_keys, {ord('W'), ord('B')})
            self.assertTrue(inp.interrupted.is_set())
            ups = [call.args[0] for call in user.keybd_event.call_args_list if call.args[2] == 2]
            self.assertEqual(set(ups), {ord('W'), ord('B')})

    def test_tap_releases_key_if_stop_arrives_while_held(self):
        session = boss_farmer.BossSession.__new__(boss_farmer.BossSession)
        session.inp, session.guard = Mock(), Mock()
        session.wait = Mock(side_effect=RuntimeError('Stopped'))
        with self.assertRaises(RuntimeError):
            session.tap('w')
        self.assertEqual(session.inp.key.call_args_list[-1].args, ('w', False))

    def test_read_only_boss_status_never_starts_or_changes_mode(self):
        with patch('control_actions.resume') as resume, patch('metrics.read', return_value={}), \
             patch('app_config.save_config') as save, redirect_stdout(io.StringIO()):
            self.assertEqual(fishing_cli.main(['boss', 'status']), 0)
            resume.assert_not_called()
            save.assert_not_called()

    def test_trial_routes_to_boss_worker_not_damage_or_full(self):
        with patch('control_actions.resume', return_value='Started') as resume, redirect_stdout(io.StringIO()):
            self.assertEqual(fishing_cli.main(['boss', 'trial', '--seconds', '35']), 0)
            resume.assert_called_once_with('boss', boss_operation='trial', boss_seconds=35.)

    def test_worker_refuses_existing_manual_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'STOP').write_text('Stopped by user')
            from contextlib import nullcontext
            with patch.object(boss_farmer, 'RUN', root), patch('control_actions.guard', return_value=nullcontext()), \
                 patch('control_actions.alive', return_value=False), \
                 patch.object(boss_farmer, 'stop_reason', return_value='Stopped by user'), \
                 patch.object(boss_farmer, 'BossSession') as session:
                with self.assertRaisesRegex(RuntimeError, 'Stop is set'):
                    boss_farmer.main(['--operation', 'trial'])
                session.assert_not_called()


if __name__ == '__main__':
    unittest.main()
