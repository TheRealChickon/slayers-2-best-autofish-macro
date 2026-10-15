"""Bounded, opt-in fishing-title setup from the visible Titles screen."""
import re
from difflib import SequenceMatcher
import numpy as np


# Fishing title buffs read in game on 2026-10-15. Luck matters most for rare drops,
# so the three luck titles lead; ties preserve the user's current loadout.
# Unknown/new titles are never guessed.
TITLE_BUFFS = {'Salvager': {'fishing_luck': 1.08}, 'Legendary Fisherman': {'fishing_luck': 1.07, 'bite_speed': 1.05},
               'Leviathan Hunter': {'fishing_luck': 1.05}, 'Deep Water Angler': {'bite_speed': 1.05},
               'Angler': {'bite_speed': 1.03}}
PRIORITY = ('Salvager', 'Legendary Fisherman', 'Leviathan Hunter',
            'Deep Water Angler', 'Angler')
SLOTS = ('One', 'Two', 'Three')


def normalized(value):
    return re.sub(r'[^a-z]', '', value.lower())


def matching_title(value):
    clean=normalized(value)
    for title in PRIORITY:
        if normalized(title) in clean:return title
    ranked=sorted(((SequenceMatcher(None,normalized(title),clean).ratio(),title)
                   for title in PRIORITY),reverse=True)
    if ranked and ranked[0][0]>.83 and (len(ranked)==1 or ranked[0][0]-ranked[1][0]>.12):
        return ranked[0][1]
    return None


def slot_titles(rows):
    """Require a title immediately above each numbered slot; unknowns are kept."""
    result={}
    for row in rows:
        word=normalized(row['text'])
        if word not in ('one','two','three'):continue
        slot=word.title();sx,sy=row['center']
        candidates=[r for r in rows if 0 < sy-r['center'][1] < 75 and abs(sx-r['center'][0]) < 105]
        candidates.sort(key=lambda r:r['center'][0])
        result[slot]=(matching_title(' '.join(r['text'] for r in candidates)) if candidates else None,
                      (sx,sy-36))
    return result


def owned_check(frame, requirement_y):
    """The completed requirement has a white check at the right end of its bar."""
    if frame.shape[:2]!=(1440,2560):return False
    white=np.all(frame[requirement_y+45:requirement_y+165,2248:2283]>195,axis=2)
    if white.shape!=(120,35):return False
    return max((int(white[y:y+34].sum()) for y in range(0,87,4)),default=0)>130


def desired_titles(owned):
    return tuple(name for name in PRIORITY if name in owned)[:3]


class TitleManager:
    def __init__(self,driver):
        self.driver=driver

    def rows(self,box=None):
        return self.driver.text(self.driver.capture(),box)

    def named(self,rows,name,pattern=None):
        want=normalized(name)
        found=[r for r in rows if (re.fullmatch(pattern,r['text'].strip(),re.I) if pattern else want==normalized(r['text']))]
        if len(found)!=1:raise ValueError(f'Fishing title screen did not show one {name}; read {[r["text"] for r in rows][:24]}')
        return found[0]

    def slots(self):
        rows=self.rows((1120,1070,1050,170))
        slots=slot_titles(rows)
        if set(slots)!=set(SLOTS):raise ValueError('Fishing title slots are not readable')
        return slots

    def shows(self,rows,title):
        header=' '.join(r['text'] for r in rows if r['center'][1]<450)
        return normalized(title) in normalized(header) or matching_title(header)==title

    def inspect(self,title):
        d=self.driver
        frame=d.capture()
        rows=d.text(frame,(1980,320,560,700))
        # Clicking the title that is already open closes its detail panel.
        if not self.shows(rows,title):
            title_row=self.named(self.rows((600,340,1500,300)),title)
            d.click(*title_row['center']);d.sleep(.45)
            frame=d.capture()
            rows=d.text(frame,(1980,320,560,700))
        if not self.shows(rows,title):
            raise ValueError(f'Fishing title detail changed for {title}')
        requirement=self.named(rows,'Requirements')
        return owned_check(frame,requirement['center'][1])

    def run(self):
        d=self.driver
        d.key('M');d.sleep(.6)
        try:
            # Titles moved under Progression in the menu sidebar (2026-10).
            rows=self.rows((0,380,420,700))
            if not any(normalized(r['text'])=='titles' for r in rows):
                d.click(*self.named(rows,'Progression')['center'])
                d.sleep(.45)
                rows=self.rows((0,380,420,700))
            titles=self.named(rows,'Titles')['center']
            for _ in range(3):
                d.click(*titles);d.sleep(.7)
                categories=self.rows((360,300,460,820))
                # The Titles screen has Combat/Ouwigahara categories; the inventory does not.
                if any(normalized(r['text']).startswith(('combat','ouwigahara')) for r in categories):break
            else:raise ValueError('Titles screen did not open')
            d.click(*self.named(categories,'Fishing',r'Fishing\s*[\(\[]?\s*\d*\s*[\)\]]?')['center'])
            d.sleep(.55)
            frame=d.capture()
            listing=d.text(frame,(600,340,1500,300))
            if any(sum(normalized(t)==normalized(r['text']) for r in listing) != 1 for t in PRIORITY):
                raise ValueError('Fishing title list changed; read '+str([r['text'] for r in listing]))
            owned={title for title in PRIORITY if self.inspect(title)}
            chosen=desired_titles(owned)
            slots=self.slots()
            current={name for name,_ in slots.values() if name}
            d.event('fishing_titles_checked',owned=list(owned),equipped=list(current),best=list(chosen))
            if current==set(chosen):return
            if len(chosen)<3:
                d.event('fishing_titles_kept',reason='Fewer than three known fishing titles are owned')
                return
            # A partially read loadout could contain a non-fishing title. Keep
            # it rather than clearing a slot that cannot be restored by name.
            if any(name is None for name,_ in slots.values()):
                d.event('fishing_titles_kept',reason='An equipped title could not be identified')
                return
            # Current game UI: select the wanted title, click the slot to replace,
            # then Equip swaps it in directly (2026-10-15).
            missing=[title for title in chosen if title not in current]
            for slot,(name,_) in list(slots.items()):
                if name in chosen or not missing:continue
                title=missing.pop(0)
                if not self.inspect(title):raise ValueError(f'{title} ownership changed during setup')
                d.click(*self.slots()[slot][1])
                d.sleep(.45)
                button=self.named(self.rows((1150,1160,430,105)),'Equip')
                d.click(*button['center'])
                d.sleep(.6)
                if self.slots()[slot][0]!=title:
                    raise ValueError(f'{title} did not equip into slot {slot}')
            d.event('fishing_titles_equipped',best=list(chosen))
        finally:
            # Menu close is always attempted so a failed optional setup cannot
            # leave the full farmer clicking inside its own menu.
            try:d.key('M');d.sleep(.25)
            except Exception:pass
