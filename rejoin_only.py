"""CLI-only Roblox connection guard. Never casts, attacks, or equips gear."""

import argparse
import ctypes
import json
import os
import re
import time

import psutil
import win32gui
from pynput.keyboard import Key, Listener

from app_config import load_config
from fishing_assistant import find_window
from full_pause import F8Toggle, InputPaused, PAUSE_FILE
from metrics import RUN, read, write
from presence_watch import query
from recovery import Recovery, RecoveryError, UserStop
from rejoin_policy import RejoinPolicy


DISCONNECT = ('disconnected', 'connection lost', 'connection error',
              'failed to connect', 'same account launched', 'error code:')


class LastInputInfo(ctypes.Structure):
    _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]


def desktop_idle_seconds():
    info = LastInputInfo(ctypes.sizeof(LastInputInfo), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    ctypes.windll.kernel32.GetTickCount.restype = ctypes.c_uint
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xffffffff) / 1000


def scene_kind(rows, world_visible):
    labels = [str(row['text']).strip().lower() for row in rows]
    text = ' '.join(labels)
    compact = re.sub(r'[^a-z]', '', text)
    if any(phrase in text for phrase in DISCONNECT):
        return 'disconnect'
    if ('last played' in text and 'ouwlan' in text) or 'privateserver' in compact or 'play' in labels:
        return 'lobby'
    if 'backtomainmenu' in compact or 'go back to the main menu' in text:
        return 'game_menu'
    if world_visible and ('mistfall' in compact or re.search(r'lv\.?\s*\d+', text)):
        return 'world'
    return 'other'


class RejoinRecovery(Recovery):
    def check_stop(self):
        # Ordinary Escape/F9/F12 in another app cannot stop this CLI mode.
        if (RUN/'STOP').exists():
            self.inp.release()
            raise UserStop('Stopped by user')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--respect-stop', action='store_true')
    parser.add_argument('--resume-counters', action='store_true')
    args = parser.parse_args(argv)
    config = load_config()
    if not config['account_username'] or not config['user_id']:
        raise ValueError('Configure a Roblox username first; presence checks need its user ID')
    import control_actions as controls
    RUN.mkdir(parents=True, exist_ok=True)
    with controls.guard():
        if controls.alive('route-recorder-pid.json'):
            raise RuntimeError('Bait route recorder is open; close it before starting Fishing')
        if controls.alive() or controls.alive('pid.json'):
            raise RuntimeError('Another controller is already running')
        if (RUN/'STOP').exists() or (RUN/'PAUSE').exists():
            raise RuntimeError('Stop is set; use explicit Continue')
        record = {'pid': os.getpid(), 'created': psutil.Process().create_time()}
        write('supervisor-pid.json', record)
        write('pid.json', record)

    previous = read('rejoin-status.json') if args.resume_counters else {}
    attempts = max(0, int(previous.get('attempts', 0)))
    rejoins = max(0, int(previous.get('rejoins', 0)))
    launches = max(0, int(previous.get('launches', 0)))
    session = time.strftime('%Y%m%d-%H%M%S') + '-' + str(os.getpid())
    started = time.time()
    log = (RUN/f'events-rejoin-{session}.jsonl').open('a', encoding='utf-8', buffering=1)

    def event(kind, message, **fields):
        log.write(json.dumps({'at': time.time(), 'event': kind, 'message': message,
                              'mode': 'rejoin', **fields}) + '\n')

    driver = RejoinRecovery()
    policy = RejoinPolicy()
    presence = {}
    next_presence = 0.0
    stage = 'watching'
    detail = 'Waiting for Roblox'
    reason = ''
    last_success = previous.get('last_success')

    def status(running=True):
        now = time.time()
        data = {'running': running, 'mode': 'rejoin', 'session': session,
                'updated': now, 'account': config['account_username'],
                'user_id': config['user_id'], 'stage': stage, 'detail': detail,
                'presence': presence.get('state', 'Checking'), 'attempts': attempts,
                'rejoins': rejoins, 'launches': launches, 'last_success': last_success,
                'retry_seconds': round(max(0, policy.retry_at-time.monotonic())),
                'reason': reason if not running else ''}
        write('rejoin-status.json', data)
        write('supervisor.json', {'running': running, 'pid': os.getpid(),
              'started': started, 'updated': now, 'stage': stage if running else 'stopped',
              'mode': 'rejoin', 'recoveries': rejoins, 'reason': reason if not running else ''})
        write('status.json', {'running': running, 'pid': os.getpid(),
              'updated': now, 'stage': stage, 'mode': 'rejoin',
              'wait_reason': detail, 'reason': reason if not running else ''})

    toggle = F8Toggle(RUN, lambda: driver.hwnd)

    def hotkey(key):
        if key == Key.f8:
            toggle.press()
        elif key in (Key.f9, Key.f12):
            hwnd = driver.hwnd
            if hwnd and win32gui.IsWindow(hwnd) and win32gui.GetForegroundWindow() == hwnd:
                (RUN/'STOP').write_text('Stopped by physical hotkey in Roblox')

    def hotkey_up(key):
        if key == Key.f8:
            toggle.release()

    listener = Listener(on_press=hotkey, on_release=hotkey_up)
    listener.start()
    event('rejoin_started', f"Watching {config['account_username']} for disconnects.")
    status()
    try:
        while True:
            if (RUN/'STOP').exists():
                reason = (RUN/'STOP').read_text(encoding='utf-8').strip() or 'Stopped by user'
                break
            now = time.monotonic()
            if now >= next_presence:
                try:
                    presence = query()
                    policy.presence(presence, now)
                except Exception as error:
                    presence = {'ok': False, 'state': 'Unavailable',
                                'account': config['account_username'],
                                'error': str(error)[:250], 'checked_at': time.time()}
                    policy.presence(presence, now)
                write('presence.json', presence)
                next_presence = time.monotonic() + 45
            if (RUN/'PAUSE').exists() or (RUN/PAUSE_FILE).exists():
                stage, detail = 'paused_manual', 'F8 resumes; CLI Pause/Continue restarts the guard'
                status()
                time.sleep(.3)
                continue
            try:
                try:
                    hwnd = find_window()
                    has_window = True
                except RuntimeError as error:
                    if 'found 0' not in str(error):
                        raise
                    hwnd, has_window = None, False

                if not has_window:
                    action = policy.decide('missing', False, now)
                    stage, detail = 'waiting_game', 'Roblox client is closed; waiting for desktop idle time'
                    if action == 'launch' and desktop_idle_seconds() >= 90:
                        stage, detail = 'rejoining', 'Opening Roblox through its place link'
                        attempts += 1
                        launches += 1
                        status()
                        event('rejoin_launch', detail)
                        driver.launch()
                        driver.inp.gate.acknowledge()
                        driver.recover(equip_rod=False)
                        rejoins += 1
                        last_success = time.time()
                        policy.succeeded()
                        event('rejoin_success', 'Roblox world is ready after relaunch.')
                    status()
                    time.sleep(1)
                    continue

                driver.hwnd = hwnd
                foreground = not win32gui.IsIconic(hwnd) and win32gui.GetForegroundWindow() == hwnd
                if not foreground:
                    stage, detail = 'paused_focus', 'Another app is active; no Roblox input'
                    if policy.inspect_background(now) and desktop_idle_seconds() >= 90:
                        driver.select(focus=True)
                    status()
                    time.sleep(1)
                    continue

                driver.select()
                if not driver.inp.gate.acknowledge():
                    stage, detail = 'paused_focus', 'Waiting for navigation keys to be released'
                    status()
                    time.sleep(.3)
                    continue
                image = driver.capture()
                rows = driver.text(image)
                scene = scene_kind(rows, driver.world_visible(image))
                action = policy.decide(scene, True, now)
                stage, detail = ('watching', 'Roblox world connected') if scene == 'world' else ('watching', f'Observed {scene}')
                if action == 'recover':
                    stage, detail = 'rejoining', f'Recovering from {scene}'
                    attempts += 1
                    status()
                    event('rejoin_attempt', detail, scene=scene)
                    driver.recover(equip_rod=False)
                    rejoins += 1
                    last_success = time.time()
                    policy.succeeded()
                    stage, detail = 'watching', 'Roblox world connected'
                    event('rejoin_success', 'Roblox world is ready; watching connection.')
                status()
                time.sleep(3 if scene == 'world' else 1)
            except UserStop as error:
                reason = str(error)
                break
            except InputPaused:
                stage, detail = 'paused_focus', 'Roblox focus changed; input released'
                status()
                time.sleep(.3)
            except (RuntimeError, RecoveryError, ValueError, win32gui.error) as error:
                delay = policy.failed(time.monotonic())
                driver.restarts = 0
                stage, detail = 'retry_wait', str(error)[:220]
                event('rejoin_retry', detail, retry_seconds=round(delay))
                status()
                time.sleep(1)
    except Exception as error:
        reason = f'{type(error).__name__}: {error}'
        event('rejoin_error', reason)
        raise
    finally:
        listener.stop()
        driver.inp.gate.close()
        driver.sct.close()
        stage = 'stopped'
        status(False)
        event('rejoin_stopped', reason or 'Connection guard ended.')
        log.close()
        for name in ('supervisor-pid.json', 'pid.json'):
            try:
                record = json.loads((RUN/name).read_text(encoding='utf-8'))
                if record.get('pid') == os.getpid():
                    (RUN/name).unlink(missing_ok=True)
            except (OSError, ValueError):
                pass


if __name__ == '__main__':
    main()
