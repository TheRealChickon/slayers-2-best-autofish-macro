"""A cast target in the game's resolution-independent 2560 x 1440 space."""

DEFAULT = (1650, 800)
SAFE_X = (260, 2240)
SAFE_Y = (160, 1240)


def validate(value):
    try:
        if isinstance(value, str):
            value = value.replace(',', ' ').split()
        if len(value) != 2:
            raise ValueError
        x, y = (int(part) for part in value)
    except (TypeError, ValueError):
        raise ValueError('Enter X, Y in the 2560 x 1440 game view') from None
    if not (SAFE_X[0] <= x <= SAFE_X[1] and SAFE_Y[0] <= y <= SAFE_Y[1]):
        raise ValueError('Cast point must be over the game world, away from the hotbar and menus')
    return [x, y]


def capture_pointer():
    """Read the pointer over Roblox; never focus the game or send input."""
    import win32gui
    from fishing_assistant import find_window, rectangle
    from screen_space import ScreenSpace

    hwnd = find_window()
    pointer = win32gui.GetCursorPos()
    if win32gui.GetAncestor(win32gui.WindowFromPoint(pointer), 2) != hwnd:
        raise ValueError('Place the pointer over the Roblox game world and try again')
    screen = ScreenSpace(rectangle(hwnd))
    x = round((pointer[0] - screen.rect[0]) / screen.sx)
    y = round((pointer[1] - screen.rect[1]) / screen.sy)
    return validate((x, y))
