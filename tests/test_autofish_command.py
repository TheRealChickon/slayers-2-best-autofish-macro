"""Launcher and installer checks; all starts are mocked and PATH tests isolated."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import control_actions
import fishing_cli
import game_catalog
import start_picker


class StartFlow(unittest.TestCase):
    def test_game_and_mode_picker_launches_only_after_both_choices(self):
        choices=[]
        with patch.object(control_actions,'resume',return_value='Started') as resume:
            def choose(title,options,colors):
                resume.assert_not_called()
                choices.append((title,options))
                return 'project-slayers-2' if len(choices)==1 else 'assist'
            with patch.object(start_picker,'choose',side_effect=choose),redirect_stdout(io.StringIO()):
                self.assertEqual(fishing_cli.main(['start','--no-ui']),0)
            resume.assert_called_once_with('assist')
        self.assertEqual([key for key,_ in choices[1][1]],['assist','spot','full','damage'])

    def test_cancel_either_picker_never_starts(self):
        for values in ([None],['project-slayers-2',None]):
            with patch.object(start_picker,'choose',side_effect=values),patch.object(control_actions,'resume') as resume:
                self.assertEqual(fishing_cli.main(['start']),0)
                resume.assert_not_called()

    def test_explicit_game_and_mode_work_without_terminal_or_picker(self):
        with patch.object(start_picker,'choose') as choose,patch.object(control_actions,'resume',return_value='Started') as resume,redirect_stdout(io.StringIO()):
            self.assertEqual(fishing_cli.main(['start','--game','project-slayers-2','--mode','assist','--no-ui']),0)
            choose.assert_not_called();resume.assert_called_once_with('assist')

    def test_invalid_game_and_missing_noninteractive_options_never_start(self):
        with patch.object(control_actions,'resume') as resume,patch.object(sys.stdin,'isatty',return_value=False):
            with self.assertRaisesRegex(ValueError,'Unknown game'):
                start_picker.start(fishing_cli.parser().parse_args(['start','--game','unknown','--mode','assist']))
            with self.assertRaisesRegex(ValueError,'--game and --mode'):
                start_picker.start(fishing_cli.parser().parse_args(['start']))
            resume.assert_not_called()

    def test_picker_arrows_numbers_and_cancel(self):
        options=[('assist','Minigame only'),('spot','Fish here'),('full','Full farmer')]
        for keys,result in ((['\xe0','P','\r'],'spot'),(['3','\r'],'full'),(['q'],None)):
            with patch.object(sys.stdin,'isatty',return_value=True),patch.object(sys.stdout,'isatty',return_value=True), \
                 patch.object(start_picker.msvcrt,'getwch',side_effect=keys),patch.object(sys.stdout,'write'),patch.object(sys.stdout,'flush'):
                self.assertEqual(start_picker.choose('Mode',options),result)

    def test_games_command_lists_only_registered_support_without_controls(self):
        output=io.StringIO()
        with patch.object(control_actions,'resume') as resume,redirect_stdout(output):
            self.assertEqual(fishing_cli.main(['games']),0)
        self.assertIn('project-slayers-2',output.getvalue());resume.assert_not_called()


@unittest.skipUnless(os.name=='nt','Windows installer')
class InstallCommand(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.app=self.root/"App & O'Brien (test)";self.app.mkdir()
        self.bin=self.root/'Commands & tools'/'bin'
        for name in ('Install-CLI.ps1','Runtime.ps1','autofish.py'):
            shutil.copy2(ROOT/name,self.app/name)
        shutil.copytree(ROOT/'cli',self.app/'cli')
        (self.app/'runtime.local.json').write_text(json.dumps({'python':sys.executable}))
        (self.app/'fishing_cli.py').write_text(
            'import json, os\ndef main(argv, prog):\n'
            ' print(json.dumps({"args":argv,"prog":prog,"cwd":os.getcwd()}))\n'
            ' return 7 if "fail" in argv else 0\n')

    def install(self,*extra):
        return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(self.app/'Install-CLI.ps1'),
                               '-BinDirectory',str(self.bin),'-NoPath',*extra],capture_output=True,text=True,timeout=20)

    def invoke(self,*args):
        # Only this child shell's PATH changes; no registry or game process.
        quoted=str(self.bin).replace("'","''")
        encoded=','.join("'"+value.replace("'","''")+"'" for value in args)
        command=f"$env:Path='{quoted};'+$env:Path; & autofish @({encoded}); exit $LASTEXITCODE"
        return subprocess.run(['powershell.exe','-NoProfile','-Command',command],cwd=self.root,
                              capture_output=True,text=True,timeout=20)

    def test_install_reinstall_and_bare_command_from_unrelated_directory(self):
        for _ in range(2):
            result=self.install();self.assertEqual(result.returncode,0,result.stderr)
        manifest=json.loads((self.bin/'installation.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(Path(manifest['appDirectory']),self.app)
        self.assertFalse(manifest['pathAdded'])
        result=self.invoke();self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout)
        self.assertEqual(value['args'],['tui']);self.assertEqual(value['prog'],'autofish')
        self.assertEqual(Path(value['cwd']),self.root)
        result=self.invoke('status','--json')
        self.assertEqual(json.loads(result.stdout)['args'],['status','--json'])
        self.assertEqual(self.invoke('fail').returncode,7)

    def test_uninstall_keeps_unrelated_files_and_application(self):
        self.assertEqual(self.install().returncode,0)
        keep=self.bin/'keep.txt';keep.write_text('user file')
        result=self.install('-Uninstall');self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((self.bin/'autofish.cmd').exists())
        self.assertEqual(keep.read_text(),'user file')
        self.assertTrue((self.app/'autofish.py').exists())

    def test_install_refuses_unmanaged_command(self):
        self.bin.mkdir(parents=True)
        command=self.bin/'autofish.cmd';command.write_text('existing command')
        result=self.install();self.assertNotEqual(result.returncode,0)
        self.assertEqual(command.read_text(),'existing command')


if __name__=='__main__':unittest.main()
