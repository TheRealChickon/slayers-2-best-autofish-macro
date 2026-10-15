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


def matching_title(value,names=PRIORITY):
    """Match OCR text to a known title. `names` includes titles discovered in game."""
    clean=normalized(value)
    # Longest name first so 'Deep Water Angler' wins over 'Angler'.
    for title in sorted(names,key=lambda n:-len(normalized(n))):
        if normalized(title) and normalized(title) in clean:return title
    ranked=sorted(((SequenceMatcher(None,normalized(title),clean).ratio(),title)
                   for title in names),reverse=True)
    if ranked and ranked[0][0]>.83 and (len(ranked)==1 or ranked[0][0]-ranked[1][0]>.12):
        return ranked[0][1]
    return None


def slot_titles(rows,names=PRIORITY):
    """Require a title immediately above each numbered slot; unknowns are kept."""
    result={}
    for row in rows:
        word=normalized(row['text'])
        if word not in ('one','two','three'):continue
        slot=word.title();sx,sy=row['center']
        candidates=[r for r in rows if 0 < sy-r['center'][1] < 75 and abs(sx-r['center'][0]) < 105]
        candidates.sort(key=lambda r:r['center'][0])
        result[slot]=(matching_title(' '.join(r['text'] for r in candidates),names) if candidates else None,
                      (sx,sy-36))
    return result


TITLE_NAME = re.compile(r"[A-Za-z][A-Za-z'\- ]{3,39}")


def listed_titles(rows):
    """Title pills left of the detail panel; slot labels and categories are not titles."""
    names=[]
    for r in sorted(rows,key=lambda r:(round(r['center'][1]/20),r['center'][0])):
        text=re.sub(r'\s+',' ',r['text']).strip()
        if r['center'][0]>=2000 or not TITLE_NAME.fullmatch(text):continue
        if normalized(text) in ('one','two','three','vanity','equip','equipped','unequip','requirements','buffs'):continue
        if normalized(text) not in {normalized(n) for n in names}:names.append(text)
    return names


def canonical_title(text):
    """Repair clipped OCR of a built-in title ('Leviathan H'); any other text is a new title.
    Containment is not enough here: 'Master Angler' must not become 'Angler'."""
    clean=normalized(text)
    for title in PRIORITY:
        if normalized(title)==clean:return title
    # A pill clipped at the panel edge reads as the start of its name.
    clipped=[t for t in PRIORITY if len(clean)>=6 and normalized(t).startswith(clean)]
    if len(clipped)==1:return clipped[0]
    ranked=sorted(((SequenceMatcher(None,normalized(t),clean).ratio(),t) for t in PRIORITY),reverse=True)
    if ranked[0][0]>.83 and ranked[0][0]-ranked[1][0]>.12:return ranked[0][1]
    return text


def category_count(text):
    """6 from 'Fishing (6)'; None when the label has no count."""
    found=re.search(r'(\d+)',text or '')
    return int(found.group(1)) if found else None


def owned_check(frame, requirement_y):
    """The completed requirement has a white check at the right end of its bar."""
    if frame.shape[:2]!=(1440,2560):return False
    white=np.all(frame[requirement_y+45:requirement_y+165,2248:2283]>195,axis=2)
    if white.shape!=(120,35):return False
    return max((int(white[y:y+34].sum()) for y in range(0,87,4)),default=0)>130


BUFF_KEYS = {'fishingluckfactor': 'fishing_luck', 'fishluck': 'fishing_luck', 'bitespeedfactor': 'bite_speed',
             'bitespeedmultiplier': 'bite_speed'}
CATALOG_FILE = 'fishing-titles.json'


def parse_buffs(rows):
    """'1.07x (Fishing Luck Factor)' lines from the detail panel, in reading order."""
    text = ' '.join(r['text'] for r in sorted(rows, key=lambda r: (round(r['center'][1]/14), r['center'][0])))
    buffs = {}
    for value, name in re.findall(r'(\d+(?:\.\d+)?)\s*[x×]\s*\(([^)]*)\)?', text, re.I):
        key = BUFF_KEYS.get(normalized(name))
        if key and key not in buffs: buffs[key] = float(value)
    return buffs


def known_buffs(catalog=None):
    """Built-in buffs merged with every title the farmer has read in game."""
    merged = {name: dict(b) for name, b in TITLE_BUFFS.items()}
    for name, row in (catalog or {}).items():
        merged[name] = dict(row.get('buffs') or {})
    return merged


def desired_titles(owned, priority='luck', buffs=None):
    """Best three owned titles for the rod's priority: 'luck' or 'bite'. Ties keep PRIORITY order."""
    table = buffs or TITLE_BUFFS
    key = 'bite_speed' if priority == 'bite' else 'fishing_luck'
    other = 'fishing_luck' if key == 'bite_speed' else 'bite_speed'
    order = {name: i for i, name in enumerate(PRIORITY)}
    ranked = sorted(owned, key=lambda n: (-(table.get(n, {}).get(key, 1)), -(table.get(n, {}).get(other, 1)), order.get(n, 99), n))
    return tuple(ranked[:3])


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

    def update_catalog(self,names,owned,details):
        """Remember every fishing title's buffs; log titles seen for the first time."""
        import json,time
        from app_config import data_directory
        path=data_directory()/CATALOG_FILE
        try:catalog=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):catalog={}
        for name in names:
            buffs=details.get(name) or (catalog.get(name) or {}).get('buffs') or TITLE_BUFFS.get(name,{})
            if name not in catalog and name not in TITLE_BUFFS:
                self.driver.event('fishing_title_new',title=name,buffs=buffs,
                                  message=f"New fishing title: {name} "+', '.join(f"{v}x {k.replace('_',' ')}" for k,v in buffs.items()))
            catalog[name]={'buffs':buffs,'owned':name in owned,'seen':time.time()}
        from discord_hourly import atomic_json
        atomic_json(path,catalog)
        return catalog

    def slots(self):
        rows=self.rows((1120,1070,1050,170))
        slots=slot_titles(rows,getattr(self,'names',PRIORITY))
        if set(slots)!=set(SLOTS):raise ValueError('Fishing title slots are not readable')
        return slots

    def shows(self,rows,title):
        header=' '.join(r['text'] for r in rows if r['center'][1]<450)
        return normalized(title) in normalized(header) or matching_title(header,getattr(self,'names',PRIORITY))==title

    def listing(self,expected=None):
        """Read every title pill, scrolling the list when the tab count says some are hidden."""
        d=self.driver
        frame=d.capture()
        self.save_frame(frame)
        names=listed_titles(d.text(frame,(720,340,1300,700)))
        for _ in range(4):
            if expected is None or len(names)>=expected:break
            scroll=getattr(d,'scroll',None)
            if scroll is None:break
            scroll(1370,690,-3);d.sleep(.45)
            more=listed_titles(d.text(d.capture(),(720,340,1300,700)))
            added=[n for n in more if normalized(n) not in {normalized(x) for x in names}]
            if not added:break
            names+=added
        if expected is not None and len(names)<expected:
            d.event('fishing_titles_partial',expected=expected,read=names)
        return names

    @staticmethod
    def save_frame(frame):
        """Keep the latest Fishing titles screen for diagnosing new or hidden titles."""
        try:
            import cv2
            from app_config import data_directory
            cv2.imwrite(str(data_directory()/'titles-list.jpg'),frame,[cv2.IMWRITE_JPEG_QUALITY,85])
        except Exception:pass

    def inspect(self,title,details=None):
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
        if details is not None:details[title]=parse_buffs(rows)
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
            fishing=self.named(categories,'Fishing',r'Fishing\s*[\(\[]?\s*\d*\s*[\)\]]?')
            d.click(*fishing['center'])
            d.sleep(.55)
            # Title pills only: left of the detail panel, not the One/Two/Three check labels.
            # The tab count ('Fishing (6)') says how many exist, so later unlocks are found.
            names=self.listing(category_count(fishing['text']))
            names=[canonical_title(n) for n in names]
            if any(sum(normalized(t)==normalized(n) for n in names) != 1 for t in PRIORITY):
                raise ValueError('Fishing title list changed; read '+str(names))
            self.names=tuple(dict.fromkeys(list(PRIORITY)+names))
            details={}
            owned=set()
            for title in list(names):
                try:
                    if self.inspect(title,details):owned.add(title)
                except ValueError as error:
                    # A known title must be readable; a stray OCR line is just dropped.
                    if title in PRIORITY:raise
                    names.remove(title)
                    d.event('fishing_title_skipped',title=title,reason=str(error))
            self.names=tuple(dict.fromkeys(list(PRIORITY)+names))
            catalog=self.update_catalog(names,owned,details)
            self.names=tuple(dict.fromkeys(list(self.names)+list(catalog)))
            from app_config import load_config
            rod=str(load_config().get('active_rod') or '')
            priority=(load_config().get('title_priority') or {}).get(rod,'luck')
            chosen=desired_titles(owned,priority,known_buffs(catalog))
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
