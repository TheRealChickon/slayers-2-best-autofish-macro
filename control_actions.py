"""Explicit controls shared by the window and CLI; serialized across processes."""
import ctypes
import datetime
import hashlib
import json
import math
import re
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
        name = 'Local\\Slayers2MacroControls'
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
        if alive('bait-driver-pid.json'):
            (RUN/'PAUSE').write_text('Bait purchase paused by user')
            event('pause','Bait purchase pause requested; input will be released.')
            return 'Pausing bait purchase. Use autofish bait resume to continue its remaining amount.'
        if alive('route-recorder-pid.json'):
            (RUN/'route-recorder-stop').write_text('Paused by user')
            if not alive() and not starting():
                return 'Ending the bait route recording; the partial demonstration is retained.'
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
        save_config({'overnight_enabled':False,'overnight_auto_enable_idle':False})
        event('stop', 'Stopped by user; saved totals retained.')
    return 'Stop requested. Saved totals are retained.'


def focus_game():
    h = find_window()
    if win32gui.IsIconic(h):
        win32gui.ShowWindow(h, 9)
    win32gui.SetForegroundWindow(h)


def seconds_until_local_clock(value):
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value or ''):
        raise ValueError('--until must be HH:MM in local time')
    now=datetime.datetime.now().astimezone()
    hour,minute=map(int,value.split(':'))
    end=now.replace(hour=hour,minute=minute,second=0,microsecond=0)
    remaining=math.ceil((end-now).total_seconds())
    if remaining<=0:raise ValueError('--until must be later today')
    return remaining


def resume(mode=None,until=None,automatic=False):
    global _starting
    mode = mode or load_config().get('mode','full')
    if mode not in MODES:raise ValueError('Unknown controller mode')
    if until and mode not in ('full','here'):raise ValueError('--until is available for Full farmer only (or Farm here)')
    seconds=seconds_until_local_clock(until) if until else 0
    with guard():
        refuse_peer_controller()
        if alive('bait-driver-pid.json'):
            return 'Bait purchase is active. Finish or pause it before Continue.'
        if alive('route-recorder-pid.json'):
            return 'Bait route recorder is open. Finish or close it before Continue.'
        if alive('calibration-pid.json'):
            return 'Reference setup is running. Stop cancels it.'
        live, pending = alive(), starting()
        if automatic:
            if not load_config()['overnight_enabled']:return 'Overnight is off.'
            if (RUN/'PAUSE').exists() or (RUN/'F8_PAUSE').exists():return 'Manual pause retained.'
            if (RUN/'STOP').exists():
                if (RUN/'STOP').read_text().strip()!='Supervisor stopped':return 'Manual stop retained.'
            if live or pending:return 'Controller already active.'
        if live or pending:
            if until:return 'Already running. Pause first to set a timed stop, then Continue again.'
            if (RUN / 'PAUSE').exists() or (RUN / 'STOP').exists():
                return 'Pause/stop is still finishing. Try Continue in a moment.'
            if not live:
                return 'Starting; waiting for the fishing supervisor.'
            try:current_mode=json.loads((RUN/'supervisor.json').read_text()).get('mode','full')
            except (OSError,ValueError):current_mode='full'
            if current_mode!=mode:return 'Pause the current mode before switching modes.'
            if mode=='assist':return 'Minigame only is active. F8 pauses/resumes; bring Roblox forward and cast manually.'
            if mode=='spot':return 'Fish here is active. Equip your rod, position the mouse, then press F8.'
            if mode=='rejoin':return 'Auto rejoin is watching the configured account. Use status or logs --activity.'
            (RUN/'F8_PAUSE').unlink(missing_ok=True)
            focus_game()
            event('continue', 'Returned focus to Roblox.')
            return 'Roblox is focused. Fishing will resume automatically.'
        # Only an explicit Continue command may release a manual stop.
        try:previous_mode=json.loads((RUN/'supervisor.json').read_text()).get('mode')
        except (OSError,ValueError):previous_mode=None
        resume_rejoin_counters = mode=='rejoin' and previous_mode=='rejoin' and (RUN/'PAUSE').exists()
        resume_log_run=automatic or (RUN/'PAUSE').exists()
        save_config({'mode':mode})
        (RUN / 'PAUSE').unlink(missing_ok=True)
        (RUN / 'STOP').unlink(missing_ok=True)
        (RUN / 'F8_PAUSE').unlink(missing_ok=True)
        args = ([sys.executable,str(ROOT/'rejoin_only.py'),'--respect-stop'] +
                (['--resume-counters'] if resume_rejoin_counters else []) if mode=='rejoin' else
                [sys.executable,str(ROOT/'minigame_assist.py'),'--respect-stop','--mode',mode] if mode in ('assist','spot') else
                [sys.executable, str(ROOT / 'recovery.py'), '--seconds', str(seconds)]+(['--here'] if mode=='here' else ['--rejoin'])+[
                 '--focus', '--resume-counters', '--respect-stop']+(['--resume-log-run'] if resume_log_run else []))
        try:
            with (RUN / 'supervisor-stdout.log').open('a') as out, (RUN / 'supervisor-stderr.log').open('a') as err:
                _starting = subprocess.Popen(args, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
            record = {'pid': _starting.pid, 'created': psutil.Process(_starting.pid).create_time()}
            (RUN / 'control-start.json').write_text(json.dumps(record))
        except Exception:
            (RUN / 'STOP').write_text('Continue failed; input stopped')
            raise
        message = ('Auto rejoin started. Watching the configured Roblox account; no fishing or attacks.' if mode=='rejoin' else
                   'Minigame only is active. F8 pauses/resumes; bring Roblox forward and cast manually.' if mode=='assist' else
                   'Fish here is active. Equip your rod, position the mouse, then press F8; losing focus pauses input.' if mode=='spot' else
                   ('Continuing the saved run until '+until+' local time. Rejoining and equipping the rod...' if until else
                    'Continuing the saved run. Rejoining and equipping the rod...'))
        event('continue',message)
        if load_config()['overnight_enabled'] or load_config()['overnight_auto_enable_idle']:
            from overnight_guard import ensure_guard
            ensure_guard()
        return message


def refuse_peer_controller():
    peer = load_config().get('peer_data_dir')
    if not peer:
        return
    from pathlib import Path
    for name in ('supervisor-pid.json', 'pid.json', 'control-start.json', 'calibration-pid.json', 'route-recorder-pid.json'):
        try:
            record = json.loads((Path(peer)/name).read_text())
            if abs(psutil.Process(record['pid']).create_time() - record['created']) < 1:
                raise RuntimeError('The other Slayers 2 macro is running or stopping. Stop it before switching projects.')
        except (OSError, ValueError, KeyError, psutil.Error):
            pass


def restart_full(overnight=False):
    """Explicit restart: retain the run, release input, then use Full's rejoin."""
    with guard():
        refuse_peer_controller()
        if any(alive(name) for name in ('bait-driver-pid.json','route-recorder-pid.json','calibration-pid.json')):
            raise RuntimeError('Finish or pause the other controller before restarting Full farmer')
        pause()
        (RUN/'PAUSE').write_text('Full farmer restart requested')
        stamp=(RUN/'PAUSE').stat().st_mtime_ns
        f8=(RUN/'F8_PAUSE').stat().st_mtime_ns if (RUN/'F8_PAUSE').exists() else None
        stopped=(RUN/'STOP').stat().st_mtime_ns if (RUN/'STOP').exists() else None
    def unchanged():
        return ((RUN/'PAUSE').exists() and (RUN/'PAUSE').stat().st_mtime_ns==stamp and
                ((RUN/'F8_PAUSE').stat().st_mtime_ns if (RUN/'F8_PAUSE').exists() else None)==f8 and
                ((RUN/'STOP').stat().st_mtime_ns if (RUN/'STOP').exists() else None)==stopped)
    until=time.monotonic()+15
    while alive() or starting() or alive('pid.json'):
        if time.monotonic()>until:
            raise RuntimeError('Controller is still stopping; input remains paused. Retry Full restart.')
        if not unchanged():
            raise RuntimeError('A new manual hold interrupted Full restart')
        time.sleep(.1)
    with guard():
        if not unchanged():raise RuntimeError('A new manual hold interrupted Full restart')
        if overnight:
            save_config({'overnight_enabled':True,'overnight_autofocus':True,'overnight_auto_enable_idle':True})
        return resume('full')
