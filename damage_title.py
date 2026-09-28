"""Read the combat title's displayed damage total through the existing inventory driver."""

import re


def normalized(value):
    return re.sub(r'[^a-z0-9]', '', value.casefold())


def progress_from_rows(rows, title, target):
    """Accept one unambiguous current/target pair from a verified title detail."""
    words = [str(row['text']) for row in rows if row['score'] >= .70]
    header = ' '.join(row['text'] for row in rows if row['score'] >= .70 and row['center'][1] < 470)
    if normalized(title) not in normalized(header):
        raise ValueError('Configured damage title was not verified in the detail panel')
    if 'requirement' not in ' '.join(words).casefold():
        raise ValueError('Damage title Requirements panel was not verified')
    joined = ' '.join(words)
    pairs = re.findall(r'(?<!\d)(\d[\d,.]*?)\s*/\s*(\d[\d,.]*)(?!\d)', joined)
    values = set()
    # The live title panel shows a requirement and a separate remaining count.
    requirements = re.findall(r'Deal\s+([\d,]+)\s+total\s+damage', joined, re.I)
    remaining = re.findall(r'(?<!\d)(\d[\d,]*)\s+left\b', joined, re.I)
    if len(requirements) == 1 and int(requirements[0].replace(',', '')) == target:
        for value in remaining:
            left = int(value.replace(',', ''))
            if 0 <= left <= target:
                values.add(target-left)
    for current, total in pairs:
        try:
            pair = int(re.sub(r'\D', '', current)), int(re.sub(r'\D', '', total))
        except ValueError:
            continue
        if pair[1] == target and 0 <= pair[0] <= target:
            values.add(pair[0])
    if len(values) != 1:
        raise ValueError('Damage title progress is unreadable or ambiguous; inspect the visible title')
    return values.pop()


class DamageTitleReader:
    """InventoryDriver supplies guarded capture, click and key methods."""

    def __init__(self, driver, title, target, category='Combat'):
        self.driver, self.title, self.target, self.category = driver, title, target, category

    def rows(self, box=None):
        d = self.driver
        x, y, w, h = box or (0, 0, 2560, 1440)
        import cv2
        frame = d.capture()[y:y+h, x:x+w]
        if box is None:
            frame = cv2.resize(frame, (1280, 720))
            scale = 2
        else:
            scale = 1
        raw = d.text(frame, min_confidence=.70)
        return [{'text': str(row[1]), 'score': float(row[2]),
                 'center': (int(x+sum(p[0] for p in row[0])/4*scale),
                            int(y+sum(p[1] for p in row[0])/4*scale))} for row in raw]

    def click_named(self, name, box=None, category=False):
        want = normalized(name)
        for attempt in range(3):
            found = [row for row in self.rows(box) if
                     (re.fullmatch(re.escape(want)+r'\d+', normalized(row['text'])) if category
                      else normalized(row['text']) == want)]
            if len(found) == 1:
                break
            self.driver.sleep(.4)
        if len(found) != 1:
            raise ValueError(f'Expected one visible {name} control in the title menu')
        self.driver.click(*found[0]['center'])
        self.driver.sleep(.35)

    def inspect(self):
        d = self.driver
        from damage_vision import hotbar_visible
        sidebar = (0, 610, 320, 180)
        def menu_visible():
            return any(normalized(row['text']) == 'titles' for row in self.rows(sidebar))
        try:
            for attempt in range(3):
                if menu_visible():
                    break
                # A late skill animation can swallow M. Retry only from the
                # verified gameplay HUD, never blindly toggle an unknown menu.
                if hotbar_visible(d.capture()):
                    d.key('M')
                d.sleep(.8)
            self.click_named('Titles', (0, 610, 320, 180))
            self.click_named(self.category, (320, 250, 450, 620), category=True)
            self.click_named(self.title, (640, 320, 1340, 750))
            rows = self.rows((1980, 310, 570, 760))
            return progress_from_rows(rows, self.title, self.target)
        finally:
            # The driver rechecks stop, focus and window bounds before closing.
            if menu_visible():
                d.key('M'); d.sleep(.8)
            d.move(1280, 690)
