"""Read the game's combo indicator and the C skill's cooldown overlay."""

import re

import cv2


# Coordinates are in ScreenSpace's 2560 x 1440 client view. The combo number
# sits at the left of the ornamental ring, so the ring is excluded from OCR.
COMBO_BOX = (490, 680, 160, 120)
C_ICON_BOX = (1205, 1280, 45, 45)


def hotbar_visible(frame):
    """Wait for the playable HUD after a respawn before touching a slot."""
    if frame.shape[:2] != (1440, 2560):
        return False
    gray = cv2.cvtColor(frame[1340:1430, 1050:1530], cv2.COLOR_BGR2GRAY)
    return bool((gray > 180).mean() > .003)


def gauntlet_selected(frame):
    """The fighting-style action bar is present only while a weapon is out.

    The hotbar's selection ring can be hidden by the statue or camera motion,
    so it must not be used to decide whether pressing 1 will toggle the weapon.
    """
    if frame.shape[:2] != (1440, 2560):
        return False
    gray = cv2.cvtColor(frame[1260:1335, 1025:1540], cv2.COLOR_BGR2GRAY)
    return bool((gray > 180).mean() > .02)


def crop(frame, box):
    x, y, width, height = box
    return frame[y:y+height, x:x+width]


def combo_count(frame, ocr):
    roi = crop(frame, COMBO_BOX)
    if roi.size == 0:
        return None
    rows, _ = ocr(cv2.resize(roi, None, fx=2.5, fy=2.5), use_cls=False)
    numbers = []
    for row in rows or []:
        text = str(row[1]).strip().replace(' ', '')
        if float(row[2]) >= .76 and re.fullmatch(r'\d{1,5}', text):
            number = int(text)
            if 0 < number < 100000:
                numbers.append(number)
    return max(numbers, default=None)


def c_icon(frame):
    return cv2.cvtColor(crop(frame, C_ICON_BOX), cv2.COLOR_BGR2GRAY)


class SkillReady:
    def __init__(self):
        self.reference = None

    def observe(self, frame):
        icon = c_icon(frame)
        if icon.shape != (45, 45):
            return False
        bright = float((icon > 180).mean())
        if self.reference is None:
            if bright < .075:
                return False
            self.reference = icon.copy()
            return True
        # A cooldown cover can contain bright numbers; the full icon must
        # match the learned ready art before another C press is allowed.
        reference_bright = float((self.reference > 180).mean())
        if bright < max(.055, reference_bright*.72):
            return False
        score = cv2.matchTemplate(icon, self.reference, cv2.TM_CCOEFF_NORMED)[0, 0]
        return bool(score >= .82)


def scene_text(frame, ocr):
    # This slower OCR is sampled outside the fast attack loop.
    smaller = cv2.resize(frame[150:1200, 370:2210], (920, 525))
    rows, _ = ocr(smaller, use_cls=False)
    return ' '.join(str(row[1]).lower() for row in rows or [] if float(row[2]) >= .65)


def blocked_scene(frame, ocr):
    text = scene_text(frame, ocr)
    return any(phrase in text for phrase in ('disconnected', 'connection lost', 'error code',
        'main menu', 'private server', 'reset character', 'respawn', 'are you sure',
        'leave game', 'resume experience', 'purchase', 'search titles',
        'inventory', 'archives', 'skill tree', 'settings'))
