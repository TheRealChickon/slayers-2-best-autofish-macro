"""Real game frames, re-rendered at the client sizes players actually have.

Each fixture is a frame from a live fishing recording. It is scaled to a client
size, placed at a window offset on a fake desktop, then read back through
ScreenSpace exactly as the farmer does. The vision results must match what the
same frame gives at the 2560 x 1440 reference. Fixtures named ``*-1440`` are
native captures; ``*-480`` frames come from a downscaled recording.
"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import cv2
import numpy as np
from screen_space import ScreenSpace
from fishing_vision import detect
from rod_detector import locate_rod
from window_fit import plan_window

FIXTURES = Path(__file__).resolve().parent/'fixtures'/'game'
MINIGAME_BOX = (1850, 400, 140, 600)
FRAME = (8, 31, 8, 8)

# Fullscreen 16:9 screens, maximized 16:9 windows (title bar + taskbar), and the
# windows window_fit gives laptops, 16:10, 5:4, 4:3, ultrawide and 150 % screens.
SIZES = sorted({
    (960, 540), (1280, 720), (1366, 768), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160),
    (1920, 1009), (2560, 1369),
    *[(w-FRAME[0]-FRAME[2], h-FRAME[1]-FRAME[3]) for w, h in (
        plan_window(work, FRAME)[2:] for work in (
            (0, 0, 1366, 728), (0, 0, 1920, 1160), (0, 0, 1280, 984), (0, 0, 1024, 728),
            (0, 0, 3440, 1400), (0, 0, 2560, 1560)))],
    (1735, 976),  # 1920 x 1080 at 150 % with its thicker frame
})


class Desktop:
    """An mss stand-in: a desktop image with the Roblox client drawn at an offset."""

    def __init__(self, client, offset):
        h, w = client.shape[:2]
        self.pixels = np.zeros((h+offset[1]+40, w+offset[0]+40, 3), np.uint8)
        self.pixels[offset[1]:offset[1]+h, offset[0]:offset[0]+w] = client

    def grab(self, region):
        x, y = region['left'], region['top']
        return self.pixels[y:y+region['height'], x:x+region['width']]


def fixtures(prefix):
    found = sorted(FIXTURES.glob(prefix+'-*.*'))
    if not found:
        raise unittest.SkipTest('no '+prefix+' fixtures')
    return [(path.stem, cv2.imread(str(path))) for path in found]


def reference(image):
    return cv2.resize(image, (2560, 1440), interpolation=cv2.INTER_CUBIC)


def as_client(image, size, offset=(13, 47)):
    """What ScreenSpace reads when Roblox shows ``image`` at ``size``."""
    interpolation = cv2.INTER_AREA if size[0] < image.shape[1] else cv2.INTER_CUBIC
    client = cv2.resize(image, size, interpolation=interpolation)
    screen = ScreenSpace((offset[0], offset[1], offset[0]+size[0], offset[1]+size[1]))
    return screen, Desktop(client, offset)


class MinigameAtEverySize(unittest.TestCase):
    def test_bar_and_marker_match_the_reference(self):
        for name, image in fixtures('minigame'):
            x, y, w, h = MINIGAME_BOX
            expected = detect(reference(image)[y:y+h, x:x+w])
            self.assertIsNotNone(expected, name)
            for size in SIZES:
                with self.subTest(name=name, size=size):
                    screen, desktop = as_client(image, size)
                    found = detect(screen.capture(desktop, MINIGAME_BOX))
                    self.assertIsNotNone(found)
                    self.assertAlmostEqual(found['target'], expected['target'], delta=8)
                    self.assertAlmostEqual(found['ball'], expected['ball'], delta=8)
                    self.assertEqual(found['inside'], expected['inside'])


class HotbarAtEverySize(unittest.TestCase):
    def test_rod_is_found_in_the_same_slot(self):
        for name, image in fixtures('hotbar'):
            expected = locate_rod(reference(image))
            self.assertIsNotNone(expected, name)
            for size in SIZES:
                with self.subTest(name=name, size=size):
                    screen, desktop = as_client(image, size)
                    found = locate_rod(screen.capture(desktop))
                    self.assertIsNotNone(found)
                    self.assertEqual(found['name'], expected['name'])
                    self.assertLessEqual(abs(found['x']-expected['x']), 10)
                    self.assertLessEqual(abs(found['y']-expected['y']), 10)


class Coordinates(unittest.TestCase):
    def test_clicks_land_on_the_same_game_spot_at_every_size(self):
        for size in SIZES:
            with self.subTest(size=size):
                screen = ScreenSpace((100, 60, 100+size[0], 60+size[1]))
                x, y = screen.point(1650, 800)  # default cast point
                self.assertAlmostEqual((x-100)/size[0], 1650/2560, delta=1.5/size[0])
                self.assertAlmostEqual((y-60)/size[1], 800/1440, delta=1.5/size[1])


if __name__ == '__main__':
    unittest.main()
