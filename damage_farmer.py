"""Foreground-only stationary damage mode. Attacks use C and M1 only."""

import argparse
import json
import os
import threading
import time

import mss
import psutil
import win32gui
from rapidocr_onnxruntime import RapidOCR

from damage_cycle import DamageCycle, ProgressGuard
from damage_vision import SkillReady, combo_count, blocked_scene, scene_text, gauntlet_selected, hotbar_visible
from fishing_assistant import ROOT, USER, find_window, rectangle, move_pointer
from metrics import RUN, read, write
from minigame_assist import ForegroundInput, foreground, navigation_keys_down, request_hotkey_stop, stop_reason, watch_focus
from screen_space import ScreenSpace


def press(inp, key, hold=.045):
    """One guarded tap; the key-up also runs if focus changes mid-tap."""
    vk = {'enter': 13, 'esc': 27}[key] if key in ('enter', 'esc') else ord(key.upper())
    inp.guard_press(True)
    USER.keybd_event(vk, USER.MapVirtualKeyW(vk, 0), 0, 0)
    try:
        time.sleep(hold)
    finally:
        USER.keybd_event(vk, USER.MapVirtualKeyW(vk, 0), 2, 0)


def attack_click(inp):
    inp.hold(True)
    time.sleep(.065)
    inp.hold(False)


def wait_for_scene(inp, screen, sct, ocr, predicate, seconds=2.5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        inp.guard_press(True)
        if predicate(scene_text(screen.capture(sct), ocr)):
            return True
        time.sleep(.2)
    return False


def reset_character(inp, screen, sct, ocr, event):
    """Use Roblox's visible reset menu; never blindly confirm a dialog."""
    inp.guard_press(True)
    inp.release()
    press(inp, 'esc')
    if not wait_for_scene(inp, screen, sct, ocr,
                          lambda text: any(word in text for word in ('respawn', 'reset character', 'reset avatar'))):
        event('reset_attention', message='Reset menu could not be verified; attacks paused.')
        return False
    press(inp, 'r')
    # "Respawn" alone is on the first menu. Require confirmation-specific text
    # so Enter cannot accidentally activate Resume if R was missed.
    if not wait_for_scene(inp, screen, sct, ocr,
                          lambda text: 'are you sure' in text or
                          ('cancel' in text and any(word in text for word in ('respawn', 'reset character', 'reset avatar')))):
        event('reset_attention', message='Reset confirmation could not be verified; attacks paused.')
        return False
    press(inp, 'enter')
    event('damage_reset', message='Combo stalled; reset character to saved spawn.')
    return True


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--respect-stop', action='store_true')
    parser.add_argument('--resume-counters', action='store_true')
    args = parser.parse_args(argv)
    import control_actions as controls
    RUN.mkdir(parents=True, exist_ok=True)
    with controls.guard():
        if controls.alive() or controls.alive('pid.json'):
            raise RuntimeError('A fishing controller is already running')
        if (RUN/'STOP').exists() or (RUN/'PAUSE').exists():
            raise RuntimeError('Stop is set; use explicit Continue')
        record = {'pid': os.getpid(), 'created': psutil.Process().create_time()}
        write('supervisor-pid.json', record)
        write('pid.json', record)
    session = time.strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid())
    started = time.time()
    events = (RUN/f'events-damage-{session}.jsonl').open('a', encoding='utf-8', buffering=1)
    def event(kind, **fields):
        events.write(json.dumps({'at': time.time(), 'event': kind, 'mode': 'damage', **fields})+'\n')

    inp = ForegroundInput()
    inp.toggle_enabled = True
    done = threading.Event()
    watcher = threading.Thread(target=watch_focus, args=(inp, done), daemon=True)
    watcher.start()
    cycle, progress, skill = DamageCycle(), ProgressGuard(), SkillReady()
    ocr = RapidOCR()
    hwnd = screen = None
    manual_paused = False
    stage = 'waiting_game'
    wait_reason = 'Bring Roblox forward'
    reason = ''
    last_scan = last_status = last_frame = 0.
    previous = read('damage-status.json') if args.resume_counters else {}
    if previous.get('mode') != 'damage':
        previous = {}
    active_seconds = max(0., float(previous.get('active_seconds', 0)))
    last_tick = time.monotonic()
    clicks, casts, cycles, resets = (max(0, int(previous.get(name, 0))) for name in
                                     ('m1_clicks', 'c_casts', 'cycles', 'resets'))
    observed_hits = max(0, int(previous.get('observed_hits', 0)))
    estimated_damage = max(0., float(previous.get('estimated_damage', 0)))
    combo = None
    skill_ready = False
    needs_setup = True
    next_setup = 0.
    scene_blocked = False
    def status(running=True):
        now = time.time()
        dps = estimated_damage/active_seconds if active_seconds >= 15 else None
        payload = {'running': running, 'updated': now, 'session': session, 'mode': 'damage',
                   'stage': stage, 'wait_reason': wait_reason, 'manual_paused': manual_paused,
                   'combo': combo, 'observed_hits': observed_hits, 'm1_clicks': clicks,
                   'c_casts': casts, 'cycles': cycles, 'resets': resets,
                   'estimated_damage': round(estimated_damage), 'active_seconds': round(active_seconds, 1),
                   'estimated_dps': round(dps, 1) if dps else None,
                   'five_million_hours': round(5_000_000/dps/3600, 2) if dps else None,
                   'estimate_note': 'Approximate: 70 per M1 hit and 38 per extra C tick; observed combo hits only.',
                   'reason': reason if not running else ''}
        write('damage-status.json', payload)
        write('supervisor.json', {'running': running, 'pid': os.getpid(), 'started': started,
             'updated': now, 'stage': stage if running else 'stopped', 'mode': 'damage',
             'worker_pid': os.getpid(), 'recoveries': resets, 'reason': reason if not running else ''})
        write('status.json', {'running': running, 'pid': os.getpid(), 'updated': now,
             'session': session, 'mode': 'damage', 'stage': stage, 'manual_paused': manual_paused,
             'wait_reason': wait_reason, 'reason': reason if not running else ''})
    event('damage_started', message='C then five M1s; Roblox focus and F8 control input.')
    status()
    try:
        with mss.MSS() as sct:
            while True:
                tick = time.monotonic()
                delta = min(1., tick-last_tick)
                last_tick = tick
                reason = stop_reason()
                if reason:
                    break
                try:
                    selected = hwnd if hwnd and win32gui.IsWindow(hwnd) else find_window()
                    inp.hwnd = selected
                    if request_hotkey_stop(selected):
                        reason = stop_reason()
                        break
                    if inp.toggle_requested.is_set():
                        inp.toggle_requested.clear()
                        manual_paused = not manual_paused
                        inp.suspend_input()
                        cycle.resync(tick)
                        event('damage_paused' if manual_paused else 'damage_resumed',
                              message='F8 paused attacks.' if manual_paused else 'F8 resumed attacks.')
                    if not foreground(selected) or navigation_keys_down():
                        stage = 'paused_focus'
                        wait_reason = 'Return to Roblox; attacks resume automatically'
                        needs_setup = True
                        last_scan = 0.
                        cycle.resync(tick)
                        time.sleep(.05)
                        continue
                    rect = rectangle(selected)
                    if selected != hwnd or screen is None or screen.rect != rect:
                        hwnd = selected
                        screen = ScreenSpace(rect)
                        needs_setup = True
                        cycle.resync(tick)
                    if manual_paused:
                        stage = 'paused_manual'
                        wait_reason = 'F8 resumes attacks'
                        time.sleep(.05)
                        continue
                    if inp.interrupted.is_set():
                        inp.interrupted.clear()
                        needs_setup = True
                        last_scan = 0.
                        cycle.resync(tick)
                    if tick-last_scan >= 2.:
                        frame = screen.capture(sct)
                        last_scan = tick
                        was_blocked = scene_blocked
                        scene_blocked = blocked_scene(frame, ocr)
                        if was_blocked and not scene_blocked:
                            needs_setup = True
                            cycle.resync(tick)
                    if scene_blocked:
                        stage = 'blocked_scene'
                        wait_reason = 'Close the game menu to resume'
                        time.sleep(.1)
                        continue
                    if needs_setup:
                        if tick < next_setup:
                            time.sleep(.05)
                            continue
                        # All attack clicks stay in the 3D viewport, never on a hotbar or menu.
                        inp.guard_press(True)
                        move_pointer(*screen.point(1280, 690))
                        time.sleep(.15)
                        setup_frame = screen.capture(sct)
                        if not hotbar_visible(setup_frame):
                            stage = 'waiting_spawn'
                            wait_reason = 'Waiting for the playable HUD'
                            next_setup = tick + 1.
                            continue
                        if not gauntlet_selected(setup_frame):
                            press(inp, '1')
                            time.sleep(.5)
                            if not gauntlet_selected(screen.capture(sct)):
                                manual_paused = True
                                stage = 'attention'
                                wait_reason = 'Gauntlet slot 1 did not equip; inspect the hotbar and press F8'
                                event('damage_attention', message=wait_reason)
                                continue
                        cycle.resync(time.monotonic())
                        needs_setup = False
                        next_setup = tick+2.
                        event('damage_ready', message='Gauntlet slot 1 selected; statue attack position ready.')
                    frame = screen.capture(sct) if tick-last_frame >= .18 else None
                    if frame is not None:
                        last_frame = tick
                        combo = combo_count(frame, ocr)
                        gain = progress.observe(combo)
                        observed_hits += gain
                        skill_ready = skill.observe(frame)
                    # OCR can take longer than a frame; schedule from the actual
                    # press time so the fifth M1 is never squeezed by scan delay.
                    action_at = time.monotonic()
                    action = cycle.due(action_at, skill_ready)
                    if action == 'c':
                        press(inp, 'c')
                        casts += 1
                        skill_ready = False
                        event('damage_skill', message=f'C cast {casts}; five M1s follow.')
                    elif action == 'm1':
                        attack_click(inp)
                        clicks += 1
                    elif action == 'cycle_end':
                        cycles += 1
                        hits = progress.cycle_hits
                        if cycle.skill_this_cycle:
                            estimated_damage += min(5, hits)*70 + max(0, hits-5)*38
                        else:
                            estimated_damage += min(5, hits)*70
                        stalled = progress.finish_cycle(cycle.skill_this_cycle)
                        if cycles % 5 == 0:
                            event('damage_progress', message=f'Combo {combo or "—"} · {clicks} M1 · {casts} C · {resets} respawns.')
                        if stalled:
                            if not progress.reset_allowed(action_at):
                                manual_paused = True
                                stage = 'attention'
                                wait_reason = 'Repeated resets did not restore combo; inspect statue position and press F8'
                                event('damage_attention', message=wait_reason)
                            elif reset_character(inp, screen, sct, ocr, event):
                                resets += 1
                                needs_setup = True
                                next_setup = time.monotonic()+7.
                                cycle.resync(next_setup)
                            else:
                                manual_paused = True
                                stage = 'attention'
                                wait_reason = 'Reset UI was uncertain; inspect Roblox and press F8'
                    active_seconds += delta
                    if not manual_paused:
                        stage = 'attacking'
                        wait_reason = ''
                    time.sleep(.025)
                except (RuntimeError, win32gui.error, ValueError) as error:
                    inp.suspend_input()
                    stage = 'paused_focus' if 'focus' in str(error).lower() or 'Roblox' in str(error) else 'attention'
                    wait_reason = str(error)
                    needs_setup = True
                    cycle.resync(tick)
                    time.sleep(.2)
                finally:
                    if tick-last_status >= 1.:
                        status()
                        last_status = tick
    except Exception as error:
        reason = f'Controller error: {type(error).__name__}: {error}'
        event('damage_error', message=reason)
        raise
    finally:
        done.set()
        inp.release()
        stage = 'stopped'
        status(False)
        event('damage_stopped', message=reason or 'Controller exited')
        events.close()
        for name in ('supervisor-pid.json', 'pid.json'):
            try:
                record = json.loads((RUN/name).read_text())
                if record.get('pid') == os.getpid():
                    (RUN/name).unlink(missing_ok=True)
            except (OSError, ValueError):
                pass


if __name__ == '__main__':
    main()
