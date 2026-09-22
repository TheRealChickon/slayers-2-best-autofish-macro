"""Screen-only Roblox fishing controller; F9, F12 or Escape stops all input."""
import argparse, ctypes, json, os, time, sys, traceback, re
from ctypes import wintypes
from pathlib import Path
import cv2, mss, numpy as np, psutil, win32gui, win32process, win32api
from rapidocr_onnxruntime import RapidOCR
from metrics import Ledger, write as write_metrics, RUN
from app_config import load_config
from rod_detector import locate_rod
from screen_space import ScreenSpace
from inventory_watch import InventoryDriver, InventoryWatcher

ROOT = Path(__file__).resolve().parent
USER = ctypes.windll.user32
USER.SetProcessDPIAware()

def move_pointer(x,y):
    # Both monitors are valid; coordinates are absolute virtual-desktop pixels.
    monitors=[entry[2] for entry in win32api.EnumDisplayMonitors()]
    left=min(r[0] for r in monitors);top=min(r[1] for r in monitors)
    width=max(r[2] for r in monitors)-left;height=max(r[3] for r in monitors)-top
    if not (left<=x<left+width and top<=y<top+height):raise RuntimeError(f'Input ({x}, {y}) is outside desktop ({left}, {top}, {width}, {height})')
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
    if len(found)!=1: raise RuntimeError(f'Expected one Roblox window, found {len(found)}')
    return found[0]

def rectangle(h):
    # Client pixels exclude the title bar and resize border in windowed mode.
    l,t,r,b=win32gui.GetClientRect(h)
    x,y=win32gui.ClientToScreen(h,(0,0))
    return x,y,x+r-l,y+b-t

class Input:
    def __init__(self,hwnd=None): self.mouse=False; self.t=False; self.hwnd=hwnd
    def guard_press(self,down):
        if down and self.hwnd is not None and (not win32gui.IsWindow(self.hwnd) or win32gui.IsIconic(self.hwnd) or win32gui.GetForegroundWindow()!=self.hwnd):
            raise RuntimeError('Roblox lost focus; all inputs released')
    def hold(self,down):
        if down!=self.mouse:
            self.guard_press(down)
            if down and self.hwnd is not None:
                under=win32gui.WindowFromPoint(win32gui.GetCursorPos())
                if win32gui.GetAncestor(under,2)!=self.hwnd:
                    raise RuntimeError('Pointer is outside Roblox; all inputs released')
            USER.mouse_event(2 if down else 4,0,0,0,0); self.mouse=down
    def grab(self,down):
        if down!=self.t:
            self.guard_press(down)
            scan=USER.MapVirtualKeyW(ord('T'),0)
            USER.keybd_event(ord('T'),scan,0 if down else 2,0); self.t=down
    def release(self): self.hold(False); self.grab(False)

def detect(roi):
    hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
    green=cv2.inRange(hsv,np.array([20,65,48]),np.array([100,255,255]))
    targets=[]
    for c in cv2.findContours(green,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
        x,y,w,h=cv2.boundingRect(c)
        if 54<=w<=95 and 22<=h<=130 and 12<=x<=50 and cv2.contourArea(c)>500:
            targets.append((cv2.contourArea(c),y+h/2,h))
    white=cv2.inRange(roi,np.array([178]*3),np.array([255]*3))
    balls=[]
    for c in cv2.findContours(white,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
        x,y,w,h=cv2.boundingRect(c)
        if 14<=w<=45 and 14<=h<=48 and 42<=x<=87 and cv2.contourArea(c)>150:
            balls.append((cv2.contourArea(c),y+h/2,h))
    if not targets or not balls:return None
    _,target,height=max(targets)
    _,ball,bheight=max(balls)
    return {'target':target,'height':height,'ball':ball,'ball_height':bheight,'inside':abs(ball-target)<(height-bheight)/2+3}

def is_pickup_prompt(text):
    # The moving prompt can be partially occluded by the character.
    return not is_other_interaction(text) and bool(re.search(r'collect|ollect|llect|\blect\b',text,re.I))

def is_other_interaction(text):
    # T also operates world interactions. A climb prompt means the saved
    # fishing position was disturbed; holding it again cannot collect loot.
    return bool(re.search(r'\bwall\b|climb|\bpurchase\b|\bfisherman\b|\bwould you like\b',text,re.I))

def is_reward_banner(text):
    # Item text alone can still be the pickup prompt. A quantity/new label
    # belongs to the actual collection notification.
    return not is_other_interaction(text) and not is_pickup_prompt(text) and bool(re.search(r'\bx\s*\d+\b|\bnew\b',text,re.I))

def main():
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=float,default=0);p.add_argument('--focus',action='store_true');p.add_argument('--record',action='store_true');p.add_argument('--gain',type=float,default=.09);a=p.parse_args()
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
    if win32gui.GetForegroundWindow()!=hwnd:raise RuntimeError('Bring Roblox to the foreground before starting')
    # Observed open water, clear of menus and game buttons.
    move_pointer(*screen.point(1650,800))
    ocr=RapidOCR()
    exit_template=cv2.imread(str(ROOT/'assets'/'exit.png'))
    inp=Input(hwnd);started=time.monotonic();now=started;stage='casting';since=now;lastseen=now;ledger=Ledger();last_gui_scan=0;last_tracking_cast=None;last_game_activity=time.time()
    prev=None;velocity=0.;target_velocity=0.;cycles=0;casts=0;missing_casts=0;track_frames=0;inside_frames=0;laststate=0;lastimage=0;last_rod_check=0
    completed=0;failed=0;unknown=0;pickup_confirmed=0;prompt_seen=False;pickup_tries=0;last_pickup_scan=0;last_reason='';last_reward='';last_prompt='';end_percent=None;consecutive_failed=0;cast_press_started=None
    session=time.strftime('%Y%m%d-%H%M%S'); log=open(RUN/f'events-{session}.jsonl','a',buffering=1)
    telemetry=open(RUN/f'tracking-{session}.csv','w',buffering=1);telemetry.write('time,cycle,ball,target,height,velocity,held,inside\n')
    def event(kind,**kw):log.write(json.dumps({'at':time.time(),'event':kind,**kw})+'\n');print(json.dumps({'event':kind,**kw}),flush=True)
    def inventory_progress(**kw):
        write_metrics('status.json',{'running':True,'pid':os.getpid(),'session':session,'updated':time.time(),
            'stage':'inventory','inventory':kw,'last_game_activity':last_game_activity,
            'held_mouse':False,'held_t':False,'cycles':cycles,'casts':casts})
    def record_reward(raw):
        nonlocal pickup_confirmed,last_reward
        inp.grab(False);pickup_confirmed+=1;last_reward=raw
        reward_id=f'{session}:{cycles}:{pickup_confirmed}'
        event('reward_observed',cycle=cycles,text=raw,reward_id=reward_id)
        inventory.observe(raw,last_prompt,reward_id)
    def screenshot(tag):
        im=screen.capture(sct)
        cv2.imwrite(str(RUN/f'{session}-{cycles%12:03d}-{tag}.jpg'),im,[cv2.IMWRITE_JPEG_QUALITY,88])
        cv2.imwrite(str(RUN/'latest.jpg'),im,[cv2.IMWRITE_JPEG_QUALITY,80])
        return im
    def read_text(im):
        result,_=ocr(im)
        return ' '.join(r[1] for r in result or [] if r[2]>.8)
    def pickup_text():
        # Cover dropped loot and nearby interaction prompts across camera positions.
        im=screen.capture(sct,(550,480,1500,850))
        return read_text(im)
    def check_pickup_position(raw):
        if is_other_interaction(raw):
            inp.release();event('wrong_interaction',text=raw);screenshot('wrong-interaction')
            raise RuntimeError('Non-fishing interaction replaced pickup; rejoin to restore fishing position')
    def ui_active():
        im=screen.capture(sct,(1190,1360,180,70))
        return float(cv2.minMaxLoc(cv2.matchTemplate(im,exit_template,cv2.TM_CCOEFF_NORMED))[1])>.84
    event('started',pid=os.getpid(),session=session)
    try:
        with mss.MSS() as sct:
            inventory=InventoryWatcher(InventoryDriver(hwnd,screen,sct,inp,ocr,USER,move_pointer),event,inventory_progress)
            inventory.start();now=time.monotonic();since=now
            while now-started<limit:
                tick=time.monotonic();now=tick
                if stop.exists():raise RuntimeError('Stopped by stop file')
                if (RUN/'RECOVER').exists():
                    (RUN/'RECOVER').unlink();raise RuntimeError('Roblox presence requested reconnect after stalled activity')
                if any(USER.GetAsyncKeyState(k)&0x8000 for k in (27,120,123)):raise RuntimeError('Stopped by Escape/F9/F12')
                if not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd) or win32gui.GetForegroundWindow()!=hwnd:raise RuntimeError('Roblox lost focus; all inputs released')
                if rectangle(hwnd)!=rect:raise RuntimeError('Roblox moved or resized; reacquiring the client area')
                roi=screen.capture(sct,(1850,400,140,600))
                d=detect(roi)
                if d is None and stage!='tracking' and now-last_gui_scan>5:
                    gui=screen.capture(sct,(760,410,1040,580))
                    raw_gui=read_text(cv2.resize(gui,None,fx=.75,fy=.75)).lower();last_gui_scan=time.monotonic()
                    if any(t in raw_gui for t in ('disconnected','connection lost','connection error','failed to connect','same account launched','error code','reconnect')):
                        inp.release();event('disconnect_gui',text=raw_gui);raise RuntimeError('Disconnect GUI detected; rejoin required')
                if d is not None:
                    last_game_activity=time.time()
                    if stage!='tracking':
                        inventory.begin_round()
                        inp.grab(False);stage='tracking';since=now;prev=None;velocity=0;target_velocity=0;missing_casts=0
                        fresh_hook=casts!=last_tracking_cast
                        if fresh_hook:cycles+=1;last_tracking_cast=casts
                        event('minigame' if fresh_hook else 'tracking_reacquired',cycle=cycles,cast=casts);screenshot('start');prompt_seen=False;pickup_tries=0;last_prompt=''
                    lastseen=now
                    if prev:
                        dt=max(.005,now-prev[0]);raw=(d['ball']-prev[1])/dt;traw=(d['target']-prev[2])/dt
                        velocity=.55*velocity+.45*raw;target_velocity=.7*target_velocity+.3*traw
                    # Hold raises the white marker; release lets it fall. Anticipate momentum.
                    error=d['ball']-d['target']+a.gain*(velocity-target_velocity)
                    if error>3:inp.hold(True)
                    elif error< -3:inp.hold(False)
                    prev=(now,d['ball'],d['target']);track_frames+=1;inside_frames+=int(d['inside'])
                    telemetry.write(f"{now-started:.3f},{cycles},{d['ball']:.1f},{d['target']:.1f},{d['height']:.1f},{velocity:.1f},{int(inp.mouse)},{int(d['inside'])}\n")
                    if a.record and now-lastimage>.1:
                        cv2.imwrite(str(RUN/f'{session}-track-{cycles}-{int((now-since)*10):04d}.jpg'),roi);lastimage=now
                    if now-since>75:raise RuntimeError('Minigame stalled for 75 seconds')
                elif stage=='tracking':
                    if now-lastseen>.12: inp.hold(False)
                    if now-lastseen>.16 and not ui_active():
                        inp.release();im=screenshot('end');raw=read_text(cv2.resize(im[1280:1360,1180:1380],None,fx=3,fy=3))
                        numbers=re.findall(r'(\d{1,3})\s*%',raw);end_percent=int(numbers[0]) if numbers else None
                        if end_percent==100:completed+=1;consecutive_failed=0
                        elif end_percent is not None:failed+=1;consecutive_failed+=1
                        else:unknown+=1
                        event('minigame_ended',cycle=cycles,seconds=round(now-since,2),percent=end_percent)
                        stage='pickup_wait';since=time.monotonic();prev=None;last_pickup_scan=0
                        if consecutive_failed>=5:raise RuntimeError('Five consecutive failed rounds; stopped for review')
                    elif now-lastseen>5:raise RuntimeError('Fishing UI visible but marker detection missing for five seconds')
                elif stage=='casting':
                    if now-last_rod_check>4 and load_config()['auto_rod']:
                        frame=screen.capture(sct)
                        rod=locate_rod(frame);last_rod_check=now
                        if rod and not rod['equipped']:
                            inp.release();move_pointer(*screen.point(rod['x'],rod['y']))
                            # Recheck focus immediately before each injected button action.
                            if win32gui.GetForegroundWindow()!=hwnd:raise RuntimeError('Roblox lost focus; all inputs released')
                            inp.hold(True);time.sleep(.15);inp.hold(False)
                            event('rod_equipped',method='visible hotbar');stage='equipping';since=time.monotonic();continue
                    # Time the actual press, not entry into the casting state:
                    # OCR and rod detection can delay this iteration substantially.
                    if not inp.mouse:
                        inventory.begin_round()
                        move_pointer(*screen.point(1650,800))
                        inp.hold(True);cast_press_started=time.monotonic()
                    elif cast_press_started is not None and time.monotonic()-cast_press_started>=.16:
                        inp.hold(False);cast_press_started=None;casts+=1;event('cast',cast=casts);stage='waiting';since=time.monotonic()
                elif stage=='equipping':
                    if now-since>.65:
                        move_pointer(*screen.point(1650,800));stage='casting';since=now
                elif stage=='waiting':
                    if now-since>30:
                        missing_casts+=1;event('no_minigame',count=missing_casts);screenshot('missing')
                        if missing_casts>=3:raise RuntimeError('Three casts without a recognized minigame')
                        stage='pickup_wait';since=now
                elif stage=='pickup_wait':
                    if now-since>.4 and now-last_pickup_scan>.35:
                        raw=pickup_text();check_pickup_position(raw);last_pickup_scan=time.monotonic();prompt_seen=is_pickup_prompt(raw)
                        if prompt_seen or now-since>3:
                            if prompt_seen:last_prompt=raw
                            inp.grab(True);stage='pickup';since=time.monotonic();pickup_tries+=1;screenshot('pickup');event('pickup_hold',attempt=pickup_tries,prompt_seen=prompt_seen,text=raw)
                elif stage=='pickup':
                    if now-since>.3 and now-last_pickup_scan>.3:
                        raw=pickup_text();check_pickup_position(raw);last_pickup_scan=time.monotonic()
                        if now-since>1.8 and is_reward_banner(raw):
                            record_reward(raw);screenshot('collected');stage='cooldown';since=time.monotonic();continue
                    if now-since>4.0:
                        inp.grab(False);raw=pickup_text();check_pickup_position(raw);screenshot('after-pickup')
                        if is_pickup_prompt(raw) or (not raw and pickup_tries<2):stage='pickup_retry_wait'
                        else:
                            if is_reward_banner(raw):record_reward(raw)
                            elif prompt_seen:inventory.observe_unconfirmed(last_prompt,f'{session}:{cycles}:inventory')
                            stage='cooldown';event('pickup_attempted',cycle=cycles,attempts=pickup_tries)
                        since=time.monotonic()
                elif stage=='pickup_retry_wait':
                    if now-since>.5:
                        if pickup_tries>=3:raise RuntimeError('Pickup prompt still present after three held-T attempts')
                        inp.grab(True);stage='pickup';since=now;pickup_tries+=1
                elif stage=='cooldown':
                    if now-since>1.0:
                        recovered=inventory.check_pending()
                        if recovered:
                            pickup_confirmed+=1;last_reward=f"{recovered['item']} X{recovered['quantity']} (inventory)"
                        inventory.end_round()
                        stage='casting';now=time.monotonic();since=now;cast_press_started=None
                if now-laststate>1:
                    status={'running':True,'pid':os.getpid(),'session':session,'updated':time.time(),'elapsed':round(now-started,1),'stage':stage,'cycles':cycles,'casts':casts,'completed_100_percent':completed,'failed_rounds':failed,'unknown_rounds':unknown,'reward_banners_observed':pickup_confirmed,'last_reward':last_reward,'track_frames':track_frames,'inside_fraction':round(inside_frames/max(1,track_frames),3),'last_detection':d,'held_mouse':inp.mouse,'held_t':inp.t}
                    status['last_game_activity']=last_game_activity
                    write_metrics('status.json',status);laststate=now
                    ledger.update(now-started,casts,cycles,pickup_confirmed,failed,last_reward)
                time.sleep(max(0,.02-(time.monotonic()-tick)))
        last_reason='session_limit';event('session_limit')
    except BaseException as ex:
        last_reason=str(ex);event('stopped',reason=str(ex));raise
    finally:
        inp.release()
        ledger.update(time.monotonic()-started,casts,cycles,pickup_confirmed,failed,last_reward)
        prior=json.loads((RUN/'status.json').read_text()) if (RUN/'status.json').exists() else {}
        prior.update(running=False,updated=time.time(),ended=time.time(),reason=last_reason,held_mouse=False,held_t=False,casts=casts,cycles=cycles,reward_banners_observed=pickup_confirmed,failed_rounds=failed,last_reward=last_reward);(RUN/'status.json').write_text(json.dumps(prior,indent=2))
        log.close();telemetry.close()

if __name__=='__main__':main()
