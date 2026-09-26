"""Bounded, opt-in fishing-title setup from the visible Titles screen."""
import re
from difflib import SequenceMatcher
import numpy as np


# Observed fishing buffs in this game version. Luck matters most for rare drops;
# ties preserve the user's current loadout. Unknown/new titles are never guessed.
PRIORITY = ('Legendary Fisherman', 'Salvager', 'Leviathan Hunter',
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

    def named(self,rows,name):
        want=normalized(name)
        found=[r for r in rows if want==normalized(r['text'])]
        if len(found)!=1:raise ValueError(f'Fishing title screen did not show one {name}')
        return found[0]

    def slots(self):
        rows=self.rows((1120,1070,1050,170))
        slots=slot_titles(rows)
        if set(slots)!=set(SLOTS):raise ValueError('Fishing title slots are not readable')
        return slots

    def inspect(self,title):
        d=self.driver
        title_row=self.named(self.rows((690,340,1370,260)),title)
        d.click(*title_row['center']);d.sleep(.45)
        frame=d.capture()
        rows=d.text(frame,(1980,320,560,700))
        header=[r['text'] for r in rows if r['center'][1]<450]
        if not (normalized(title) in normalized(' '.join(header)) or
                matching_title(' '.join(header))==title):
            raise ValueError(f'Fishing title detail changed for {title}')
        requirement=self.named(rows,'Requirements')
        return owned_check(frame,requirement['center'][1])

    def run(self):
        d=self.driver
        d.key('M');d.sleep(.25)
        try:
            d.click(*self.named(self.rows(),'Titles')['center'])
            d.sleep(.45)
            d.click(*self.named(self.rows(),'Fishing (5)')['center'])
            d.sleep(.55)
            frame=d.capture()
            listing=d.text(frame,(700,340,1350,260))
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
            for slot,(name,point) in slots.items():
                if name in chosen:continue
                # The slot action appears only when its title detail is open.
                self.inspect(name)
                point=self.slots()[slot][1]
                d.click(*point)
                d.sleep(.45)
                button=self.named(self.rows((1150,1160,430,105)),'Unequip')
                d.click(*button['center'])
                d.sleep(.45)
                after=self.slots()
                if after[slot][0] is not None:
                    raise ValueError(f'Could not free fishing title slot {slot}')
            for title in chosen:
                if title in current:continue
                if not self.inspect(title):raise ValueError(f'{title} ownership changed during setup')
                button=self.named(self.rows((1150,1160,430,105)),'Equip')
                d.click(*button['center'])
                d.sleep(.45)
                if title not in {name for name,_ in self.slots().values()}:
                    raise ValueError(f'{title} did not equip')
            d.event('fishing_titles_equipped',best=list(chosen))
        finally:
            # Menu close is always attempted so a failed optional setup cannot
            # leave the full farmer clicking inside its own menu.
            try:d.key('M');d.sleep(.25)
            except Exception:pass
