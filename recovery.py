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

LAUNCH_URL='roblox://placeId='+str(load_config()['place_id'])

class UserStop(Exception):pass
class RecoveryError(Exception):pass

class Recovery:
    def __init__(self):
        self.inp=Input();self.hwnd=None;self.rect=None;self.ocr=RapidOCR();self.sct=mss.MSS();self.shots=0
        self.stop=RUN/'STOP';self.log=RUN/'recovery.jsonl';self.last_action='';self.last_action_at=0;self.restarts=0;self.progress=lambda **kw:None
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
        if focus:
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
        if not self.hwnd or not win32gui.IsWindow(self.hwnd):raise RecoveryError('Roblox window closed')
        if win32gui.GetForegroundWindow()!=self.hwnd:raise RecoveryError('Roblox lost focus')
        if win32gui.IsIconic(self.hwnd):raise RecoveryError('Roblox lost focus')
        if rectangle(self.hwnd)!=self.rect:raise RecoveryError('Roblox window changed')
    def sleep(self,seconds,focus=True):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            self.guard() if focus else self.check_stop();time.sleep(.025)
    def move(self,x,y):
        self.guard();move_pointer(*self.screen.point(x,y))
    def click(self,x,y,hold=.18):
        self.move(x,y);self.sleep(.18);self.move(x+1,y);self.sleep(.08);self.move(x,y);self.sleep(.16)
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
            self.shots+=1;cv2.imwrite(str(RUN/f'recovery-{self.shots%20:02d}-{tag}.jpg'),im,[cv2.IMWRITE_JPEG_QUALITY,87])
            cv2.imwrite(str(RUN/'recovery-latest.jpg'),im,[cv2.IMWRITE_JPEG_QUALITY,85])
        return im
    def text(self,im,box=None):
        if box:
            x,y,w,h=box;im=im[y:y+h,x:x+w];scale=1
        else:x=y=0;im=cv2.resize(im,(1280,720));scale=2
        rows,_=self.ocr(im)
        return [{'text':r[1],'center':(int(x+np.mean(np.array(r[0])[:,0])*scale),int(y+np.mean(np.array(r[0])[:,1])*scale)),'score':float(r[2])} for r in rows or [] if r[2]>.82]
    @staticmethod
    def world_visible(im):
        hp=im[1400:1422,45:300].astype(int)
        red=np.count_nonzero((hp[:,:,2]>110)&(hp[:,:,2]>hp[:,:,1]*2)&(hp[:,:,2]>hp[:,:,0]*2))
        return red>500
    def launch(self,restart=False):
        self.inp.release();self.check_stop()
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
        self.move(1650,800);self.sleep(.3)
        rod=locate_rod(self.capture()) if config['auto_rod'] else None
        if rod and rod['equipped']:
            self.event('rod_already_equipped',score=rod['score'])
        elif rod:
            self.click(rod['x'],rod['y']);self.sleep(.6)
            self.event('rod_equipped',method='visible hotbar',score=rod['score'])
        else:
            self.key(str(config['rod_slot']));self.sleep(.6)
            self.event('rod_equipped',method='configured slot',slot=config['rod_slot'])
        self.move(1650,800);self.sleep(.35)
    def recover(self,force_menu=False):
        self.inp.release();self.event('recovery_started',force_menu=force_menu)
        try:self.select()
        except RuntimeError:self.launch()
        deadline=time.monotonic()+180;next_action=0;world_since=None;menu_sent=False;join_started=False;last_class=''
        while time.monotonic()<deadline:
            self.guard();self.progress(detail=last_class or 'inspecting');im=self.capture();now=time.monotonic()
            rows=self.text(im);text=' '.join(r['text'].lower() for r in rows)
            skip=[r for r in rows if re.sub(r'[^a-z]','',r['text'].lower())=='skiploading']
            if skip and now>=next_action:
                self.click(*skip[0]['center']);self.event('skip_optional_loading')
                next_action=time.monotonic()+8;self.sleep(.4);continue
            if any(term in text for term in ['disconnected','connection lost','connection error','failed to connect','same account launched','error code:']):
                self.capture('disconnect');self.event('disconnect_observed',text=text[:600])
                reconnect=[r for r in rows if re.fullmatch(r'(reconnect|rejoin|retry)',r['text'].strip(),re.I)]
                if reconnect and now>=next_action:
                    self.click(*reconnect[0]['center']);next_action=now+18;self.sleep(2);continue
                if now>=next_action:self.launch(restart=True);next_action=time.monotonic()+12;deadline=time.monotonic()+180
                self.sleep(1);continue
            cancel=[r for r in rows if r['text'].strip().lower()=='cancel']
            if 'purchase' in text and len(cancel)==1:
                kind='vendor_dialog'
                if now>=next_action:
                    self.click(*cancel[0]['center']);self.event('closed_vendor_dialog');force_menu=True;next_action=now+1
            elif 'go back to the main menu' in text:
                kind='confirm_menu'
                if now>=next_action:self.capture(kind);self.click(1208,797);next_action=now+4;self.event(kind);force_menu=False;world_since=None
            elif 'back to main menu' in text:
                kind='game_menu'
                if now>=next_action:
                    target=next(r for r in rows if 'back to main menu' in r['text'].lower());self.capture(kind);self.click(*target['center']);next_action=now+1;self.event('back_to_main_menu')
            elif ('private server' in text and 'join' in text):
                kind='private_join'
                if now>=next_action:
                    joins=[r for r in rows if r['text'].strip().lower()=='join']
                    if len(joins)!=1:raise RecoveryError('Private Join button is ambiguous')
                    self.capture(kind);self.event('hold_private_join');self.click(*joins[0]['center'],hold=3.2);next_action=time.monotonic()+15;join_started=True;force_menu=False;world_since=None
            elif any('ouwlan' in r['text'].lower() for r in rows) and 'last played' in text:
                kind='world_selection'
                if now>=next_action:
                    self.capture(kind);self.click(520,680);next_action=now+1;self.event('select_ouwland')
            elif any(r['text'].strip().lower()=='play' for r in rows):
                kind='main_menu'
                if now>=next_action:
                    target=next(r for r in rows if r['text'].strip().lower()=='play');self.capture(kind);self.click(*target['center']);next_action=now+1;self.event('play');world_since=None;force_menu=False
            elif self.world_visible(im) and ('mistfall' in text.replace(' ','') or re.search(r'lv\.?\s*\d+',text)):
                kind='world'
                if force_menu:
                    if now>=next_action:
                        self.capture('before-menu');self.key('M');menu_sent=True;next_action=now+2;self.event('open_menu')
                else:
                    if world_since is None:world_since=now
                    if now-world_since>3:
                        self.equip_rod();self.capture('equipped');self.event('equipped_rod');self.restarts=0;return
            else:
                kind='loading';world_since=None
            if kind!=last_class:self.event('screen',kind=kind);last_class=kind
            self.sleep(.4)
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
    # Temporary: restored when this process exits. No persistent Windows setting is changed.
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)
    def emergency_key(key):
        if key in (Key.esc,Key.f9,Key.f12):stop.write_text('Stopped by physical hotkey')
    listener=Listener(on_press=emergency_key);listener.start()
    presence_stop=presence_watch.start()
    def status(stage,**kw):
        write_metrics('supervisor.json',{'running':True,'pid':os.getpid(),'updated':time.time(),'started':started,'stage':stage,'recoveries':max(0,recoveries-1),'last_error':last_error,'runs_until_stopped':a.seconds<=0,**kw})
    driver.progress=lambda **kw:status('recovering',**kw)
    try:
        try:driver.select(focus=a.focus)
        except RuntimeError:driver.launch()
        if a.restart:driver.launch(restart=True)
        force=a.rejoin
        while time.monotonic()<deadline:
            status('recovering')
            try:driver.recover(force_menu=force)
            except RecoveryError as ex:
                driver.inp.release();last_error=str(ex);driver.event('recovery_retry',reason=last_error)
                if 'lost focus' in last_error and driver.hwnd and win32gui.IsWindow(driver.hwnd):
                    while win32gui.GetForegroundWindow()!=driver.hwnd and time.monotonic()<deadline:
                        driver.check_stop();status('paused_focus');time.sleep(.3)
                    continue
                if 'window changed' in last_error:
                    # Reconnect can move the same full-screen client to another monitor.
                    # Release input, discard old coordinates, and validate the window again.
                    driver.event('window_reacquiring',reason=last_error)
                    driver.sleep(1,focus=False)
                    driver.select()
                    continue
                if 'window needs' in last_error:raise
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
                driver.check_stop();status('fishing',worker_pid=child.pid);time.sleep(.3)
            child=None
            child_status=json.loads((RUN/'status.json').read_text())
            if child_status.get('updated',0)<worker_started:raise RecoveryError('Fishing worker failed before reporting its state; inspect worker-stderr.log')
            reason=child_status.get('reason','Unknown worker exit');last_error=reason;driver.event('worker_exit',reason=reason)
            if reason.startswith('Stopped by'):raise UserStop(reason)
            if reason=='session_limit':break
            if reason.startswith('Pickup prompt still present'):
                driver.event('pickup_exhausted_rejoining',reason=reason)
            if 'lost focus' in reason and win32gui.IsWindow(driver.hwnd):
                driver.event('paused_focus')
                while win32gui.GetForegroundWindow()!=driver.hwnd and time.monotonic()<deadline:
                    driver.check_stop();status('paused_focus');time.sleep(.3)
            driver.sleep(1,focus=False)
    except BaseException as ex:
        last_error=str(ex);exit_code=0 if isinstance(ex,UserStop) else 1;driver.event('supervisor_stopped',reason=last_error)
    finally:
        if child and child.poll() is None:
            stop.write_text('Supervisor stopped')
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
        driver.inp.release()
        listener.stop()
        presence_stop.set()
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        (RUN/'supervisor.json').write_text(json.dumps({'running':False,'pid':os.getpid(),'updated':time.time(),'started':started,'stage':'stopped','recoveries':max(0,recoveries-1),'reason':last_error or 'session_limit'},indent=2))
    return exit_code

if __name__=='__main__':sys.exit(main())
