"""Observed Project Slayers 2 menu recovery, using visible UI and ordinary input."""
import json, os, re, subprocess, sys, time
import ctypes
from pathlib import Path
import cv2, mss, numpy as np, psutil, win32gui, win32process
from rapidocr_onnxruntime import RapidOCR
from pynput.keyboard import Listener, Key
from fishing_assistant import ROOT, RUN, USER, Input, find_window, rectangle,move_pointer
from metrics import new_run, write as write_metrics
import presence_watch
from app_config import load_config
from rod_detector import locate_rod
from screen_space import ScreenSpace
from recovery_pacing import MenuPacer, private_join_target
from faults import FaultRecorder, FishingFault, RecoveryPolicy, reason_code
from performance import PerformanceRecorder
from metrics import read as read_metrics
import landmarks
from full_pause import InputGate, InputPaused, F8Toggle, PAUSE_FILE

LAUNCH_URL='roblox://placeId='+str(load_config()['place_id'])


def confirm_menu_button_visible(im):
    """Recognize the green confirm button when dimmed inventory hides OCR text."""
    if not isinstance(im,np.ndarray) or im.shape[:2]!=(1440,2560):return False
    button=im[779:815,1140:1277]
    pixels=((button[:,:,1]>75)
            &(button[:,:,1]>button[:,:,2].astype(np.float32)*1.5)
            &(button[:,:,1]>button[:,:,0].astype(np.float32)*1.1))
    return int(np.count_nonzero(pixels))>400

class UserStop(Exception):pass
class RecoveryError(Exception):pass

class Recovery:
    def __init__(self):
        self.inp=Input();self.hwnd=None;self.rect=None;self.ocr=RapidOCR();self.sct=mss.MSS();self.shots=0
        self.inp.gate=InputGate(self.inp,RUN,USER);self.inp.gate.start()
        self.stop=RUN/'STOP';self.log=RUN/'recovery.jsonl';self.last_action='';self.last_action_at=0;self.restarts=0;self.progress=lambda **kw:None
        self.diagnostics=FaultRecorder(RUN,'recovery-'+time.strftime('%Y%m%d-%H%M%S'))
    def event(self,event,**kw):
        row={'at':time.time(),'event':event,**kw}
        with self.log.open('a') as f:f.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)
    def check_stop(self):
        if any(USER.GetAsyncKeyState(k)&0x8000 for k in (27,120,123)) and not self.stop.exists():
            self.stop.write_text('Stopped by physical hotkey')
        if self.stop.exists():
            self.inp.release();raise UserStop('Stopped by user')
    def select(self,focus=False):
        self.check_stop();self.hwnd=find_window()
        self.inp.hwnd=self.hwnd
        if focus and not (RUN/PAUSE_FILE).exists():
            if win32gui.IsIconic(self.hwnd):win32gui.ShowWindow(self.hwnd,9)
            try:
                if win32gui.GetForegroundWindow()!=self.hwnd:win32gui.SetForegroundWindow(self.hwnd)
            except win32gui.error:pass  # Windows may refuse background focus; guard waits safely.
            self.sleep(.4,focus=False)
        if win32gui.IsIconic(self.hwnd):raise RecoveryError('Roblox lost focus')
        self.rect=rectangle(self.hwnd)
        try:self.screen=ScreenSpace(self.rect)
        except ValueError as error:raise RecoveryError('Roblox window needs adjustment: '+str(error))
    def guard(self):
        self.check_stop()
        self.inp.gate.check()
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):raise RecoveryError('Roblox window closed')
        if win32gui.GetForegroundWindow()!=self.hwnd:raise RecoveryError('Roblox lost focus')
        if win32gui.IsIconic(self.hwnd):raise RecoveryError('Roblox lost focus')
        if rectangle(self.hwnd)!=self.rect:raise RecoveryError('Roblox window changed')
    def sleep(self,seconds,focus=True):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            if (RUN/PAUSE_FILE).exists():
                if focus:raise InputPaused('paused_manual')
                paused_at=time.monotonic()
                while (RUN/PAUSE_FILE).exists():
                    self.check_stop();self.inp.release();self.progress(detail='paused_manual');time.sleep(.1)
                until+=time.monotonic()-paused_at
            self.guard() if focus else self.check_stop();time.sleep(.025)
    def move(self,x,y):
        self.guard()
        try:move_pointer(*self.screen.point(x,y))
        except RuntimeError as error:
            if reason_code(str(error))!='focus':raise
            self.inp.gate.interrupted.set();raise InputPaused('paused_focus') from error
    def click(self,x,y,hold=.18):
        self.move(x,y);self.sleep(.30);self.move(x+1,y);self.sleep(.15);self.move(x,y);self.sleep(.30)
        self.inp.hold(True)
        try:self.sleep(hold)
        finally:self.inp.hold(False)
    def key(self,k,seconds=.2):
        self.guard();scan=USER.MapVirtualKeyW(ord(k.upper()),0)
        USER.keybd_event(ord(k.upper()),scan,0,0)
        try:self.sleep(seconds)
        finally:USER.keybd_event(ord(k.upper()),scan,2,0)
    def capture(self,tag=None):
        self.guard();im=self.screen.capture(self.sct)
        if tag:
            self.diagnostics.observe(im,tag)
            self.shots+=1;cv2.imwrite(str(RUN/f'recovery-{self.shots%20:02d}-{tag}.jpg'),im,[cv2.IMWRITE_JPEG_QUALITY,87])
            cv2.imwrite(str(RUN/'recovery-latest.jpg'),im,[cv2.IMWRITE_JPEG_QUALITY,85])
        return im
    def text(self,im,box=None):
        if box:
            x,y,w,h=box;im=im[y:y+h,x:x+w];scale=1
        else:x=y=0;im=cv2.resize(im,(1280,720));scale=2
        rows,_=self.ocr(im,use_cls=False)  # Game labels are upright; do not rotate short words.
        return [{'text':r[1],'center':(int(x+np.mean(np.array(r[0])[:,0])*scale),int(y+np.mean(np.array(r[0])[:,1])*scale)),'score':float(r[2])} for r in rows or [] if r[2]>.82]
    @staticmethod
    def world_visible(im):
        hp=im[1400:1422,45:300].astype(int)
        red=np.count_nonzero((hp[:,:,2]>110)&(hp[:,:,2]>hp[:,:,1]*2)&(hp[:,:,2]>hp[:,:,0]*2))
        return red>500
    def launch(self,restart=False):
        self.inp.release();self.check_stop()
        while (RUN/PAUSE_FILE).exists():self.sleep(.1,focus=False)
        if self.restarts>=3:raise RecoveryError('Three game restart attempts failed')
        if restart and self.hwnd and win32gui.IsWindow(self.hwnd):
            # Restart only the selected Roblox game client, as requested.
            pid=win32process.GetWindowThreadProcessId(self.hwnd)[1]
            proc=psutil.Process(pid)
            if proc.name().lower()!='robloxplayerbeta.exe':raise RecoveryError('Refused to restart an unrelated process')
            proc.terminate()
            try:proc.wait(8)
            except psutil.TimeoutExpired:raise RecoveryError('Roblox did not close for restart')
        self.restarts+=1;self.event('launching_game',attempt=self.restarts)
        os.startfile(LAUNCH_URL);deadline=time.monotonic()+100
        while time.monotonic()<deadline:
            self.sleep(1,focus=False)
            try:self.select(focus=True);return
            except (RuntimeError,RecoveryError):continue
        raise RecoveryError('Roblox did not open within 100 seconds')
    def equip_rod(self):
        config=load_config()
        cast_x, cast_y = config['cast_point']
        self.move(cast_x,cast_y);self.sleep(.3)
        rod=locate_rod(self.capture()) if config['auto_rod'] else None
        if rod and rod['equipped']:
            self.event('rod_already_equipped',score=rod['score'])
        elif rod:
            self.click(rod['x'],rod['y']);self.sleep(.6)
            self.event('rod_equipped',method='visible hotbar',score=rod['score'])
        else:
            self.key(str(config['rod_slot']));self.sleep(.6)
            self.event('rod_equipped',method='configured slot',slot=config['rod_slot'])
        # Refresh Roblox's hover target after leaving the hotbar. The OS cursor
        # can arrive before the game's hit test; otherwise the first cast may
        # toggle the rod off and spend a full bite timeout waiting for nothing.
        for point,delay in (((cast_x,cast_y),.30),((cast_x+1,cast_y),.15),((cast_x,cast_y),.30)):
            self.move(*point);self.sleep(delay)
    def hold_private_join(self,target):
        # The friend-Join button animates into a larger private-Join button.
        # Revalidate after hover settles so an old center cannot dismiss it.
        x,y=target
        # The game's rendered cursor can obscure JOIN and make OCR read Nior.
        # Settle inside the blue button, away from its central label.
        self.move(x+65,y+12);self.sleep(.30);self.move(x+66,y+12);self.sleep(.15);self.move(x+65,y+12);self.sleep(.30)
        rows=self.text(self.capture(),(820,1190,920,250))
        current=private_join_target(rows)
        self.guard()
        if current is None or np.linalg.norm(np.array(current)-target)>10:
            self.event('private_join_retry',reason='Join button moved; waiting for a stable target')
            return False
        self.event('hold_private_join',target=list(current));started=time.monotonic();reason='hold limit'
        until=started+4.5
        self.inp.hold(True)
        try:
            while time.monotonic()<until:
                self.sleep(min(.2,until-time.monotonic()))
                if time.monotonic()>=until:break
                rows=self.text(self.capture(),(820,1190,920,250))
                self.guard()
                current=private_join_target(rows)
                if current is None:
                    reason='Join panel changed';break
                if np.linalg.norm(np.array(current)-target)>12:
                    reason='Join button moved';break
        finally:self.inp.hold(False)
        self.event('private_join_released',seconds=round(time.monotonic()-started,2),reason=reason)
        return True
    def recover(self,force_menu=False):
        self.inp.release();self.event('recovery_started',force_menu=force_menu)
        try:self.select()
        except RuntimeError:self.launch()
        deadline=time.monotonic()+180;pacer=MenuPacer();join_attempts=0;last_class=''
        while time.monotonic()<deadline:
            self.guard();self.progress(detail=last_class or 'inspecting');im=self.capture()
            rows=self.text(im);text=' '.join(r['text'].lower() for r in rows)
            self.guard();now=time.monotonic();target=None
            skip=[r for r in rows if re.sub(r'[^a-z]','',r['text'].lower())=='skiploading']
            cancel=[r for r in rows if r['text'].strip().lower()=='cancel']
            if any(term in text for term in ['disconnected','connection lost','connection error','failed to connect','same account launched','error code:']):
                kind='disconnect'
                reconnect=[r for r in rows if re.fullmatch(r'(reconnect|rejoin|retry)',r['text'].strip(),re.I)]
                target=reconnect[0]['center'] if len(reconnect)==1 else None
            elif skip:kind='skip_loading';target=skip[0]['center']
            elif 'purchase' in text and len(cancel)==1:kind='vendor_dialog';target=cancel[0]['center']
            elif confirm_menu_button_visible(im) or 'go back to the main menu' in text:
                kind='confirm_menu';target=(1208,797)
            elif 'back to main menu' in text:
                kind='game_menu';target=next(r['center'] for r in rows if 'back to main menu' in r['text'].lower())
            elif ('privateserver' in re.sub(r'[^a-z]','',text) and 'join' in text):
                kind='private_join'
                # Full-screen downsampling can turn JOIN into J0IN. Read the
                # observed panel at native vision scale before deciding input.
                target=private_join_target(self.text(im,(820,1190,920,250)))
            elif any('ouwlan' in r['text'].lower() for r in rows) and 'last played' in text:
                kind='world_selection';target=(520,680)
            elif any(r['text'].strip().lower()=='play' for r in rows):
                kind='main_menu';target=next(r['center'] for r in rows if r['text'].strip().lower()=='play')
            elif self.world_visible(im) and ('mistfall' in text.replace(' ','') or re.search(r'lv\.?\s*\d+',text)):
                kind='world'
            else:kind='loading'
            pacer.observe(kind,target,now)
            if kind!=last_class:self.event('screen',kind=kind);last_class=kind
            if kind=='disconnect' and pacer.ready(kind,now):
                self.capture(kind);self.event('disconnect_observed',text=text[:600])
                if target:
                    self.click(*target);pacer.acted(kind,time.monotonic(),18)
                else:
                    self.launch(restart=True);pacer.acted(kind,time.monotonic(),12);deadline=time.monotonic()+180
            elif kind=='world':
                if force_menu:
                    if pacer.ready('open_menu',now):
                        self.capture('before-menu');self.key('M');pacer.acted('open_menu',time.monotonic(),2);self.event('open_menu')
                elif pacer.ready('world_ready',now,stable_seconds=3):
                    self.equip_rod();self.capture('equipped');self.event('equipped_rod');self.restarts=0;return
            elif kind=='private_join' and pacer.ready(kind,now):
                if target is None:
                    self.event('private_join_retry',reason='Waiting for an unambiguous private Join button')
                    self.move(1630,1120)
                    pacer.acted(kind,now,3)
                    self.sleep(.25);continue
                self.capture(kind)
                if self.hold_private_join(target):
                    join_attempts+=1;pacer.joined(time.monotonic(),join_attempts);force_menu=False
            elif target is not None and kind!='disconnect' and pacer.ready(kind,now):
                self.capture(kind);self.click(*target)
                action,delay={'skip_loading':('skip_optional_loading',8),'vendor_dialog':('closed_vendor_dialog',1),
                    'confirm_menu':('confirm_menu',4),'game_menu':('back_to_main_menu',1),
                    'world_selection':('select_ouwland',1),'main_menu':('play',1)}[kind]
                self.event(action);pacer.acted(kind,time.monotonic(),delay)
                if kind=='vendor_dialog':force_menu=True
                elif kind in ('confirm_menu','main_menu'):force_menu=False
            self.sleep(.25)
        self.capture('timeout');raise RecoveryError('Rejoin did not reach the game within three minutes')

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=0);parser.add_argument('--rejoin',action='store_true');parser.add_argument('--focus',action='store_true');parser.add_argument('--restart',action='store_true');parser.add_argument('--bait-stock',type=int,default=-1);parser.add_argument('--resume-counters',action='store_true');parser.add_argument('--respect-stop',action='store_true');a=parser.parse_args()
    RUN.mkdir(parents=True,exist_ok=True)
    lock=RUN/'supervisor-pid.json'
    if lock.exists():
        prior=json.loads(lock.read_text())
        if psutil.pid_exists(prior['pid']) and abs(psutil.Process(prior['pid']).create_time()-prior['created'])<1:raise RuntimeError('Fishing supervisor already running')
    lock.write_text(json.dumps({'pid':os.getpid(),'created':psutil.Process().create_time()}))
    stop=RUN/'STOP'
    if stop.exists():
        if a.respect_stop:raise UserStop('Start cancelled by stop request')
        stop.unlink()
    (RUN/'PAUSE').unlink(missing_ok=True)
    (RUN/'RECOVER').unlink(missing_ok=True)
    if not a.resume_counters:
        new_run()
        write_metrics('bait.json',{'starting_stock':a.bait_stock if a.bait_stock>=0 else None,'bait_per_hook':1,'note':'One bait per hook. Fishing continues without bait.'})
    driver=Recovery();deadline=time.monotonic()+a.seconds if a.seconds>0 else float('inf');recoveries=0;last_error='';child=None;exit_code=0;started=time.time()
    policy=RecoveryPolicy();performance=PerformanceRecorder(read_metrics('totals.json').get('started'))
    # Temporary: restored when this process exits. No persistent Windows setting is changed.
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)
    def paused_changed(paused):
        driver.inp.gate.poll()
        driver.event('f8_paused' if paused else 'f8_resumed')
    toggle=F8Toggle(RUN,lambda:driver.hwnd,paused_changed)
    def emergency_key(key):
        if key==Key.f8:toggle.press()
        if key in (Key.esc,Key.f9,Key.f12):stop.write_text('Stopped by physical hotkey')
    def released_key(key):
        if key==Key.f8:toggle.release()
    listener=Listener(on_press=emergency_key,on_release=released_key);listener.start()
    presence_stop=presence_watch.start()
    def status(stage,**kw):
        if (RUN/PAUSE_FILE).exists():stage='paused_manual'
        performance.tick(stage,read_metrics('status.json'),read_metrics('totals.json'))
        write_metrics('supervisor.json',{'running':True,'pid':os.getpid(),'updated':time.time(),'started':started,'stage':stage,'mode':'full','manual_paused':(RUN/PAUSE_FILE).exists(),'recoveries':max(0,recoveries-1),'last_error':last_error,'runs_until_stopped':a.seconds<=0,**kw})
    driver.progress=lambda **kw:status('recovering',**kw)
    try:
        try:driver.select(focus=a.focus and not (RUN/PAUSE_FILE).exists())
        except RuntimeError:driver.launch()
        if a.restart:driver.launch(restart=True)
        force=a.rejoin
        while time.monotonic()<deadline:
            while driver.inp.gate.reason() or not driver.inp.gate.acknowledge():
                driver.check_stop();driver.inp.release();status(driver.inp.gate.reason() or 'paused_focus');time.sleep(.1)
                if time.monotonic()>=deadline:break
            if time.monotonic()>=deadline:break
            status('recovering')
            try:
                driver.recover(force_menu=force)
                landmarks.align(driver)
            except InputPaused:
                driver.inp.release();force=False;continue
            except (RecoveryError,FishingFault) as ex:
                driver.inp.release();last_error=str(ex);driver.event('recovery_retry',reason=last_error)
                if 'lost focus' in last_error and driver.hwnd and win32gui.IsWindow(driver.hwnd):
                    while win32gui.GetForegroundWindow()!=driver.hwnd and time.monotonic()<deadline:
                        driver.check_stop();status('paused_focus');time.sleep(.3)
                    force=False
                    continue
                if 'window changed' in last_error:
                    # Reconnect can move the same full-screen client to another monitor.
                    # Release input, discard old coordinates, and validate the window again.
                    driver.event('window_reacquiring',reason=last_error)
                    driver.sleep(1,focus=False)
                    driver.select()
                    continue
                if 'window needs' in last_error:raise
                code=getattr(ex,'code',reason_code(last_error))
                driver.diagnostics.save(code,last_error,**getattr(ex,'details',{}))
                if code=='alignment':
                    # A local reference must never make the bot wander or enter
                    # a relaunch storm. Rejoin once, then wait for adjustment.
                    if force:raise
                    force=True;continue
                status('restarting')
                try:driver.launch(restart=bool(driver.hwnd and win32gui.IsWindow(driver.hwnd)))
                except (RuntimeError,RecoveryError) as restart_error:
                    last_error=str(restart_error);driver.event('restart_backoff',reason=last_error);status('retry_wait')
                    driver.sleep(60,focus=False);driver.restarts=0
                force=False;continue
            recoveries+=1;force=True
            if time.monotonic()>=deadline:break
            remaining=max(1,int(deadline-time.monotonic())) if a.seconds>0 else 0;status('fishing');worker_started=time.time()
            with open(RUN/'worker-stdout.log','a') as stdout,open(RUN/'worker-stderr.log','a') as stderr:
                child=subprocess.Popen([sys.executable,str(ROOT/'fishing_assistant.py'),'--seconds',str(remaining)],stdout=stdout,stderr=stderr)
            while child.poll() is None:
                driver.check_stop()
                worker=read_metrics('status.json')
                stage='paused_manual' if (RUN/PAUSE_FILE).exists() else 'paused_focus' if worker.get('updated',0)>=worker_started and worker.get('stage')=='paused_focus' else 'fishing'
                status(stage,worker_pid=child.pid);time.sleep(.1)
            child=None
            child_status=json.loads((RUN/'status.json').read_text())
            if child_status.get('updated',0)<worker_started:raise RecoveryError('Fishing worker failed before reporting its state; inspect worker-stderr.log')
            reason=child_status.get('reason','Unknown worker exit');last_error=reason;driver.event('worker_exit',reason=reason)
            if reason.startswith('Stopped by'):raise UserStop(reason)
            if reason=='session_limit':break
            if reason.startswith('Pickup prompt still present'):
                driver.event('pickup_exhausted_rejoining',reason=reason)
            code=child_status.get('failure_code') or reason_code(reason)
            action=policy.choose(code,time.monotonic(),landmarks.profile() is not None)
            driver.event('recovery_decision',code=code,action=action)
            if action=='local':
                force=False;driver.event('local_repair',reason=reason)
            elif action=='wait_focus' and win32gui.IsWindow(driver.hwnd):
                driver.event('paused_focus')
                while win32gui.GetForegroundWindow()!=driver.hwnd and time.monotonic()<deadline:
                    driver.check_stop();status('paused_focus');time.sleep(.3)
                force=False
            driver.sleep(1,focus=False)
    except BaseException as ex:
        last_error=str(ex);exit_code=0 if isinstance(ex,UserStop) else 1;driver.event('supervisor_stopped',reason=last_error)
        if not isinstance(ex,UserStop):
            try:
                try:driver.capture('failure')
                except (RuntimeError,RecoveryError,UserStop):pass
                driver.diagnostics.save(getattr(ex,'code',reason_code(last_error)),last_error,**getattr(ex,'details',{}))
            except Exception as diagnostic_error:driver.event('diagnostic_error',message=str(diagnostic_error))
    finally:
        if child and child.poll() is None:
            try:
                with stop.open('x') as stream:stream.write('Supervisor stopped')
            except FileExistsError:pass  # A user or maintenance stop keeps its reason.
            try:child.wait(5)
            except subprocess.TimeoutExpired:
                # The venv launcher may have a real Python worker beneath it.
                try:
                    parent=psutil.Process(child.pid)
                    for process in reversed(parent.children(recursive=True)):
                        try:process.terminate()
                        except psutil.NoSuchProcess:pass
                    parent.terminate()
                except psutil.NoSuchProcess:pass
                USER.mouse_event(4,0,0,0,0);USER.keybd_event(ord('T'),USER.MapVirtualKeyW(ord('T'),0),2,0)
        driver.inp.gate.close()
        listener.stop()
        presence_stop.set()
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        (RUN/'supervisor.json').write_text(json.dumps({'running':False,'pid':os.getpid(),'updated':time.time(),'started':started,'stage':'stopped','recoveries':max(0,recoveries-1),'reason':last_error or 'session_limit'},indent=2))
    return exit_code

if __name__=='__main__':sys.exit(main())
