"""Foreground-only fishing controllers; the player owns position and focus."""
import argparse
import json
import os
import time
import threading

import cv2
import mss
import psutil
import win32gui
import numpy as np

from fishing_assistant import ROOT, USER, Input, detect, find_window, rectangle
from metrics import RUN, Ledger, read, write
from screen_space import ScreenSpace
from fishing_vision import ui_visible
from pickup_policy import classify, PickupGate, Pickup
from spot_fishing import SpotCycle
from rod_detector import locate_rod, RodReady
from performance import PerformanceRecorder


class ForegroundInput(Input):
    """The watcher may release held input even while OCR is running."""
    def __init__(self):
        super().__init__()
        self.lock = threading.RLock()
        self.interrupted = threading.Event()
        self.toggle_requested = threading.Event()
        self.toggle_enabled = False

    def guard_press(self, down):
        super().guard_press(down)
        if down and (self.interrupted.is_set() or (RUN/'STOP').exists() or (RUN/'PAUSE').exists()):
            raise RuntimeError('Input suspended')

    def hold(self, down):
        with self.lock:
            super().hold(down)

    def grab(self, down):
        with self.lock:
            super().grab(down)

    def aim(self, *args, **kwargs):
        raise RuntimeError('Manual fishing modes never move the pointer')


def foreground(hwnd):
    return (hwnd is not None and win32gui.IsWindow(hwnd) and not win32gui.IsIconic(hwnd)
            and win32gui.GetForegroundWindow()==hwnd
            and win32gui.GetAncestor(win32gui.WindowFromPoint(win32gui.GetCursorPos()),2)==hwnd)


def watch_focus(inp, done):
    f8_down = False
    while not done.wait(.015):
        try:
            f8 = bool(USER.GetAsyncKeyState(119)&0x8000)
            if inp.toggle_enabled and f8 and not f8_down and foreground(inp.hwnd):
                inp.interrupted.set()
                inp.toggle_requested.set()
                inp.release()
            f8_down = f8
            hotkey = any(USER.GetAsyncKeyState(k)&0x8000 for k in (27,120,123))
            if hotkey and not (RUN/'STOP').exists():
                (RUN/'STOP').write_text('Stopped by physical hotkey')
            if hotkey or (RUN/'STOP').exists() or (RUN/'PAUSE').exists() or not foreground(inp.hwnd):
                inp.interrupted.set()
                inp.release()
        except (RuntimeError, win32gui.error):
            inp.interrupted.set()
            inp.release()


def read_scene(frame, ocr):
    x,y,w,h = 160,100,2240,1200
    scale=1.
    result,_=ocr(cv2.resize(frame[y:y+h,x:x+w],None,fx=scale,fy=scale),use_cls=False)
    rows=[{'text':r[1],'score':float(r[2]),
           'center':(x+float(np.mean(np.array(r[0])[:,0]))/scale,
                     y+float(np.mean(np.array(r[0])[:,1]))/scale)} for r in result or []]
    text=' '.join(r['text'].lower() for r in rows if r['score']>=.75)
    blocked=any(word in text for word in ('disconnected','reconnect','connection lost','error code',
        'same account','main menu','private server','inventory','settings','leave game','reset character',
        'resume experience','would you like','purchase','fisherman'))
    rod=locate_rod(frame)
    evidence=classify(rows)
    return evidence,(bool(rod) or evidence.kind in ('collect','reward')) and not blocked,rod


def safe_cast_pointer(screen):
    x,y=win32gui.GetCursorPos()
    x=(x-screen.rect[0])/screen.sx;y=(y-screen.rect[1])/screen.sy
    # A pointer left on the hotbar could unequip the rod instead of casting.
    return 260<=x<=2240 and 160<=y<=1240


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
    parser.add_argument('--mode', choices=('assist','spot'), default='assist')
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
    started = time.time();monotonic_started=time.monotonic();session=time.strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid())
    ledger=Ledger();tracker=TrackingAssist();inp=ForegroundInput();next_state=0;hwnd=None;screen=None;last_activity=0
    reason='session_limit';stage='assist_waiting';last_count=0;wait_reason=''
    log=(RUN/f'events-{session}.jsonl').open('a',buffering=1)
    def event(kind,**kw):
        if 'reward_id' in kw:kw['reward_id']=session+':'+kw['reward_id']
        log.write(json.dumps({'at':time.time(),'event':kind,'mode':args.mode,**kw})+'\n')
    spot=SpotCycle(event) if args.mode=='spot' else None
    inp.toggle_enabled = spot is not None
    ocr=None
    if spot:
        from rapidocr_onnxruntime import RapidOCR
        ocr=RapidOCR()
    gate=PickupGate();rod_gate=RodReady();rod_ready=False;evidence=Pickup('empty');stable=False;world=False;rod=None
    active_time=0.;last_tick=time.monotonic();last_scan=-10.;resuming=True
    missing_since=None;last_capture=0.;capture_index=0
    done=threading.Event()
    watcher=threading.Thread(target=watch_focus,args=(inp,done),daemon=True);watcher.start()
    performance=PerformanceRecorder(ledger.base.get('started'))
    def status(running=True):
        now=time.time()
        write('supervisor.json',{'running':running,'pid':os.getpid(),'updated':now,'started':started,
              'stage':('paused_focus' if stage=='paused_focus' else 'fishing') if running else 'stopped',
              'mode':args.mode,'worker_pid':os.getpid(),'recoveries':0,'reason':reason if not running else '',
              'runs_until_stopped':args.seconds<=0})
        write('status.json',{'running':running,'pid':os.getpid(),'updated':now,'session':session,'mode':args.mode,
              'stage':stage,'cycles':tracker.count,'casts':spot.casts if spot else 0,
              'reward_banners_observed':spot.rewards if spot else 0,'failed_rounds':0,
              'held_mouse':inp.mouse,'held_t':inp.t,'last_game_activity':last_activity,
              'spot_armed':spot.armed if spot else False,'active_seconds':round(active_time,1),
              'spot_paused':spot.paused if spot else False,
              'wait_reason':wait_reason,
              'reason':reason if not running else '', 'elapsed':round(time.monotonic()-monotonic_started,1)})
        # These hooks are observed minigames; manual pickups stay outside the journal.
        ledger.update(active_time,spot.casts if spot else 0,tracker.count,spot.rewards if spot else 0,0,spot.last_reward if spot else '')
        if running:performance.tick('paused_focus' if stage=='paused_focus' else 'fishing',{'stage':stage},read('totals.json'))
    try:
        event('assist_started',message='Equip your rod, position the mouse, then press F8 to start.' if spot else 'Minigame only: waiting for a manual cast');status()
        with mss.MSS() as sct:
            while args.seconds<=0 or time.monotonic()-monotonic_started<args.seconds:
                tick=time.monotonic()
                delta=min(2,tick-last_tick);last_tick=tick
                if (RUN/'STOP').exists() or (RUN/'PAUSE').exists():reason='Stopped by stop file';break
                if any(USER.GetAsyncKeyState(k)&0x8000 for k in (27,120,123)):
                    (RUN/'STOP').write_text('Stopped by physical hotkey');reason='Stopped by physical hotkey';break
                try:
                    selected=find_window()
                    if not foreground(selected):
                        raise RuntimeError('Waiting for Roblox')
                    rect=rectangle(selected)
                    if selected!=hwnd or screen is None or screen.rect!=rect:
                        if hwnd is not None and hwnd!=selected and spot:
                            spot.armed=False  # A new Roblox process needs the player to rearm.
                            spot.paused=True
                        inp.release();tracker.suspend();screen=ScreenSpace(rect);hwnd=selected;inp.hwnd=hwnd
                        resuming=True
                    if spot and inp.toggle_requested.is_set():
                        inp.toggle_requested.clear()
                        spot.toggle(active_time)
                        inp.release();tracker.suspend();resuming=True
                    if spot and (not spot.armed or spot.paused):
                        inp.release()
                        stage='spot_paused' if spot.armed else 'select_spot'
                        wait_reason='Press F8 in Roblox to resume' if spot.armed else 'Equip your rod, position the mouse, then press F8'
                        if tick>=next_state:status();next_state=tick+1
                        time.sleep(.03)
                        continue
                    if inp.interrupted.is_set():resuming=True
                    if resuming:
                        inp.release();inp.interrupted.clear();tracker.suspend()
                        if spot:spot.resume(active_time)
                        gate=PickupGate();rod_gate.reset();rod_ready=False;last_scan=-10.;stable=False;world=False
                        resuming=False;event('focus_resumed',message='Roblox foreground; checking the current scene.')
                    else:active_time+=delta
                    wait_reason=''
                    roi=screen.capture(sct,(1850,400,140,600))
                    detection=detect(roi)
                    ui=screen.capture(sct,(1190,1360,180,70))
                    visible=ui_visible(ui,template)
                    down=tracker.step(detection,visible,tick)
                    stage='tracking' if tracker.active and visible else 'assist_waiting'
                    if detection is not None and visible:last_activity=time.time()
                    if tracker.count!=last_count:
                        last_count=tracker.count;event('minigame',cycle=tracker.count)
                    if visible:
                        inp.grab(False);inp.hold(down)
                        if spot:spot.tracking(active_time)
                        if detection is None:
                            missing_since=missing_since or tick
                            if tick-last_capture>.5:
                                cv2.imwrite(str(RUN/f'vision-missing-{capture_index%12:02d}.png'),roi)
                                capture_index+=1;last_capture=tick
                        else:missing_since=None
                        if tick-last_capture>1:
                            cv2.imwrite(str(RUN/'vision-latest.png'),roi);last_capture=tick
                        # Persistent missing visual data never authorizes a
                        # blind cast or collection while the minigame is open.
                        if missing_since and tick-missing_since>2:stage='waiting_marker'
                    elif spot:
                        if spot.stage=='tracking':
                            inp.release()
                            if tracker.clear_since is not None and tick-tracker.clear_since>.55:
                                spot.ended(active_time);last_scan=-10.
                        else:
                            # Waiting for a bite requires only fast minigame
                            # vision. OCR here delayed the first reel input.
                            if spot.armed and tick-last_scan>.35 and spot.stage not in ('cast_press','waiting'):
                                frame=screen.capture(sct)
                                evidence,world,rod=read_scene(frame,ocr)
                                stable=gate.observe(evidence,time.monotonic());last_scan=time.monotonic()
                                rod_ready=rod_gate.observe(rod if world else None,last_scan)
                                if inp.interrupted.is_set() or not foreground(hwnd):raise RuntimeError('Focus changed during observation')
                            action=spot.step(active_time,evidence,stable,world,rod_ready)
                            if action=='cast':
                                inp.release()
                                fresh=screen.capture(sct)
                                if (not rod_gate.matches(locate_rod(fresh)) or not safe_cast_pointer(screen)
                                        or ui_visible(fresh[1360:1430,1190:1370],template)):
                                    spot.cancel_unstarted_press(active_time)
                                    rod_gate.reset();rod_ready=False;last_scan=-10.
                                    event('cast_withheld',message='Waiting for an equipped rod and a mouse position clear of the HUD.')
                                    continue
                                try:
                                    inp.hold(True)
                                except (RuntimeError,ValueError,win32gui.error):
                                    # No click was sent: do not invent a pending
                                    # bite and wait 30 seconds on the next scan.
                                    spot.cancel_unstarted_press(active_time)
                                    raise
                                spot.since=active_time+time.monotonic()-tick
                            elif action=='hold':inp.grab(False);inp.hold(True)
                            elif action=='collect':
                                inp.hold(False)
                                if not inp.t:spot.since=active_time+time.monotonic()-tick
                                inp.grab(True)
                            else:inp.release()
                            stage=spot.stage
                            if stage=='checking_spot' and not rod_ready:
                                stage='waiting_rod'
                    else:
                        inp.release()
                except (RuntimeError, ValueError, win32gui.error) as error:
                    # No focus stealing, menu input, or relaunch in this mode.
                    inp.release();tracker.suspend();stage='paused_focus';resuming=True
                    if wait_reason!=str(error):event('assistant_waiting',message=str(error))
                    wait_reason=str(error)
                if tick>=next_state:status();next_state=tick+1
                time.sleep(max(.01, .03-(time.monotonic()-tick)))
    except BaseException as error:
        reason=str(error);raise
    finally:
        done.set();watcher.join(timeout=1);inp.release();event('stopped',reason=reason);status(False);log.close()
    return 0


if __name__ == '__main__': raise SystemExit(main())
