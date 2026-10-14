"""Screen-only Roblox fishing controller; F9, F12 or Escape stops all input."""
import argparse, ctypes, json, math, os, time, sys, traceback, re, threading
from ctypes import wintypes
from pathlib import Path
import cv2, mss, numpy as np, psutil, win32gui, win32process, win32api
from ocr_engine import RapidOCR
from pynput.keyboard import Listener,Key
from metrics import Ledger, read as read_metrics, write as write_metrics, RUN
from app_config import load_config,save_config
from rod_detector import locate_rod, unselected_rod, selected_rod, recheck_selected_rod
from fishing_vision import detect, ui_visible
from tracking_control import ReelMotion
from tracking_watchdog import TrackingWatchdog
from screen_space import ScreenSpace
from inventory_watch import InventoryDriver, InventoryWatcher
import landmarks
from pickup_policy import Pickup, classify as classify_pickup, classify_toast, same_reward, PickupGate,clear_collect,RewardGate,waiting_decision,before_cast_decision,retain_collect_hold,collect_hold_timeout,CollectHoldMotion,CollectReadyGate
from reward_evidence import reward_quantity
from faults import FishingFault, FaultRecorder, reason_code
from full_pause import InputGate, InputPaused, PAUSE_FILE, resumed_stage
from unattended_focus import TaggedInput
from capture_session import CaptureSession
from snapshot_writer import SnapshotWriter
from prompt_shape import find_discs, DiscTrack
import ocr_engine

ROOT = Path(__file__).resolve().parent
USER = TaggedInput(ctypes.windll.user32)
USER.SetProcessDPIAware()

# Normal hooks arrive within about seven seconds in the observed sessions.
# Two missed hooks can be ordinary bad luck; wait for a third before rejoining.
BITE_WAIT_TIMEOUT_SECONDS = 10
MISSED_CASTS_BEFORE_REJOIN = 3
CONFIRMED_REWARD_COOLDOWN_SECONDS = 0.
CAST_PRESS_SECONDS = .16
# A drop's prompt appears ~0.7 s after the minigame while the item is still
# airborne. Two thirds of logged pickups held T on that moving prompt, lost the
# hold when it landed, and needed a second ~2.6 s hold. Wait for the key disc
# to stop (bounded), and re-press as soon as a held disc lands elsewhere.
PROMPT_REGION = (480,150,1630,1110)
LANDING_WAIT_LIMIT_SECONDS = 1.8
HELD_DISC_MOVE_PIXELS = 40
# A held disc absent this long (several 30-60 Hz frames) means the prompt is gone.
PROMPT_GONE_SECONDS = .15

def move_pointer(x,y):
    # Both monitors are valid; coordinates are absolute virtual-desktop pixels.
    monitors=[entry[2] for entry in win32api.EnumDisplayMonitors()]
    left=min(r[0] for r in monitors);top=min(r[1] for r in monitors)
    width=max(r[2] for r in monitors)-left;height=max(r[3] for r in monitors)-top
    if not (left<=x<left+width and top<=y<top+height):raise RuntimeError(f'Input ({x}, {y}) is outside desktop ({left}, {top}, {width}, {height})')
    primary_width=USER.GetSystemMetrics(0);primary_height=USER.GetSystemMetrics(1)
    if 0<=x<primary_width and 0<=y<primary_height:
        # Use primary-screen absolute events on that screen, as Roblox's normal
        # UI expects. Virtual-desktop events can leave its hit test behind the
        # OS cursor on a multi-monitor desktop. Other monitors still use their
        # full virtual-desktop coordinates and the position check below.
        USER.mouse_event(0x8001,round(x*65535/(primary_width-1)),round(y*65535/(primary_height-1)),0,0)
    else:
        USER.mouse_event(0xC001,round((x-left)*65535/(width-1)),round((y-top)*65535/(height-1)),0,0)
    # Some display transitions briefly report stale virtual-desktop metrics.
    # Confirm physical position before any click can be issued.
    actual=win32gui.GetCursorPos()
    if abs(actual[0]-x)>2 or abs(actual[1]-y)>2:
        USER.SetCursorPos(x,y)
        actual=win32gui.GetCursorPos()
        if abs(actual[0]-x)>2 or abs(actual[1]-y)>2:raise RuntimeError('Pointer did not reach the intended game position')

def find_window():
    found=[]
    def visit(h,_):
        if not win32gui.IsWindowVisible(h): return
        try:
            if psutil.Process(win32process.GetWindowThreadProcessId(h)[1]).name().lower()=='robloxplayerbeta.exe': found.append(h)
        except (psutil.Error,OSError): pass
    win32gui.EnumWindows(visit,None)
    if not found:raise FishingFault('client_lost','Roblox Player window closed; found 0 game windows')
    if len(found)!=1:raise FishingFault('user_required','Multiple Roblox Player windows need user selection')
    return found[0]

def rectangle(h):
    # Client pixels exclude the title bar and resize border in windowed mode.
    l,t,r,b=win32gui.GetClientRect(h)
    x,y=win32gui.ClientToScreen(h,(0,0))
    return x,y,x+r-l,y+b-t

class Input:
    def __init__(self,hwnd=None):
        self.mouse=False; self.t=False; self.hwnd=hwnd
        self.cast_target=None
        self.lock=threading.RLock(); self.gate=None;self.physical_stop_owned=False
    def guard_press(self,down):
        if down and self.gate is not None:self.gate.check()
        if down and self.hwnd is not None and (not win32gui.IsWindow(self.hwnd) or win32gui.IsIconic(self.hwnd) or win32gui.GetForegroundWindow()!=self.hwnd):
            raise RuntimeError('Roblox lost focus; all inputs released')
    def hold(self,down):
        with self.lock:
            self.guard_press(down)
            if down!=self.mouse:
                if down and self.hwnd is not None:
                    under=win32gui.WindowFromPoint(win32gui.GetCursorPos())
                    if win32gui.GetAncestor(under,2)!=self.hwnd:
                        if self.gate is not None:raise InputPaused('paused_focus')
                        raise RuntimeError('Pointer is outside Roblox; all inputs released')
                USER.mouse_event(2 if down else 4,0,0,0,0); self.mouse=down
    def grab(self,down):
        with self.lock:
            self.guard_press(down)
            if down!=self.t:
                scan=USER.MapVirtualKeyW(ord('T'),0)
                USER.keybd_event(ord('T'),scan,0 if down else 2,0); self.t=down
    def release(self): self.hold(False); self.grab(False)

    def zoom_first_person(self):
        """Use Roblox's zoom limit, with the same focus and pause guard as casts."""
        self.release()
        for _ in range(16):
            self.guard_press(True)
            if (RUN/'STOP').exists():raise RuntimeError('Stopped by stop file')
            USER.mouse_event(0x0800,0,0,120,0)
            time.sleep(.035)
        self.cast_target=None

    def aim(self,x,y,after_menu=False):
        self.cast_target=None
        # Roblox can process its hotbar hover one frame behind the OS cursor.
        # Let the same small hover movement used by recovery settle before a
        # cast or rod click, rather than clicking the previous hotbar target.
        delays=(.30,.15,.30) if after_menu else (.10,.06,.10)
        for point,delay in zip(((x,y),(x+1,y),(x,y)),delays):
            self.guard_press(True)
            if (RUN/'STOP').exists():raise RuntimeError('Stopped by stop file')
            move_pointer(*point)
            until=time.monotonic()+delay
            while time.monotonic()<until:
                self.guard_press(True)
                if (RUN/'STOP').exists():raise RuntimeError('Stopped by stop file')
                time.sleep(.01)

    def aim_cast(self,x,y,after_menu=False):
        # Once Roblox has seen the cast target, repeating the three hover
        # movements every round only delays fishing. Re-settle after any menu,
        # rod click, focus pause, or pointer movement.
        self.guard_press(True)
        actual=win32gui.GetCursorPos()
        if (not after_menu and self.cast_target==(x,y)
                and abs(actual[0]-x)<=2 and abs(actual[1]-y)<=2):
            return
        self.aim(x,y,after_menu=after_menu)
        self.cast_target=(x,y)

def is_pickup_prompt(text):
    # The moving prompt can be partially occluded by the character.
    return not is_other_interaction(text) and bool(re.search(r'collect|ollect|llect|\blect\b',text,re.I))

def is_other_interaction(text):
    # T also operates world interactions. A climb prompt means the saved
    # fishing position was disturbed; holding it again cannot collect loot.
    return bool(re.search(r'\bwall\b|climb|\bpurchase\b|\bwould you like\b',text,re.I))

def is_reward_banner(text):
    # Item text alone can still be the pickup prompt. A quantity/new label
    # belongs to the actual collection notification.
    return not is_other_interaction(text) and not is_pickup_prompt(text) and reward_quantity(text) is not None

def main():
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=float,default=0);p.add_argument('--focus',action='store_true');p.add_argument('--record',action='store_true');p.add_argument('--gain',type=float,default=None,help='Override adaptive braking with the legacy fixed predictor')
    p.add_argument('--current-position',action='store_true',help='Use the adopted live position instead of the saved landmark reference')
    a=p.parse_args()
    limit=a.seconds if a.seconds>0 else float('inf')
    RUN.mkdir(parents=True,exist_ok=True)
    lock=RUN/'pid.json'
    if lock.exists():
        previous=json.loads(lock.read_text())
        if psutil.pid_exists(previous['pid']) and abs(psutil.Process(previous['pid']).create_time()-previous['created'])<1:
            raise RuntimeError('A fishing controller is already running')
    lock.write_text(json.dumps({'pid':os.getpid(),'created':psutil.Process().create_time()}))
    stop=RUN/'STOP'
    if stop.exists():raise RuntimeError('Stop is set; use the launcher to start a new session')
    hwnd=find_window();rect=rectangle(hwnd)
    screen=ScreenSpace(rect)
    if a.focus:win32gui.SetForegroundWindow(hwnd);time.sleep(.3)
    ocr=RapidOCR()
    exit_template=cv2.imread(str(ROOT/'assets'/'exit.png'))
    inp=Input(hwnd);started=time.monotonic();now=started;stage='casting';since=now;lastseen=now;ledger=Ledger();last_gui_scan=0;last_tracking_cast=None;last_game_activity=time.time()
    # Roblox captures and recenters the cursor in first person. The foreground
    # window remains the reliable guard there; a pointer hit test can flicker
    # outside for a frame and livelock the worker before its first cast.
    inp.gate=InputGate(inp,RUN,USER,pointer=load_config()['camera_mode']!='first_person');inp.gate.start()
    def emergency_key(key):
        if key in (Key.esc,Key.f9,Key.f12) and win32gui.GetForegroundWindow()==hwnd and not win32gui.IsIconic(hwnd):
            stop.write_text('Stopped by physical hotkey')
            save_config({'overnight_enabled':False,'overnight_auto_enable_idle':False})
    emergency_listener=Listener(on_press=emergency_key,win32_event_filter=lambda message,data:not data.flags&0x10)
    emergency_listener.start()
    inp.physical_stop_owned=True
    prev=None;velocity=0.;target_velocity=0.;cycles=0;casts=0;missing_casts=0;track_frames=0;inside_frames=0;laststate=0;lastimage=0;last_rod_check=0
    first_person_active=False
    motion=ReelMotion();tracking_watchdog=TrackingWatchdog()
    completed=0;failed=0;unknown=0;pickup_confirmed=0;prompt_seen=False;pickup_tries=0;last_pickup_scan=0;last_toast_scan=0;last_reason='';last_reward='';last_prompt='';end_percent=None;consecutive_failed=0;cast_press_started=None;cast_needs_settle=True
    cooldown_delay=1.0;prompt_detected_at=None;reward_gate=RewardGate();collect_motion=CollectHoldMotion();collect_ready=CollectReadyGate()
    confirmed_recast=None;reward_confirmed_at=None
    disc_track=DiscTrack();pending_collect=None;hold_anchor=None;landing_wait_logged=False;disc_gone_logged=None;disc_represses=0;disc_repress_cycle=None;claim_pending=None;drop_eligible=False;drop_cast_gap=.3;drop_cast_at_cast=None
    last_verified_rod=None
    needs_scene_check=True;scene_check_started=None;hooked_cycles=0;last_wait_pickup_check=0;startup_ui_wait_since=None
    last_reference_check=0;reference_matcher=None;paused_at=None
    session=time.strftime('%Y%m%d-%H%M%S'); log=open(RUN/f'events-{session}.jsonl','a',buffering=1)
    diagnostics=FaultRecorder(RUN,session);pickup_gate=PickupGate();last_pickup_evidence={};failure_code='';failure_details={}
    telemetry=open(RUN/f'tracking-{session}.csv','w',buffering=1);telemetry.write('time,cycle,ball,target,height,velocity,held,inside\n')
    def event(kind,**kw):log.write(json.dumps({'at':time.time(),'event':kind,**kw})+'\n');print(json.dumps({'event':kind,**kw}),flush=True)
    def inventory_progress(**kw):
        write_metrics('status.json',{'running':True,'pid':os.getpid(),'session':session,'updated':time.time(),
            'stage':'inventory','inventory':kw,'last_game_activity':last_game_activity,
            'held_mouse':False,'held_t':False,'cycles':hooked_cycles,'casts':casts})
    def record_reward(raw):
        nonlocal pickup_confirmed,last_reward,confirmed_recast,reward_confirmed_at
        if not reward_gate.accept(cycles):
            inp.grab(False);event('duplicate_reward_ignored',cycle=cycles);return False
        inp.grab(False);pickup_confirmed+=1;last_reward=raw
        confirmed_recast=Pickup('reward',raw);reward_confirmed_at=time.monotonic()
        reward_id=f'{session}:{cycles}:{pickup_confirmed}'
        event('reward_observed',cycle=cycles,text=raw,reward_id=reward_id)
        inventory.observe(raw,last_prompt,reward_id)
        return True
    def start_cooldown(seconds):
        nonlocal stage,since,cooldown_delay
        stage='cooldown';cooldown_delay=seconds
        # A confirmed item banner releases T and proceeds straight to the
        # fresh scene check; there is no post-collection dwell.
        since=(reward_confirmed_at if confirmed_recast is not None
               and seconds==CONFIRMED_REWARD_COOLDOWN_SECONDS else time.monotonic())
    def screenshot(tag,defer=False):
        image_writer.wait()
        im=screen.capture(sct)
        image_writer.save(im,RUN/f'{session}-{cycles%12:03d}-{tag}.jpg',RUN/'latest.jpg',defer=defer,
                          observe=lambda frame:diagnostics.observe(frame,tag))
        return im
    def read_text(im):
        result,_=ocr(im)
        return ' '.join(r[1] for r in result or [] if r[2]>.8)
    def check_disconnect(raw):
        if any(t in raw.lower() for t in ('disconnected','connection lost','connection error','failed to connect','same account launched','error code','reconnect')):
            inp.release();event('disconnect_gui',text=raw.lower());raise RuntimeError('Disconnect GUI detected; rejoin required')
    def scan_gui():
        nonlocal last_gui_scan
        gui=screen.capture(sct,(760,410,1040,580))
        raw=read_text(cv2.resize(gui,None,fx=.75,fy=.75))
        inp.guard_press(True);last_gui_scan=time.monotonic();check_disconnect(raw)
    def pickup_text(full_scene=False):
        nonlocal last_pickup_evidence,prompt_detected_at,last_gui_scan
        # Prompt height changes with the camera. The previous crop missed
        # Collect above y=480, causing blind T holds on otherwise empty rounds.
        scan_started=time.monotonic()
        # Read the shoulder prompt first. A moving/occluded prompt still gets
        # the wide fallback; no missing prompt authorizes a blind T press.
        if last_pickup_evidence.get('kind')=='collect':
            cx,cy=last_pickup_evidence['center']
            narrow=(max(480,min(1660,int(cx)-240)),max(150,min(1030,int(cy)-110)),480,220)
        else:narrow=(1080,480,660,460)
        evidence=None
        regions=((480,150,1630,1110),) if full_scene else (narrow,(480,150,1630,1110))
        for x,y,w,h in regions:
            im=screen.capture(sct,(x,y,w,h))
            scale=1 if w<1000 else .75
            results,_=ocr(cv2.resize(im,None,fx=scale,fy=scale),use_cls=full_scene)
            inp.guard_press(True)
            rows=[{'text':r[1],'score':float(r[2]),
                   'center':(x+float(np.mean(np.array(r[0])[:,0]))/scale,
                             y+float(np.mean(np.array(r[0])[:,1]))/scale)} for r in results or []]
            if full_scene:
                # The full frame contains the old GUI crop at the same scale.
                # Keep its bounds, orientation and confidence checks so labels
                # outside that region cannot masquerade as a disconnect.
                check_disconnect(' '.join(row['text'] for row in rows if row['score']>.8
                                         and 760<=row['center'][0]<=1800 and 410<=row['center'][1]<=990))
                last_gui_scan=time.monotonic()
            evidence=classify_pickup(rows)
            if evidence.kind!='empty':break
        finished=time.monotonic()
        stable=pickup_gate.observe(evidence,finished,finished-scan_started)
        if evidence.kind=='collect':
            if prompt_detected_at is None:
                prompt_detected_at=finished
                event('pickup_prompt_seen',cycle=cycles,text=evidence.text,scan_seconds=round(finished-scan_started,3))
            stable=stable or clear_collect(rows,after_minigame=last_tracking_cast==casts and cycles not in reward_gate.confirmed)
        last_pickup_evidence={'kind':evidence.kind,'text':evidence.text,'center':evidence.center,'stable':stable,'scan_seconds':round(finished-scan_started,3)}
        if evidence.kind=='empty':last_pickup_evidence['ocr_rows']=rows
        if evidence.kind in ('other','ambiguous'):
            inp.grab(False)
            if stable and stage=='pickup':
                event('wrong_interaction',evidence=last_pickup_evidence);screenshot('wrong-interaction')
                raise FishingFault('pickup_other','Non-fishing interaction replaced pickup; local alignment required',evidence=last_pickup_evidence)
        return evidence,stable
    def empty_round(delay):
        message='No pickup prompt after repeated wide scans; continuing without holding T'
        screenshot('empty-round')
        report=diagnostics.save('empty_round',message,cycle=cycles,percent=end_percent,evidence=last_pickup_evidence)
        event('empty_round',cycle=cycles,message=message,percent=end_percent,
              evidence=last_pickup_evidence,diagnostic_sequence=report['sequence'])
        start_cooldown(delay)
    def pickup_toast(require_x=False):
        # The toast sits beside the avatar's right shoulder. A narrow OCR pass
        # avoids the player title and waterfall that can hide its small X1 in
        # the wide prompt scan. This only confirms a reward after a held T.
        # First person moves the toast toward screen center and long names can
        # extend well past the third-person shoulder crop.
        x,y,w,h=(1180,670,620,180) if first_person_active else (1240,670,310,180)
        im=screen.capture(sct,(x,y,w,h))
        results,_=ocr(cv2.resize(im,None,fx=1.5,fy=1.5),use_cls=False)
        inp.guard_press(True)
        rows=[{'text':r[1],'score':float(r[2]),
               'center':(float(np.mean(np.array(r[0])[:,0])),float(np.mean(np.array(r[0])[:,1])))}
              for r in results or []]
        return classify_toast(rows,require_x)
    def disc_observe():
        x,y,w,h=PROMPT_REGION
        found=[(x+cx,y+cy) for cx,cy in find_discs(screen.capture(sct,(x,y,w,h)))]
        inp.guard_press(True)
        return disc_track.observe(found,time.monotonic())
    def reset_disc(near=None):
        nonlocal pending_collect,hold_anchor,landing_wait_logged
        disc_track.reset(near);pending_collect=None;hold_anchor=None;landing_wait_logged=False
    def landed(now):
        # A fresh prompt often reads as text a frame before its moving disc is found;
        # give the disc 0.3 s to show up. Otherwise (occluded or off-crop) the OCR
        # gates stay in charge.
        if disc_track.seen_at is None:return True
        if now-disc_track.seen_at>.25:return True
        if disc_track.settled(now):return True
        return prompt_detected_at is not None and now-prompt_detected_at>LANDING_WAIT_LIMIT_SECONDS
    def start_hold(evidence):
        nonlocal last_prompt,stage,since,pickup_tries,last_toast_scan,pending_collect,hold_anchor
        last_prompt=evidence.text
        inp.grab(True);stage='pickup';since=time.monotonic();pickup_tries+=1;last_toast_scan=0
        collect_motion.start(evidence,since);pending_collect=None;hold_anchor=disc_track.position
        event('pickup_hold',cycle=cycles,attempt=pickup_tries,prompt_seen=True,text=evidence.text,key_center=evidence.key_center,
              scan_seconds=last_pickup_evidence['scan_seconds'],prompt_to_hold_seconds=round(since-(prompt_detected_at or since),3),
              disc=disc_track.position,disc_settled=disc_track.settled(since));screenshot('pickup',defer=True)
    def ui_active():
        im=screen.capture(sct,(1190,1360,180,70))
        return ui_visible(im,exit_template)
    def finish_cooldown():
        nonlocal last_reference_check,reference_matcher,inventory_open,confirmed_recast,last_verified_rod
        nonlocal cast_needs_settle,pickup_confirmed,last_reward,stage,now,since,cast_press_started
        nonlocal needs_scene_check,scene_check_started,pickup_gate
        if not a.current_position and now-last_reference_check>180 and landmarks.profile():
            last_reference_check=now
            reference_matcher=reference_matcher or landmarks.load_matcher(landmarks.profile())
            measured=reference_matcher.measure(screen.capture(sct))
            if measured and measured['rms']>10:
                second=reference_matcher.measure(screen.capture(sct))
                if second and second['rms']>10:
                    screenshot('drift')
                    raise FishingFault('alignment_drift','Fishing reference drifted; local alignment required',error=round(second['rms'],2))
        menu_scan_due=bool(inventory.pending and inventory.clock()>=inventory.next_check_at
                           and getattr(inventory,'comparison_blocked',False) is not True)
        # A due inventory menu still gets the separate disconnect check before
        # any menu input. Ordinary recasts use the fresh full-scene OCR below.
        if menu_scan_due and time.monotonic()-last_gui_scan>8:scan_gui()
        inventory_open=True
        recovered=inventory.check_pending();inventory_open=False
        if menu_scan_due:
            confirmed_recast=None;last_verified_rod=None
            inp.cast_target=None;cast_needs_settle=True
        if recovered:
            pickup_confirmed+=1;last_reward=f"{recovered['item']} X{recovered['quantity']} (inventory)"
        inventory.end_round()
        stage='casting';now=time.monotonic();since=now;cast_press_started=None
        needs_scene_check=True;scene_check_started=None;pickup_gate=PickupGate()
    event('started',pid=os.getpid(),session=session,current_position=a.current_position,ocr_device=ocr_engine.device)
    try:
        with CaptureSession(event) as sct, SnapshotWriter() as image_writer:
            inventory=InventoryWatcher(InventoryDriver(hwnd,screen,sct,inp,ocr,USER,move_pointer),event,inventory_progress)
            needs_inventory_start=True;inventory_open=False
            while now-started<limit:
                if inp.gate.reason() or inp.gate.interrupted.is_set():
                    confirmed_recast=None
                    last_verified_rod=None
                    startup_ui_wait_since=None
                    paused_at=time.monotonic();inp.release();motion.suspend();prev=None;claim_pending=None
                    event('input_paused',stage=stage,reason=inp.gate.reason() or 'paused_focus')
                    while True:
                        if stop.exists():raise RuntimeError('Stopped by stop file')
                        reason=inp.gate.reason()
                        if not reason and inp.gate.acknowledge():break
                        state={'running':True,'pid':os.getpid(),'session':session,'updated':time.time(),
                            'stage':reason or 'paused_focus','manual_paused':(RUN/PAUSE_FILE).exists(),
                            'wait_reason':'Paused — F8 to resume' if reason=='paused_manual' else 'Waiting for Roblox and pointer',
                            'elapsed':round(paused_at-started,1),'casts':casts,'cycles':hooked_cycles,
                            'completed_100_percent':completed,'failed_rounds':failed,'reward_banners_observed':pickup_confirmed,
                            'last_reward':last_reward,'last_game_activity':last_game_activity,'held_mouse':False,'held_t':False}
                        write_metrics('status.json',state);time.sleep(.1)
                    pause_seconds=time.monotonic()-paused_at;started+=pause_seconds;since+=pause_seconds;lastseen+=pause_seconds
                    paused_at=None
                    inp.cast_target=None;cast_needs_settle=True;tracking_watchdog.reset()
                    previous_stage=stage;stage=resumed_stage(stage,cast_press_started is not None)
                    if previous_stage=='casting' and cast_press_started is not None:
                        casts+=1;event('cast',cast=casts,interrupted=True)
                    cast_press_started=None
                    if stage!=previous_stage:since=time.monotonic()
                    pickup_gate=PickupGate();collect_ready=CollectReadyGate();last_pickup_scan=0;laststate=0;reset_disc()
                    needs_scene_check=stage in ('casting','waiting','cooldown','equipping')
                    scene_check_started=None
                    event('input_resumed',stage=stage,paused_seconds=round(pause_seconds,2))
                try:
                    tick=time.monotonic();now=tick
                    if stop.exists():raise RuntimeError('Stopped by stop file')
                    inp.guard_press(True)
                    if inventory_open:
                        inventory.scanner.close();inventory_open=False
                    if needs_inventory_start and not needs_scene_check and stage=='casting':
                        needs_inventory_start=False;inventory_open=True
                        inventory.start();inventory_open=False;now=time.monotonic();since=now
                        supervisor_started=read_metrics('supervisor.json').get('started')
                        observation=read_metrics('bait-observation.json')
                        if not observation or observation.get('supervisor_started')!=supervisor_started:
                            try:
                                inventory_open=True
                                bait_count=inventory.scanner.read_equipped_bait()
                                inventory_open=False
                                if not isinstance(bait_count,int) or bait_count<0:
                                    raise ValueError('Equipped bait count is not readable')
                                base_rounds=ledger.base.get('rounds',0)
                                if not isinstance(base_rounds,int):
                                    base_rounds=read_metrics('totals.json').get('rounds',0)
                                if not isinstance(base_rounds,int):base_rounds=0
                                write_metrics('bait-observation.json',{'at':time.time(),'count':bait_count,
                                    'hooks':base_rounds+hooked_cycles,'supervisor_started':supervisor_started})
                                event('bait_read',count=bait_count)
                            except (ValueError,RuntimeError) as error:
                                # The bait badge is an estimate, never a reason to stop
                                # fishing. A menu failure once looped worker restarts
                                # and rejoins all night; note it once per supervisor.
                                if isinstance(error,RuntimeError) and 'inventory' not in str(error).lower():raise
                                inventory_open=False
                                event('bait_unreadable',message=str(error))
                                write_metrics('bait-observation.json',{'at':time.time(),'count':None,
                                    'unreadable':str(error),'supervisor_started':supervisor_started})
                                try:inventory.scanner.close()
                                except RuntimeError as close_error:event('inventory_close_failed',message=str(close_error))
                        if load_config()['camera_mode']=='first_person':
                            inp.zoom_first_person();event('camera_zoom',mode='first_person');screenshot('camera-first-person')
                            first_person_active=True
                            now=time.monotonic();since=now;cast_needs_settle=True
                        # Menu/camera work invalidates the previous empty-scene read.
                        confirmed_recast=None
                        last_verified_rod=None
                        needs_scene_check=True;scene_check_started=None;pickup_gate=PickupGate()
                    if (RUN/'RECOVER').exists():
                        (RUN/'RECOVER').unlink();raise RuntimeError('Roblox presence requested reconnect after stalled activity')
                    if stage in ('cooldown','casting') and (RUN/'RELOAD').exists():
                        (RUN/'RELOAD').unlink();inp.release()
                        raise FishingFault('worker_reload','Planned worker reload at a safe catch boundary')
                    inp.guard_press(True)
                    if not win32gui.IsWindow(hwnd):raise RuntimeError('Roblox window closed; rejoin required')
                    if rectangle(hwnd)!=rect:raise RuntimeError('Roblox moved or resized; reacquiring the client area')
                    roi=screen.capture(sct,(1850,400,140,600))
                    d=detect(roi)
                    if d is not None and not ui_active():d=None
                    if a.current_position and casts==0 and stage=='casting' and d is None and ui_active():
                        # A visible startup minigame owns input even while its
                        # markers are obscured or a capture is still settling.
                        inp.release()
                        if startup_ui_wait_since is None:
                            startup_ui_wait_since=now;event('startup_minigame_wait')
                        if now-startup_ui_wait_since>12:
                            raise FishingFault('tracking_lost','Startup fishing UI visible but markers unavailable for 12 seconds')
                        time.sleep(.02);continue
                    startup_ui_wait_since=None
                    if d is None and stage=='cooldown' and now-since>cooldown_delay:
                        finish_cooldown()
                        if confirmed_recast is None:
                            d=detect(screen.capture(sct,(1850,400,140,600)))
                            if d is not None and not ui_active():d=None
                        # A confirmed recast gets its fresh minigame read after
                        # the scene OCR below, immediately before casting.
                    combined_scene=confirmed_recast is not None and (stage=='cooldown' or stage=='casting' and needs_scene_check)
                    if d is None and stage in ('casting','waiting','cooldown') and now-last_gui_scan>8 and not combined_scene:
                        scan_gui()
                    if d is None and stage=='waiting' and not needs_scene_check and now-last_wait_pickup_check>.75 and claim_pending is None:
                        # A cast can be ignored while an existing drop owns the
                        # interaction. Do not wait for the bite timeout to find it.
                        needs_scene_check=True;scene_check_started=None;pickup_gate=PickupGate()
                    if d is None and needs_scene_check and stage in ('casting','waiting','cooldown','equipping'):
                        # Local worker replacement must not abandon loot from the
                        # interrupted worker. Repeat this check after pause and at
                        # every cast boundary; only fresh evidence authorizes T.
                        if scene_check_started is None:scene_check_started=time.monotonic()
                        full_scene=confirmed_recast is not None
                        evidence,stable=pickup_text(full_scene=full_scene);now=time.monotonic()
                        decision=before_cast_decision(evidence,stable,now-scene_check_started,confirmed_recast,full_scene)
                        if decision=='collect':
                            if cycles==0 or cycles in reward_gate.confirmed or last_tracking_cast!=casts:
                                cycles+=1;last_tracking_cast=casts;end_percent=None
                            inventory.begin_round();prompt_seen=True;pickup_tries=0;last_prompt=evidence.text
                            collect_ready=CollectReadyGate();collect_ready.observe(evidence,stable,now)
                            confirmed_recast=None
                            needs_scene_check=False;scene_check_started=None
                            stage='pickup_wait';since=now-.1;last_pickup_scan=0;reset_disc(evidence.key_center or evidence.center)
                            event('pending_pickup_recovered',cycle=cycles,text=evidence.text)
                        elif decision=='clear':
                            if confirmed_recast is not None:
                                event('recast_ready',cycle=cycles,matching_receipt=same_reward(evidence,confirmed_recast),
                                      reward_to_ready_seconds=round(now-reward_confirmed_at,3),
                                      scan_seconds=last_pickup_evidence['scan_seconds'])
                            needs_scene_check=False;scene_check_started=None;last_wait_pickup_check=now
                            if needs_inventory_start and stage=='casting':continue
                            if full_scene:
                                # A minigame that appeared during OCR owns input.
                                d=detect(screen.capture(sct,(1850,400,140,600)))
                                if d is not None and not ui_active():d=None
                        elif decision=='timeout':
                            raise FishingFault('pickup_timeout','Cannot confirm a clear scene before casting; pending loot retained',evidence=last_pickup_evidence)
                        else:
                            time.sleep(.08);continue
                    if d is not None:
                        confirmed_recast=None
                        needs_scene_check=False;scene_check_started=None
                        if tracking_watchdog.observe(d,now):
                            inp.release();screenshot('frozen-minigame')
                            raise FishingFault('tracking_frozen','Minigame markers frozen for 12 seconds; rejoin required',detection=d)
                        last_game_activity=time.time()
                        if stage!='tracking':
                            inventory.begin_round()
                            if claim_pending is not None:
                                # The bite beat the claim; the drop stays for the next pickup.
                                event('drop_cast_interrupted',cycle=claim_pending['cycle'],text=claim_pending['text'],holds=claim_pending['holds']);claim_pending=None
                            inp.grab(False);stage='tracking';since=now;prev=None;velocity=0;target_velocity=0;missing_casts=0
                            motion.suspend()
                            fresh_hook=casts!=last_tracking_cast
                            if fresh_hook:cycles+=1;hooked_cycles+=1;last_tracking_cast=casts
                            event('minigame' if fresh_hook else 'tracking_reacquired',cycle=cycles,cast=casts);screenshot('start');prompt_seen=False;pickup_tries=0;last_prompt=''
                            prompt_detected_at=None
                        lastseen=now
                        if a.gain is None:
                            inp.hold(motion.step(d,now))
                            velocity=motion.velocity;target_velocity=motion.target_velocity
                        else:
                            if prev:
                                dt=max(.005,now-prev[0]);raw=(d['ball']-prev[1])/dt;traw=(d['target']-prev[2])/dt
                                velocity=.55*velocity+.45*raw;target_velocity=.7*target_velocity+.3*traw
                            error=d['ball']-d['target']+a.gain*(velocity-target_velocity)
                            if error>3:inp.hold(True)
                            elif error< -3:inp.hold(False)
                        prev=(now,d['ball'],d['target']);track_frames+=1;inside_frames+=int(d['inside'])
                        telemetry.write(f"{now-started:.3f},{cycles},{d['ball']:.1f},{d['target']:.1f},{d['height']:.1f},{velocity:.1f},{int(inp.mouse)},{int(d['inside'])}\n")
                        if a.record and now-lastimage>.1:
                            cv2.imwrite(str(RUN/f'{session}-track-{cycles}-{int((now-since)*10):04d}.jpg'),roi);lastimage=now
                        if now-since>120:
                            inp.release();screenshot('minigame-timeout')
                            raise FishingFault('tracking_timeout','Minigame did not finish within 120 seconds; rejoin required')
                    elif stage=='tracking':
                        tracking_watchdog.reset()
                        motion.suspend();prev=None
                        if now-lastseen>.12: inp.hold(False)
                        if now-lastseen>.16 and not ui_active():
                            from minigame_result import read_percent
                            inp.release();im=screenshot('end')
                            end_percent,percent_evidence=read_percent(im,ocr,lambda:inp.guard_press(True))
                            if end_percent==100:completed+=1;consecutive_failed=0
                            elif end_percent is not None:failed+=1;consecutive_failed+=1
                            else:unknown+=1
                            event('minigame_ended',cycle=cycles,seconds=round(now-since,2),percent=end_percent,
                                  percent_evidence=percent_evidence)
                            stage='pickup_wait';since=time.monotonic();prev=None;last_pickup_scan=0;collect_ready=CollectReadyGate();reset_disc();drop_eligible=True
                            if consecutive_failed>=5:raise RuntimeError('Five consecutive failed rounds; stopped for review')
                        elif now-lastseen>12:
                            screenshot('missing-markers')
                            raise FishingFault('tracking_lost','Fishing UI visible but marker detection missing for 12 seconds')
                    elif stage=='casting':
                        if now-last_rod_check>12 and load_config()['auto_rod']:
                            frame=screen.capture(sct)
                            rod=recheck_selected_rod(frame,last_verified_rod)
                            if rod is None:rod=locate_rod(frame)
                            last_verified_rod=rod if selected_rod(rod) else None
                            last_rod_check=now
                            if unselected_rod(rod):
                                inp.release();inp.aim(*screen.point(rod['x'],rod['y']))
                                # Recheck focus immediately before each injected button action.
                                if win32gui.GetForegroundWindow()!=hwnd:raise RuntimeError('Roblox lost focus; all inputs released')
                                inp.hold(True);time.sleep(.15);inp.hold(False)
                                event('rod_selection_attempt',method='visible hotbar');cast_needs_settle=True;stage='equipping';since=time.monotonic();continue
                        # Time the actual press, not entry into the casting state:
                        # OCR and rod detection can delay this iteration substantially.
                        if not inp.mouse:
                            recast_reward_at=reward_confirmed_at if confirmed_recast is not None else None
                            confirmed_recast=None
                            inventory.begin_round()
                            if not first_person_active:
                                inp.aim_cast(*screen.point(*load_config()['cast_point']),after_menu=cast_needs_settle)
                            cast_needs_settle=False
                            inp.hold(True);cast_press_started=time.monotonic()
                            if recast_reward_at is not None:
                                event('recast_pressed',cycle=cycles,
                                      reward_to_press_seconds=round(cast_press_started-recast_reward_at,3))
                        if cast_press_started is not None:
                            # Capture/OCR between mouse-down and mouse-up extended
                            # this short press. The focus watcher remains active;
                            # check its gate while completing the bounded press.
                            while time.monotonic()-cast_press_started<CAST_PRESS_SECONDS:
                                inp.guard_press(True)
                                time.sleep(.005)
                            inp.hold(False);cast_press_started=None;casts+=1;event('cast',cast=casts);stage='waiting';since=time.monotonic();last_wait_pickup_check=since
                    elif stage=='equipping':
                        if now-since>.65:
                            inp.guard_press(True);move_pointer(*screen.point(*load_config()['cast_point']));stage='casting';since=now
                            needs_scene_check=True;scene_check_started=None;pickup_gate=PickupGate()
                    elif stage=='waiting':
                        if claim_pending is not None:
                            cp=claim_pending
                            if not inp.t:
                                if now-last_pickup_scan>.08:
                                    evidence,stable=pickup_text();now=time.monotonic();last_pickup_scan=now
                                    if evidence.kind=='collect' and (stable or evidence.key_center is not None):
                                        inp.grab(True);cp['hold_at']=now;cp['holds']+=1;last_toast_scan=0
                                        event('drop_cast_hold',cycle=cp['cycle'],attempt=cp['holds'],text=evidence.text,
                                              drop_to_hold_seconds=round(now-cp['dropped'],3))
                                    elif evidence.kind=='reward' and stable:
                                        record_reward(evidence.text);confirmed_recast=None;claim_pending=None
                                    elif now-cp['dropped']>4.5 or cp['holds']>=3:
                                        event('drop_cast_unclaimed',cycle=cp['cycle'],text=cp['text']);claim_pending=None
                            elif now-cp['hold_at']>.2 and now-last_toast_scan>.08:
                                last_toast_scan=time.monotonic()
                                first=pickup_toast(require_x=True)
                                receipt=None
                                if first.kind=='reward':
                                    second=pickup_toast(require_x=True)
                                    if same_reward(first,second):receipt=second
                                now=time.monotonic()
                                if receipt is not None:
                                    inp.grab(False);record_reward(receipt.text);confirmed_recast=None
                                    event('drop_cast_claimed',cycle=cp['cycle'],text=receipt.text,
                                          drop_to_claim_seconds=round(now-cp['dropped'],3),holds=cp['holds'])
                                    claim_pending=None
                                elif now-cp['hold_at']>collect_hold_timeout(cp['holds']):
                                    inp.grab(False)  # Rescan; a persisting prompt gets another hold.
                        if now-since>BITE_WAIT_TIMEOUT_SECONDS:
                            missing_casts+=1;event('no_minigame',count=missing_casts);screenshot('missing')
                            if drop_cast_at_cast==casts and drop_cast_gap<.5:
                                # The recast right after a drop did not take; wait longer next time.
                                drop_cast_gap=round(drop_cast_gap+.2,2);event('drop_cast_gap',seconds=drop_cast_gap)
                            if first_person_active:
                                # The game's camera can slowly pitch into a nearby
                                # railing. Scrolling out and moving the pointer while
                                # Roblox still has camera lock pitches it farther
                                # down; a fresh join restores the saved view safely.
                                event('camera_rejoin',reason='First-person cast did not reach water')
                                raise FishingFault('no_minigame','First-person cast did not start a minigame; rejoin to restore camera',
                                    missed_casts=missing_casts,wait_seconds=BITE_WAIT_TIMEOUT_SECONDS)
                            if missing_casts>=MISSED_CASTS_BEFORE_REJOIN:
                                raise FishingFault('no_minigame','Three casts without a recognized minigame',
                                    missed_casts=missing_casts,wait_seconds=BITE_WAIT_TIMEOUT_SECONDS)
                            inp.grab(False);claim_pending=None;stage='pickup_wait';since=now;reset_disc()
                    elif stage=='pickup_wait':
                        if prompt_detected_at is not None:
                            disc_observe();now=time.monotonic()
                        if pending_collect is not None and landed(now):
                            # The OCR-confirmed prompt has landed; hold on this frame.
                            if now-pending_collect[1]<.6:start_hold(pending_collect[0])
                            else:pending_collect=None
                        elif now-since>.08 and now-last_pickup_scan>.08:
                            evidence,stable=pickup_text();now=time.monotonic();last_pickup_scan=now;prompt_seen=evidence.kind=='collect' and stable
                            if evidence.kind=='collect' and disc_track.position is None:
                                disc_track.near=evidence.key_center or evidence.center
                            collect_is_ready=collect_ready.observe(evidence,stable,now)
                            decision=waiting_decision(evidence,stable,now-since,last_tracking_cast==casts,end_percent)
                            if decision=='reward':
                                record_reward(evidence.text);screenshot('collected',defer=True);start_cooldown(CONFIRMED_REWARD_COOLDOWN_SECONDS)
                            elif (decision=='collect' and claim_pending is None and drop_eligible and last_tracking_cast==casts
                                    and cycles not in reward_gate.confirmed and load_config().get('drop_cast')):
                                # Drop-cast mode: one click drops the caught item, the next
                                # press recasts, and T claims the drop while the line is out.
                                last_prompt=evidence.text;inp.release()
                                inp.hold(True);time.sleep(.05);inp.hold(False);time.sleep(drop_cast_gap)
                                drop_cast_at_cast=casts+1
                                drop_eligible=False
                                claim_pending={'cycle':cycles,'text':evidence.text,'dropped':time.monotonic(),'hold_at':None,'holds':0}
                                # Completing a claim after the line lands reels it in (22 of 23
                                # trials). Start the 2 s claim hold now so it finishes while the
                                # cast is still in the air.
                                inp.grab(True);claim_pending['hold_at']=time.monotonic();claim_pending['holds']=1;last_toast_scan=0
                                event('drop_cast_drop',cycle=cycles,text=evidence.text,gap_seconds=round(drop_cast_gap,2),hold_first=True)
                                stage='casting';since=time.monotonic();needs_scene_check=False;scene_check_started=None
                            elif decision=='collect' and collect_is_ready:
                                if landed(now):start_hold(evidence)
                                else:
                                    pending_collect=(evidence,now)
                                    if not landing_wait_logged:
                                        landing_wait_logged=True;event('pickup_landing_wait',cycle=cycles,disc=disc_track.position)
                            elif decision=='empty':
                                empty_round(0. if evidence.kind=='empty' and stable else .6)
                            elif decision=='timeout':
                                raise FishingFault('pickup_timeout','Pickup prompt remained ambiguous after wide scans',evidence=last_pickup_evidence)
                    elif stage=='pickup':
                        if inp.t and pickup_tries<3 and not (disc_repress_cycle==cycles and disc_represses>=3):
                            # Follow the held key disc every frame; OCR is too slow
                            # to see a drop land and replace its prompt.
                            position=disc_observe();now=time.monotonic()
                            if position is not None and hold_anchor is None:hold_anchor=position
                            if (position is not None and math.dist(position,hold_anchor)>HELD_DISC_MOVE_PIXELS
                                    and disc_track.settled(now)):
                                # Re-presses on a landed disc do not use up the three
                                # state-driven attempts; they are capped separately.
                                inp.grab(False);time.sleep(.04);inp.grab(True);since=time.monotonic()
                                disc_represses=disc_represses+1 if disc_repress_cycle==cycles else 1;disc_repress_cycle=cycles
                                event('pickup_hold',cycle=cycles,attempt=pickup_tries,prompt_seen=True,text=last_prompt,
                                      reason='Prompt disc landed elsewhere',from_center=hold_anchor,center=position,repress=disc_represses)
                                hold_anchor=position;collect_motion.start(Pickup('collect',last_prompt,position,position),since)
                            # Only trust absence when the disc stayed detectable mid-hold.
                            if (hold_anchor is not None and disc_gone_logged!=(cycles,pickup_tries) and disc_track.seen_at is not None
                                    and disc_track.seen_at-since>.2 and disc_track.missing_for(now)>=PROMPT_GONE_SECONDS):
                                # Keep holding: at hold completion the disc can vanish
                                # before the claim registers. Log the moment for timing.
                                disc_gone_logged=(cycles,pickup_tries)
                                event('pickup_disc_gone',cycle=cycles,attempt=pickup_tries,hold_seconds=round(now-since,3))
                        # The tiny toast is much faster than another scene OCR.
                        if now-since>.20 and now-last_toast_scan>.08:
                            last_toast_scan=time.monotonic()
                            first=pickup_toast()
                            if first.kind=='reward':
                                second=pickup_toast()
                                if same_reward(first,second):
                                    record_reward(second.text);screenshot('collected',defer=True);start_cooldown(CONFIRMED_REWARD_COOLDOWN_SECONDS);continue
                            now=time.monotonic()
                        if now-since>.45 and now-last_pickup_scan>.35:
                            evidence,stable=pickup_text();last_pickup_scan=time.monotonic()
                            now=time.monotonic()
                            moved_collect=collect_motion.observe(evidence,stable,now,pickup_tries)
                            if evidence.kind=='reward' and stable:
                                record_reward(evidence.text);screenshot('collected',defer=True);start_cooldown(CONFIRMED_REWARD_COOLDOWN_SECONDS);continue
                            if evidence.kind=='empty' and stable and inp.t and not retain_collect_hold(evidence,now-since,attempt=pickup_tries):
                                inp.grab(False);event('pickup_released',cycle=cycles,reason='Prompt disappeared')
                            elif evidence.kind=='collect' and stable and not inp.t:
                                if pickup_tries>=3:raise FishingFault('pickup_timeout','Collect remained after three state-driven attempts')
                                inp.grab(True);pickup_tries+=1;since=time.monotonic()
                                collect_motion.start(evidence,since);hold_anchor=disc_track.position
                                event('pickup_hold',cycle=cycles,attempt=pickup_tries,prompt_seen=True,text=evidence.text)
                            elif evidence.kind=='collect' and inp.t and moved_collect:
                                prior_center=collect_motion.origin
                                inp.grab(False);time.sleep(.06);inp.grab(True);pickup_tries+=1;since=time.monotonic()
                                collect_motion.start(evidence,since);hold_anchor=disc_track.position
                                event('pickup_hold',cycle=cycles,attempt=pickup_tries,prompt_seen=True,text=evidence.text,
                                      reason='Collect target moved and settled',from_center=prior_center,center=evidence.center,key_center=evidence.key_center)
                        # Confirm the small toast twice while T is held. This
                        # avoids waiting for the full hold timeout when wide OCR misses X1.
                        if now-since>collect_hold_timeout(pickup_tries):
                            inp.grab(False);evidence,stable=pickup_text()
                            # A banner can appear just as the T hold ends. Confirm
                            # it across another frame before deferring to the
                            # inventory, while still retrying a persistent prompt.
                            if evidence.kind!='collect' and not (evidence.kind=='reward' and stable):
                                for _ in range(2):
                                    time.sleep(.08)
                                    follow,follow_stable=pickup_text()
                                    if follow.kind in ('collect','reward'):
                                        evidence,stable=follow,follow_stable
                                    if follow.kind=='collect' or (follow.kind=='reward' and follow_stable):
                                        break
                            if evidence.kind!='collect' and not (evidence.kind=='reward' and stable):
                                first=pickup_toast();time.sleep(.08);second=pickup_toast()
                                if same_reward(first,second):
                                    evidence,stable=second,True
                            screenshot('after-pickup',defer=evidence.kind=='reward' and stable)
                            if evidence.kind=='collect' and stable:
                                if pickup_tries>=3:raise FishingFault('pickup_timeout','Collect remained after three state-driven attempts')
                                # This is already a fresh stable scan after T-up.
                                # Its OCR took longer than a release frame; do not
                                # add another dwell and duplicate scan to retry.
                                inp.grab(True);pickup_tries+=1;since=time.monotonic()
                                collect_motion.start(evidence,since);hold_anchor=disc_track.position
                                event('pickup_hold',cycle=cycles,attempt=pickup_tries,prompt_seen=True,text=evidence.text,
                                      reason='Collect persisted after hold deadline',key_center=evidence.key_center)
                            elif evidence.kind=='collect':stage='pickup_retry_wait';since=time.monotonic()
                            else:
                                if evidence.kind=='reward' and stable:record_reward(evidence.text)
                                elif prompt_seen:inventory.observe_unconfirmed(last_prompt,f'{session}:{cycles}:inventory')
                                start_cooldown(CONFIRMED_REWARD_COOLDOWN_SECONDS if evidence.kind=='reward' and stable else 1.0)
                                event('pickup_attempted',cycle=cycles,attempts=pickup_tries)
                    elif stage=='pickup_retry_wait':
                        if now-since>.08:
                            if pickup_tries>=3:raise RuntimeError('Pickup prompt still present after three held-T attempts')
                            evidence,stable=pickup_text()
                            if evidence.kind=='collect' and stable:
                                inp.grab(True);stage='pickup';since=time.monotonic();pickup_tries+=1
                                collect_motion.start(evidence,since);hold_anchor=disc_track.position
                                event('pickup_hold',cycle=cycles,attempt=pickup_tries,prompt_seen=True,text=evidence.text,
                                      scan_seconds=last_pickup_evidence['scan_seconds'])
                            else:stage='pickup_wait';since=time.monotonic()
                    elif stage=='cooldown':
                        pass  # The guarded transition above runs before the fresh scene read.
                    if now-laststate>1:
                        status={'running':True,'pid':os.getpid(),'session':session,'updated':time.time(),'elapsed':round(now-started,1),'stage':stage,'cycles':hooked_cycles,'recovered_pickups':cycles-hooked_cycles,'casts':casts,'completed_100_percent':completed,'failed_rounds':failed,'unknown_rounds':unknown,'reward_banners_observed':pickup_confirmed,'last_reward':last_reward,'track_frames':track_frames,'inside_fraction':round(inside_frames/max(1,track_frames),3),'last_detection':d,'held_mouse':inp.mouse,'held_t':inp.t}
                        status['last_game_activity']=last_game_activity
                        status['capture_resets']=sct.resets
                        write_metrics('status.json',status);laststate=now
                        ledger.update(now-started,casts,hooked_cycles,pickup_confirmed,failed,last_reward)
                    time.sleep(max(.001,1/60-(time.monotonic()-tick)))
                except InputPaused:
                    inp.gate.interrupted.set();inp.release()
                except RuntimeError as error:
                    if reason_code(str(error))!='focus':raise
                    inp.gate.interrupted.set();inp.release()
        last_reason='session_limit';event('session_limit')
    except BaseException as ex:
        last_reason=str(ex);failure_code=getattr(ex,'code',reason_code(last_reason));failure_details=getattr(ex,'details',{})
        if failure_code not in ('manual_stop','session_limit','focus'):
            inp.release()
            try:
                screenshot('failure')
                diagnostics.save(failure_code,last_reason,pickup=last_pickup_evidence,**failure_details)
            except Exception as diagnostic_error:event('diagnostic_error',message=str(diagnostic_error))
        event('stopped',reason=str(ex),code=failure_code);raise
    finally:
        emergency_listener.stop()
        inp.gate.close()
        ledger.update((paused_at if paused_at is not None else time.monotonic())-started,casts,hooked_cycles,pickup_confirmed,failed,last_reward)
        prior=json.loads((RUN/'status.json').read_text()) if (RUN/'status.json').exists() else {}
        prior.update(running=False,updated=time.time(),ended=time.time(),reason=last_reason,failure_code=failure_code,held_mouse=False,held_t=False,casts=casts,cycles=hooked_cycles,recovered_pickups=cycles-hooked_cycles,reward_banners_observed=pickup_confirmed,failed_rounds=failed,last_reward=last_reward);write_metrics('status.json',prior)
        log.close();telemetry.close()

if __name__=='__main__':main()
