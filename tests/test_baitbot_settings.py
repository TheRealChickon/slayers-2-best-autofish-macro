"""Settings, CLI routing and safe external bot dispatch; no game input."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

import app_config
import baitbot_controls as bot
import control_actions
import fishing_cli
import terminal_app


class BaitBotSettings(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        # Resolved: Windows runners hand out 8.3 temp paths (RUNNER~1) that the code expands.
        self.root=Path(temporary.name).resolve()
        self.config=self.root/'config.local.json'
        self.config.write_text(json.dumps({'account_username':'Player','data_dir':str(self.root/'data'),
                                         'cast_point':[1332,508],'overnight_enabled':False,'overnight_defaults_version':2}))
        patcher=patch.object(app_config,'CONFIG',self.config);patcher.start();self.addCleanup(patcher.stop)
        self.route=self.root/'route';self.route.mkdir()
        self.script=self.root/'bait_bot.py';self.script.write_text('# Simulated installed bot')
        self.python=self.root/'python.exe';self.python.write_text('Simulated runtime')
        self.deps=self.root/'deps';self.deps.mkdir()
        self.spec=self.root/'baitbot.local.json'
        self.spec.write_text(json.dumps({'python':str(self.python),'script':str(self.script),
                                       'route_dir':str(self.route),'dependencies':str(self.deps)}))
        patcher=patch.object(bot,'SPEC',self.spec);patcher.start();self.addCleanup(patcher.stop)

    def app(self,key):
        app=terminal_app.Terminal.__new__(terminal_app.Terminal)
        app.page=3;app.selection=app.settings_keys.index(key);app.config=app_config.load_config();app.data={}
        app.job=Mock();app.toast=Mock();app.edit=Mock()
        return app

    def test_settings_defaults_are_reserve_and_buffer_not_purchase_budget(self):
        for key,value in (('Fish Head reserve',2500),('Refill buffer',500)):
            app=self.app(key);app.activate();app.edit.assert_called_once_with(key,value)
        self.assertIn('Buy bait now',terminal_app.Terminal.settings_keys)
        self.assertIn('Run bait restock',terminal_app.Terminal.settings_keys)

    def test_saving_reserve_keeps_camera_account_manual_intent_and_purchase_controls(self):
        app=self.app('Fish Head reserve');app.editing='Fish Head reserve';app.buffer='2700'
        app.finish_edit()
        cfg=app_config.load_config()
        self.assertEqual(cfg['bait_reserve'],2700);self.assertEqual(cfg['bait_refill_buffer'],500)
        self.assertEqual(cfg['account_username'],'Player');self.assertEqual(cfg['cast_point'],[1332,508])
        self.assertFalse(cfg['overnight_enabled'])
        before=self.config.read_bytes();app.editing='Refill buffer';app.buffer='-1';app.finish_edit()
        self.assertEqual(self.config.read_bytes(),before)

    def test_run_check_and_stop_entries_dispatch_only_when_selected(self):
        for key,method in (('Run bait restock','launch'),('Check bait route','check'),('BaitBot status','status')):
            app=self.app(key)
            with patch.object(bot,method) as function:
                app.activate();app.job.assert_called_once_with(function);function.assert_not_called()
        app=self.app('Stop bait restock')
        with patch.object(bot,'invoke',return_value='Stopped') as invoke:
            app.activate();app.job.call_args.args[0]()
            invoke.assert_called_once_with('stop')

    def test_cli_baitbot_check_returns_incomplete_without_starting_a_controller(self):
        report={'ready_for_trip':False,'errors':['Drop calibration missing']}
        with patch.object(bot,'invoke',return_value=report) as invoke,patch.object(bot,'launch') as launch,\
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(fishing_cli.main(['--no-color','baitbot','check']),1)
        invoke.assert_called_once_with('check');launch.assert_not_called()
        self.assertEqual(json.loads(output.getvalue()),report)

    def test_incomplete_route_withholds_subprocess_and_run_state_changes(self):
        report={'ready_for_trip':False,'errors':['Ledge missing']}
        before=self.config.read_bytes()
        with patch.object(bot,'invoke',return_value=report),patch.object(bot.subprocess,'Popen') as spawn:
            with self.assertRaisesRegex(ValueError,'Ledge missing'):bot.launch()
        spawn.assert_not_called();self.assertEqual(self.config.read_bytes(),before)
        self.assertFalse((self.root/'data').exists())

    def test_live_controller_withholds_bot_and_preserves_manual_markers(self):
        data=self.root/'data';data.mkdir();(data/'F8_PAUSE').write_text('Manual pause')
        with patch.object(bot,'check'),patch.object(control_actions,'guard',return_value=contextlib.nullcontext()),\
                patch.object(control_actions,'refuse_peer_controller'),\
                patch.object(control_actions,'starting',return_value=False),\
                patch.object(control_actions,'alive',side_effect=lambda name:name=='supervisor-pid.json'),\
                patch.object(bot.subprocess,'Popen') as spawn:
            with self.assertRaisesRegex(ValueError,'current controller'):bot.launch()
        spawn.assert_not_called();self.assertEqual((data/'F8_PAUSE').read_text(),'Manual pause')

    def test_launch_passes_current_autofish_config_stock_target_and_shared_controller_data(self):
        with patch.object(bot,'check'),patch.object(control_actions,'guard',return_value=contextlib.nullcontext()),\
                patch.object(control_actions,'refuse_peer_controller'),\
                patch.object(control_actions,'starting',return_value=False),\
                patch.object(control_actions,'alive',return_value=False),patch.object(bot.subprocess,'Popen') as spawn:
            bot.launch(reserve=2800,buffer=600)
        args=spawn.call_args.args[0]
        self.assertEqual(args[args.index('--config-file')+1],str(self.config.resolve()))
        self.assertEqual(args[args.index('--reserve')+1],'2800')
        self.assertEqual(args[args.index('--buffer')+1],'600')
        self.assertEqual(spawn.call_args.kwargs['env']['FISHING_DATA_DIR'],str(self.root/'data'))
        self.assertEqual(spawn.call_args.kwargs['env']['PYTHONPATH'],str(self.deps))
        self.assertNotIn('shell',spawn.call_args.kwargs)

    def test_settings_summary_is_read_only_and_rejects_stale_process_identity(self):
        (self.route/'route.json').write_text(json.dumps({'incomplete':'Drops'}))
        (self.route/'test-result.json').write_text(json.dumps({'status':'running','pid':123,'created':10}))
        before={p:p.read_bytes() for p in self.route.iterdir()}
        with patch.object(bot.psutil,'Process') as process,patch.object(bot.subprocess,'run') as run:
            process.return_value.create_time.return_value=20
            self.assertEqual(bot.summary(),'Route incomplete')
        run.assert_not_called();self.assertEqual(before,{p:p.read_bytes() for p in self.route.iterdir()})

    def test_every_settings_row_remains_visible_when_scrolled_into_view(self):
        app=self.app('Run bait restock');app.scroll=0;app.reference_position=False
        with patch.object(terminal_app,'data_directory',return_value=self.root),patch.object(terminal_app,'read',return_value={}):
            for key in ('Fish Head reserve','Refill buffer','Run bait restock','Check bait route','Stop bait restock','BaitBot status','Buy bait now'):
                app.selection=app.settings_keys.index(key)
                rendered='\n'.join(terminal_app.ANSI.sub('',line) for line in app.body(12))
                self.assertIn(key,rendered)


if __name__=='__main__':unittest.main()
