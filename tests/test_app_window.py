"""The app window serves only this PC, only with its token, from the same data as the CLI."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import app_config
import app_window
import control_actions
import item_journal
import live_feed
import metrics
import status_view


class AppWindow(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for module in (metrics, item_journal, live_feed, control_actions, status_view):
            patcher = patch.object(module, 'RUN', self.root); patcher.start(); self.addCleanup(patcher.stop)
        for patcher in (patch.object(app_config, 'CONFIG', self.root/'config.local.json'),
                        patch.dict(app_config.DEFAULTS, {'spawn_gamepass': None}),
                        patch.object(app_window, 'current_rod', return_value='Legendary')):
            patcher.start(); self.addCleanup(patcher.stop)
        metrics.write('totals.json', {'started': 100, 'casts': 40, 'rounds': 40, 'rewards': 30, 'active_seconds': 1800})
        with (self.root/'events-20261015-010000.jsonl').open('w', encoding='utf-8') as stream:
            for i, text in enumerate(('Coral X2', 'OuwFish X1', 'Krathulon X1', 'Refinement Ore X3')):
                stream.write(json.dumps({'at': 110+i, 'event': 'reward_observed', 'text': text, 'cycle': i})+'\n')
        self.server = app_window.make_server('secret-token')
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.port = self.server.server_port

    def call(self, method, path, body=None, token='secret-token', host=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = {'Host': host or f'127.0.0.1:{self.port}', 'Content-Type': 'application/json'}
        if token: headers['X-Autofish-Token'] = token
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = connection.getresponse(); data = response.read(); connection.close()
        return response.status, data

    def test_requests_without_the_token_or_from_another_host_are_refused(self):
        self.assertEqual(self.call('GET', '/api/state', token=None)[0], 403)
        self.assertEqual(self.call('GET', '/api/state', token='wrong')[0], 403)
        self.assertEqual(self.call('GET', '/api/state', host='evil.example')[0], 403)
        with patch.object(control_actions, 'stop') as stop:
            self.assertEqual(self.call('POST', '/api/action', {'action': 'stop'}, token=None)[0], 403)
        stop.assert_not_called()

    def test_page_carries_the_token_and_fonts_and_no_placeholders(self):
        status, body = self.call('GET', '/?t=secret-token', token=None)
        self.assertEqual(status, 200)
        page = body.decode('utf-8')
        self.assertIn('"token": "secret-token"', page)
        self.assertNotIn('/*BOOT*/', page); self.assertNotIn('/*FONTS*/', page)
        self.assertNotIn('claude.ai', page)

    def test_state_reports_the_run_catch_and_first_run_question(self):
        status, body = self.call('GET', '/api/state')
        self.assertEqual(status, 200)
        state = json.loads(body)
        self.assertEqual(state['hooks'], 40)
        self.assertEqual(state['fish'], 4)
        self.assertEqual({r['name']: r['count'] for r in state['catch']}, {'Coral': 2, 'OuwFish': 1, 'Krathulon': 1})
        self.assertEqual(state['catch'][0]['rarity'], 'Common')
        self.assertIsNone(state['config']['spawn_gamepass'])
        self.assertTrue(any(e['group'] == 'catches' for e in state['events']))
        self.assertIn('Refinement Ore', [i['item'] for i in state['items']])

    def test_controls_and_settings_use_the_existing_handlers(self):
        with patch.object(control_actions, 'resume', return_value='Started') as resume:
            status, body = self.call('POST', '/api/action', {'action': 'start', 'mode': 'here'})
        self.assertEqual(status, 200); resume.assert_called_once_with(mode='here')
        self.assertEqual(json.loads(body)['message'], 'Started')
        self.assertEqual(self.call('POST', '/api/action', {'action': 'start', 'mode': 'rejoin'})[0], 400)
        self.assertEqual(self.call('POST', '/api/settings', {'rod_slot': 3})[0], 200)
        self.assertEqual(app_config.load_config()['rod_slot'], 3)
        self.assertEqual(self.call('POST', '/api/settings', {'rod_slot': 12})[0], 400)
        self.assertEqual(self.call('POST', '/api/settings', {'spawn_gamepass': False})[0], 200)
        self.assertIs(app_config.load_config()['spawn_gamepass'], False)
        self.assertEqual(self.call('POST', '/api/settings', {'overnight': False})[0], 200)
        self.assertFalse(app_config.load_config()['overnight_enabled'])
        self.assertEqual(self.call('POST', '/api/settings', {'webhook': 'x'})[0], 400)
        with patch.object(app_config, 'resolve_account', return_value={'account_username': 'FishFan42', 'user_id': 7}):
            self.assertEqual(self.call('POST', '/api/settings', {'account_username': 'fishfan42'})[0], 200)
        self.assertEqual(app_config.load_config()['account_username'], 'FishFan42')


if __name__ == '__main__':
    unittest.main()
