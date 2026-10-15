"""The in-game overlay: a small always-on-top card over Roblox's top-right corner.

It is an Edge/Chrome app window showing /overlay from the app window's local server,
restyled with win32 so it has no frame, never takes focus, lets clicks fall through
to the game and follows the Roblox window around."""
import subprocess
import threading
import time

from app_config import data_directory

WIDTH, HEIGHT = 284, 432   # CSS pixels; scaled by the overlay window's DPI
ALPHA = 238                # 0-255: the game shows through a little
RADIUS = 18


def placement(game, size, scale=1.0):
    """Top-left corner for the card: right edge of the game, a quarter of the way down
    (clear of Roblox's top bar and leaderboard), kept inside the game window."""
    left, top, right, bottom = game
    width, height = size
    margin = round(12*scale)
    x = right-width-margin
    y = top+round(.24*(bottom-top))
    y = max(top+margin, min(y, bottom-height-margin))
    return max(left, x), y


def roblox_window():
    import psutil
    import win32gui
    import win32process
    found = []

    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd): return
        try:
            if psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1]).name().lower() == 'robloxplayerbeta.exe':
                found.append(hwnd)
        except (psutil.Error, OSError):
            pass
    win32gui.EnumWindows(visit, None)
    return found[0] if len(found) == 1 else None


def windows_of(pid):
    import win32gui
    import win32process
    found = []

    def visit(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1] == pid and win32gui.GetWindowText(hwnd):
            found.append(hwnd)
    win32gui.EnumWindows(visit, None)
    return found


def dpi_scale(hwnd):
    import ctypes
    try: return ctypes.windll.user32.GetDpiForWindow(hwnd)/96 or 1.0
    except Exception: return 1.0


def style_overlay(hwnd):
    """No frame, topmost, click-through, never activated, not on the taskbar."""
    import win32con
    import win32gui
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    style &= ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME | win32con.WS_SYSMENU | win32con.WS_MINIMIZEBOX | win32con.WS_MAXIMIZEBOX)
    win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
    ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    ex |= win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE
    ex &= ~win32con.WS_EX_APPWINDOW
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex)
    win32gui.SetLayeredWindowAttributes(hwnd, 0, ALPHA, win32con.LWA_ALPHA)


def move(hwnd, x, y, width, height, radius):
    import win32con
    import win32gui
    flags = win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED | win32con.SWP_SHOWWINDOW
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, x, y, width, height, flags)
    win32gui.SetWindowRgn(hwnd, win32gui.CreateRoundRectRgn(0, 0, width+1, height+1, 2*radius, 2*radius), True)


class Overlay:
    def __init__(self, browser_path):
        self.browser_path = browser_path
        self.process = None
        self.thread = None
        self.lock = threading.Lock()

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    def start(self, url):
        with self.lock:
            if self.running: return
            if not self.browser_path: raise RuntimeError('The overlay needs Microsoft Edge or Google Chrome')
            # Its own profile, so Edge starts a separate process whose window we can find and restyle.
            profile = data_directory()/'overlay-profile'
            self.process = subprocess.Popen([self.browser_path, f'--app={url}', f'--user-data-dir={profile}',
                                             f'--window-size={WIDTH},{HEIGHT}', '--window-position=-32000,-32000',
                                             '--no-first-run', '--no-default-browser-check', '--disable-features=Translate'])
            try:
                import win32gui
                before = win32gui.GetForegroundWindow()
            except Exception:
                before = None
            self.thread = threading.Thread(target=self.follow, args=(self.process, before), daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            if self.process is not None and self.process.poll() is None: self.process.terminate()
            self.process = None

    def follow(self, process, before=None):
        import win32con
        import win32gui
        hwnd, last = None, None
        deadline = time.time()+20
        while process.poll() is None:
            if hwnd is None or not win32gui.IsWindow(hwnd):
                found = windows_of(process.pid)
                if not found:
                    if time.time() > deadline: process.terminate(); return
                    time.sleep(.2); continue
                hwnd, last = found[0], None
                style_overlay(hwnd)
                # Edge takes focus when it opens; hand it back to whatever had it (usually Roblox).
                if before and win32gui.IsWindow(before):
                    try: win32gui.SetForegroundWindow(before)
                    except Exception: pass
            game = roblox_window()
            if game is None or win32gui.IsIconic(game):
                if last != 'hidden': win32gui.ShowWindow(hwnd, win32con.SW_HIDE); last = 'hidden'
            else:
                scale = dpi_scale(hwnd)
                size = round(WIDTH*scale), round(HEIGHT*scale)
                l, t, r, b = win32gui.GetClientRect(game)
                x0, y0 = win32gui.ClientToScreen(game, (0, 0))
                spot = (*placement((x0, y0, x0+r-l, y0+b-t), size, scale), *size)
                if spot != last:
                    move(hwnd, *spot, round(RADIUS*scale)); last = spot
            time.sleep(.5)
