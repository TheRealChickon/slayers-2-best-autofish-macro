"""Cooperative full-farmer pause, shared by supervisor and fishing worker."""
import threading
import time
from client_geometry import client_rect,enable_physical_coordinates
import win32gui

PAUSE_FILE = 'F8_PAUSE'


class InputPaused(RuntimeError):
    pass


class F8Toggle:
    """Only the supervisor owns the hotkey; repeats and other apps are ignored."""
    def __init__(self, root, hwnd, changed=lambda paused: None):
        self.root, self.hwnd, self.changed = root, hwnd, changed
        self.down = False

    def press(self):
        if self.down: return
        self.down = True
        h = self.hwnd()
        if not h or not win32gui.IsWindow(h) or win32gui.IsIconic(h) or win32gui.GetForegroundWindow() != h: return
        if (self.root/'STOP').exists() or (self.root/'PAUSE').exists(): return
        flag = self.root/PAUSE_FILE
        if flag.exists(): flag.unlink()
        else: flag.write_text('Paused by F8 in Roblox')
        self.changed(flag.exists())

    def release(self):
        self.down = False


class InputGate:
    """Release input during slow OCR and invalidate decisions made before a pause."""
    def __init__(self, inp, root, user, pointer=False, activity=None, competing_grace=30):
        self.inp, self.root, self.user, self.pointer = inp, root, user, pointer
        self.activity = activity
        self.activity_baseline = activity.last if activity else None
        self.competing_grace = competing_grace
        self.interrupted = threading.Event()
        self.done = threading.Event()
        self.thread = None
        self.needs_mouse_sync = self.needs_t_sync = False

    def reason(self):
        if (self.root/PAUSE_FILE).exists() or (self.root/'PAUSE').exists(): return 'paused_manual'
        if self.activity:
            now=time.monotonic()
            if self.activity.last>self.activity_baseline and now-self.activity.last<45:return 'paused_human'
            other=self.activity.last_other_input
            if other is not None and now-other<self.competing_grace:return 'paused_competing_input'
        h = self.inp.hwnd
        if h and win32gui.IsWindow(h):
            if win32gui.IsIconic(h) or win32gui.GetForegroundWindow() != h: return 'paused_focus'
            if any(self.user.GetAsyncKeyState(k)&0x8000 for k in (18, 9, 91, 92)): return 'paused_focus'
            if self.pointer and win32gui.GetAncestor(win32gui.WindowFromPoint(win32gui.GetCursorPos()), 2) != h:
                return 'paused_focus'
        return None

    def check(self):
        if (self.root/'STOP').exists(): raise RuntimeError('Stopped by stop file')
        reason = self.reason()
        if reason != 'paused_manual' and self.inp.hwnd and not win32gui.IsWindow(self.inp.hwnd):
            raise RuntimeError('Roblox window closed; rejoin required')
        if reason or self.interrupted.is_set():
            raise InputPaused(reason or 'paused_focus')

    def poll(self):
        with self.inp.lock:
            changed=(getattr(self.inp,'client_rect',None) is not None and self.inp.hwnd
                     and win32gui.IsWindow(self.inp.hwnd) and client_rect(win32gui,self.inp.hwnd)!=self.inp.client_rect)
            if changed or self.reason() or (self.root/'STOP').exists() or (self.inp.hwnd and not win32gui.IsWindow(self.inp.hwnd)):
                self.interrupted.set()
                self.needs_mouse_sync |= self.inp.mouse
                self.needs_t_sync |= self.inp.t
                self.inp.release()

    def acknowledge(self):
        with self.inp.lock:
            if self.reason(): return False
            if (self.root/'STOP').exists(): raise RuntimeError('Stopped by stop file')
            # Releases sent to a background Roblox client may be missed. Repeat
            # only our own releases after focus returns; never inject Alt/Tab.
            h = self.inp.hwnd
            if h and win32gui.IsWindow(h) and win32gui.GetForegroundWindow() == h:
                if self.needs_mouse_sync: self.user.mouse_event(4, 0, 0, 0, 0)
                if self.needs_t_sync: self.user.keybd_event(ord('T'), self.user.MapVirtualKeyW(ord('T'), 0), 2, 0)
            self.needs_mouse_sync = self.needs_t_sync = False
            self.interrupted.clear()
            return True

    def start(self):
        def watch():
            enable_physical_coordinates(self.user)
            while not self.done.wait(.015):
                self.poll()
        self.thread = threading.Thread(target=watch, daemon=True, name='FullFishingFocus')
        self.thread.start()

    def close(self):
        self.done.set()
        if self.thread: self.thread.join(1)
        self.inp.release()


def resumed_stage(stage, cast_pressed):
    # Releasing an interrupted cast may already have hooked a fish. Wait for
    # it instead of clicking twice. Always reread an interrupted Collect prompt.
    if stage == 'casting' and cast_pressed: return 'waiting'
    if stage in ('pickup', 'pickup_retry_wait'): return 'pickup_wait'
    return stage
