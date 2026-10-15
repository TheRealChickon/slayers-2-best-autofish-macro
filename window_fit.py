"""Give the Roblox window a 16:9 client area that fits its screen.

The game's UI is anchored to different window edges (health bar bottom-left,
hotbar bottom-centre, minigame right of centre), so no single mapping reads a
4:3, 16:10, 21:9 or "maximized laptop" client correctly. Resizing the window to
the largest 16:9 client that fits the monitor's work area makes every screen
size look like the 2560 x 1440 reference. Only the window is moved; leaving
fullscreen uses Roblox's own F11 toggle and only when the caller allows it.
"""
import time

from screen_space import ASPECT, MIN_SIZE, client_problem

SW_RESTORE = 9
SW_SHOWMAXIMIZED = 3
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
MONITOR_DEFAULTTONEAREST = 2


def plan_window(work, frame):
    """Window rectangle (left, top, width, height) giving the largest centred
    16:9 client inside ``work``; None when even that is below the minimum.

    ``work`` is the monitor work area (left, top, right, bottom) and ``frame``
    the window border thickness (left, top, right, bottom) around the client.
    """
    fl, ft, fr, fb = frame
    space_w = work[2]-work[0]-fl-fr
    space_h = work[3]-work[1]-ft-fb
    height = min(space_h, int(space_w/ASPECT))
    width = round(height*ASPECT)
    if width > space_w:
        width = space_w
        height = int(width/ASPECT)
    if width < MIN_SIZE[0] or height < MIN_SIZE[1]:
        return None
    outer_w, outer_h = width+fl+fr, height+ft+fb
    left = work[0]+(work[2]-work[0]-outer_w)//2
    top = work[1]+(work[3]-work[1]-outer_h)//2
    return left, top, outer_w, outer_h


def frame_of(window, client):
    """Border thickness from the window and client rectangles (screen pixels)."""
    return client[0]-window[0], client[1]-window[1], window[2]-client[2], window[3]-client[3]


class WindowFitError(RuntimeError):
    pass


def client_rect(hwnd):
    import win32gui
    l, t, r, b = win32gui.GetClientRect(hwnd)
    x, y = win32gui.ClientToScreen(hwnd, (0, 0))
    return x, y, x+r-l, y+b-t


def is_fullscreen(hwnd):
    import win32api
    import win32gui
    style = win32gui.GetWindowLong(hwnd, GWL_STYLE)
    monitor = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST))['Monitor']
    return not style & WS_CAPTION and tuple(win32gui.GetWindowRect(hwnd)) == tuple(monitor)


def fit_window(hwnd, press_f11=None, sleep=time.sleep, event=None):
    """Make the Roblox client 16:9 if it is not; returns its client rectangle.

    ``press_f11`` (optional) sends Roblox's fullscreen toggle when the game is
    fullscreen on a screen that is not 16:9. Without it, that case raises a
    WindowFitError that tells the player what to do.
    """
    import win32api
    import win32gui
    rect = client_rect(hwnd)
    if client_problem(rect[2]-rect[0], rect[3]-rect[1]) is None:
        return rect
    if is_fullscreen(hwnd):
        if press_f11 is None:
            raise WindowFitError('Roblox is fullscreen on a screen that is not 16:9. Press F11 in Roblox to leave '
                                 'fullscreen; Autofish then sizes the window for you.')
        press_f11()
        for _ in range(30):
            sleep(.1)
            if not is_fullscreen(hwnd):
                break
        else:
            raise WindowFitError('Roblox stayed fullscreen. Press F11 in Roblox to leave fullscreen and start again.')
    if win32gui.GetWindowPlacement(hwnd)[1] == SW_SHOWMAXIMIZED:
        win32gui.ShowWindow(hwnd, SW_RESTORE)
        sleep(.4)
    monitor = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST))
    frame = frame_of(win32gui.GetWindowRect(hwnd), client_rect(hwnd))
    target = plan_window(monitor['Work'], frame)
    if target is None:
        w, h = monitor['Work'][2]-monitor['Work'][0], monitor['Work'][3]-monitor['Work'][1]
        raise WindowFitError(f'This screen ({w} × {h}) is too small for a {MIN_SIZE[0]} × {MIN_SIZE[1]} Roblox window. '
                             'Use F11 fullscreen on a 16:9 screen, or lower Windows display scaling.')
    win32gui.SetWindowPos(hwnd, 0, *target, SWP_NOZORDER | SWP_NOACTIVATE)
    for _ in range(20):
        sleep(.1)
        rect = client_rect(hwnd)
        if client_problem(rect[2]-rect[0], rect[3]-rect[1]) is None:
            if event:
                event('client_fitted', width=rect[2]-rect[0], height=rect[3]-rect[1],
                      message=f'Resized Roblox to a 16:9 window ({rect[2]-rect[0]} × {rect[3]-rect[1]}).')
            return rect
    raise WindowFitError(client_problem(rect[2]-rect[0], rect[3]-rect[1]))


def fitted(hwnd, rect, **options):
    """``rect`` when Roblox is already readable; otherwise fit the window."""
    if client_problem(rect[2]-rect[0], rect[3]-rect[1]) is None:
        return rect
    return fit_window(hwnd, **options)
