"""Minigame-only assistant. Never casts, collects, equips, moves, or reconnects."""
import argparse
import json
import os
import time

import cv2
import mss
import psutil
import win32gui

from fishing_assistant import ROOT, USER, Input, detect, find_window, rectangle
from metrics import RUN, Ledger, read, write
from screen_space import ScreenSpace


class TrackingAssist:
    def __init__(self):
        self.active = False
        self.count = 0
        self.candidate = 0
        self.last_seen = 0
        self.clear_since = None
        self.previous = None
        self.velocity = self.target_velocity = 0
        self.held = False

    def suspend(self):
        self.previous = None
        self.held = False
        self.candidate = 0
        self.velocity = self.target_velocity = 0

    def step(self, detection, visible, now):
        if detection is None or not visible:
            self.candidate = 0
            if now-self.last_seen > .12: self.held = False
            if not visible:
                if self.clear_since is None: self.clear_since = now
                if now-self.clear_since > .5:
                    self.active = False; self.previous = None
            else:
                self.clear_since = None
            return self.held if self.active and visible else False
        self.clear_since = None
        self.candidate += 1
        self.last_seen = now
        if not self.active:
            if self.candidate < 2: return False
            self.active = True; self.count += 1
            self.previous = None; self.velocity = self.target_velocity = 0
        if self.previous:
            dt = max(.005, now-self.previous[0])
            self.velocity = .55*self.velocity+.45*(detection['ball']-self.previous[1])/dt
            self.target_velocity = .7*self.target_velocity+.3*(detection['target']-self.previous[2])/dt
        error = detection['ball']-detection['target']+.09*(self.velocity-self.target_velocity)
        if error > 3: self.held = True
        elif error < -3: self.held = False
        self.previous = (now,detection['ball'],detection['target'])
        return self.held


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=float, default=0)
    parser.add_argument('--respect-stop', action='store_true')
    args = parser.parse_args(argv)
    template=cv2.imread(str(ROOT/'assets/exit.png'))
    if template is None: raise RuntimeError('Missing fishing UI reference')
    import control_actions as controls
    RUN.mkdir(parents=True,exist_ok=True)
    with controls.guard():
        if controls.alive() or controls.alive('pid.json'):
            raise RuntimeError('A fishing controller is already running')
        if (RUN/'STOP').exists() or (RUN/'PAUSE').exists():
            raise RuntimeError('Stop is set; use an explicit Continue')
        record = {'pid':os.getpid(),'created':psutil.Process().create_time()}
        write('supervisor-pid.json',record);write('pid.json',record)
    started = time.time();monotonic_started=time.monotonic();session=time.strftime('%Y%m%d-%H%M%S')
    ledger=Ledger();tracker=TrackingAssist();inp=Input();next_state=0;hwnd=None;screen=None;last_activity=0
    reason='session_limit';stage='assist_waiting';last_count=0
    log=(RUN/f'events-{session}.jsonl').open('a',buffering=1)
    def event(kind,**kw):log.write(json.dumps({'at':time.time(),'event':kind,'mode':'assist',**kw})+'\n')
    def status(running=True):
        now=time.time()
        write('supervisor.json',{'running':running,'pid':os.getpid(),'updated':now,'started':started,
              'stage':('paused_focus' if stage=='paused_focus' else 'fishing') if running else 'stopped',
              'mode':'assist','worker_pid':os.getpid(),'recoveries':0,'reason':reason if not running else '',
              'runs_until_stopped':args.seconds<=0})
        write('status.json',{'running':running,'pid':os.getpid(),'updated':now,'session':session,'mode':'assist',
              'stage':stage,'cycles':tracker.count,'casts':0,'reward_banners_observed':0,'failed_rounds':0,
              'held_mouse':inp.mouse,'held_t':False,'last_game_activity':last_activity,
              'reason':reason if not running else '', 'elapsed':round(time.monotonic()-monotonic_started,1)})
        # These hooks are observed minigames; manual pickups stay outside the journal.
        ledger.update(time.monotonic()-monotonic_started,0,tracker.count,0,0,'')
    try:
        event('assist_started',message='Minigame only: waiting for a manual cast');status()
        with mss.MSS() as sct:
            while args.seconds<=0 or time.monotonic()-monotonic_started<args.seconds:
                tick=time.monotonic()
                if (RUN/'STOP').exists():reason='Stopped by stop file';break
                if any(USER.GetAsyncKeyState(k)&0x8000 for k in (27,120,123)):
                    (RUN/'STOP').write_text('Stopped by physical hotkey');reason='Stopped by physical hotkey';break
                try:
                    selected=find_window()
                    if win32gui.IsIconic(selected) or win32gui.GetForegroundWindow()!=selected:
                        raise RuntimeError('Waiting for Roblox')
                    if win32gui.GetAncestor(win32gui.WindowFromPoint(win32gui.GetCursorPos()),2)!=selected:
                        raise RuntimeError('Waiting for the pointer to return to Roblox')
                    rect=rectangle(selected)
                    if selected!=hwnd or screen is None or screen.rect!=rect:
                        inp.release();tracker.suspend();screen=ScreenSpace(rect);hwnd=selected;inp.hwnd=hwnd
                    detection=detect(screen.capture(sct,(1850,400,140,600)))
                    ui=screen.capture(sct,(1190,1360,180,70))
                    visible=cv2.minMaxLoc(cv2.matchTemplate(ui,template,cv2.TM_CCOEFF_NORMED))[1]>.84
                    down=tracker.step(detection,visible,tick)
                    inp.hold(down)
                    stage='tracking' if tracker.active and visible else 'assist_waiting'
                    if detection is not None and visible:last_activity=time.time()
                    if tracker.count!=last_count:
                        last_count=tracker.count;event('minigame',cycle=tracker.count)
                except (RuntimeError, ValueError, win32gui.error):
                    # No focus stealing, menu input, or relaunch in this mode.
                    inp.release();tracker.suspend();stage='paused_focus'
                if tick>=next_state:status();next_state=tick+1
                time.sleep(max(.01, .03-(time.monotonic()-tick)))
    except BaseException as error:
        reason=str(error);raise
    finally:
        inp.release();event('stopped',reason=reason);status(False);log.close()
    return 0


if __name__ == '__main__': raise SystemExit(main())
