"""The release zip: one launcher on top, the app beside it, nothing private."""
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import share_build


class ShareZip(unittest.TestCase):
    def test_zip_holds_the_launcher_and_the_app_only(self):
        try:
            subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=share_build.ROOT, check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError):
            raise unittest.SkipTest('not a git checkout')
        with tempfile.TemporaryDirectory() as folder:
            names = zipfile.ZipFile(share_build.build(out=folder)).namelist()
        self.assertEqual({name.split('/')[1] for name in names}, {'Autofish.exe', 'app'})
        self.assertIn('Autofish/app/Install-Autofish.ps1', names)
        self.assertIn('Autofish/app/VERSION', names)
        for left_out in ('tests/', 'private/', 'launcher/', '.github/', 'docs/images/'):
            self.assertFalse([name for name in names if name.startswith('Autofish/app/'+left_out)], left_out)


if __name__ == '__main__':
    unittest.main()
