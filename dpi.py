"""Use physical pixels on every monitor, so window, cursor and capture agree.

With 125 % or 150 % Windows scaling a DPI-unaware process sees a scaled-down
Roblox window while screen capture returns real pixels. Per-monitor awareness
also keeps a second monitor with a different scale exact.
"""


def dpi_aware(user32):
    # PER_MONITOR_AWARE_V2 (Windows 10 1703+), then system-aware fallbacks.
    try:
        if user32.SetProcessDpiAwarenessContext(-4):
            return 'per_monitor_v2'
    except (AttributeError, OSError):
        pass
    try:
        import ctypes
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return 'per_monitor'
    except (AttributeError, OSError):
        pass
    user32.SetProcessDPIAware()
    return 'system'
