"""A notification-area (tray) icon for the app window, using only pywin32.

Left-click (or double-click) opens the window again; right-click shows Open / Quit.
The icon runs its own hidden message window on a background thread.
"""
import threading

WM_TRAY = 0x8000+20  # WM_APP + 20
OPEN, QUIT = 1001, 1002


class Tray:
    def __init__(self, icon_path, tooltip, on_open, on_quit):
        self.icon_path, self.tooltip = str(icon_path), tooltip[:120]
        self.on_open, self.on_quit = on_open, on_quit
        self.hwnd = None
        self._ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name='Autofish tray')

    def start(self):
        self.thread.start()
        self._ready.wait(5)
        return self

    def stop(self):
        import win32con, win32gui
        if self.hwnd:
            try: win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception: pass
        if self.thread.is_alive() and threading.current_thread() is not self.thread: self.thread.join(3)

    def _menu(self):
        import win32con, win32gui
        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, OPEN, 'Open Autofish')
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, '')
        win32gui.AppendMenu(menu, win32con.MF_STRING, QUIT, 'Quit')
        x, y = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self.hwnd)  # lets the menu close when clicking elsewhere
        win32gui.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN, x, y, 0, self.hwnd, None)
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)

    def _run(self):
        import win32api, win32con, win32gui
        name = f'AutofishTray-{id(self)}'
        instance = win32api.GetModuleHandle(None)

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_TRAY:
                if lparam in (win32con.WM_LBUTTONUP, win32con.WM_LBUTTONDBLCLK): self.on_open()
                elif lparam == win32con.WM_RBUTTONUP: self._menu()
                return 0
            if msg == win32con.WM_COMMAND:
                if win32api.LOWORD(wparam) == OPEN: self.on_open()
                elif win32api.LOWORD(wparam) == QUIT: self.on_quit()
                return 0
            if msg == win32con.WM_CLOSE:
                try: win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, 0))
                except Exception: pass
                win32gui.DestroyWindow(hwnd)
                return 0
            if msg == win32con.WM_DESTROY:
                win32gui.PostQuitMessage(0)
                return 0
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        wc = win32gui.WNDCLASS(); wc.hInstance = instance; wc.lpszClassName = name; wc.lpfnWndProc = wndproc
        win32gui.RegisterClass(wc)
        try:
            self.hwnd = win32gui.CreateWindow(name, 'Autofish tray', 0, 0, 0, 0, 0, 0, 0, instance, None)
            try:
                icon = win32gui.LoadImage(instance, self.icon_path, win32con.IMAGE_ICON, 0, 0,
                                          win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE)
            except Exception:
                icon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, (self.hwnd, 0, flags, WM_TRAY, icon, self.tooltip))
            self._ready.set()
            win32gui.PumpMessages()
        finally:
            self._ready.set()
            self.hwnd = None
            try: win32gui.UnregisterClass(name, instance)
            except Exception: pass
