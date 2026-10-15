"""Native, per-pixel translucent overlay with compositor backdrop blur. It never activates or handles game input.

Only a matching foreground Roblox window makes it visible. Pillow draws opaque
text on a translucent surface; UpdateLayeredWindow preserves both alpha levels.
The Windows compositor blurs the live backdrop without screen capture.
No browser window is restyled and no focus-restoration call is needed.
"""
import json
import math
import os
import threading
import time
import urllib.request
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 284, 432
RADIUS = 18
SURFACE_ALPHA = 174
TEXT = (241, 245, 249, 255)
MUTED = (183, 193, 207, 240)
DIM = (150, 161, 178, 230)
GOLD = (255, 198, 75, 255)
GREEN = (117, 220, 171, 255)
MODE = {'full': 'Full farmer', 'here': 'Farm here', 'spot': 'Fish here', 'assist': 'Minigame'}
RARITY = {'Impossible': (255, 137, 111, 255), 'Mythic': (198, 157, 255, 255),
          'Legendary': GOLD, 'Rare': (64, 215, 235, 255), 'Uncommon': (82, 174, 255, 255)}


def placement(game, size, scale=1.0):
    left, top, right, bottom = game
    width, height = size
    margin = round(12*scale)
    x = right-width-margin
    y = max(top+margin, min(top+round(.24*(bottom-top)), bottom-height-margin))
    return max(left, x), y


def roblox_window():
    import psutil, win32gui, win32process
    # Foreground ownership also prevents the overlay covering the dashboard.
    hwnd = win32gui.GetForegroundWindow()
    try:
        if hwnd and win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd):
            if psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1]).name().lower() == 'robloxplayerbeta.exe':
                return hwnd
    except (psutil.Error, OSError):
        pass
    return None


def dpi_scale(hwnd):
    import ctypes
    try: return ctypes.windll.user32.GetDpiForWindow(hwnd)/96 or 1.0
    except Exception: return 1.0


@lru_cache(maxsize=32)
def font(size, bold=False):
    root = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts'
    try: return ImageFont.truetype(str(root/('seguisb.ttf' if bold else 'segoeui.ttf')), size)
    except OSError: return ImageFont.load_default(size=size)


def compact(value):
    if value is None: return '—'
    try:
        v = float(value)
        if not math.isfinite(v): return '—'
        return f'{v/1000:.1f}k' if abs(v) >= 1000 else f'{v:,.0f}'
    except (ValueError, TypeError): return '—'


def render(state, gear=None, scale=1.0):
    """Overlay design A (see overlay_card); also used for deterministic visual QA."""
    import overlay_card
    from rod_stats import item_rarity
    return overlay_card.render(state, gear, scale, rarity_of=item_rarity)


def paint(hwnd, surface, position):
    """Upload a premultiplied BGRA DIB; never apply whole-window opacity."""
    import ctypes, win32con, win32gui, win32ui
    from ctypes import wintypes
    import numpy as np
    width, height = surface.size
    pixels = np.array(surface, dtype=np.uint16)
    pixels[:, :, :3] = (pixels[:, :, :3]*pixels[:, :, 3:4]+127)//255
    raw = pixels[:, :, [2, 1, 0, 3]].astype(np.uint8).tobytes()
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG),
                    ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG),
                    ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]
    screen = win32gui.GetDC(0)
    source = win32ui.CreateDCFromHandle(screen)
    memory = source.CreateCompatibleDC()
    info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, len(raw), 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    gdi = ctypes.windll.gdi32
    gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi.CreateDIBSection.restype = wintypes.HBITMAP
    bitmap = gdi.CreateDIBSection(memory.GetSafeHdc(), ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    if not bitmap:
        memory.DeleteDC(); win32gui.ReleaseDC(0, screen)
        raise OSError('Could not create overlay surface')
    previous = win32gui.SelectObject(memory.GetSafeHdc(), bitmap)
    try:
        ctypes.memmove(bits, raw, len(raw))
        win32gui.UpdateLayeredWindow(hwnd, screen, position, (width, height), memory.GetSafeHdc(), (0, 0), 0,
                                     (win32con.AC_SRC_OVER, 0, 255, win32con.AC_SRC_ALPHA), win32con.ULW_ALPHA)
    finally:
        win32gui.SelectObject(memory.GetSafeHdc(), previous)
        win32gui.DeleteObject(bitmap)
        memory.DeleteDC()
        win32gui.ReleaseDC(0, screen)


def enable_blur(hwnd):
    """Blur the live backdrop while keeping the layered text fully opaque.

    DWMWA_SYSTEMBACKDROP_TYPE produces an opaque inactive surface on this
    no-activate layered window. WCA_ACCENT_POLICY applies blur to its backdrop
    without changing activation, input handling, or the uploaded alpha surface.
    """
    import ctypes
    from ctypes import wintypes
    class AccentPolicy(ctypes.Structure):
        _fields_ = [('state', wintypes.DWORD), ('flags', wintypes.DWORD),
                    ('color', wintypes.DWORD), ('animation', wintypes.DWORD)]
    class CompositionData(ctypes.Structure):
        _fields_ = [('attribute', wintypes.DWORD), ('data', ctypes.c_void_p),
                    ('size', ctypes.c_size_t)]
    policy = AccentPolicy(3, 0, 0, 0)  # ACCENT_ENABLE_BLURBEHIND; tint comes from Pillow.
    data = CompositionData(19, ctypes.addressof(policy), ctypes.sizeof(policy))
    try:
        apply = ctypes.windll.user32.SetWindowCompositionAttribute
    except AttributeError as error:
        raise OSError('Windows backdrop blur is unavailable') from error
    apply.argtypes = [wintypes.HWND, ctypes.POINTER(CompositionData)]
    apply.restype = wintypes.BOOL
    if not apply(hwnd, ctypes.byref(data)):
        raise OSError('Windows could not enable overlay backdrop blur')



class Overlay:
    def __init__(self, browser_path=None):
        self.thread = None
        self.hwnd = None
        self.error = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self.lock = threading.Lock()

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive() and not self._stop.is_set() and self.hwnd)

    def start(self, url):
        with self.lock:
            if self.running: return
            self._stop.clear(); self._ready.clear(); self.error = None
            self.thread = threading.Thread(target=self.follow, args=(url,), daemon=True, name='Autofish overlay')
            self.thread.start()
            if not self._ready.wait(5):
                self._stop.set()
                raise RuntimeError('Overlay did not initialize')
            if self.error: raise RuntimeError(self.error)

    def stop(self):
        with self.lock:
            self._stop.set()
            if self.thread and self.thread is not threading.current_thread(): self.thread.join(3)

    def follow(self, url):
        import win32api, win32con, win32gui
        import ctypes
        try: ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception: pass
        name = f'AutofishOverlay-{os.getpid()}-{id(self)}'
        instance = win32api.GetModuleHandle(None)
        def wndproc(hwnd, msg, wparam, lparam):
            if msg == win32con.WM_NCHITTEST: return win32con.HTTRANSPARENT
            if msg == win32con.WM_MOUSEACTIVATE: return win32con.MA_NOACTIVATE
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
        registered = False
        try:
            wc = win32gui.WNDCLASS(); wc.hInstance = instance; wc.lpszClassName = name; wc.lpfnWndProc = wndproc
            win32gui.RegisterClass(wc); registered = True
            ex = win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE
            self.hwnd = win32gui.CreateWindowEx(ex, name, 'Autofish overlay', win32con.WS_POPUP,
                                               0, 0, WIDTH, HEIGHT, 0, 0, instance, None)
            parts = urlsplit(url)
            if parts.hostname != '127.0.0.1': raise ValueError('Overlay requires the local app server')
            token = parse_qs(parts.query)['t'][0]
            origin = f'http://127.0.0.1:{parts.port}'
            def fetch(path):
                req = urllib.request.Request(origin+path, headers={'X-Autofish-Token': token})
                with urllib.request.urlopen(req, timeout=1) as response: return json.load(response)
            # Paint once while hidden, catching native setup errors before reporting On.
            paint(self.hwnd, render({'state': 'Loading'}), (0, 0))
            enable_blur(self.hwnd)
            self._ready.set()
            state, gear, next_poll, next_gear, last = {}, {}, 0., 0., None
            while not self._stop.is_set():
                win32gui.PumpWaitingMessages()
                game = roblox_window()
                if not game:
                    win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
                    last = None
                else:
                    now = time.monotonic()
                    if now >= next_poll:
                        try:
                            state = fetch('/api/state')
                            if now >= next_gear: gear = fetch('/api/gear'); next_gear = now+30
                        except Exception:
                            state = {**state, 'state': 'Reconnecting', 'activity_running': False}
                        next_poll = now+1
                        last = None
                    scale = dpi_scale(game)
                    l, t, r, b = win32gui.GetClientRect(game)
                    x, y = win32gui.ClientToScreen(game, (0, 0))
                    size = round(WIDTH*scale), round(HEIGHT*scale)
                    position = placement((x, y, x+r-l, y+b-t), size, scale)
                    if last != (position, size):
                        paint(self.hwnd, render(state, gear, scale), position)
                        win32gui.SetWindowPos(self.hwnd, win32con.HWND_TOPMOST, *position, *size,
                                             win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW)
                        last = position, size
                self._stop.wait(.1)
        except Exception as error:
            self.error = f'Overlay: {error}'
        finally:
            self._ready.set()
            if self.hwnd:
                win32gui.DestroyWindow(self.hwnd); self.hwnd = None
            if registered: win32gui.UnregisterClass(name, instance)
