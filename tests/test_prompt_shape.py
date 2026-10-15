import unittest
import cv2
import numpy as np
from prompt_shape import find_discs, DiscTrack


def scene(center=None, diameter=54, letter=True):
    image = np.full((1110, 1630, 3), 30, np.uint8)
    if center is not None:
        cv2.circle(image, center, diameter//2, (255, 255, 255), -1)
        if letter:
            x, y = center
            cv2.rectangle(image, (x-9, y-11), (x+9, y-6), (20, 20, 20), -1)
            cv2.rectangle(image, (x-3, y-11), (x+3, y+12), (20, 20, 20), -1)
    return image


class PromptShapeTest(unittest.TestCase):
    def test_key_disc_is_found_at_its_centre(self):
        (x, y), = find_discs(scene((740, 430)))
        self.assertLess(abs(x-740)+abs(y-430), 6)

    def test_smaller_distant_prompt_is_found(self):
        self.assertEqual(len(find_discs(scene((300, 300), diameter=37))), 1)

    def test_plain_white_blob_without_key_letter_is_ignored(self):
        self.assertEqual(find_discs(scene((740, 430), letter=False)), [])

    def test_white_bar_is_ignored(self):
        image = scene()
        cv2.rectangle(image, (100, 100), (260, 140), (255, 255, 255), -1)
        self.assertEqual(find_discs(image), [])

    def test_track_reports_settled_only_after_disc_stops(self):
        track = DiscTrack()
        for step, at in enumerate((0, .03, .06, .09)):
            track.observe([(500+20*step, 400)], at)
        self.assertFalse(track.settled(.09))
        track.observe([(561, 400)], .12)
        self.assertFalse(track.settled(.12))
        track.observe([(562, 401)], .2)
        self.assertTrue(track.settled(.2))
        track.observe([(620, 450)], .23)
        self.assertFalse(track.settled(.23))

    def test_track_rejects_unrelated_disc_far_from_ocr_prompt(self):
        track = DiscTrack()
        track.reset(near=(1200, 600))
        self.assertIsNone(track.observe([(200, 200)], 0))
        self.assertEqual(track.observe([(200, 200), (1150, 610)], .03), (1150, 610))


if __name__ == '__main__':
    unittest.main()
