"""Client events and control boundaries, with no game input or real run writes."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app_config
import control_actions
import control_api
import cli_scene
import discord_hourly
import fishing_cli
import item_journal
import live_feed
import metrics
import status_view
import terminal_app
from cli_effects import CatchEffects


def catch(at=100, name='Golden Fish', reward_id='drop-1'):
    return {'at': at, 'item': name, 'quantity': 1, 'session': 'test',
            'reward_id': reward_id, 'raw': name+' X1'}


class CatchLifecycle(unittest.TestCase):
    def test_history_duplicates_corrections_and_expiry(self):
        fx = CatchEffects()
        old = catch(99, reward_id='old')
        fx.observe([old], 1, 100, 10)
        self.assertIsNone(fx.active)
        new = catch()
        fx.observe([old, new], 1, 101, 11)
        self.assertIn('Golden Fish', fx.active.title)
        fx.observe([old, new], 1, 102, 12)
        self.assertEqual(fx.active.started, 11)
        self.assertIsNone(fx.rows(80, 16))
        unknown = catch(102, 'Unidentified item', 'unknown')
        fx.observe([old, new, unknown], 1, 102, 17)
        unknown['item'] = 'Zebra Fish'
        fx.observe([old, new, unknown], 1, 103, 18)
        self.assertIsNone(fx.active)
        fx.observe([catch(80, reward_id='delayed')], 1, 104, 19)
        self.assertIsNone(fx.active)
        fx.observe([catch(105)], 2, 105, 20)
        self.assertIsNone(fx.active)

    def test_bursts_are_bounded_and_reduced_motion_is_still(self):
        fx = CatchEffects()
        fx.observe([], 1, 100, 10)
        fx.observe([catch(101, reward_id='one'), catch(102, 'Clown Fish', 'two')], 1, 103, 11)
        self.assertIn('Clown Fish', fx.active.title)
        self.assertEqual(fx.rows(61, 12, True), fx.rows(61, 14, True))
        self.assertIsNone(fx.rows(61, 16, True))

    def test_new_ore_uses_a_distinct_short_effect_once(self):
        fx = CatchEffects()
        fx.observe([], 1, 100, 10)
        row = catch(101, 'Ore', 'ore-1')
        fx.observe([row], 1, 101, 11)
        self.assertEqual((fx.active.kind, fx.active.tone), ('ore', 'ore'))
        self.assertTrue(any('◆' in segment[0] for line in fx.rows(80, 11.3) for segment in line))
        fx.observe([row], 1, 102, 12)
        self.assertEqual(fx.active.started, 11)
        self.assertIsNone(fx.rows(80, 14.7))

    def test_secret_timeout_and_unrelated_keys_reset_sequence(self):
        fx = CatchEffects()
        for key in 'blu': fx.key(key, 10)
        fx.key('b', 13)
        self.assertIsNone(fx.active)
        fx.key('s', 13)
        for key in 'lub': fx.key(key, 13)
        self.assertIsNone(fx.active)
        for key in 'blub': fx.key(key, 14)
        self.assertEqual(fx.active.kind, 'egg')
        self.assertIsNone(fx.rows(61, 20))


class IsolatedClients(unittest.TestCase):
    def test_cli_catches_session_defaults_and_explicit_total(self):
        metrics.write('current-run.json',{'id':'current','started':100,'ended':200})
        self.append([{'at':50,'event':'reward_observed','text':'Ore X3','cycle':1},
                     {'at':110,'event':'reward_observed','text':'Coral X2','cycle':2},
                     {'at':250,'event':'reward_observed','text':'GoldenFish X1','cycle':3}])
        with patch('app_config.data_directory',return_value=self.root):
            for command in ('items',):
                with redirect_stdout(io.StringIO()) as output:
                    fishing_cli.execute(fishing_cli.parser().parse_args([command,'--json']))
                self.assertIn('Coral',output.getvalue())
                self.assertNotIn('Ore',output.getvalue());self.assertNotIn('Golden',output.getvalue())
                with redirect_stdout(io.StringIO()) as output:
                    fishing_cli.execute(fishing_cli.parser().parse_args([command,'--json','--total']))
                self.assertIn('Ore',output.getvalue());self.assertIn('Golden',output.getvalue())

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for module in (metrics, item_journal, live_feed, control_actions, status_view):
            p = patch.object(module, 'RUN', self.root)
            p.start(); self.addCleanup(p.stop)
        for target, value in ((app_config, 'CONFIG'),):
            p = patch.object(target, value, self.root/'config.local.json')
            p.start(); self.addCleanup(p.stop)
        for name in ('alive', 'starting'):
            p = patch.object(control_actions, name, return_value=False)
            p.start(); self.addCleanup(p.stop)
        metrics.write('totals.json', {'started': 1})

    def append(self, rows):
        with (self.root/'events-test.jsonl').open('a', encoding='utf-8') as stream:
            for row in rows: stream.write(json.dumps(row)+'\n')

    def test_refresh_new_reward_animates_without_changing_journal(self):
        app = terminal_app.Terminal()
        with patch('time.time', return_value=100):
            app.refresh()
            self.append([{'at': 100, 'event': 'reward_observed', 'text': 'Golden Fish X1', 'reward_id': 'one'}])
            app.refresh()
            self.assertIn('Golden Fish', app.effects.active.title)
            app.refresh()
        self.assertEqual(app.journal.counts, {'Golden Fish': 1})
        self.assertEqual(len(app.journal.items), 1)

    def test_webhook_is_editable_without_displaying_secret(self):
        app = terminal_app.Terminal()
        app.refresh(); app.switch(3)
        app.edit('Discord webhook', 'https://discord.com/api/webhooks/123/secret')
        rendered='\n'.join(terminal_app.ANSI.sub('', line) for line in app.render(120, 35))
        self.assertNotIn('secret', rendered)
        with patch.object(discord_hourly, 'configure_secret') as configure:
            app.finish_edit()
            configure.assert_called_once()
        self.assertEqual(app.buffer, '')

    def test_webhook_cli_status_does_not_reveal_token(self):
        with patch.object(app_config, 'data_directory', return_value=self.root):
            (self.root/'discord-webhook.dpapi').write_bytes(b'encrypted')
            output=io.StringIO()
            with redirect_stdout(output):
                code=fishing_cli.main(['webhook','status'])
        self.assertEqual(code,0)
        self.assertIn('configured',output.getvalue())
        self.assertNotIn('encrypted',output.getvalue())

    def test_effects_preserve_controls_log_layout_and_editing(self):
        app = terminal_app.Terminal(); app.refresh(); app.switch(2)
        app.changed_at -= 1
        before = app.render(100, 32)
        for key in 'blub': app.key(key)
        after = app.render(100, 32)
        self.assertEqual(before[7:], after[7:])
        for width, height in ((65, 22), (100, 32), (150, 50)):
            lines = app.render(width, height)
            self.assertTrue(any('S stop' in line for line in lines))
            self.assertLessEqual(len(lines), height-1)
            self.assertTrue(all(len(terminal_app.ANSI.sub('', line)) < width for line in lines))
        app.effects.active = None
        app.edit('Search')
        for key in 'blub': app.key(key)
        self.assertEqual(app.buffer, 'blub')
        self.assertIsNone(app.effects.active)
        app.key('CANCEL'); app.busy = True
        for key in 'blub': app.key(key)
        with patch.object(control_actions, 'stop', return_value='Stopped') as stop:
            app.key('s'); stop.assert_called_once()
        app.key('q'); self.assertFalse(app.alive)

    def test_terminal_transitions_respect_reduced_motion(self):
        app = terminal_app.Terminal()
        with patch.object(terminal_app.sys.stdout, 'write') as write, \
             patch.object(terminal_app.sys.stdout, 'flush'), \
             patch.object(terminal_app.time, 'sleep') as sleep:
            app.transition('opening')
            self.assertEqual(write.call_count, 19)  # 18 full-screen frames, then dashboard
            self.assertEqual(sleep.call_count, 18)
            self.assertIn('\x1b[2J', write.call_args_list[0].args[0])
            app.config['reduced_motion'] = True
            app.transition('closing')
            self.assertEqual(write.call_count, 19)

    def test_rod_cast_and_reel_frames_move_the_float(self):
        def float_position(phase, progress):
            rows = [terminal_app.ANSI.sub('', line) for line in cli_scene.scene_frame(80, 24, progress, phase)]
            return next((row.index('●'), y) for y, row in enumerate(rows) if '●' in row)
        self.assertLess(float_position('opening', 0), float_position('opening', 1))
        self.assertGreater(float_position('closing', 0), float_position('closing', 1))
        rows = [terminal_app.ANSI.sub('', line) for line in cli_scene.scene_frame(80, 24, 1, 'opening')]
        frame = ''.join(rows)
        self.assertEqual(len(rows), 23)
        self.assertTrue(all(len(row) == 79 for row in rows))
        for columns, lines in ((65, 22), (120, 40)):
            sized = [terminal_app.ANSI.sub('', line) for line in cli_scene.scene_frame(columns, lines, .5, 'closing')]
            self.assertEqual(len(sized), lines-1)
            self.assertTrue(all(len(row) == columns-1 for row in sized))
        self.assertIn('╱', frame)
        self.assertIn('≈', frame)
        self.assertIn('✦', frame)
        self.assertIn('><(((o>', frame)

    def test_console_restores_if_closing_animation_fails(self):
        app = terminal_app.Terminal()
        app.alive = False
        with patch.object(terminal_app.sys.stdin, 'isatty', return_value=True), \
             patch.object(terminal_app.sys.stdout, 'isatty', return_value=True), \
             patch.object(terminal_app.sys.stdout, 'write') as write, \
             patch.object(terminal_app.sys.stdout, 'flush'), \
             patch.object(app, 'transition', side_effect=[None, RuntimeError('closed')]):
            with self.assertRaisesRegex(RuntimeError, 'closed'):
                app.run()
        self.assertIn('?25h', write.call_args.args[0])

    def test_api_read_commands_are_json_and_do_not_control_game(self):
        with patch.object(control_actions, 'resume') as resume, patch.object(control_actions, 'pause') as pause, patch.object(control_actions, 'stop') as stop:
            for operation in ('status', 'items', 'events'):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = fishing_cli.main(['api', operation, '--request-id', 'discord-later'])
                envelope = json.loads(output.getvalue())
                self.assertEqual(code, 0)
                self.assertTrue(envelope['ok'])
                self.assertEqual(envelope['api_version'], 1)
                self.assertEqual(envelope['request_id'], 'discord-later')
                self.assertNotIn('\x1b', output.getvalue())
            resume.assert_not_called(); pause.assert_not_called(); stop.assert_not_called()
        self.assertFalse((self.root/'STOP').exists())

    def test_api_event_ids_survive_polls_appends_and_equal_events(self):
        row = {'at': 100, 'event': 'reward_observed', 'text': 'Golden Fish X1'}
        self.append([row, row])
        first = control_api.dispatch('events')[0]['data']['events']
        self.assertEqual(len(first), 2)
        self.assertNotEqual(first[0]['id'], first[1]['id'])
        self.append([dict(row, at=101)])
        second = control_api.dispatch('events')[0]['data']['events']
        self.assertEqual(second[:2], first)
        self.assertFalse(any(row['kind'] == 'state' for row in second))

    def test_api_controls_delegate_and_errors_are_structured(self):
        for command in ('pause', 'resume', 'stop'):
            with patch.object(control_actions, command, return_value='Requested') as action:
                response, code = control_api.dispatch(command)
                action.assert_called_once_with()
                self.assertEqual(code, 0)
                self.assertIn('status', response['data'])
        with patch.object(control_actions, 'resume', side_effect=RuntimeError('Busy')):
            response, code = control_api.dispatch('resume', 'r1')
            self.assertEqual(code, 1)
            self.assertEqual(response['error'], {'code': 'command_failed', 'message': 'Busy'})
            self.assertEqual(response['request_id'], 'r1')
        with patch.object(control_actions, 'stop') as stop:
            self.assertEqual(control_api.dispatch('stop', limit=0)[1], 2)
            self.assertEqual(control_api.dispatch('shell')[1], 2)
            stop.assert_not_called()


if __name__ == '__main__': unittest.main()
