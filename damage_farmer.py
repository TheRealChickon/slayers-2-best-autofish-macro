"""Foreground-only stationary damage mode with title-verified measurements."""

import argparse
import json
import os
import threading
import time

import mss
import psutil
import win32gui
from rapidocr_onnxruntime import RapidOCR

from damage_cycle import FiveHitGuard, ProgressGuard
from damage_plan import DamageRotation
from damage_title import DamageTitleReader
from damage_measure import DamageMeasurements
from damage_vision import B_ICON_BOX, C_ICON_BOX, Z_ICON_BOX, B_READY_REFERENCE, SkillReady, combo_count, blocked_scene, scene_text, gauntlet_selected, hotbar_visible
from inventory_watch import InventoryDriver
from app_config import load_config
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


def hold_key(inp, key, seconds):
    """Release a held skill even when focus or a stop changes during it."""
    vk = ord(key.upper())
    inp.guard_press(True)
    USER.keybd_event(vk, USER.MapVirtualKeyW(vk, 0), 0, 0)
    try:
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            inp.guard_press(True)
            time.sleep(.025)
    finally:
        USER.keybd_event(vk, USER.MapVirtualKeyW(vk, 0), 2, 0)


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

    config = load_config()
    if not config['damage_title']:
        raise ValueError('Configure the exact damage title with autofish damage --title NAME --configure-only')
    rotation = config['damage_rotation']
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
    if B_READY_REFERENCE is None:
        raise RuntimeError('The verified ultimate icon reference is missing')
    cycle, progress, hit_guard, ultimate_vision = (DamageRotation(rotation), ProgressGuard(), FiveHitGuard(),
                                         SkillReady(B_ICON_BOX, B_READY_REFERENCE))
    shock_vision, followup_vision = SkillReady(C_ICON_BOX), SkillReady(Z_ICON_BOX)
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
    move_uses = {name: max(0, int((previous.get('move_uses') or {}).get(name, 0)))
                 for name in ('shock_wave', 'followup', 'ultimate')}
    observed_hits = max(0, int(previous.get('observed_hits', 0)))
    measurements = DamageMeasurements(config['damage_target'],
        previous.get('title_start', 0) if args.resume_counters else 0, active_seconds)
    if args.resume_counters and previous.get('title_progress'):
        measurements.total = int(previous['title_progress'])
    combo = None
    ultimate_ready = False
    needs_setup = True
    needs_calibration = True
    last_progress_check = 0.
    next_setup = 0.
    scene_blocked = False
    def status(running=True):
        now = time.time()
        measurements.active_seconds = active_seconds
        measured = measurements.summary()
        payload = {'running': running, 'updated': now, 'session': session, 'mode': 'damage',
                   'stage': stage, 'wait_reason': wait_reason, 'manual_paused': manual_paused,
                   'combo': combo, 'observed_hits': observed_hits, 'm1_clicks': clicks,
                   'c_casts': casts, 'move_uses': dict(move_uses), 'cycles': cycles, 'resets': resets,
                   'active_seconds': round(active_seconds, 1), 'title_start': measurements.starting_total,
                   'title_name': config['damage_title'], 'rotation': rotation,
                   'five_million_hours': measured['eta_hours'],
                   'estimate_note': 'Verified in-game title progress; pace updates at each periodic read.',
                   **measured,
                   'reason': reason if not running else ''}
        write('damage-status.json', payload)
        write('supervisor.json', {'running': running, 'pid': os.getpid(), 'started': started,
             'updated': now, 'stage': stage if running else 'stopped', 'mode': 'damage',
             'worker_pid': os.getpid(), 'recoveries': resets, 'reason': reason if not running else ''})
        write('status.json', {'running': running, 'pid': os.getpid(), 'updated': now,
             'session': session, 'mode': 'damage', 'stage': stage, 'manual_paused': manual_paused,
             'wait_reason': wait_reason, 'reason': reason if not running else ''})

    def guarded_wait(seconds):
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            inp.guard_press(True)
            if inp.toggle_requested.is_set():
                raise RuntimeError('F8 requested during damage measurement')
            time.sleep(.025)

    def perform_move(role):
        nonlocal casts
        keys = rotation['keys']
        if role == 'ultimate_pair':
            # X is never sent alone. Release it before holding B.
            press(inp, keys['ultimate_prep'], rotation['ultimate_prep_tap_seconds'])
            hold_key(inp, keys['ultimate'], rotation['ultimate_hold_seconds'])
        else:
            press(inp, keys[role])
        counted = 'ultimate' if role == 'ultimate_pair' else role
        move_uses[counted] += 1
        if role == 'shock_wave':
            casts += 1

    def calibrate(reader):
        """Establish title progress without disrupting the requested rotation."""
        baseline = reader.inspect()
        if not args.resume_counters or not previous.get('last_verified'):
            measurements.starting_total = baseline
        measurements.observe(baseline, time.time())
        event('damage_baseline', title_progress=baseline,
              message=f'Verified starting title damage: {baseline:,}')
    event('damage_started', message='Measured five-M1, Shock Wave, follow-up and conditional ultimate rotation; F8 controls input.')
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
                        hit_guard.cancel()
                        cycle.resync(tick)
                        event('damage_paused' if manual_paused else 'damage_resumed',
                              message='F8 paused attacks.' if manual_paused else 'F8 resumed attacks.')
                    if not foreground(selected) or navigation_keys_down():
                        stage = 'paused_focus'
                        wait_reason = 'Return to Roblox; attacks resume automatically'
                        needs_setup = True
                        last_scan = 0.
                        hit_guard.cancel()
                        cycle.resync(tick)
                        time.sleep(.05)
                        continue
                    rect = rectangle(selected)
                    if selected != hwnd or screen is None or screen.rect != rect:
                        hwnd = selected
                        screen = ScreenSpace(rect)
                        needs_setup = True
                        hit_guard.cancel()
                        cycle.resync(tick)
                    if manual_paused:
                        stage = 'paused_manual'
                        wait_reason = 'F8 resumes attacks'
                        time.sleep(.05)
                        continue
                    if measurements.last_verified is not None and measurements.total >= measurements.target:
                        manual_paused = True
                        stage = 'title_complete'
                        wait_reason = 'Configured damage title is complete; stop this mode'
                        time.sleep(.05)
                        continue
                    if inp.interrupted.is_set():
                        inp.interrupted.clear()
                        needs_setup = True
                        last_scan = 0.
                        hit_guard.cancel()
                        cycle.resync(tick)
                    if tick-last_scan >= 2.:
                        frame = screen.capture(sct)
                        last_scan = tick
                        was_blocked = scene_blocked
                        scene_blocked = blocked_scene(frame, ocr)
                        if was_blocked and not scene_blocked:
                            needs_setup = True
                            hit_guard.cancel()
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
                        ultimate_ready = ultimate_vision.observe(setup_frame)
                        cycle.resync(time.monotonic())
                        needs_setup = False
                        next_setup = tick+2.
                        event('damage_ready', message='Gauntlet slot 1 selected; statue attack position ready.')
                        if needs_calibration:
                            stage = 'calibrating'
                            wait_reason = 'Measuring the configured title and each attack'
                            status()
                            driver = InventoryDriver(hwnd,screen,sct,inp,ocr,USER,move_pointer)
                            reader = DamageTitleReader(driver, config['damage_title'],
                                                       config['damage_target'], config['damage_title_category'])
                            try:
                                calibrate(reader)
                            except (RuntimeError, ValueError) as error:
                                manual_paused = True
                                needs_setup = True
                                stage = 'attention'
                                wait_reason = 'Damage calibration needs a manual check: '+str(error)
                                event('damage_attention', message=wait_reason)
                                continue
                            needs_calibration = False
                            last_progress_check = time.monotonic()
                            hit_guard.cancel()
                            cycle.resync(last_progress_check)
                    frame = screen.capture(sct) if tick-last_frame >= .18 else None
                    if frame is not None:
                        last_frame = tick
                        combo = combo_count(frame, ocr)
                        gain = progress.observe(combo)
                        observed_hits += gain
                        ultimate_ready = ultimate_vision.observe(frame)
                    if (tick-last_progress_check >= config['damage_check_seconds'] and
                            cycle.phase == 'm1' and cycle.m1_index == 0):
                        stage = 'checking_damage'
                        driver = InventoryDriver(hwnd,screen,sct,inp,ocr,USER,move_pointer)
                        reader = DamageTitleReader(driver, config['damage_title'],
                                                   config['damage_target'], config['damage_title_category'])
                        try:
                            measurements.observe(reader.inspect(), time.time())
                        except (RuntimeError, ValueError) as error:
                            manual_paused = True
                            needs_setup = True
                            last_progress_check = 0.
                            stage = 'attention'
                            wait_reason = 'Damage progress needs a manual check: '+str(error)
                            event('damage_attention', message=wait_reason)
                            continue
                        last_progress_check = time.monotonic()
                        hit_guard.cancel()
                        cycle.resync(last_progress_check)
                        event('damage_progress', message=f"Verified {measurements.total:,}/{measurements.target:,} title damage")
                        if measurements.total >= measurements.target:
                            manual_paused = True
                            stage = 'title_complete'
                            wait_reason = 'Configured damage title is complete'
                            event('damage_title_complete', message=wait_reason)
                            continue
                    # OCR can take longer than a frame; schedule from the actual
                    # press time so the fifth M1 is never squeezed by scan delay.
                    action_at = time.monotonic()
                    readiness_frame = screen.capture(sct)
                    if not hotbar_visible(readiness_frame):
                        # Ultimate cinematics hide the HUD. Do not send clicks
                        # or count that interval as a failed attack string.
                        stage = 'waiting_animation'
                        wait_reason = 'Waiting for the skill animation to finish'
                        hit_guard.cancel()
                        cycle.resync(time.monotonic())
                        time.sleep(.1)
                        continue
                    due = cycle.due(action_at, ultimate_vision.observe(readiness_frame),
                                    shock_vision.observe(readiness_frame),
                                    followup_vision.observe(readiness_frame))
                    action = due[0] if due else None
                    if action in ('shock_wave', 'skip_shock_wave'):
                        # Check after the fifth click but before any skill can
                        # add combo ticks. Two stable reads are required.
                        first_post = combo_count(screen.capture(sct), ocr)
                        observed_hits += progress.observe(first_post)
                        guarded_wait(.18)
                        second_post = combo_count(screen.capture(sct), ocr)
                        observed_hits += progress.observe(second_post)
                        combo = second_post if second_post is not None else first_post
                        baseline_combo = hit_guard.start_combo
                        result = hit_guard.check(observed_hits, first_post, second_post)
                        event('damage_five_hit_check', result=result, baseline=baseline_combo,
                              first_post=first_post, second_post=second_post, clicks=5,
                              message=f'Five M1s: {baseline_combo} -> {first_post}/{second_post}; {result}')
                        if result == 'investigate':
                            stage = 'checking_damage'
                            wait_reason = 'Two five-hit strings lacked confirmed combo growth; checking title'
                            status()
                            prior_title = measurements.total
                            driver = InventoryDriver(hwnd,screen,sct,inp,ocr,USER,move_pointer)
                            reader = DamageTitleReader(driver, config['damage_title'],
                                config['damage_target'], config['damage_title_category'])
                            try:
                                measurements.observe(reader.inspect(), time.time())
                            except (RuntimeError, ValueError) as error:
                                manual_paused = True
                                stage = 'attention'
                                wait_reason = 'Combo uncertain and title unreadable; reset withheld: '+str(error)
                                event('damage_attention', message=wait_reason)
                                continue
                            last_progress_check = time.monotonic()
                            hit_guard.title_progressed()
                            if measurements.total > prior_title:
                                event('damage_stall_cleared', message='Title increased despite uncertain combo; no reset.')
                            elif not progress.reset_allowed(action_at):
                                manual_paused = True
                                stage = 'attention'
                                wait_reason = 'Repeated verified stalls; reset limit reached'
                                event('damage_attention', message=wait_reason)
                            elif reset_character(inp, screen, sct, ocr, event):
                                resets += 1
                                needs_setup = True
                                next_setup = time.monotonic()+7.
                            else:
                                manual_paused = True
                                stage = 'attention'
                                wait_reason = 'Reset UI uncertain after verified stall'
                            cycle.resync(time.monotonic())
                            continue
                        if result != 'healthy':
                            event('damage_combo_uncertain', message=f'Five-hit result: {result}; reset withheld.')
                    if action == 'shock_wave':
                        perform_move('shock_wave')
                        event('damage_skill', message=f"{rotation['names']['shock_wave']} used after five M1s")
                    elif action == 'followup':
                        perform_move('followup')
                        event('damage_skill', message=f"{rotation['names']['followup']} used")
                    elif action == 'ultimate_pair':
                        perform_move('ultimate_pair')
                        ultimate_ready = False
                        event('damage_skill', message='Quick prep tap and held ultimate used together')
                    elif action == 'm1':
                        if due[1] == 1:
                            # Read immediately before this string, after prior skill ticks.
                            combo = combo_count(screen.capture(sct), ocr)
                            observed_hits += progress.observe(combo)
                            hit_guard.begin(observed_hits, combo)
                        attack_click(inp)
                        clicks += 1
                    elif action == 'cycle_end':
                        cycles += 1
                        progress.finish_cycle(True)
                        if cycles % 5 == 0:
                            event('damage_progress', message=f'Combo {combo or "—"} · {clicks} M1 · {casts} C · {resets} respawns.')
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
                    hit_guard.cancel()
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
