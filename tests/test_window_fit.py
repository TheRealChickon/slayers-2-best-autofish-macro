import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from screen_space import ScreenSpace, client_problem
import window_fit
from window_fit import plan_window, frame_of, fit_window, fitted, WindowFitError

# Windows 10/11 window borders around the client (invisible resize border + title bar).
FRAME_100 = (8, 31, 8, 8)
FRAME_150 = (11, 45, 11, 11)


class FakeWindow:
    """A Roblox Player window as win32gui/win32api report it."""

    def __init__(self, monitor, work, client, frame=FRAME_100, maximized=False, fullscreen=False):
        self.monitor, self.work, self.frame = monitor, work, frame
        self.maximized, self.fullscreen = maximized, fullscreen
        self.set_client(*client)
        self.moves = []

    def set_client(self, left, top, width, height):
        self.client = (left, top, left+width, top+height)

    def window(self):
        if self.fullscreen:
            return self.monitor
        fl, ft, fr, fb = self.frame
        l, t, r, b = self.client
        return l-fl, t-ft, r+fr, b+fb

    def modules(self):
        win = self
        gui = types.SimpleNamespace(
            GetClientRect=lambda h: (0, 0, win.client[2]-win.client[0], win.client[3]-win.client[1]),
            ClientToScreen=lambda h, p: (win.client[0]+p[0], win.client[1]+p[1]),
            GetWindowRect=lambda h: win.window(),
            GetWindowLong=lambda h, i: 0 if win.fullscreen else window_fit.WS_CAPTION,
            GetWindowPlacement=lambda h: (0, window_fit.SW_SHOWMAXIMIZED if win.maximized else 1),
            ShowWindow=win.show, SetWindowPos=win.move)
        api = types.SimpleNamespace(MonitorFromWindow=lambda h, f: 1,
                                    GetMonitorInfo=lambda m: {'Monitor': win.monitor, 'Work': win.work})
        return {'win32gui': gui, 'win32api': api}

    def show(self, hwnd, command):
        if command == window_fit.SW_RESTORE:
            self.maximized = False
            self.set_client(200, 150, 900, 500)

    def move(self, hwnd, insert_after, left, top, width, height, flags):
        self.moves.append((left, top, width, height))
        fl, ft, fr, fb = self.frame
        self.set_client(left+fl, top+ft, width-fl-fr, height-ft-fb)

    def leave_fullscreen(self):
        self.fullscreen = False
        self.set_client(200, 150, 1100, 620)


def run_fit(window, **options):
    with patch.dict(sys.modules, window.modules()):
        return fit_window(1, sleep=lambda s: None, **options)


def size(rect):
    return rect[2]-rect[0], rect[3]-rect[1]


class Planning(unittest.TestCase):
    # (screen, work area, frame): typical monitors, taskbar at the bottom.
    SCREENS = {
        '1366x768 laptop': ((0, 0, 1366, 728), FRAME_100),
        '1280x720': ((0, 0, 1280, 680), FRAME_100),
        '1600x900': ((0, 0, 1600, 860), FRAME_100),
        '1920x1080': ((0, 0, 1920, 1040), FRAME_100),
        '1920x1080 at 150%': ((0, 0, 1920, 1032), FRAME_150),
        '1920x1200 16:10': ((0, 0, 1920, 1160), FRAME_100),
        '2560x1440 at 125%': ((0, 0, 2560, 1390), (10, 39, 10, 10)),
        '2560x1600 16:10': ((0, 0, 2560, 1560), FRAME_100),
        '3440x1440 ultrawide': ((0, 0, 3440, 1400), FRAME_100),
        '1280x1024 5:4': ((0, 0, 1280, 984), FRAME_100),
        '1024x768 4:3': ((0, 0, 1024, 728), FRAME_100),
        'second monitor': ((2560, -200, 4480, 880), FRAME_100),
    }

    def test_every_common_screen_gets_a_readable_centred_16_9_client(self):
        for name, (work, frame) in self.SCREENS.items():
            with self.subTest(name):
                left, top, width, height = plan_window(work, frame)
                client_w, client_h = width-frame[0]-frame[2], height-frame[1]-frame[3]
                self.assertIsNone(client_problem(client_w, client_h))
                self.assertLessEqual(abs(client_w/client_h-16/9), .002)
                # Inside the work area, and as large as the tighter side allows.
                self.assertGreaterEqual(left, work[0])
                self.assertGreaterEqual(top, work[1])
                self.assertLessEqual(left+width, work[2])
                self.assertLessEqual(top+height, work[3])
                self.assertTrue(work[2]-work[0]-width < 20 or work[3]-work[1]-height < 3, name)
                self.assertLessEqual(abs((left+width/2)-(work[0]+work[2])/2), 1)
                ScreenSpace((0, 0, client_w, client_h))

    def test_laptop_gets_a_much_bigger_window_than_the_minimum(self):
        _, _, width, height = plan_window((0, 0, 1366, 728), FRAME_100)
        self.assertEqual((width-16, height-39), (1225, 689))

    def test_screens_too_small_for_the_minimum_are_refused(self):
        self.assertIsNone(plan_window((0, 0, 1024, 560), FRAME_100))
        self.assertIsNone(plan_window((0, 0, 900, 700), FRAME_100))

    def test_frame_is_measured_from_window_and_client(self):
        self.assertEqual(frame_of((92, 119, 1708, 1028), (100, 150, 1700, 1020)), (8, 31, 8, 8))


class ClientShapes(unittest.TestCase):
    def test_messages_name_the_size_and_the_fix(self):
        self.assertIn('1366 × 705', client_problem(1366, 705))
        self.assertIn('16:9', client_problem(1366, 705))
        self.assertIn('minimum', client_problem(800, 450))
        for ok in [(2560, 1440), (2560, 1369), (1920, 1009), (1366, 768), (1225, 689), (960, 540)]:
            self.assertIsNone(client_problem(*ok), ok)
        for bad in [(1366, 705), (1920, 1200), (1280, 1024), (3440, 1440), (959, 540)]:
            self.assertIsNotNone(client_problem(*bad), bad)


class Fitting(unittest.TestCase):
    def test_16_9_window_is_left_alone(self):
        window = FakeWindow((0, 0, 2560, 1440), (0, 0, 2560, 1400), (300, 200, 1600, 900))
        self.assertEqual(size(run_fit(window)), (1600, 900))
        self.assertEqual(window.moves, [])
        self.assertEqual(fitted(1, (0, 0, 1600, 900)), (0, 0, 1600, 900))

    def test_maximized_laptop_window_is_restored_and_resized(self):
        window = FakeWindow((0, 0, 1366, 768), (0, 0, 1366, 728), (0, 23, 1366, 705), maximized=True)
        events = []
        rect = run_fit(window, event=lambda kind, **kw: events.append((kind, kw)))
        self.assertFalse(window.maximized)
        self.assertEqual(size(rect), (1225, 689))
        self.assertEqual(events[0][0], 'client_fitted')
        ScreenSpace(rect)

    def test_16_10_fullscreen_uses_f11_then_resizes(self):
        window = FakeWindow((0, 0, 1920, 1200), (0, 0, 1920, 1160), (0, 0, 1920, 1200), fullscreen=True)
        rect = run_fit(window, press_f11=window.leave_fullscreen)
        self.assertEqual(size(rect), (1904, 1071))
        ScreenSpace(rect)

    def test_fullscreen_without_permission_explains_f11(self):
        window = FakeWindow((0, 0, 1920, 1200), (0, 0, 1920, 1160), (0, 0, 1920, 1200), fullscreen=True)
        with self.assertRaisesRegex(WindowFitError, 'F11'):
            run_fit(window)
        self.assertEqual(window.moves, [])

    def test_tiny_screen_reports_what_to_change(self):
        window = FakeWindow((0, 0, 1024, 600), (0, 0, 1024, 560), (0, 0, 800, 520))
        with self.assertRaisesRegex(WindowFitError, 'too small'):
            run_fit(window)


if __name__ == '__main__':
    unittest.main()
