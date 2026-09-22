"""Screen-only Roblox fishing controller; F9, F12 or Escape stops all input."""
import argparse, ctypes, json, os, time, sys, traceback, re
from ctypes import wintypes
from pathlib import Path
import cv2, mss, numpy as np, psutil, win32gui, win32process
from rapidocr_onnxruntime import RapidOCR
from metrics import Ledger, write as write_metrics, RUN
from app_config import load_config
from rod_detector import locate_rod

ROOT = Path(__file__).resolve().parent
USER = ctypes.windll.user32
USER.SetProcessDPIAware()

def move_pointer(x,y):
    # Both monitors are valid; coordinates are absolute virtual-desktop pixels.
    left,top=USER.GetSystemMetrics(76),USER.GetSystemMetrics(77)
    width,height=USER.GetSystemMetrics(78),USER.GetSystemMetrics(79)
    if not (left<=x<left+width and top<=y<top+height):raise RuntimeError('Input is outside the desktop')
    USER.mouse_event(0xC001,round((x-left)*65535/(width-1)),round((y-top)*65535/(height-1)),0,0)

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
    r=wintypes.RECT()
    ok=ctypes.windll.dwmapi.DwmGetWindowAttribute(h,9,ctypes.byref(r),ctypes.sizeof(r))
    return (r.left,r.top,r.right,r.bottom) if ok==0 else win32gui.GetWindowRect(h)

class Input:
    def __init__(self,hwnd=None): self.mouse=False; self.t=False; self.hwnd=hwnd
    def guard_press(self,down):
        if down and self.hwnd is not None and (not win32gui.IsWindow(self.hwnd) or win32gui.IsIconic(self.hwnd) or win32gui.GetForegroundWindow()!=self.hwnd):
            raise RuntimeError('Roblox lost focus; all inputs released')
    def hold(self,down):
        if down!=self.mouse:
            self.guard_press(down)
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
    return bool(re.search(r'\bwall\b|climb',text,re.I))

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
    if rect[2]-rect[0]!=2560 or rect[3]-rect[1]!=1440:raise RuntimeError('This calibration needs Roblox at 2560 × 1440')
    if a.focus:win32gui.SetForegroundWindow(hwnd);time.sleep(.3)
    if win32gui.GetForegroundWindow()!=hwnd:raise RuntimeError('Bring Roblox to the foreground before starting')
    # Observed open water, clear of menus and game buttons.
    move_pointer(rect[0]+1650,rect[1]+800)
    ocr=RapidOCR()
    exit_template=cv2.imread(str(ROOT/'assets'/'exit.png'))
    inp=Input(hwnd);started=time.monotonic();now=started;stage='casting';since=now;lastseen=now;ledger=Ledger();last_gui_scan=0;last_tracking_cast=None;last_game_activity=time.time()
    prev=None;velocity=0.;target_velocity=0.;cycles=0;casts=0;missing_casts=0;track_frames=0;inside_frames=0;laststate=0;lastimage=0;last_rod_check=0
    completed=0;failed=0;unknown=0;pickup_confirmed=0;prompt_seen=False;pickup_tries=0;last_pickup_scan=0;last_reason='';last_reward='';end_percent=None;consecutive_failed=0
    session=time.strftime('%Y%m%d-%H%M%S'); log=open(RUN/f'events-{session}.jsonl','a',buffering=1)
    telemetry=open(RUN/f'tracking-{session}.csv','w',buffering=1);telemetry.write('time,cycle,ball,target,height,velocity,held,inside\n')
    def event(kind,**kw):log.write(json.dumps({'at':time.time(),'event':kind,**kw})+'\n');print(json.dumps({'event':kind,**kw}),flush=True)
    def screenshot(tag):
        l,t,r,b=rect;im=np.array(sct.grab({'left':l,'top':t,'width':r-l,'height':b-t}))[:,:,:3]
        cv2.imwrite(str(RUN/f'{session}-{cycles%12:03d}-{tag}.jpg'),im,[cv2.IMWRITE_JPEG_QUALITY,88])
        cv2.imwrite(str(RUN/'latest.jpg'),im,[cv2.IMWRITE_JPEG_QUALITY,80])
        return im
    def read_text(im):
        result,_=ocr(im)
        return ' '.join(r[1] for r in result or [] if r[2]>.8)
    def pickup_text():
        im=np.array(sct.grab({'left':rect[0]+950,'top':rect[1]+570,'width':720,'height':360}))[:,:,:3]
        return read_text(im)
    def check_pickup_position(raw):
        if is_other_interaction(raw):
            inp.release();event('wrong_interaction',text=raw);screenshot('wrong-interaction')
            raise RuntimeError('Wall climb prompt replaced pickup; rejoin to restore fishing position')
    def ui_active():
        im=np.array(sct.grab({'left':rect[0]+1190,'top':rect[1]+1360,'width':180,'height':70}))[:,:,:3]
        return float(cv2.minMaxLoc(cv2.matchTemplate(im,exit_template,cv2.TM_CCOEFF_NORMED))[1])>.84
    event('started',pid=os.getpid(),session=session)
    try:
        with mss.MSS() as sct:
            while now-started<limit:
                tick=time.monotonic();now=tick
                if stop.exists():raise RuntimeError('Stopped by stop file')
                if (RUN/'RECOVER').exists():
                    (RUN/'RECOVER').unlink();raise RuntimeError('Roblox presence requested reconnect after stalled activity')
                if any(USER.GetAsyncKeyState(k)&0x8000 for k in (27,120,123)):raise RuntimeError('Stopped by Escape/F9/F12')
                if not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd) or win32gui.GetForegroundWindow()!=hwnd:raise RuntimeError('Roblox lost focus; all inputs released')
                if rectangle(hwnd)!=rect:raise RuntimeError('Roblox moved or resized; recalibration required')
                roi=np.array(sct.grab({'left':rect[0]+1850,'top':rect[1]+400,'width':140,'height':600}))[:,:,:3]
                d=detect(roi)
                if d is None and stage!='tracking' and now-last_gui_scan>5:
                    gui=np.array(sct.grab({'left':rect[0]+760,'top':rect[1]+410,'width':1040,'height':580}))[:,:,:3]
                    raw_gui=read_text(cv2.resize(gui,None,fx=.75,fy=.75)).lower();last_gui_scan=time.monotonic()
                    if any(t in raw_gui for t in ('disconnected','connection lost','connection error','failed to connect','same account launched','error code','reconnect')):
                        inp.release();event('disconnect_gui',text=raw_gui);raise RuntimeError('Disconnect GUI detected; rejoin required')
                if d is not None:
                    last_game_activity=time.time()
                    if stage!='tracking':
                        inp.grab(False);stage='tracking';since=now;prev=None;velocity=0;target_velocity=0;missing_casts=0
                        fresh_hook=casts!=last_tracking_cast
                        if fresh_hook:cycles+=1;last_tracking_cast=casts
                        event('minigame' if fresh_hook else 'tracking_reacquired',cycle=cycles,cast=casts);screenshot('start');prompt_seen=False;pickup_tries=0
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
                        frame=np.array(sct.grab({'left':rect[0],'top':rect[1],'width':2560,'height':1440}))[:,:,:3]
                        rod=locate_rod(frame);last_rod_check=now
                        if rod and not rod['equipped']:
                            inp.release();move_pointer(rect[0]+rod['x'],rect[1]+rod['y'])
                            # Recheck focus immediately before each injected button action.
                            if win32gui.GetForegroundWindow()!=hwnd:raise RuntimeError('Roblox lost focus; all inputs released')
                            inp.hold(True);time.sleep(.15);inp.hold(False)
                            event('rod_equipped',method='visible hotbar');stage='equipping';since=time.monotonic();continue
                    if casts==0 or now-since<.06:
                        inp.hold(True)
                    if now-since>=.14:
                        inp.hold(False);casts+=1;event('cast',cast=casts);stage='waiting';since=now
                elif stage=='equipping':
                    if now-since>.65:
                        move_pointer(rect[0]+1650,rect[1]+800);stage='casting';since=now
                elif stage=='waiting':
                    if now-since>30:
                        missing_casts+=1;event('no_minigame',count=missing_casts);screenshot('missing')
                        if missing_casts>=3:raise RuntimeError('Three casts without a recognized minigame')
                        stage='pickup_wait';since=now
                elif stage=='pickup_wait':
                    if now-since>.4 and now-last_pickup_scan>.35:
                        raw=pickup_text();check_pickup_position(raw);last_pickup_scan=time.monotonic();prompt_seen=is_pickup_prompt(raw)
                        if prompt_seen or now-since>3:
                            inp.grab(True);stage='pickup';since=time.monotonic();pickup_tries+=1;screenshot('pickup');event('pickup_hold',attempt=pickup_tries,prompt_seen=prompt_seen,text=raw)
                elif stage=='pickup':
                    if now-since>.3 and now-last_pickup_scan>.3:
                        raw=pickup_text();check_pickup_position(raw);last_pickup_scan=time.monotonic()
                        if now-since>1.8 and is_reward_banner(raw):
                            inp.grab(False);pickup_confirmed+=1;last_reward=raw;event('reward_observed',cycle=cycles,text=raw);screenshot('collected');stage='cooldown';since=time.monotonic();continue
                    if now-since>4.0:
                        inp.grab(False);raw=pickup_text();check_pickup_position(raw);screenshot('after-pickup')
                        if is_pickup_prompt(raw) or (not raw and pickup_tries<2):stage='pickup_retry_wait'
                        else:
                            if is_reward_banner(raw):pickup_confirmed+=1;last_reward=raw;event('reward_observed',cycle=cycles,text=raw)
                            stage='cooldown';event('pickup_attempted',cycle=cycles,attempts=pickup_tries)
                        since=time.monotonic()
                elif stage=='pickup_retry_wait':
                    if now-since>.5:
                        if pickup_tries>=3:raise RuntimeError('Pickup prompt still present after three held-T attempts')
                        inp.grab(True);stage='pickup';since=now;pickup_tries+=1
                elif stage=='cooldown':
                    if now-since>1.0:stage='casting';since=now
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
