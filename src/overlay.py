"""Native, per-pixel translucent overlay. It never activates or handles game input.

Only a matching foreground Roblox window makes it visible. Pillow draws opaque
text on a translucent surface; UpdateLayeredWindow preserves both alpha levels.
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

WIDTH, HEIGHT = 284, 436
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
    """Render the actual overlay surface; also used for deterministic visual QA."""
    gear = gear or {}
    density = max(2., scale*2)
    size = (round(WIDTH*density), round(HEIGHT*density))
    image = Image.new('RGBA', size)
    draw = ImageDraw.Draw(image)
    def box(rect, fill, radius=0, outline=None):
        layer = Image.new('RGBA', image.size)
        ImageDraw.Draw(layer).rounded_rectangle(tuple(round(v*density) for v in rect), round(radius*density), fill, outline)
        image.alpha_composite(layer)
    def text(x, y, value, color=TEXT, size=12, bold=False, max_width=None):
        value = str(value)
        face = font(round(size*density), bold)
        if max_width:
            while value and draw.textlength(value, font=face) > max_width*density:
                value = value[:-2]+'…' if not value.endswith('…') else value[:-2]+'…'
        draw.text((round(x*density), round(y*density)), value, font=face, fill=color)
    # A fixed alpha surface leaves the game visible while all primary text stays solid.
    box((0, 0, WIDTH-1, HEIGHT-1), (28, 34, 47, SURFACE_ALPHA), RADIUS, (212, 228, 244, 45))
    box((13, 13, 55, 55), (235, 243, 255, 24), 12)
    # A quiet bobber, used instead of a filled crown badge.
    draw.ellipse((28*density, 25*density, 40*density, 37*density), outline=TEXT, width=round(1.5*density))
    draw.line([(34*density, 20*density), (34*density, 26*density)], fill=TEXT, width=round(1.5*density))
    draw.line([(24*density, 42*density), (29*density, 40*density), (34*density, 42*density),
               (39*density, 40*density), (44*density, 42*density)], fill=TEXT, width=round(1.4*density))
    label = state.get('state') or 'Not farming'
    text(66, 14, label, size=15, bold=True, max_width=205)
    seconds = max(0, int(state.get('active_seconds') or 0))
    text(67, 37, f'{seconds//3600}:{seconds//60%60:02}:{seconds%60:02}', DIM, 11)
    box((13, 66, 271, 68), (245, 249, 255, 24), 1)
    if state.get('activity_running'): box((13, 66, 170, 68), (233, 243, 255, 210), 1)
    pace = state.get('pace')
    if pace is None and state.get('hooks_per_hour'): pace = state['hooks_per_hour']/60
    gold = state.get('gold_per_hour')
    total = gold*seconds/3600 if gold is not None and seconds else None
    stats = [('Pace', f'{pace:.1f}' if pace is not None else '—', '/min', GREEN),
             ('Gold / h', compact(gold), '', GOLD), ('Session', compact(total), '', GOLD)]
    for n, (name, value, unit, color) in enumerate(stats):
        x = 13+n*87
        box((x, 80, x+80, 134), (228, 238, 255, 17), 12)
        text(x+10, 87, name, DIM, 10)
        text(x+10, 104, value, color, 17, True)
        if unit: text(x+45, 112, unit, MUTED, 9)
    box((13, 146, 271, 147), (240, 245, 255, 25))
    rod = gear.get('rod') or state.get('rod')
    text(16, 158, (rod+' Fishing Rod') if rod else 'No rod picked', GOLD if rod else MUTED, 13, True, 216)
    enchant = gear.get('enchant')
    if enchant:
        box((235, 159, 269, 177), (255, 198, 75, 35), 7)
        text(241, 159, f'+{enchant}', GOLD, 11, True)
    titles = gear.get('titles') or []
    for n, title in enumerate(titles[:3]):
        y = 185+n*19
        text(16, y, title.get('name', ''), MUTED, 11, max_width=170)
        factors = []
        for k in ('luck', 'bite'):
            if title.get(k) is not None: factors.append(f"{title[k]:g}×")
        text(188, y, ' '.join(factors), TEXT, 10, True, 80)
    if not titles: text(16, 186, 'No fishing titles recorded', DIM, 11)
    box((13, 246, 137, 272), (235, 243, 255, 22), 13)
    bait = state.get('bait_remaining_estimate')
    text(24, 250, f'{bait:,}' if bait is not None else 'Bait unknown', TEXT, 12, True)
    hours = state.get('bait_hours_remaining_estimate')
    if hours: text(83, 253, f'≈{hours:.0f}h', DIM, 10)
    box((144, 246, 271, 272), (235, 243, 255, 22), 13)
    text(156, 250, MODE.get(state.get('mode'), 'Stopped'), TEXT, 12, True, 104)
    box((13, 284, 271, 285), (240, 245, 255, 25))
    text(15, 296, 'RECENT', DIM, 10)
    rows = [e for e in state.get('events', []) if e.get('group') == 'catches'][-5:][::-1]
    if not rows: text(15, 322, 'Catches show up here', MUTED, 12)
    from rod_stats import item_rarity
    for n, row in enumerate(rows):
        y = 323+n*20
        name = row.get('text', '')
        rarity = item_rarity(name)
        if rarity == 'Impossible': box((7, y-1, 277, y+20), (255, 100, 133, 35), 8)
        text(14, y, time.strftime('%H:%M', time.localtime(row.get('at', 0))), DIM, 10)
        text(59, y-1, name, RARITY.get(rarity, MUTED), 12, rarity != 'Common', 211)
    return image.resize((round(WIDTH*scale), round(HEIGHT*scale)), Image.Resampling.LANCZOS)


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
