"""Read separate boss header and world labels; never chase the fixed HUD."""
import re
from dataclasses import replace
import cv2
import numpy as np
from boss_plan import BossObservation

WORLD_NAMES = ('saneri', 'sanemi', 'saneri shinazugawa', 'sanemi shinazugawa')


def world_name(text):
    # Waypoint distances can overlap the world name in the same OCR row.
    text = re.sub(r'^\s*\d[\d,.]*\s*m\s*', '', text, flags=re.I)
    normalized = re.sub(r'[^a-z]', '', text.lower())
    return (normalized in tuple(name.replace(' ','') for name in WORLD_NAMES) or
            normalized in ('manerishinazugawa','anerishinazugawa'))


def rows_in(frame, ocr, box, scale=1.):
    x, y, w, h = box
    image = frame[y:y+h, x:x+w]
    if scale != 1:
        image = cv2.resize(image, None, fx=scale, fy=scale)
    rows, _ = ocr(image, use_cls=False)
    result = []
    for points, text, score in rows or []:
        points = np.asarray(points)
        result.append({'text': text, 'score': float(score),
                       'x': x+float(points[:, 0].mean())/scale,
                       'y': y+float(points[:, 1].mean())/scale,
                       'height': float(np.ptp(points[:,1]))/scale})
    return result


def health_pair(text):
    match = re.search(r'(\d[\d,.]*)\s*/\s*(\d[\d,.]*)', text)
    if not match:
        return None
    try:
        # Game health uses decimal points and sometimes thousands separators.
        current, maximum = (float(value.replace(',', '')) for value in match.groups())
        return (current, maximum) if 0 <= current <= maximum and maximum > 0 else None
    except ValueError:
        return None


def respawn_timer(text):
    short = re.search(r'spawns?\s*in\s*(\d{1,2})\s*s\b',text,re.I)
    if short:
        value=int(short.group(1))
        return value if value < 60 else None
    match = re.search(r'spawns?\s*in\s*(\d{1,2})\s*:\s*(\d{2})', text, re.I)
    if not match:
        return None
    minutes, seconds = map(int, match.groups())
    return minutes*60+seconds if 0 <= minutes <= 15 and 0 <= seconds < 60 else None


def boss_from_rows(header, world, player, blocked=False):
    names = [r['text'].strip() for r in header if r['score'] >= .8
             and r['text'].strip().lower() in ('saneri', 'sanemi')]
    name = names[0].capitalize() if len(names) == 1 else None
    pairs = [health_pair(r['text']) for r in header if r['score'] >= .8]
    pairs = [p for p in pairs if p is not None and p[1] == 3000]
    hp, maximum = pairs[0] if name and len(pairs) == 1 else (None, None)
    targets = [r for r in world if r['score'] >= .8
               and world_name(r['text'])
               and 200 < r['x'] < 2460 and 350 < r['y'] < 1200]
    # Multiple matching labels are ambiguous; do not choose another player.
    target = (targets[0]['x'], targets[0]['y']) if len(targets) == 1 else None
    player_pairs = [health_pair(r['text']) for r in player if r['score'] >= .75]
    player_pairs = [p for p in player_pairs if p]
    fraction = player_pairs[0][0]/player_pairs[0][1] if len(player_pairs) == 1 else None
    timers = [respawn_timer(r['text']) for r in header if r['score'] >= .8]
    timers = [value for value in timers if value is not None]
    timer = timers[0] if name and len(timers) == 1 else None
    if timer is not None:
        hp, maximum, target = None, None, None
    return BossObservation(name, hp, maximum, target, fraction, blocked, timer,
                           targets[0].get('height') if target else None)


def observe(frame, ocr, blocked=False):
    header = rows_in(frame, ocr, (870, 130, 850, 185), 1.4)
    world = rows_in(frame, ocr, (200, 350, 2260, 850), .85)
    if not any(world_name(r['text']) for r in world):
        world.extend(distant_names(frame, ocr))
    if not any(world_name(r['text']) for r in world):
        # A partially depleted bar turns gold/brown, so its green-bar locator
        # cannot find it. Re-read small names at native scale before turning.
        world.extend(row for row in rows_in(frame,ocr,(200,350,2260,850),1.4)
                     if world_name(row['text']))
    result = boss_from_rows(header, world,
        rows_in(frame, ocr, (160, 1355, 220, 50), 2), blocked)
    if result.name and result.hp is None and result.respawn_seconds is None:
        hp = fast_health(frame,ocr)
        if hp is not None:result = replace(result,hp=hp,maximum=3000.)
    # Dark text becomes unreadable against nighttime grass. The fixed red HP
    # gauge remains legible; accept only a continuous fill from its left edge.
    bar = player_bar_fraction(frame)
    if bar is not None:
        result = replace(result, player_fraction=bar)
    return result


def distant_names(frame, ocr):
    """Upscale tiny world names above observed green health bars."""
    roi = frame[350:1200,200:2460]
    b,g,r = cv2.split(roi.astype('float32'))
    mask = ((g > 160) & (g > r*.8) & (g > b*1.15)).astype('uint8')*255
    mask = cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),'uint8'))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    bars = []
    for n in range(1,count):
        x,y,w,h,area=map(int,stats[n])
        if 35 <= w <= 430 and 4 <= h <= 28 and 4 <= w/h <= 35 and area/(w*h) > .65:
            bars.append((x+200,y+350,w,h))
    if len(bars)>6:return []
    names=[]
    for x,y,w,h in bars:
        padding=max(20,round(w*.3));top=max(350,y-max(25,h*4))
        rows=rows_in(frame,ocr,(max(200,x-padding),top,min(2460-x+padding,w+padding*2),y-top),3.)
        names.extend(row for row in rows if world_name(row['text']))
    return names


def fast_health(frame, ocr):
    rows=rows_in(frame,ocr,(880,232,390,40),2.)
    pairs=[health_pair(row['text']) for row in rows if row['score']>.8]
    pairs=[pair for pair in pairs if pair and pair[1]==3000]
    return pairs[0][0] if len(pairs)==1 else None


def cutscene_visible(frame):
    # Normal B's cinematic has black bars across the top and bottom. The
    # center strips exclude Roblox controls and desktop notification overlays.
    if frame.shape[:2] != (1440,2560):return False
    return bool((frame[65:105,500:2000] < 12).mean() > .97 and
                (frame[1350:1410,500:2000] < 12).mean() > .97)


def combat_hud_visible(frame):
    """B includes bright flashes; require the returning HUD, not just no bars."""
    if frame.shape[:2] != (1440,2560) or player_bar_fraction(frame) is None:
        return False
    gray = cv2.cvtColor(frame[1260:1335,1025:1540],cv2.COLOR_BGR2GRAY)
    return bool((gray > 180).mean() > .02)


def chat_send_button(frame, field_y):
    x,y=350,max(0,round(field_y)-45)
    roi=frame[y:y+90,x:510]
    b,g,r=cv2.split(roi.astype('float32'))
    mask=((b>170)&(b>g*1.3)&(b>r*1.8)).astype('uint8')*255
    count,_,stats,centers=cv2.connectedComponentsWithStats(mask)
    candidates=[(x+float(centers[n][0]),y+float(centers[n][1])) for n in range(1,count)
                if 20 <= stats[n][2] <= 55 and 20 <= stats[n][3] <= 55 and stats[n][4] >= 300]
    return candidates[0] if len(candidates)==1 else None


def player_bar_fraction(frame):
    if frame.shape[:2] != (1440, 2560):
        return None
    b, g, r = cv2.split(frame[1404:1418, 50:305].astype('float32'))
    red = ((r > 95) & (r > g*2) & (r > b*2)).mean(axis=0) > .7
    if not red[:5].all():
        return None
    missing = np.flatnonzero(~red)
    end = int(missing[0]) if len(missing) else len(red)
    if red[end+3:].any():
        return None
    return end/len(red)
