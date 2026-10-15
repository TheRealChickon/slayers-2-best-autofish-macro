"""Automatic colour adaptation of the minigame reader on real, tinted frames."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from fishing_vision import SceneColors, detect
from test_resolution_fixtures import MINIGAME_BOX, as_client, fixtures, reference


def multiply(gains):
    return lambda roi: np.clip(roi*np.array(gains), 0, 255).astype(np.uint8)


def overlay(color, alpha):
    return lambda roi: np.clip(roi*(1-alpha)+np.array(color)*alpha*roi.mean()/128, 0, 255).astype(np.uint8)


# Colour casts a player can meet: red skies/events, night, fog, green water light.
TINTS = {
    'red sky': multiply((.35, .4, 1.4)),
    'deep red': multiply((.25, .3, 1.5)),
    'red overlay': overlay((30, 30, 230), .7),
    'night': multiply((.45, .45, .5)),
    'dark night': multiply((.3, .3, .32)),
    'blue night': multiply((.9, .6, .45)),
    'green light': multiply((.6, 1.2, .6)),
}
SIZES = [(960, 540), (1225, 689), (1920, 1080), (2560, 1440)]


def daylight():
    """Minigame fixtures filmed in daylight (the native capture is at night)."""
    return [(name, image) for name, image in fixtures('minigame') if name != 'minigame-1440']


def box(image, size):
    screen, desktop = as_client(image, size)
    return screen.capture(desktop, MINIGAME_BOX)


class TintedMinigame(unittest.TestCase):
    def test_tinted_scenes_read_like_daylight(self):
        for name, image in fixtures('minigame'):
            x, y, w, h = MINIGAME_BOX
            expected = detect(reference(image)[y:y+h, x:x+w])
            for size in SIZES:
                daylight = box(image, size)
                for tint, apply in TINTS.items():
                    with self.subTest(name=name, size=size, tint=tint):
                        events = []
                        colors = SceneColors(lambda kind, **kw: events.append(kind))
                        found = None
                        for _ in range(3):  # a few frames, as during a round
                            found = colors.detect(apply(daylight))
                        self.assertIsNotNone(found)
                        self.assertAlmostEqual(found['target'], expected['target'], delta=8)
                        self.assertAlmostEqual(found['ball'], expected['ball'], delta=8)
                        self.assertEqual(found['inside'], expected['inside'])
                        self.assertEqual(events, ['colors_adjusted'])

    def test_daylight_is_left_unchanged(self):
        for name, image in daylight():
            roi = box(image, (2560, 1440))
            events = []
            colors = SceneColors(lambda kind, **kw: events.append(kind))
            self.assertEqual(colors.detect(roi), detect(roi))
            self.assertFalse(colors.adjusted)
            self.assertEqual(events, [])

    def test_native_night_scene_is_brightened_and_still_reads_right(self):
        # A real 2560 x 1440 capture at night: scenery is nearly black.
        image = dict(fixtures('minigame'))['minigame-1440']
        roi = box(image, (2560, 1440))
        expected = detect(roi)
        events = []
        colors = SceneColors(lambda kind, **kw: events.append(kind))
        for _ in range(3):
            found = colors.detect(roi)
        self.assertEqual(events, ['colors_adjusted'])
        self.assertAlmostEqual(found['target'], expected['target'], delta=8)
        self.assertAlmostEqual(found['ball'], expected['ball'], delta=8)
        self.assertEqual(found['inside'], expected['inside'])

    def test_adjustment_switches_back_when_the_scene_clears(self):
        name, image = daylight()[0]
        roi = box(image, (1920, 1080))
        events = []
        colors = SceneColors(lambda kind, **kw: events.append((kind, kw)))
        for _ in range(4):
            colors.detect(TINTS['red sky'](roi))
        for _ in range(20):
            colors.detect(roi)
        self.assertEqual([kind for kind, _ in events], ['colors_adjusted', 'colors_normal'])
        self.assertIn('message', events[0][1])
        self.assertGreater(events[0][1]['tint'], SceneColors.TINT_ON)


class NoMinigame(unittest.TestCase):
    def test_tinted_world_without_a_minigame_stays_empty(self):
        for name, image in fixtures('hotbar'):
            roi = box(image, (1920, 1080))
            for tint, apply in TINTS.items():
                with self.subTest(name=name, tint=tint):
                    colors = SceneColors()
                    for _ in range(3):
                        self.assertIsNone(colors.detect(apply(roi)))

    def test_non_image_input_goes_straight_to_the_detector(self):
        seen = []
        colors = SceneColors(detector=lambda roi: seen.append(roi) or 'raw')
        self.assertEqual(colors.detect(None), 'raw')
        self.assertEqual(seen, [None])


if __name__ == '__main__':
    unittest.main()
