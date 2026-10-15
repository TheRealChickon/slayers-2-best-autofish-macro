"""Build a versioned zip of the committed app for someone without GitHub access.

Only files tracked in Git go in, so local settings, logs, stats, recordings and
the webhook never do. The friend unzips it and runs Install.cmd, which installs
or updates and keeps their own settings and data.
"""
import io
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEFT_OUT = ('tests/', 'private/', 'docs/images/', '.github/', 'CLAUDE.md', 'AGENTS.md', 'CONTRIBUTING.md', '.gitignore')


def build(ref='HEAD', out=None):
    sha = subprocess.run(['git', 'rev-parse', '--short', ref], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    version = time.strftime('%Y.%m.%d-%H%M')+'-'+sha
    archive = subprocess.run(['git', 'archive', '--format=zip', ref], cwd=ROOT, capture_output=True, check=True).stdout
    out = Path(out or ROOT/'share'); out.mkdir(parents=True, exist_ok=True)
    path = out/f'Autofish-{version}.zip'
    with zipfile.ZipFile(io.BytesIO(archive)) as source, zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            name = info.filename
            if info.is_dir() or name.startswith(LEFT_OUT) or name.lower().endswith(('.mp4', '.avi')):
                continue
            target.writestr('Autofish/'+name, source.read(info))
        target.writestr('Autofish/VERSION', version+'\n')
    return path


if __name__ == '__main__':
    print(build(*sys.argv[1:2]))
