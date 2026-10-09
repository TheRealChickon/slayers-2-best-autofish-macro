"""Physical client coordinates and a quiet interval after window changes."""
import ctypes


class ClientAreaChanged(RuntimeError):
    pass


def enable_physical_coordinates(user):
    """Set this process/thread to physical pixels, even after MSS initialized."""
    for name in ('SetProcessDpiAwarenessContext', 'SetThreadDpiAwarenessContext'):
        api = getattr(user, name, None)
        if api is not None:
            try:
                api.argtypes = [ctypes.c_void_p]
                api.restype = ctypes.c_void_p if name.startswith('SetThread') else ctypes.c_bool
                result = api(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
                if result and name.startswith('SetThread'):
                    return 'per_monitor_v2'
            except (OSError, AttributeError, TypeError):
                pass
    fallback = getattr(user, 'SetProcessDPIAware', None)
    if fallback is not None:
        fallback()
    return 'legacy'


def client_rect(gui, hwnd):
    left, top, right, bottom = gui.GetClientRect(hwnd)
    x, y = gui.ClientToScreen(hwnd, (left, top))
    return x, y, x + right - left, y + bottom - top


class ClientStability:
    def __init__(self, rect, settle_seconds=.15):
        self.current = tuple(rect)
        self.pending = None
        self.changed_at = None
        self.settle_seconds = settle_seconds

    def observe(self, rect, now):
        rect = tuple(rect)
        if rect == self.current:
            self.pending = None
            return True
        if rect != self.pending:
            self.pending, self.changed_at = rect, now
            return False
        if now - self.changed_at < self.settle_seconds:
            return False
        self.current, self.pending = rect, None
        return True
