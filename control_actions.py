"""Explicit controls shared by the window and CLI; serialized across processes."""
import ctypes
import hashlib
import json
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
import psutil
import win32gui
from metrics import RUN
from fishing_assistant import ROOT, find_window
from app_config import load_config, save_config, MODES

_mutex = threading.RLock()
_starting = None


@contextmanager
def guard():
    # A CLI invocation and the window must not create two supervisors at once.
    with _mutex:
        RUN.mkdir(parents=True, exist_ok=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        name = 'Local\\FishingControls-' + hashlib.sha1(str(RUN.resolve()).lower().encode()).hexdigest()
        handle = kernel.CreateMutexW(None, False, name)
        if not handle:
            raise OSError('Could not lock fishing controls')
        acquired = False
        try:
            acquired = kernel.WaitForSingleObject(handle, 5000) in (0, 0x80)
            if not acquired:
                raise RuntimeError('Another control command is still finishing; try again.')
            yield
        finally:
            if acquired:
                kernel.ReleaseMutex(handle)
            kernel.CloseHandle(handle)


def alive(lock_name='supervisor-pid.json'):
    try:
        record = json.loads((RUN / lock_name).read_text())
        return abs(psutil.Process(record['pid']).create_time() - record['created']) < 1
    except (OSError, ValueError, KeyError, psutil.Error):
        return False


def starting():
    return ((_starting is not None and _starting.poll() is None) or alive('control-start.json'))


def event(action, message):
    with (RUN / 'controls.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps({'at': time.time(), 'event': action, 'message': message}) + '\n')


def pause():
    with guard():
        if not alive() and not starting():
            return 'Already stopped. Continue resumes the saved run.'
        (RUN / 'PAUSE').write_text('Paused by user')
        (RUN / 'STOP').write_text('Paused by user')
        event('pause', 'Pause requested; releasing game input and keeping totals.')
    return 'Pausing. Continue resumes the selected mode and keeps all counters.'


def stop():
    with guard():
        (RUN / 'STOP').write_text('Stopped by user')
        (RUN / 'PAUSE').unlink(missing_ok=True)
        event('stop', 'Stopped by user; saved totals retained.')
    return 'Stop requested. Saved totals are retained.'


def focus_game():
    h = find_window()
    if win32gui.IsIconic(h):
        win32gui.ShowWindow(h, 9)
    win32gui.SetForegroundWindow(h)


def resume(mode=None):
    global _starting
    mode = mode or load_config().get('mode','full')
    if mode not in MODES:raise ValueError('Mode must be full, assist, or spot')
    with guard():
        if alive('calibration-pid.json'):
            return 'Reference setup is running. Stop cancels it.'
        live, pending = alive(), starting()
        if live or pending:
            if (RUN / 'PAUSE').exists() or (RUN / 'STOP').exists():
                return 'Pause/stop is still finishing. Try Continue in a moment.'
            if not live:
                return 'Starting; waiting for the fishing supervisor.'
            try:current_mode=json.loads((RUN/'supervisor.json').read_text()).get('mode','full')
            except (OSError,ValueError):current_mode='full'
            if current_mode!=mode:return 'Pause the current mode before switching modes.'
            if mode=='assist':return 'Minigame only is active. F8 pauses/resumes; bring Roblox forward and cast manually.'
            if mode=='spot':return 'Fish here is active. Equip your rod, position the mouse, then press F8.'
            focus_game()
            event('continue', 'Returned focus to Roblox.')
            return 'Roblox is focused. Fishing will resume automatically.'
        # Only an explicit Continue command may release a manual stop.
        save_config({'mode':mode})
        (RUN / 'PAUSE').unlink(missing_ok=True)
        (RUN / 'STOP').unlink(missing_ok=True)
        args = ([sys.executable,str(ROOT/'minigame_assist.py'),'--respect-stop','--mode',mode] if mode in ('assist','spot') else
                [sys.executable, str(ROOT / 'recovery.py'), '--seconds', '0', '--rejoin',
                 '--focus', '--resume-counters', '--respect-stop'])
        try:
            with (RUN / 'supervisor-stdout.log').open('a') as out, (RUN / 'supervisor-stderr.log').open('a') as err:
                _starting = subprocess.Popen(args, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
            record = {'pid': _starting.pid, 'created': psutil.Process(_starting.pid).create_time()}
            (RUN / 'control-start.json').write_text(json.dumps(record))
        except Exception:
            (RUN / 'STOP').write_text('Continue failed; input stopped')
            raise
        message = ('Minigame only is active. F8 pauses/resumes; bring Roblox forward and cast manually.' if mode=='assist' else
                   'Fish here is active. Equip your rod, position the mouse, then press F8; losing focus pauses input.' if mode=='spot' else
                   'Continuing the saved run. Rejoining and equipping the rod...')
        event('continue',message)
        return message
