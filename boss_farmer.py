"""Foreground-only Sanemi setup and bounded combat trials.

The statue controller is never imported or started as a worker. Boss inputs,
health measurements, stop reasons and events have their own run records.
"""
import argparse
import ctypes
from dataclasses import asdict, replace
import json
import math
import os
import threading
import time

import cv2
import mss
import psutil
from rapidocr_onnxruntime import RapidOCR

from app_config import load_config
from boss_plan import FightLedger, can_attack
from boss_vision import observe, rows_in, fast_health, cutscene_visible, combat_hud_visible, chat_send_button, player_bar_fraction
from boss_tracking import BossTracker
from boss_loot import prompt_from_rows, reward_from_rows
from damage_vision import blocked_scene, gauntlet_selected, SkillReady, C_ICON_BOX, Z_ICON_BOX, B_ICON_BOX, B_READY_REFERENCE
from fishing_assistant import USER, find_window, rectangle, move_pointer
from metrics import RUN, read, write
from minigame_assist import ForegroundInput, foreground, navigation_keys_down, stop_reason, watch_focus
from screen_space import ScreenSpace


class BossInput(ForegroundInput):
    """Own every held key so the focus watcher can release movement immediately."""
    def __init__(self):
        super().__init__()
        self.keys = set()
        self.released_keys = set()
        self.right_mouse = False

    def right(self, down):
        with self.lock:
            self.guard_press(down)
            if down != self.right_mouse:
                USER.mouse_event(8 if down else 16, 0, 0, 0, 0)
                self.right_mouse = down

    def key(self, key, down):
        vk = {'enter': 13, 'esc': 27, 'space': 32}.get(key)
        if vk is None:
            vk = ord(key.upper())
        self.key_code(vk, down)

    def key_code(self, vk, down):
        with self.lock:
            self.guard_press(down)
            if down and vk not in self.keys:
                self.keys.add(vk)
                USER.keybd_event(vk, USER.MapVirtualKeyW(vk, 0), 0, 0)
            elif not down and vk in self.keys:
                USER.keybd_event(vk, USER.MapVirtualKeyW(vk, 0), 2, 0)
                self.keys.discard(vk)

    def release(self):
        with self.lock:
            super().release()
            if self.right_mouse:
                USER.mouse_event(16, 0, 0, 0, 0)
                self.right_mouse = False
            for vk in tuple(self.keys):
                USER.keybd_event(vk, USER.MapVirtualKeyW(vk, 0), 2, 0)
                self.released_keys.add(vk)
                self.keys.discard(vk)

    def sync_game_input(self):
        with self.lock:
            super().sync_game_input()
            for vk in tuple(self.released_keys):
                USER.keybd_event(vk, USER.MapVirtualKeyW(vk, 0), 2, 0)
                self.released_keys.discard(vk)


class BossSession:
    def __init__(self, operation, seconds):
        self.operation, self.seconds = operation, seconds
        self.config = load_config()['boss']
        self.inp = BossInput()
        self.inp.hwnd = find_window()
        self.inp.toggle_enabled = True
        self.screen = ScreenSpace(rectangle(self.inp.hwnd))
        self.ocr = RapidOCR()
        self.ledger = FightLedger()
        self.stage, self.reason = 'boss_waiting', 'Waiting for Roblox focus'
        self.observation = None
        self.started = time.time()
        self.session = time.strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid())
        self.log = (RUN/f'events-boss-{self.session}.jsonl').open('a', encoding='utf-8', buffering=1)
        self.skill_damage = {}
        self.actions = 0
        self.last_status = 0.
        self.tracker = BossTracker(RUN/'boss-reference')
        self.target = None
        self.cycles = self.resets = self.empty_cycles = 0
        self.last_timer = None
        self.respawn_deadline = None
        self.last_timer_read = None
        self.timer_samples = 0
        self.world_label = None
        self.search_direction = 1
        self.visions = {'c': SkillReady(C_ICON_BOX), 'z': SkillReady(Z_ICON_BOX),
                        'b': SkillReady(B_ICON_BOX),
                        'ultimate': SkillReady(B_ICON_BOX, B_READY_REFERENCE)}
        self.spawn_updates = 0
        self.loot_items = {}
        self.loot_attempted = False
        self.last_identity_at = 0.

    def event(self, kind, **fields):
        self.log.write(json.dumps({'at': time.time(), 'event': kind, 'mode': 'boss', **fields})+'\n')

    def status(self, running=True):
        now = time.time()
        payload = {'running': running, 'updated': now, 'started': self.started,
                   'mode': 'boss', 'session': self.session, 'operation': self.operation,
                   'stage': self.stage, 'wait_reason': self.reason, 'reason': self.reason,
                   'observation': asdict(self.observation) if self.observation else {},
                   'boss_hp': self.ledger.hp, 'observed_damage': round(self.ledger.damage, 2),
                   'confirmed_kills': self.ledger.kills, 'reset_retention': self.ledger.retention,
                   'skill_samples': self.skill_damage, 'actions': self.actions,
                   'strategy': self.config['strategy'], 'cycles': self.cycles, 'resets': self.resets,
                   'spawn_updates': self.spawn_updates,
                   'loot_items': self.loot_items,
                   'observed_dph': round(self.ledger.damage*3600/max(1,now-self.started),1),
                   'target_evidence': asdict(self.target) if self.target else None,
                   'respawn_remaining': max(0, round(self.respawn_deadline-time.monotonic())) if self.respawn_deadline else None,
                   'elapsed_seconds': round(now-self.started, 1),
                   'validated_for_unattended': False}
        write('boss-status.json', payload)
        write('status.json', {**payload, 'pid': os.getpid()})
        write('supervisor.json', {**payload, 'pid': os.getpid(), 'worker_pid': os.getpid(),
                                  'recoveries': 0})
        self.last_status = time.monotonic()

    def guard(self):
        self.inp.guard_press(True)
        if self.inp.toggle_requested.is_set():
            raise RuntimeError('F8 paused the boss trial; restart explicitly after inspecting the scene')
        if time.time()-self.started >= self.seconds:
            raise RuntimeError('Boss session time limit reached; input released')

    def wait(self, seconds):
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            self.guard()
            if time.monotonic()-self.last_status > .5:
                self.status()
            time.sleep(.02)

    def tap(self, key, seconds=.065):
        self.guard()
        self.inp.key(key, True)
        try:
            self.wait(seconds)
        finally:
            self.inp.key(key, False)

    def click(self, x, y):
        self.guard()
        move_pointer(*self.screen.point(x, y))
        self.wait(.35)
        move_pointer(*self.screen.point(x+1,y))
        self.wait(.15)
        move_pointer(*self.screen.point(x,y))
        self.wait(.25)
        self.inp.hold(True)
        try:
            self.wait(.075)
        finally:
            self.inp.hold(False)

    def scan(self, sct, *, locate=True):
        self.guard()
        frame = self.screen.capture(sct)
        cv2.imwrite(str(RUN/'boss-latest.jpg'), frame, [cv2.IMWRITE_JPEG_QUALITY, 94])
        blocked = blocked_scene(frame, self.ocr)
        self.observation = observe(frame, self.ocr, blocked)
        self.guard()
        o = self.observation
        self.world_label = o.target
        identity = not o.blocked and o.name in ('Saneri', 'Sanemi') and o.hp is not None and o.hp > 0
        self.last_identity_at = time.monotonic() if identity else 0.
        if o.respawn_seconds is not None:
            self.respawn_deadline = time.monotonic()+o.respawn_seconds
            self.last_timer_read = time.monotonic()
            self.timer_samples += 1
        elif identity:
            self.timer_samples = 0
            self.respawn_deadline = None
        self.target = self.tracker.update(frame, time.monotonic(), identity) if locate else None
        if locate and identity and self.target is None:
            self.target = self.tracker.from_label(frame, o.target, time.monotonic(), o.target_height)
        if self.target:
            tx, ty = self.target.center
            label = o.target
            if label is None or abs(label[0]-tx) > max(170, self.target.box[2]) or not -30 < self.target.box[1]-label[1] < 320:
                self.target = None
                self.tracker.clear()
        if locate and self.target is None:
            self.observation = replace(self.observation, target=None)
        outcome = self.ledger.observe(self.observation, time.monotonic())
        if outcome == 'kill':
            self.event('boss_kill', message='Defeat confirmed by repeated zero HP or visible respawn countdown')
        self.status()
        return self.observation, frame

    def track_step(self, sct):
        """Track short walking steps between identity scans, without stale HP votes."""
        self.guard()
        now=time.monotonic()
        if now-self.last_identity_at < 1. and self.target is not None:
            frame=self.screen.capture(sct)
            target=self.tracker.update(frame,now,True)
            player=player_bar_fraction(frame)
            if target is not None and player is not None and combat_hud_visible(frame):
                self.target=target
                return replace(self.observation,target=target.center,player_fraction=player),frame
        return self.scan(sct)

    def travel(self, sct):
        """Open travel, selecting only a unique visible Windy Peak destination."""
        self.stage, self.reason = 'boss_travel', 'Opening the travel map'
        self.status()
        self.tap('m')
        self.wait(.8)
        rows = rows_in(self.screen.capture(sct), self.ocr, (100, 80, 2360, 1250))
        destinations = [r for r in rows if r['score'] >= .8 and 'windy peak' in r['text'].lower()]
        self.event('boss_travel_menu', labels=[r['text'] for r in rows],
                   message='Inspected travel destinations')
        if len(destinations) != 1:
            raise RuntimeError('Windy Peak shrine is not uniquely visible; travel stopped for inspection')
        destination = destinations[0]
        self.click(destination['x'], destination['y'])
        self.wait(.8)
        # The next screen can contain costs or destination choices; don't
        # confirm it from the old menu. Setup is deliberately a bounded step.
        self.reason = 'Windy Peak selected; inspect the travel confirmation before proceeding'
        self.event('boss_travel_selected', message=self.reason)

    def trial(self, sct):
        self.cycle(sct)
        self.reason = 'One measured combo completed'

    def collect_loot(self, sct):
        o, frame = self.scan(sct,locate=False)
        if o.respawn_seconds is None:
            raise RuntimeError('Sanemi respawn countdown is required before loot interaction')
        self.stage, self.reason = 'boss_loot', 'Reading nearby chest and item prompts'
        deadline = time.monotonic()+min(75., max(0.,o.respawn_seconds-12.))
        self.turn(0,180)
        previous = None
        seen_rewards = set()
        searches = misses = 0
        for attempt in range(32):
            self.guard()
            if time.monotonic() >= deadline:
                break
            frame = self.screen.capture(sct)
            cv2.imwrite(str(RUN/'boss-latest.jpg'),frame)
            rows = rows_in(frame,self.ocr,(150,350,2300,900),1.2)
            if not any(row['text'].strip().upper() == 'T' for row in rows):
                for row in tuple(rows):
                    if row['text'].strip().lower() in ('open','claim','collect'):
                        rows.extend(found for found in rows_in(frame,self.ocr,
                            (max(0,round(row['x']-350)),max(0,round(row['y']-110)),350,170),2.)
                            if found['text'].strip().upper() == 'T')
            prompt = prompt_from_rows(rows)
            for name,quantity in reward_from_rows(rows):
                key=(''.join(char.lower() for char in name if char.isalpha()),quantity)
                if key not in seen_rewards:
                    seen_rewards.add(key)
                    self.loot_items[name] = self.loot_items.get(name,0)+quantity
                    self.event('boss_loot_confirmed',name=name,quantity=quantity)
            self.event('boss_loot_observation',labels=[row['text'] for row in rows],
                       message='Read nearby loot; quantities are not assumed')
            self.evidence(frame,f'loot_{attempt}')
            if prompt is None:
                misses += 1
                if misses < 3:
                    self.wait(.4)
                    continue
                if searches < 4:
                    self.turn(180)
                    searches += 1
                    misses = 0
                    continue
                break
            misses = 0
            if previous and prompt.name == previous.name and prompt.action == previous.action:
                self.tap('t',1.5)
                self.actions += 1
                self.event('boss_loot_interaction',name=prompt.name,action=prompt.action)
                self.wait(.6)
                previous = None
            else:
                previous = prompt
                self.wait(.1)
        # Searches should not leave the camera facing away from the saved
        # combat position on the next spawn.
        if searches:
            self.turn(-180*searches)
        self.turn(0,-180)
        self.reason = 'Loot search finished; only confirmed reward toasts are counted'

    def evidence(self, frame, label):
        path = RUN/f'boss-{self.session}-{self.cycles:04}-{label}.jpg'
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 94])

    def set_spawn(self, sct):
        """Type only the authorized /set command into a verified chat field."""
        self.stage, self.reason = 'boss_setting_spawn', 'Saving the verified close position with /set'
        def chat_rows():
            return rows_in(self.screen.capture(sct), self.ocr, (0,50,750,500))
        def fields(rows):
            return [row for row in rows if 'chat' in row['text'].lower() and
                    any(word in row['text'].lower() for word in ('click','here','press','type'))]
        rows = chat_rows()
        if not fields(rows):
            self.click(138,35)
            self.wait(.2)
            rows = chat_rows()
        inputs = fields(rows)
        if len(inputs) != 1:
            raise RuntimeError('Chat input is not uniquely visible; spawn command withheld')
        self.click(inputs[0]['x'],inputs[0]['y'])
        for char in '/set':
            code = USER.VkKeyScanW(ctypes.c_wchar(char))
            if code == -1 or code >> 8 & ~1:
                raise RuntimeError('Spawn command cannot be typed with this keyboard layout')
            vk, shift = code & 255, code >> 8 & 1
            if shift:self.inp.key_code(16,True)
            try:
                self.inp.key_code(vk,True)
                self.wait(.045)
            finally:
                self.inp.key_code(vk,False)
                if shift:self.inp.key_code(16,False)
            self.wait(.05)
        self.wait(.15)
        if not any(row['text'].strip().lower() == '/set' for row in chat_rows()):
            raise RuntimeError('Typed /set was not verified; command withheld')
        button = chat_send_button(self.screen.capture(sct),inputs[0]['y'])
        if button is None:
            raise RuntimeError('Chat send button is not uniquely visible; /set withheld')
        self.click(*button)
        confirmed = False
        for _ in range(8):
            self.wait(.2)
            rows = rows_in(self.screen.capture(sct),self.ocr,(950,40,700,120),1.4)
            if any('spawnset' in ''.join(char for char in row['text'].lower() if char.isalpha()) for row in rows):
                confirmed = True
                break
        if not confirmed:
            self.evidence(self.screen.capture(sct),'spawn_unconfirmed')
            self.click(138,35)
            raise RuntimeError('Spawn confirmation was not seen; input stopped')
        self.spawn_updates += 1
        self.event('boss_spawn_set',message='Verified Spawn Set after /set')
        self.click(138,35)
        self.wait(.15)

    def turn(self, pixels, vertical=0):
        self.guard()
        move_pointer(*self.screen.point(1280, 760))
        self.inp.right(True)
        try:
            self.wait(.18)
            count = max(1, abs(round(pixels))//4,abs(round(vertical))//4)
            for i in range(count):
                self.guard()
                USER.mouse_event(1, round((i+1)*pixels/count)-round(i*pixels/count),
                                 round((i+1)*vertical/count)-round(i*vertical/count),0,0)
                self.wait(.012)
        finally:
            self.inp.right(False)
        self.wait(.2)

    def acquire(self, sct):
        self.stage, self.reason = 'boss_acquiring', 'Verifying boss name, appearance, range and player HP'
        until = time.monotonic()+self.config['target_timeout']
        walked = 0.
        searched = 0
        while time.monotonic() < until:
            o, frame = self.track_step(sct)
            if o.respawn_seconds is not None:
                return None, frame
            if o.blocked:
                raise RuntimeError('Game menu or disconnected scene detected; input stopped')
            if self.target and can_attack(o):
                x, y, w, h = self.target.box
                offset = x+w/2-1280
                self.search_direction = -1 if offset < 0 else 1
                if w > 180 and y+h/2 > 680:
                    if walked+.20 > self.config['max_approach_seconds']:
                        raise RuntimeError('Approach budget reached')
                    self.tap('s', .20)
                    walked += .20
                    self.wait(.15)
                elif abs(offset) > 260:
                    # Turn toward distant targets first. Repeated short
                    # strafes plus OCR can otherwise consume the heal window.
                    self.turn(max(-160,min(160,round(offset/6))))
                elif w < 130:
                    step = .25 if w < 100 else .15
                    if walked+step > self.config['max_approach_seconds']:
                        raise RuntimeError('Approach budget reached; no unverified walking')
                    self.tap('w', step)
                    walked += step
                    self.wait(.2)
                else:
                    if not gauntlet_selected(frame):
                        self.tap('1')
                        self.wait(.3)
                        continue
                    # Movement establishes facing; pointer aiming alone does
                    # not turn an unlocked Roblox character's M1 direction.
                    face = ('a' if offset < 0 else 'd') if abs(offset) > 100 else ('s' if y+h/2 > 750 else 'w')
                    self.tap(face, .035)
                    self.wait(.1)
                    o, frame = self.scan(sct)
                    if (can_attack(o) and self.target and self.target.box[2] >= 130
                            and abs(self.target.center[0]-1280) <= 260):
                        if walked > .35:
                            self.set_spawn(sct)
                            o, frame = self.scan(sct)
                            if (not can_attack(o) or self.target is None or self.target.box[2] < 130
                                    or abs(self.target.center[0]-1280) > 260):
                                continue
                        return o, frame
            else:
                if (o.name in ('Saneri','Sanemi') and o.hp and self.world_label is None and searched < 1440):
                    self.reason = 'Looking around for Sanemi after displacement'
                    self.turn(self.search_direction*180)
                    searched += 180
                else:
                    self.wait(.2)
        raise RuntimeError('Boss reacquisition or approach did not finish within its limit; input stopped')

    def measure(self, name, before, after):
        if before is None or after is None or after > before:
            return
        damage = round(before-after, 2)
        row = self.skill_damage.setdefault(name, {'samples': 0, 'total': 0., 'last': 0., 'average': 0.})
        row['samples'] += 1
        row['total'] = round(row['total']+damage, 2)
        row['last'] = damage
        row['average'] = round(row['total']/row['samples'], 2)
        self.event('boss_damage_sample', skill=name, damage=damage,
                   message='Observed boss HP loss; may include residual or other-player damage')

    def normal_b(self, sct, before):
        self.stage, self.reason = 'boss_cutscene', 'Aiming normal B; watching for the cutscene to finish'
        self.tap('b', 1.)
        self.actions += 1
        seen = False
        start = time.monotonic()
        while time.monotonic()-start < 9:
            self.guard()
            frame = self.screen.capture(sct)
            cinematic = cutscene_visible(frame)
            seen |= cinematic
            if combat_hud_visible(frame) and (seen or time.monotonic()-start > .6):
                self.evidence(frame,'b_end')
                return frame
            self.wait(.045)
        raise RuntimeError('B cutscene did not finish within its observed limit')

    def cycle(self, sct):
        if self.config['reset_after_combo'] and not self.config['spawn_verified']:
            raise RuntimeError('Saved spawn is not verified')
        o, frame = self.acquire(sct)
        if o is None:
            return False
        before = o.hp
        self.cycles += 1
        self.evidence(frame, 'before')
        self.stage, self.reason = 'boss_attacking', 'Executing a bounded combo'
        x, y = self.target.center
        y = min(1150, y+self.target.box[3])
        move_pointer(*self.screen.point(x, y)); self.wait(.25)
        move_pointer(*self.screen.point(x+1, y)); self.wait(.1)
        move_pointer(*self.screen.point(x, y)); self.wait(.15)
        strategy = self.config['strategy']
        b_frame = None
        if strategy == 'b_m1_c_reset' and self.visions['b'].observe(frame):
            b_frame = self.normal_b(sct, before)
            self.stage, self.reason = 'boss_attacking', 'Following B with M1s during the stun'
        if strategy == 'ultimate_reset':
            if not self.visions['ultimate'].observe(frame):
                self.reason = 'Ultimate cooldown is active; waiting'
                self.wait(1)
                return False
            self.tap('x', .025)
            self.wait(.5)
            self.tap('b', 2.)
            self.actions += 2
            self.wait(.6)
            after, frame = self.scan(sct, locate=False)
            self.measure('X + B ultimate', before, after.hp)
        else:
            # Full OCR between clicks breaks the combo. Identity/range/HP were
            # just verified; this fixed four-click burst lasts under 1.5s.
            for index in range(self.config['m1_count']):
                self.guard()
                self.inp.hold(True)
                try:
                    self.wait(.065)
                finally:
                    self.inp.hold(False)
                self.actions += 1
                self.wait(self.config['m1_interval'] if index < self.config['m1_count']-1 else .5)
            frame = self.screen.capture(sct)
            self.evidence(frame, 'm1')
            use_c = strategy in ('m1_c_reset','b_m1_c_reset') and self.visions['c'].observe(frame)
            if use_c:
                # Send the follow-up before OCR: the boss can block/counter
                # during a one-second OCR gap between M1 and the skill.
                self.tap('c', .065)
                self.actions += 1
            measured_m1 = fast_health(frame, self.ocr)
            if b_frame is not None:
                b_hp = fast_health(b_frame,self.ocr)
                self.measure('B cutscene / block break',before,b_hp)
                before = b_hp
            self.measure(f"{self.config['m1_count']} M1", before, measured_m1)
            if use_c:
                self.wait(2.)
                after, frame = self.scan(sct, locate=False)
                self.evidence(frame, 'c')
                self.measure('C Explosive Fury', measured_m1, after.hp)
        self.wait(.15)
        final, frame = self.scan(sct, locate=False)
        self.empty_cycles = self.empty_cycles+1 if final.hp is not None and final.hp >= o.hp else 0
        if self.empty_cycles >= 2:
            raise RuntimeError('Two measured combos caused no HP loss; stopping to inspect positioning or blocking')
        if final.respawn_seconds is not None or final.hp == 0:
            return True
        if self.config['reset_after_combo']:
            from damage_farmer import reset_character
            self.stage, self.reason = 'boss_resetting', 'Deliberate reset after the combo'
            if self.ledger.hp is None or self.ledger.hp <= 0:
                raise RuntimeError('Boss HP is unverified; tactical reset withheld')
            self.ledger.before_reset()
            if not reset_character(self.inp, self.screen, sct, self.ocr, self.event, deliberate=True):
                raise RuntimeError('Reset menu was not confirmed')
            self.resets += 1
            self.tracker.clear()
            self.wait(self.config['respawn_wait'])
            self.scan(sct, locate=False)
            self.wait(.15)
            o, frame = self.scan(sct, locate=False)
            self.evidence(frame, 'respawn')
            if self.ledger.retention == 'healed':
                self.event('boss_healing',message='HP rose during reset/approach; re-engaging promptly')
                if o.hp is not None and before is not None and o.hp >= before:
                    self.empty_cycles += 1
                    if self.empty_cycles >= 2:
                        raise RuntimeError('Repeated resets lost all combo progress to healing')
        return True

    def farm(self, sct):
        if not self.config['spawn_verified'] or not self.config['reset_after_combo']:
            raise RuntimeError('Farm requires a verified saved spawn and explicit combo resets')
        while True:
            o, frame = self.scan(sct)
            if o.respawn_seconds is not None or (self.respawn_deadline and time.monotonic() < self.respawn_deadline):
                if not self.loot_attempted and o.respawn_seconds is not None and o.respawn_seconds > 35:
                    self.loot_attempted = True
                    self.collect_loot(sct)
                if self.cycles >= self.config['max_cycles']:
                    self.reason = 'Configured combo limit reached; nearby loot checked'
                    return
                self.stage = 'boss_respawn_wait'
                remaining = max(0, round(self.respawn_deadline-time.monotonic()))
                self.reason = f'Waiting for Sanemi: {remaining//60}:{remaining%60:02d}'
                self.inp.release()
                self.wait(min(5., max(.2, remaining)))
                continue
            if self.cycles >= self.config['max_cycles']:
                self.reason = 'Configured combo limit reached'
                return
            self.loot_attempted = False
            self.cycle(sct)

    def run(self):
        done = threading.Event()
        watcher = threading.Thread(target=watch_focus, args=(self.inp, done), daemon=True)
        watcher.start()
        try:
            self.status()
            deadline = time.monotonic()+15
            while not foreground(self.inp.hwnd) or navigation_keys_down():
                if stop_reason():
                    raise RuntimeError(stop_reason())
                if time.monotonic() > deadline:
                    raise RuntimeError('Roblox did not gain focus; no boss input sent')
                time.sleep(.1)
            self.inp.interrupted.clear()
            self.inp.sync_game_input()
            with mss.mss() as sct:
                if self.operation == 'travel':
                    self.travel(sct)
                elif self.operation == 'trial':
                    self.trial(sct)
                elif self.operation == 'farm':
                    self.farm(sct)
                elif self.operation == 'loot':
                    self.collect_loot(sct)
                else:
                    self.stage, self.reason = 'boss_observing', 'Observation only; no movement or attacks'
                    while time.time()-self.started < self.seconds:
                        self.scan(sct)
                        self.wait(.25)
        except (RuntimeError, ValueError) as error:
            self.reason = stop_reason() or str(error)
            self.event('boss_stopped', message=self.reason)
        finally:
            done.set()
            self.inp.release()
            watcher.join(timeout=1)
            self.stage = 'stopped'
            self.status(False)
            self.log.close()


def rejoin(seconds=180):
    """Use the proven menu driver without rod equip, fishing titles or fishing."""
    from recovery import Recovery
    driver = Recovery()
    started = time.time()
    deadline = time.monotonic()+seconds
    original_check = driver.check_stop
    def check():
        original_check()
        if time.monotonic() >= deadline:
            driver.inp.release()
            raise RuntimeError('Boss rejoin time limit reached')
        if driver.hwnd and foreground(driver.hwnd) and USER.GetAsyncKeyState(119)&0x8000:
            driver.inp.release()
            try:
                with (RUN/'STOP').open('x',encoding='utf-8') as stream:
                    stream.write('Stopped by F8 during boss rejoin')
            except FileExistsError:
                pass
            raise RuntimeError('Stopped by F8 during boss rejoin')
    driver.check_stop = check
    def report(detail='inspecting', running=True, reason=''):
        payload = {'mode': 'boss', 'operation': 'rejoin', 'pid': os.getpid(),
                   'worker_pid': os.getpid(), 'started': started, 'updated': time.time(),
                   'running': running, 'stage': 'boss_rejoining' if running else 'stopped',
                   'wait_reason': detail, 'reason': reason}
        write('supervisor.json', payload)
        write('status.json', payload)
        write('boss-status.json', payload)
    driver.progress = lambda **kw: report(**kw)
    report()
    reason = 'Rejoined at the saved spawn; no farming started'
    try:
        try:
            driver.select(focus=True)
        except RuntimeError:
            driver.launch()
        driver.inp.gate.acknowledge()
        driver.recover(equip_rod=False)
    except Exception as error:
        reason = stop_reason() or str(error)
        raise
    finally:
        driver.inp.gate.close()
        driver.sct.close()
        report(running=False, reason=reason)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--operation', choices=('observe', 'travel', 'trial', 'rejoin', 'farm', 'loot'), default='observe')
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--respect-stop', action='store_true')
    args = parser.parse_args(argv)
    limit = 43200 if args.operation in ('farm', 'observe') else 180
    if not math.isfinite(args.seconds) or not 5 <= args.seconds <= limit:
        raise ValueError(f'Boss session must be 5–{limit} seconds')
    import control_actions as controls
    RUN.mkdir(parents=True, exist_ok=True)
    with controls.guard():
        if controls.alive() or controls.alive('pid.json'):
            raise RuntimeError('Another controller is running')
        if stop_reason():
            raise RuntimeError('Stop is set; start the boss trial explicitly')
        record = {'pid': os.getpid(), 'created': psutil.Process().create_time()}
        write('supervisor-pid.json', record)
        write('pid.json', record)
    try:
        if args.operation == 'rejoin':
            rejoin(args.seconds)
        else:
            BossSession(args.operation, args.seconds).run()
    finally:
        with controls.guard():
            for name in ('supervisor-pid.json', 'pid.json'):
                if read(name).get('pid') == os.getpid():
                    (RUN/name).unlink(missing_ok=True)


if __name__ == '__main__':
    main()
