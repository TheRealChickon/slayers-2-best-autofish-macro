"""Observed Project Slayers 2 menu recovery, using visible UI and ordinary input."""
import json, os, re, subprocess, sys, time
import ctypes
from pathlib import Path
import cv2, mss, numpy as np, psutil, win32gui, win32process
from rapidocr_onnxruntime import RapidOCR
from pynput.keyboard import Listener, Key
from fishing_assistant import CODE, ROOT, RUN, USER, Input, find_window, rectangle,move_pointer
from metrics import new_run, write as write_metrics
import presence_watch
from app_config import load_config,save_config
from rod_detector import locate_rod, selected_rod, unselected_rod
from screen_space import ScreenSpace
from window_fit import fit_window, WindowFitError
from recovery_pacing import MenuPacer, private_join_target,main_menu_target
from faults import FaultRecorder, FishingFault, RecoveryPolicy, reason_code
from performance import PerformanceRecorder
from metrics import read as read_metrics
import landmarks
from title_manager import TitleManager
from discord_service import DiscordReporter
from full_pause import InputGate, InputPaused, F8Toggle, PAUSE_FILE
from fishing_vision import ui_visible
from farm_policy import HereRecovery,startup_rejoin
from capture_session import CaptureSession
from display_repair import DisplayRepair
from rod_recovery import RodRecovery

LAUNCH_URL='roblox://placeId='+str(load_config()['place_id'])


def launch_game(url,known_exe=None):
    try:os.startfile(url);return
    except OSError:
        # Updates can leave the per-user URI association pointing at a
        # removed version. Use the already installed/running Player executable
        # directly; do not edit Windows associations or account credentials.
        if not known_exe or not Path(known_exe).is_file():
            for p in psutil.process_iter(['name','exe']):
                if (p.info.get('name') or '').lower()=='robloxplayerbeta.exe' and p.info.get('exe'):
                    known_exe=p.info['exe'];break
        if not known_exe or not Path(known_exe).is_file():raise RecoveryError('Roblox Player launcher unavailable; user action required')
        subprocess.Popen([known_exe,url],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def confirm_menu_target(im):
    """Find the adjacent green check and red cancel in the central dialog."""
    if not isinstance(im,np.ndarray) or im.shape[:2]!=(1440,2560):return None
    left,top=1000,550
    crop=im[top:1000,left:1500].astype(np.float32)
    green=(crop[:,:,1]>75)&(crop[:,:,1]>crop[:,:,2]*1.5)&(crop[:,:,1]>crop[:,:,0]*1.1)
    red=(crop[:,:,2]>75)&(crop[:,:,2]>crop[:,:,1]*1.5)&(crop[:,:,2]>crop[:,:,0]*1.1)
    def buttons(mask):
        mask=cv2.morphologyEx(mask.astype(np.uint8)*255,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
        _,_,stats,centers=cv2.connectedComponentsWithStats(mask)
        return [(center,w,h) for i,((x,y,w,h,area),center) in enumerate(zip(stats,centers))
                if i and area>800 and 80<=w<=200 and 20<=h<=80]
    pairs=[g[0] for g in buttons(green) for r in buttons(red)
           if 90<r[0][0]-g[0][0]<220 and abs(r[0][1]-g[0][1])<12
           and abs(g[1]-r[1])<40 and abs(g[2]-r[2])<20]
    if len(pairs)!=1:return None
    center=pairs[0]
    return int(round(center[0]+left)),int(round(center[1]+top))


def confirm_menu_button_visible(im):
    return confirm_menu_target(im) is not None

class UserStop(Exception):pass
class RecoveryError(Exception):pass

class Recovery:
    def __init__(self):
        self.inp=Input();self.hwnd=None;self.rect=None;self.ocr=RapidOCR();self.sct=CaptureSession(self.event);self.shots=0
        self.inp.gate=InputGate(self.inp,RUN,USER);self.inp.gate.start()
        self.stop=RUN/'STOP';self.log=RUN/'recovery.jsonl';self.last_action='';self.last_action_at=0;self.restarts=0;self.progress=lambda **kw:None
        self.diagnostics=FaultRecorder(RUN,'recovery-'+time.strftime('%Y%m%d-%H%M%S'))
        self.last_screen_kind=''
        self.exit_template=cv2.imread(str(ROOT/'assets'/'exit.png'))
    def event(self,event,**kw):
        row={'at':time.time(),'event':event,**kw}
        with self.log.open('a') as f:f.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)
    def check_stop(self):
        # The physical-only hotkey listener owns this request. Async key state
        # also includes keys injected by unrelated automation.
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
        # Fullscreen/menu transitions can report a transient client shape.
        # Wait for a valid, stable rectangle with input released.
        self.inp.release();last_rect=None;stable=0;invalid=0;maximized=False;fitted=False;until=time.monotonic()+8
        while time.monotonic()<until:
            self.progress(detail='window_transition')
            self.check_stop();rect=rectangle(self.hwnd)
            try:screen=ScreenSpace(rect)
            except ValueError as error:
                invalid+=1
                allowed=(win32gui.GetForegroundWindow()==self.hwnd
                         and not any((RUN/name).exists() for name in ('STOP','PAUSE','F8_PAUSE')))
                if invalid>=5 and not maximized and allowed:
                    # Roblox may return to its default square window after a
                    # presentation reset. Maximize this exact Player window
                    # rather than launching another client or rejecting 1440p.
                    win32gui.ShowWindow(self.hwnd,3);maximized=True
                    self.event('client_maximized',reason='Restoring a widescreen client after display transition')
                elif invalid>=10 and maximized and not fitted and allowed:
                    # Maximized is not 16:9 on this screen (laptop, 16:10,
                    # ultrawide): size the window to the largest 16:9 client.
                    fitted=True
                    try:fit_window(self.hwnd,event=self.event)
                    except WindowFitError as failure:
                        self.event('client_fit_failed',reason=str(failure),client=str(error))
                stable=0;self.sleep(.2,focus=False);continue
            stable=stable+1 if rect==last_rect else 1;last_rect=rect
            if stable>=3:
                self.rect=rect;self.screen=screen
                self.event('client_ready',width=screen.actual_width,height=screen.actual_height)
                return
            self.sleep(.2,focus=False)
        raise FishingFault('window','Roblox client is still changing; retrying safely',rect=last_rect)
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
        # Menu transitions can warp the OS pointer back to screen centre
        # during the hover delay. Reposition immediately before pressing.
        self.move(x,y)
        self.inp.hold(True)
        try:self.sleep(hold)
        finally:self.inp.hold(False)
    def scroll(self,x,y,notches):
        """Mouse wheel over a menu list; negative notches scroll down."""
        self.move(x,y);self.sleep(.15)
        for _ in range(abs(notches)):
            self.guard();USER.mouse_event(0x0800,0,0,120 if notches>0 else -120,0);self.sleep(.06)
    def key(self,k,seconds=.2):
        self.guard();scan=USER.MapVirtualKeyW(ord(k.upper()),0)
        USER.keybd_event(ord(k.upper()),scan,0,0)
        try:self.sleep(seconds)
        finally:USER.keybd_event(ord(k.upper()),scan,2,0)
    def release_camera_lock(self):
        """Leave Roblox first person before moving the menu pointer."""
        self.inp.gate.acknowledge()
        self.key('M');self.sleep(.35)  # game menu -> world
        for _ in range(16):
            self.guard();USER.mouse_event(0x0800,0,0,-120,0);self.sleep(.035)
        self.sleep(.4)
        self.key('M');self.sleep(.45)  # world -> game menu
        self.move(350,980)
        self.event('camera_cursor_released')
    def refresh_display(self):
        # F11 refreshes the Player's own presentation surface. It does not
        # rejoin, alter Windows settings or issue a monitor power command.
        self.inp.release();self.guard()
        if find_window()!=self.hwnd:raise RecoveryError('Roblox window changed')
        code=0x7A;scan=USER.MapVirtualKeyW(code,0)
        for attempt in range(2):
            self.check_stop();self.inp.gate.check()
            if (RUN/'PAUSE').exists():raise InputPaused('paused_manual')
            self.inp.guard_press(True)
            USER.keybd_event(code,scan,0,0)
            try:self.sleep(.03,focus=False)
            finally:USER.keybd_event(code,scan,2,0)
            self.sleep(.75,focus=False)
        self.sct.reset();self.sleep(1,focus=False);self.select()
        self.event('display_surface_refreshed',width=self.screen.actual_width,height=self.screen.actual_height)
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
        known_exe=None
        if self.hwnd and win32gui.IsWindow(self.hwnd):
            known_exe=psutil.Process(win32process.GetWindowThreadProcessId(self.hwnd)[1]).exe()
        if restart and self.hwnd and win32gui.IsWindow(self.hwnd):
            # Restart only the selected Roblox game client, as requested.
            pid=win32process.GetWindowThreadProcessId(self.hwnd)[1]
            proc=psutil.Process(pid)
            if proc.name().lower()!='robloxplayerbeta.exe':raise RecoveryError('Refused to restart an unrelated process')
            proc.terminate()
            try:proc.wait(8)
            except psutil.TimeoutExpired:raise RecoveryError('Roblox did not close for restart')
        self.restarts+=1;self.event('launching_game',attempt=self.restarts)
        launch_game(LAUNCH_URL,known_exe);deadline=time.monotonic()+100
        while time.monotonic()<deadline:
            self.progress(detail='launching_wait')
            self.sleep(1,focus=False)
            try:self.select(focus=True);return
            except (RuntimeError,RecoveryError):continue
        raise RecoveryError('Roblox did not open within 100 seconds')
    def equip_rod(self):
        config=load_config()
        cast_x, cast_y = config['cast_point']
        self.move(cast_x,cast_y);self.sleep(.3)
        rod=locate_rod(self.capture()) if config['auto_rod'] else None
        fallback=False
        if selected_rod(rod):
            self.event('rod_already_equipped',score=rod['score'])
        elif unselected_rod(rod):
            self.click(rod['x'],rod['y']);self.sleep(.6)
            self.event('rod_selection_attempt',method='visible hotbar',score=rod['score'])
        else:
            self.key(str(config['rod_slot']));self.sleep(.6);fallback=True
            self.event('rod_selection_attempt',method='configured slot',slot=config['rod_slot'])
        if config['auto_rod']:
            observed=locate_rod(self.capture())
            if fallback and unselected_rod(observed):
                # The fallback can toggle an already-selected rod OFF. A
                # positive unselected icon permits one corrective toggle.
                self.key(str(config['rod_slot']));self.sleep(.6)
                self.event('rod_toggle_corrected',slot=config['rod_slot'])
                observed=locate_rod(self.capture())
            for _ in range(2):
                if selected_rod(observed):break
                self.sleep(.25);observed=locate_rod(self.capture())
            if not selected_rod(observed):
                raise FishingFault('rod_unreadable','Rod selection could not be verified; no casting input sent')
            self.event('rod_selection_verified',score=observed['score'])
        else:
            self.event('rod_selection_unverified',method='configured slot',slot=config['rod_slot'])
        # Refresh Roblox's hover target after leaving the hotbar. The OS cursor
        # can arrive before the game's hit test; otherwise the first cast may
        # toggle the rod off and spend a full bite timeout waiting for nothing.
        for point,delay in (((cast_x,cast_y),.30),((cast_x+1,cast_y),.15),((cast_x,cast_y),.30)):
            self.move(*point);self.sleep(delay)
    def backstep_after_join(self,joined):
        # This local setting is for saved spawns at a water edge. Only move
        # after a confirmed Join, never during a rod-only repair or on focus
        # return. key() rechecks focus/pause and always releases S.
        seconds=load_config()['spawn_backstep_seconds']
        if not joined or seconds<=0:return
        self.event('spawn_backstep',seconds=seconds)
        self.key('S',seconds);self.sleep(.5)
        self.capture('after-backstep')
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
    def recover(self,force_menu=False,equip_rod=True,allow_rejoin=True,prefer_current=False):
        self.inp.release();self.event('recovery_started',force_menu=force_menu)
        try:self.select()
        except RuntimeError as error:
            if getattr(error,'code',reason_code(str(error))) not in ('client_lost','disconnect'):raise
            self.launch()
        deadline=time.monotonic()+180;pacer=MenuPacer();join_attempts=0;last_class='';joined_world=False
        while time.monotonic()<deadline:
            self.guard();self.progress(detail=last_class or 'inspecting');im=self.capture()
            rows=self.text(im);text=' '.join(r['text'].lower() for r in rows)
            play_target=main_menu_target(rows)
            confirm_target=confirm_menu_target(im)
            self.guard();now=time.monotonic();target=None
            skip=[r for r in rows if re.sub(r'[^a-z]','',r['text'].lower())=='skiploading']
            cancel=[r for r in rows if r['text'].strip().lower()=='cancel']
            if any(term in text for term in ('banned','captcha','security challenge','verify you are human')):
                raise FishingFault('user_required','Roblox requires user action; automatic recovery suspended')
            if any(term in text for term in ['disconnected','connection lost','connection error','failed to connect','same account launched','error code:']):
                kind='disconnect'
                reconnect=[r for r in rows if re.fullmatch(r'(reconnect|rejoin|retry)',r['text'].strip(),re.I)]
                target=reconnect[0]['center'] if len(reconnect)==1 else None
            elif isinstance(im,np.ndarray) and getattr(self,'exit_template',None) is not None and ui_visible(im[1360:1430,1190:1370],self.exit_template):
                kind='minigame';target=(1280,1395)
            elif skip:kind='skip_loading';target=skip[0]['center']
            elif 'purchase' in text and len(cancel)==1:kind='vendor_dialog';target=cancel[0]['center']
            elif confirm_target is not None or 'go back to the main menu' in text:
                kind='confirm_menu';target=confirm_target
            elif any('backtomainmenu' in re.sub(r'[^a-z]','',r['text'].lower()) for r in rows):
                kind='game_menu';target=next(r['center'] for r in rows
                    if 'backtomainmenu' in re.sub(r'[^a-z]','',r['text'].lower()))
            elif ('privateserver' in re.sub(r'[^a-z]','',text) and 'join' in text):
                kind='private_join'
                # Full-screen downsampling can turn JOIN into J0IN. Read the
                # observed panel at native vision scale before deciding input.
                target=private_join_target(self.text(im,(820,1190,920,250)))
            elif any('ouwlan' in r['text'].lower() for r in rows) and 'last played' in text:
                kind='world_selection';target=(520,680)
            elif play_target is not None:
                kind='main_menu';target=play_target
            elif self.world_visible(im) and ('mistfall' in text.replace(' ','') or re.search(r'lv\.?\s*\d+',text)):
                kind='world'
            else:kind='loading'
            self.last_screen_kind=kind
            if kind in ('disconnect','main_menu','world_selection','private_join'):
                # Once a real join is needed, prepare the loaded world normally.
                prefer_current=False;joined_world=True
            pacer.observe(kind,target,now)
            if kind!=last_class:self.event('screen',kind=kind);last_class=kind
            if kind=='minigame' and prefer_current:
                self.restarts=0;self.event('startup_current_minigame')
                return 'current_minigame'
            if kind=='disconnect' and pacer.ready(kind,now):
                allow_rejoin=True  # Positive visible evidence, including Farm here.
                self.capture(kind);self.event('disconnect_observed',text=text[:600])
                if target:
                    self.click(*target);pacer.acted(kind,time.monotonic(),18)
                else:
                    self.launch(restart=True);pacer.acted(kind,time.monotonic(),12);deadline=time.monotonic()+180
            elif kind=='minigame' and pacer.ready(kind,now):
                # End an interrupted/stalled minigame locally; changing server
                # is unnecessary. Every click still uses the normal input gate.
                self.click(*target);self.event('local_minigame_cancelled');pacer.acted(kind,time.monotonic(),3)
            elif kind in ('game_menu','confirm_menu') and (not allow_rejoin or prefer_current):
                if pacer.ready(kind,now):
                    self.key('M');self.event('local_menu_closed');pacer.acted(kind,time.monotonic(),2)
            elif kind in ('main_menu','world_selection','private_join') and not allow_rejoin:
                raise FishingFault('user_required','Farm here needs an existing game world; startup does not join a server')
            elif kind=='world':
                if prefer_current:
                    if pacer.ready('world_ready',now,stable_seconds=3):
                        self.restarts=0;self.event('startup_current_world')
                        return 'current_world'
                elif force_menu:
                    if pacer.ready('open_menu',now):
                        self.capture('before-menu');self.key('M');pacer.acted('open_menu',time.monotonic(),2);self.event('open_menu')
                elif pacer.ready('world_ready',now,stable_seconds=3):
                    if equip_rod:
                        self.backstep_after_join(join_attempts>0)
                        self.equip_rod();self.capture('equipped');self.event('equipped_rod')
                    else:
                        self.capture('world-ready');self.event('world_ready')
                    self.restarts=0;return 'joined_world' if joined_world else None
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
                if kind=='main_menu':self.move(350,980)  # Uncover PLAY for a fresh retry observation.
                action,delay={'skip_loading':('skip_optional_loading',8),'vendor_dialog':('closed_vendor_dialog',1),
                    'confirm_menu':('confirm_menu',4),'game_menu':('back_to_main_menu',1),
                    'world_selection':('select_ouwland',1),'main_menu':('play',1)}[kind]
                self.event(action);pacer.acted(kind,time.monotonic(),delay)
                if kind=='vendor_dialog':force_menu=not prefer_current
                elif kind in ('confirm_menu','main_menu'):force_menu=False
            self.sleep(.25)
        self.capture('timeout');raise RecoveryError('Rejoin did not reach the game within three minutes')

def prepare_worker(driver,force,allow_rejoin,prefer_current,current_position,here,titles_checked):
    """Adopt a live position without menu, camera or saved-reference work."""
    result=driver.recover(force_menu=force,allow_rejoin=allow_rejoin,prefer_current=prefer_current)
    if result in ('current_minigame','current_world'):current_position=True
    elif result=='joined_world':current_position=False
    if not here and not current_position:
        target_heading=load_config()['camera_heading']
        if target_heading is not None and landmarks.profile() is None:
            landmarks.restore_heading(driver,target_heading)
            actual_heading=landmarks.heading(driver,driver.capture())
            difference=(actual_heading-target_heading+180)%360-180 if actual_heading is not None else 360
            if abs(difference)>8:
                raise FishingFault('alignment','Saved fishing heading could not be restored',
                    target=target_heading,actual=actual_heading)
            driver.event('saved_heading_ready',heading=round(actual_heading,1))
        landmarks.align(driver)
    # Titles are a menu-only check, so they also run when the farmer starts in the
    # current world (previously they only ran after a rejoin and so rarely ran at
    # all). An adopted minigame or a local repair still skips the menu.
    if load_config()['auto_fishing_titles'] and not titles_checked and (not current_position or result=='current_world'):
        try:TitleManager(driver).run()
        except ValueError as title_error:
            driver.event('fishing_titles_unreadable',reason=str(title_error))
        titles_checked=True
    return current_position,titles_checked


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=0);parser.add_argument('--rejoin',action='store_true');parser.add_argument('--focus',action='store_true');parser.add_argument('--restart',action='store_true');parser.add_argument('--bait-stock',type=int,default=-1);parser.add_argument('--resume-counters',action='store_true');parser.add_argument('--respect-stop',action='store_true')
    parser.add_argument('--resume-log-run',action='store_true')
    parser.add_argument('--unattended-until',type=float,default=0,help='Authorized overnight focus recovery expiry (epoch seconds)')
    parser.add_argument('--here',action='store_true',help='Keep current server/location; rejoin only after positive disconnect evidence')
    a=parser.parse_args()
    RUN.mkdir(parents=True,exist_ok=True)
    lock=RUN/'supervisor-pid.json'
    import control_actions as controls
    with controls.guard():
        if controls.alive('route-recorder-pid.json'):
            raise UserStop('Bait route recorder is open; close it before starting Fishing')
        if lock.exists():
            prior=json.loads(lock.read_text())
            if psutil.pid_exists(prior['pid']) and abs(psutil.Process(prior['pid']).create_time()-prior['created'])<1:raise RuntimeError('Fishing supervisor already running')
        lock.write_text(json.dumps({'pid':os.getpid(),'created':psutil.Process().create_time()}))
    stop=RUN/'STOP'
    if stop.exists():
        if a.respect_stop:raise UserStop('Start cancelled by stop request')
        stop.unlink()
    resume_log_run=a.resume_log_run or (RUN/'PAUSE').exists()
    (RUN/'PAUSE').unlink(missing_ok=True)
    (RUN/'RECOVER').unlink(missing_ok=True)
    if not a.resume_counters:
        new_run()
        write_metrics('bait.json',{'starting_stock':a.bait_stock if a.bait_stock>=0 else None,'bait_per_hook':1,'note':'One bait per hook. Fishing continues without bait.'})
    driver=Recovery();deadline=time.monotonic()+a.seconds if a.seconds>0 else float('inf');recoveries=0;last_error='';child=None;exit_code=0;failure_code='';started=time.time()
    from run_log import begin, finish
    log_run=begin(RUN,resume_log_run)
    from unattended_focus import PhysicalActivity,allowed as focus_allowed
    physical=PhysicalActivity()
    physical.start()
    focus_paused_at=None;focus_retry_at=0
    def unattended_focus(stage):
        nonlocal focus_paused_at,focus_retry_at
        now=time.monotonic()
        if stage!='paused_focus':focus_paused_at=None;return
        focus_paused_at=focus_paused_at or now
        manual=stop.exists() or (RUN/'PAUSE').exists() or (RUN/PAUSE_FILE).exists()
        settings=load_config()
        enabled=settings['overnight_enabled'] and settings['overnight_autofocus']
        expires=a.unattended_until if a.unattended_until else float('inf')
        if not enabled:expires=0
        if not focus_allowed(now,focus_paused_at,physical.last,expires,time.time(),manual,
                             settings['overnight_focus_grace_seconds'],physical.last_other_input) or now<focus_retry_at:return
        focus_retry_at=now+60
        h=driver.hwnd
        if h and win32gui.IsWindow(h):
            driver.inp.release()
            try:
                if win32gui.IsIconic(h):win32gui.ShowWindow(h,9)
                win32gui.SetForegroundWindow(h)
                if win32gui.GetForegroundWindow()==h:
                    if time.monotonic()-physical.last>=45 and not (stop.exists() or (RUN/'PAUSE').exists() or (RUN/PAUSE_FILE).exists()):
                        # A pointer left on the second screen would otherwise
                        # keep the worker's normal safety gate paused forever.
                        screen=ScreenSpace(rectangle(h))
                        if load_config()['camera_mode']!='first_person':move_pointer(*screen.point(*load_config()['cast_point']))
                    driver.event('unattended_focus_restored',physical_idle_seconds=round(now-physical.last,1))
                    focus_paused_at=None
                else:driver.event('unattended_focus_wait',message='Windows refused focus; input remains paused')
            except (win32gui.error,RuntimeError,ValueError):
                driver.inp.release();driver.event('unattended_focus_wait',message='Focus or client changed; input remains paused')
    driver.event('run_started',run_id=log_run['id'],resumed=resume_log_run)
    policy=RecoveryPolicy();here_policy=HereRecovery(rejoin=load_config().get('spawn_gamepass') is not False);here_disconnect=False;here_retries=0;rod_policy=RodRecovery();display_repair=DisplayRepair()
    performance=PerformanceRecorder(read_metrics('totals.json').get('started'))
    titles_checked=False
    camera_unlock_attempts=0
    # Temporary: restored when this process exits. No persistent Windows setting is changed.
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    def paused_changed(paused):
        driver.inp.gate.poll()
        driver.event('f8_paused' if paused else 'f8_resumed')
    toggle=F8Toggle(RUN,lambda:driver.hwnd,paused_changed)
    def emergency_key(key):
        if key==Key.f8:toggle.press()
        if key in (Key.esc,Key.f9,Key.f12) and driver.hwnd and win32gui.GetForegroundWindow()==driver.hwnd:
            stop.write_text('Stopped by physical hotkey')
    def released_key(key):
        if key==Key.f8:toggle.release()
    listener=Listener(on_press=emergency_key,on_release=released_key,win32_event_filter=lambda message,data:not data.flags&0x10);listener.start()
    driver.inp.physical_stop_owned=True
    presence_stop=presence_watch.start()
    discord_reporter=DiscordReporter(RUN);discord_reporter.start()
    def status(stage,**kw):
        if (RUN/PAUSE_FILE).exists():stage='paused_manual'
        performance.tick(stage,read_metrics('status.json'),read_metrics('totals.json'))
        write_metrics('supervisor.json',{'running':True,'pid':os.getpid(),'updated':time.time(),'started':started,'stage':stage,'mode':'here' if a.here else 'full','manual_paused':(RUN/PAUSE_FILE).exists(),'recoveries':max(0,recoveries-1),'last_error':last_error,'runs_until_stopped':a.seconds<=0,'unattended_until':a.unattended_until,'overnight_enabled':load_config()['overnight_enabled'],'physical_idle_seconds':round(time.monotonic()-physical.last,1),**kw})
        unattended_focus(stage)
    driver.progress=lambda **kw:status('recovering',**kw)
    try:
        try:driver.select(focus=a.focus and not (RUN/PAUSE_FILE).exists())
        except RuntimeError as error:
            if getattr(error,'code',reason_code(str(error))) not in ('client_lost','disconnect'):raise
            driver.launch()
        if a.restart:driver.launch(restart=True)
        force=startup_rejoin('here' if a.here else 'full',a.rejoin)
        prefer_current=True;current_position=False
        while time.monotonic()<deadline:
            while driver.inp.gate.reason() or not driver.inp.gate.acknowledge():
                driver.check_stop();driver.inp.release();status(driver.inp.gate.reason() or 'paused_focus');time.sleep(.1)
                if time.monotonic()>=deadline:break
            if time.monotonic()>=deadline:break
            status('recovering')
            try:
                current_position,titles_checked=prepare_worker(driver,force,not a.here or here_disconnect,
                    prefer_current,current_position,a.here,titles_checked)
                prefer_current=False
                here_disconnect=False
                display_repair.progress()
                rod_policy.progress()
            except InputPaused as paused:
                driver.inp.release();driver.event('recovery_input_paused',reason=str(paused),gate=driver.inp.gate.reason())
                if (str(paused)=='paused_focus' and driver.inp.gate.reason() is None
                        and driver.last_screen_kind=='game_menu'):
                    left,top,right,bottom=driver.rect
                    cursor=win32gui.GetCursorPos()
                    if abs(cursor[0]-(left+right)/2)<12 and abs(cursor[1]-(top+bottom)/2)<12:
                        if camera_unlock_attempts>=2:
                            driver.event('camera_cursor_relaunch',reason='Two zoom-out attempts left the menu cursor locked')
                            driver.launch(restart=True);camera_unlock_attempts=0;force=False;continue
                        camera_unlock_attempts+=1
                        driver.release_camera_lock();force=True;continue
                force=False;continue
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
                if code=='capture_unavailable':
                    settings=load_config();now=time.monotonic()
                    manual=any((RUN/name).exists() for name in ('STOP','PAUSE','F8_PAUSE'))
                    ownership_idle=physical.last_other_input is None or now-physical.last_other_input>=settings['overnight_focus_grace_seconds']
                    if display_repair.allowed(now,getattr(ex,'details',{}).get('blank_color')=='white',
                            settings['overnight_enabled'] and settings['overnight_autofocus'],now-physical.last,
                            driver.hwnd==win32gui.GetForegroundWindow(),manual,ownership_idle):
                        display_repair.attempted(now)
                        driver.event('display_surface_refresh_started',attempt=len(display_repair.attempts))
                        try:driver.refresh_display()
                        except (InputPaused,RuntimeError,RecoveryError) as display_error:
                            driver.inp.release();driver.event('display_surface_refresh_wait',reason=str(display_error))
                    status('capture_wait');driver.sleep(3,focus=False);force=False;continue
                if code=='alignment':
                    # A local reference must never make the bot wander or enter
                    # a relaunch storm. Rejoin once, then wait for adjustment.
                    if force:raise
                    force=True;continue
                if code=='rod_unreadable':
                    action,delay=rod_policy.choose(time.monotonic(),here=a.here)
                    force=action=='rejoin'
                    driver.event('rod_recovery_retry',action=action,retry_seconds=delay,
                        message=('Rod still unreadable; rejoining the saved fishing spawn' if force else
                                 'Rod still unreadable; input released while waiting for a fresh check'))
                    driver.sct.reset();retry_until=min(deadline,time.monotonic()+delay)
                    while time.monotonic()<retry_until:
                        remaining=retry_until-time.monotonic()
                        status('rod_wait',failure_code=code,retry_seconds=round(remaining,1))
                        driver.sleep(min(1,max(0,remaining)),focus=False)
                    continue
                if code=='user_required':raise
                if a.here:
                    here_retries+=1
                    if here_retries>3:raise FishingFault('user_required','Farm here local recovery exhausted; current server retained')
                    status('retry_wait');driver.sleep(3,focus=False);force=False;continue
                status('restarting')
                try:driver.launch(restart=bool(driver.hwnd and win32gui.IsWindow(driver.hwnd)))
                except (RuntimeError,RecoveryError) as restart_error:
                    last_error=str(restart_error);driver.event('restart_backoff',reason=last_error);status('retry_wait')
                    driver.sleep(60,focus=False);driver.restarts=0
                force=False;continue
            recoveries+=1;force=True;last_error=''
            camera_unlock_attempts=0
            if time.monotonic()>=deadline:break
            remaining=max(1,int(deadline-time.monotonic())) if a.seconds>0 else 0;status('fishing');worker_started=time.time()
            with open(RUN/'worker-stdout.log','a') as stdout,open(RUN/'worker-stderr.log','a') as stderr:
                command=[sys.executable,str(CODE/'fishing_assistant.py'),'--seconds',str(remaining)]
                if current_position:command.append('--current-position')
                child=subprocess.Popen(command,stdout=stdout,stderr=stderr)
            while child.poll() is None:
                driver.check_stop()
                worker=read_metrics('status.json')
                if a.here and worker.get('updated',0)>=worker_started and worker.get('reward_banners_observed',0)>0:here_policy.progress();here_retries=0
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
            driver.sct.reset()  # Own a fresh context at a worker/recovery boundary.
            action=here_policy.choose(code) if a.here else policy.choose(code,time.monotonic(),landmarks.profile() is not None)
            driver.event('recovery_decision',code=code,action=action)
            if action=='stop_unstable_position':
                raise FishingFault('unstable_fishing_position',
                    'Fishing position failed after three separate rejoins within 90 minutes; check that the saved spawn is safely back from the water edge')
            if action=='stop_disconnected':
                raise FishingFault('user_required',
                    'Roblox disconnected. Without the Set Spawn Anywhere gamepass a rejoin would not bring you back to '
                    'your fishing spot, so Farm here stopped. Rejoin, walk back to your spot and press Continue.')
            if action in ('stop','attention'):
                raise FishingFault('user_required','Local recovery needs user attention; automatic restart suspended')
            if a.here:
                here_disconnect=action=='rejoin';force=False
            if action=='local':
                force=False;driver.event('local_repair',reason=reason)
            elif action=='wait_focus' and win32gui.IsWindow(driver.hwnd):
                driver.event('paused_focus')
                while win32gui.GetForegroundWindow()!=driver.hwnd and time.monotonic()<deadline:
                    driver.check_stop();status('paused_focus');time.sleep(.3)
                force=False
            driver.sleep(1,focus=False)
    except BaseException as ex:
        last_error=str(ex);failure_code=getattr(ex,'code',reason_code(last_error));exit_code=0 if isinstance(ex,UserStop) else 1;driver.event('supervisor_stopped',reason=last_error)
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
        driver.sct.close()
        listener.stop()
        presence_stop.set()
        physical.stop()
        discord_reporter.stop()
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        write_metrics('supervisor.json',{'running':False,'pid':os.getpid(),'updated':time.time(),'started':started,'stage':'stopped','mode':'here' if a.here else 'full','recoveries':max(0,recoveries-1),'reason':last_error or 'session_limit','failure_code':failure_code or 'session_limit'})
        finish(RUN,last_error or 'session_limit')
        if not (RUN/'PAUSE').exists():
            try:
                from discord_hourly import send_run_end
                send_run_end(RUN)
            except Exception as error:
                from discord_hourly import atomic_json
                atomic_json(RUN/'discord-final-report.json',{'sent':False,'at':time.time(),'run_id':log_run['id'],'error':str(error)})
    return exit_code

if __name__=='__main__':sys.exit(main())
