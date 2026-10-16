"""Overlay design A drawn natively: the same card as overlay_template.html, pixel for pixel.

Same Geist fonts, sizes, weights, colours, spacing and stroke icons as the HTML card
(Sami's pick, 2026-10-15). It is drawn with Pillow because a hidden browser cannot be
driven on every PC (security tools block DevTools), and the native layered window keeps
the card click-through, never focused and blurred over the game.
"""
import math
import re
import time
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from app_config import ROOT

WIDTH, HEIGHT = 284, 432
RADIUS = 18
PAD_X, PAD_Y, GAP = 14, 12, 11
INNER = WIDTH-2*PAD_X

T1 = (243, 245, 248)
T2 = (232, 237, 245, 158)   # rgba(232,237,245,.62)
T3 = (232, 237, 245, 97)    # rgba(232,237,245,.38)
LINE = (255, 255, 255, 23)  # rgba(255,255,255,.09)
AMBER = (231, 169, 40)
RARITY = {'Impossible': (255, 106, 120), 'Mythic': (180, 124, 242), 'Legendary': (240, 172, 20),
          'Rare': (34, 181, 201), 'Uncommon': (71, 168, 255), 'Common': (232, 237, 245, 184)}
ROD_COLOUR = {'Legendary': AMBER, 'Rare': (34, 181, 201), 'Common': T1}
MODE = {'full': 'Full farmer', 'here': 'Farm here', 'spot': 'Fish here', 'assist': 'Minigame'}
# Card backdrop: design A's gradient, slightly see-through so the compositor blur shows.
TOP, BOTTOM, CARD_ALPHA = (23, 26, 33), (17, 19, 24), 232

# The stroke icons of overlay_template.html (24x24 viewBox).
ICONS = {
    'cast': 'M4 20 17 5|M17 5c2.6 3 3 7 1.2 10.5|M18.2 15.5v1.8|c18.2,19,1.6',
    'wait': 'M12 3.5v3.5|c12,11,4|M8 11h8|M3 19.5c1.5 0 1.5-1.2 3-1.2s1.5 1.2 3 1.2 1.5-1.2 3-1.2 1.5 1.2 3 1.2 1.5-1.2 3-1.2 1.5 1.2 3 1.2',
    'reel': 'c12,12,8.5|c12,12,2.4|M12 9.6V4.2M14.1 13.2l4.6 2.7M9.9 13.2l-4.6 2.7',
    'collect': 'M12 3v10|M8 9.5 12 13.5l4-4|M4 14v3.5A2.5 2.5 0 0 0 6.5 20h11a2.5 2.5 0 0 0 2.5-2.5V14',
    'rejoin': 'M20 11.5A8 8 0 0 0 5.6 7|M5 3.5V7.5h4|M4 12.5A8 8 0 0 0 18.4 17|M19 20.5v-4h-4',
    'paused': 'M9 5.5v13M15 5.5v13',
    'rod': 'M4 20 17 5|M17 5c2.6 3 3 7 1.2 10.5|M7.5 16.5l-2-2',
    'crown': 'M4 8.5l4 3.5 4-6 4 6 4-3.5-1.6 9.5H5.6z',
    'luck': 'M12 3.5c.6 4.4 2.4 6.2 6.8 6.8-4.4.6-6.2 2.4-6.8 6.8-.6-4.4-2.4-6.2-6.8-6.8 4.4-.6 6.2-2.4 6.8-6.8z',
    'bite': 'c12,13.5,7|M12 10v3.5l2.2 1.6M10 3h4',
    'bait': 'M14 3v11.5a4.5 4.5 0 0 1-9 0V12|M5 12l2.5 2|M17.5 6.5c1.5 1 1.5 3 0 4',
    'bolt': 'M13 3 5 13.5h6l-1 7.5 8-10.5h-6z',
    'pace': 'M4 17.5a8 8 0 1 1 16 0|M12 15l3.5-4.5',
    'coin': 'e12,7,7,3|M5 7v5c0 1.7 3.1 3 7 3s7-1.3 7-3V7|M5 12v5c0 1.7 3.1 3 7 3s7-1.3 7-3v-5',
    'sum': 'M17 5H7l6 7-6 7h10',
    'clock': 'c12,12,8.5|M12 7.5V12l3 2',
    'list': 'M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01',
}


@lru_cache(maxsize=64)
def font(size, weight=400, mono=False):
    path = ROOT/'assets'/'fonts'/('GeistMono-latin.woff2' if mono else 'Geist-latin.woff2')
    try:
        face = ImageFont.truetype(str(path), size)
        try: face.set_variation_by_axes([weight])
        except Exception: pass
        return face
    except OSError:
        return ImageFont.load_default(size=size)


@lru_cache(maxsize=16)
def system_font(size):
    import os
    from pathlib import Path
    try: return ImageFont.truetype(str(Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts'/'segoeui.ttf'), size)
    except OSError: return ImageFont.load_default(size=size)


def _arc(x1, y1, rx, ry, phi, large, sweep, x2, y2, n=16):
    """SVG endpoint arc -> points (excluding the start)."""
    if rx == 0 or ry == 0: return [(x2, y2)]
    cp, sp = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (x1-x2)/2, (y1-y2)/2
    xp, yp = cp*dx+sp*dy, -sp*dx+cp*dy
    rx, ry = abs(rx), abs(ry)
    lam = xp*xp/(rx*rx)+yp*yp/(ry*ry)
    if lam > 1: rx, ry = rx*math.sqrt(lam), ry*math.sqrt(lam)
    num = rx*rx*ry*ry-rx*rx*yp*yp-ry*ry*xp*xp
    den = rx*rx*yp*yp+ry*ry*xp*xp
    co = math.sqrt(max(0, num/den)) if den else 0
    if large == sweep: co = -co
    cxp, cyp = co*rx*yp/ry, -co*ry*xp/rx
    cx, cy = cp*cxp-sp*cyp+(x1+x2)/2, sp*cxp+cp*cyp+(y1+y2)/2
    def ang(ux, uy, vx, vy):
        a = math.atan2(ux*vy-uy*vx, ux*vx+uy*vy)
        return a
    t1 = ang(1, 0, (xp-cxp)/rx, (yp-cyp)/ry)
    dt = ang((xp-cxp)/rx, (yp-cyp)/ry, (-xp-cxp)/rx, (-yp-cyp)/ry)
    if not sweep and dt > 0: dt -= 2*math.pi
    elif sweep and dt < 0: dt += 2*math.pi
    out = []
    for i in range(1, n+1):
        t = t1+dt*i/n
        out.append((cx+rx*math.cos(t)*cp-ry*math.sin(t)*sp, cy+rx*math.cos(t)*sp+ry*math.sin(t)*cp))
    return out


def _bezier(p0, p1, p2, p3, n=12):
    return [((1-t)**3*p0[0]+3*(1-t)**2*t*p1[0]+3*(1-t)*t*t*p2[0]+t**3*p3[0],
             (1-t)**3*p0[1]+3*(1-t)**2*t*p1[1]+3*(1-t)*t*t*p2[1]+t**3*p3[1]) for t in (i/n for i in range(1, n+1))]


def path_points(d):
    """Polylines for an SVG path (M L H V C S A Z, absolute and relative)."""
    tokens = re.findall(r'[MLHVCSAZmlhvcsaz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?', d)
    lines, cur, start, x, y, last_ctrl, cmd, i = [], [], (0, 0), 0., 0., None, None, 0
    def num():
        nonlocal i
        v = float(tokens[i]); i += 1; return v
    while i < len(tokens):
        if re.fullmatch(r'[A-Za-z]', tokens[i]): cmd = tokens[i]; i += 1
        rel = cmd.islower(); c = cmd.upper()
        if c == 'Z':
            if cur: cur.append(start); lines.append(cur); cur = []
            x, y = start; continue
        if c == 'M':
            nx, ny = num(), num()
            if rel: nx, ny = x+nx, y+ny
            if cur: lines.append(cur)
            x, y = nx, ny; start = (x, y); cur = [(x, y)]
            cmd = 'l' if rel else 'L'; last_ctrl = None; continue
        if c in 'LHV':
            if c == 'L':
                nx, ny = num(), num()
                if rel: nx, ny = x+nx, y+ny
            elif c == 'H': nx = num()+(x if rel else 0); ny = y
            else: ny = num()+(y if rel else 0); nx = x
            x, y = nx, ny; cur.append((x, y)); last_ctrl = None
        elif c in 'CS':
            if c == 'C':
                x1, y1 = num(), num()
                if rel: x1, y1 = x+x1, y+y1
            else:
                x1, y1 = (2*x-last_ctrl[0], 2*y-last_ctrl[1]) if last_ctrl else (x, y)
            x2, y2, nx, ny = num(), num(), num(), num()
            if rel: x2, y2, nx, ny = x+x2, y+y2, x+nx, y+ny
            cur += _bezier((x, y), (x1, y1), (x2, y2), (nx, ny))
            last_ctrl = (x2, y2); x, y = nx, ny
        elif c == 'A':
            rx, ry, phi, large, sweep, nx, ny = num(), num(), num(), num(), num(), num(), num()
            if rel: nx, ny = x+nx, y+ny
            cur += _arc(x, y, rx, ry, phi, int(large), int(sweep), nx, ny)
            x, y = nx, ny; last_ctrl = None
    if cur: lines.append(cur)
    return lines


class Canvas:
    def __init__(self, scale):
        self.s = scale
        self.image = Image.new('RGBA', (round(WIDTH*scale), round(HEIGHT*scale)), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.image)

    def layer(self):
        return Image.new('RGBA', self.image.size, (0, 0, 0, 0))

    def rect(self, box, fill, radius=0, outline=None, width=1):
        layer = self.layer()
        ImageDraw.Draw(layer).rounded_rectangle([round(v*self.s) for v in box], round(radius*self.s), fill, outline,
                                                max(1, round(width*self.s)))
        self.image.alpha_composite(layer)

    def text(self, x, y, value, size, colour, weight=400, mono=False, max_w=None, spacing=0., fallback=False):
        """Draw text with its em box top at y (CSS line box); returns the advance width."""
        value = str(value)
        face = font(round(size*self.s), weight, mono)
        if fallback and value[:1] == '≈':
            # Geist's latin subset has no '≈'; draw it in Segoe UI, then the rest in Geist.
            sym = system_font(round(size*self.s))
            layer = self.layer(); ImageDraw.Draw(layer).text((x*self.s, y*self.s-1*self.s), '≈', font=sym, fill=colour)
            self.image.alpha_composite(layer)
            adv = ImageDraw.Draw(layer).textlength('≈', font=sym)/self.s
            return adv+self.text(x+adv, y, value[1:], size, colour, weight, mono, max_w, spacing)
        if max_w is not None:
            while value and self.width(value, size, weight, mono, spacing) > max_w:
                value = value[:-1]
                if not value.endswith('…'): value = value.rstrip()[:-1]+'…' if len(value) > 1 else '…'
        layer = self.layer()
        d = ImageDraw.Draw(layer)
        ascent, descent = face.getmetrics()
        top = y*self.s+(size*self.s-(ascent+descent))/2
        if spacing:
            cx = x*self.s
            for ch in value:
                d.text((cx, top), ch, font=face, fill=colour)
                cx += d.textlength(ch, font=face)+spacing*size*self.s
        else:
            d.text((x*self.s, top), value, font=face, fill=colour)
        self.image.alpha_composite(layer)
        return self.width(value, size, weight, mono, spacing)

    def width(self, value, size, weight=400, mono=False, spacing=0.):
        face = font(round(size*self.s), weight, mono)
        w = self.draw.textlength(str(value), font=face)/self.s
        return w+spacing*size*max(0, len(str(value))-1) if spacing else w

    def icon(self, name, x, y, size, colour, stroke=1.8):
        """A 24x24 stroke icon scaled to `size` CSS px at (x, y)."""
        k = size/24*self.s
        layer = self.layer(); d = ImageDraw.Draw(layer)
        w = max(1, round(stroke*k))
        for part in ICONS[name].split('|'):
            if part[0] in 'ce' and ',' in part:
                v = [float(t) for t in part[1:].split(',')]
                cx, cy, rx = v[0], v[1], v[2]; ry = v[3] if len(v) > 3 else rx
                d.ellipse([x*self.s+(cx-rx)*k, y*self.s+(cy-ry)*k, x*self.s+(cx+rx)*k, y*self.s+(cy+ry)*k], outline=colour, width=w)
                continue
            for line in path_points(part):
                pts = [(x*self.s+px*k, y*self.s+py*k) for px, py in line]
                if len(pts) == 1 or all(abs(p[0]-pts[0][0]) < .5 and abs(p[1]-pts[0][1]) < .5 for p in pts):
                    r = w/2; d.ellipse([pts[0][0]-r, pts[0][1]-r, pts[0][0]+r, pts[0][1]+r], fill=colour); continue
                d.line(pts, fill=colour, width=w, joint='curve')
                r = w/2
                for p in (pts[0], pts[-1]): d.ellipse([p[0]-r, p[1]-r, p[0]+r, p[1]+r], fill=colour)
        self.image.alpha_composite(layer)


def state_key(s):
    t = s.get('state') or ''
    if s.get('paused') or s.get('manual_paused') or not (s.get('running') or s.get('starting')): return 'paused'
    for key, pattern in (('wait', 'bite|wait'), ('reel', 'reel|minigame'), ('cast', 'cast'),
                         ('collect', 'collect|claim|pick'), ('rejoin', 'rejoin|recover|walk')):
        if re.search(pattern, t, re.I): return key
    return 'wait'


def fmt(v, d=0):
    if v is None: return '—'
    try:
        v = float(v)
        return '—' if not math.isfinite(v) else f'{v:,.{d}f}'
    except (TypeError, ValueError): return '—'


def kfmt(v):
    if v is None: return '—'
    try: v = float(v)
    except (TypeError, ValueError): return '—'
    if not math.isfinite(v): return '—'
    return f'{v/1000:.1f}k' if v >= 1000 else fmt(v)


def render(state, gear=None, scale=1.0, now=None, rarity_of=None):
    """The overlay card at `scale` (device pixels per CSS pixel), RGBA with transparent corners."""
    gear = gear or {}
    s = state or {}
    ss = max(2.0, scale*2)  # supersample, then downscale for clean edges
    c = Canvas(ss)
    # Card: design A's vertical gradient, 1px line border, 18px radius.
    grad = Image.new('RGBA', c.image.size)
    gd = ImageDraw.Draw(grad)
    h = c.image.size[1]
    for yy in range(h):
        t = yy/max(1, h-1)
        gd.line([(0, yy), (c.image.size[0], yy)], fill=tuple(round(TOP[i]+(BOTTOM[i]-TOP[i])*t) for i in range(3))+(CARD_ALPHA,))
    mask = Image.new('L', c.image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, c.image.size[0]-1, c.image.size[1]-1], round(RADIUS*ss), 255)
    c.image.paste(grad, (0, 0), mask)
    c.rect((0, 0, WIDTH-1, HEIGHT-1), None, RADIUS, LINE, 1)

    y = PAD_Y
    # Header: 42px icon tile, 17px/620 state label, 11px mono clock.
    key = state_key(s)
    label = (s.get('state') if (s.get('running') or s.get('starting')) else ('Paused' if s.get('paused') else 'Not farming')) or 'Loading'
    c.rect((PAD_X, y, PAD_X+42, y+42), (255, 255, 255, 20), 13, (255, 255, 255, 15), 1)
    c.icon(key, PAD_X+9.5, y+9.5, 23, T1, 1.7)
    tx = PAD_X+42+10
    c.text(tx, y+4, label, 17, T1, 620, max_w=WIDTH-PAD_X-tx)
    secs = max(0, int(s.get('active_seconds') or 0))
    c.icon('clock', tx, y+28.5, 11, T3)
    c.text(tx+16, y+27, f'{secs//3600}:{secs//60 % 60:02d}:{secs % 60:02d}', 11, T3, 400, mono=True)
    y += 42+GAP
    # Progress line (2px): a moving segment while actually fishing.
    if s.get('activity_running'):
        phase = ((now or time.time()) % 2.4)/2.4
        seg = INNER*.38
        x0 = PAD_X-seg+phase*(INNER+seg)
        c.rect((max(PAD_X, x0), y, min(PAD_X+INNER, x0+seg), y+2), (255, 255, 255, 184), 2)
    y += 2+GAP
    # Stats: three tiles, 6px gap.
    tile = (INNER-12)/3
    pace = s.get('pace')
    if pace is None and s.get('hooks_per_hour'): pace = s['hooks_per_hour']/60
    gold = s.get('gold_per_hour')
    total = gold*s['active_seconds']/3600 if gold and s.get('active_seconds') else None
    for n, (icon, name, value, unit) in enumerate((('pace', 'Pace', fmt(pace, 1), '/min'), ('coin', 'Gold', kfmt(gold), '/h'),
                                                   ('sum', 'Session', kfmt(total), ''))):
        x = PAD_X+n*(tile+6)
        c.rect((x, y, x+tile, y+52), (255, 255, 255, 13), 12)
        c.icon(icon, x+9, y+9, 13, T3)
        c.text(x+9+18, y+8, name, 10.5, T3, 500)
        w = c.text(x+9, y+25, value, 16, T1, 620)
        if unit: c.text(x+9+w+2, y+30, unit, 11, T3, 500)
    y += 52+GAP
    y += 1+GAP  # design A's separator line is effectively invisible on the card
    # Equipped: rod line, title rows, chips.
    rod = gear.get('rod')
    colour = ROD_COLOUR.get(rod, T2 if not rod else T1)
    c.icon('rod', PAD_X, y+1, 16, colour)
    w = c.text(PAD_X+24, y+1, f'{rod} Fishing Rod' if rod else 'No rod picked', 13, colour, 600, max_w=INNER-70)
    if gear.get('enchant'):
        lx = PAD_X+24+w+8
        lw = c.width(f"+{gear['enchant']}", 11, 650)+12
        c.rect((lx, y+1, lx+lw, y+17), (231, 169, 40, 41), 9)
        c.text(lx+6, y+3, f"+{gear['enchant']}", 11, (243, 194, 90), 650)
    y += 18+7
    for t in (gear.get('titles') or [])[:3]:
        c.icon('crown', PAD_X, y+.5, 14, T3)
        mult = []
        if t.get('luck'): mult.append(('luck', f"{t['luck']:g}×"))
        if t.get('bite'): mult.append(('bite', f"{t['bite']:g}×"))
        mw = sum(14+c.width(v, 11.5, 560) for _, v in mult)+4*max(0, len(mult)-1)
        c.text(PAD_X+21, y, t.get('name', ''), 11.5, T2, 400, max_w=INNER-21-mw-8)
        x = PAD_X+INNER-mw
        for n, (icon, value) in enumerate(mult):
            c.icon(icon, x, y+2, 11, T3)
            x += 14
            x += c.text(x, y, value, 11.5, T1, 560)+4
        y += 15+4
    if not gear.get('titles'): y += 0
    y += 3
    chips = []
    bait, hrs = s.get('bait_remaining_estimate'), s.get('bait_hours_remaining_estimate')
    if bait is not None: chips.append(('bait', fmt(bait), f'≈{round(hrs)}h' if hrs else ''))
    if s.get('mode'): chips.append(('bolt', MODE.get(s['mode'], str(s['mode'])), ''))
    x = PAD_X
    for icon, value, unit in chips:
        cw = 10+14+6+c.width(value, 12.5, 620)+(c.width(unit, 11, 500)+4 if unit else 0)+10
        c.rect((x, y, x+cw, y+28), (255, 255, 255, 15), 14)
        c.icon(icon, x+10, y+7, 14, T2)
        w = c.text(x+30, y+7, value, 12.5, T1, 620)
        if unit: c.text(x+30+w+4, y+8.5, unit, 11, T3, 500, fallback=True)
        x += cw+6
    y += (28 if chips else 0)+GAP
    y += 1+GAP  # design A's separator line is effectively invisible on the card
    # Recent catches.
    c.icon('list', PAD_X, y+1, 12, T3)
    c.text(PAD_X+18, y, 'RECENT', 10.5, T3, 550, spacing=.06)
    y += 14+GAP
    rows = [e for e in (s.get('events') or []) if e.get('group') == 'catches'][-5:][::-1]
    if not rows: c.text(PAD_X, y+4, 'Catches show up here', 12, T3)
    for e in rows:
        # Catch events read 'Collected Coral X1'; the card shows just the item name.
        name = re.sub(r'\s+[xX×]\s*\d+$', '', re.sub(r'^collected\s+', '', e.get('text', ''), flags=re.I))
        r = (rarity_of(name) if rarity_of else None) or 'Common'
        if r == 'Impossible': c.rect((PAD_X-6, y, PAD_X+INNER+6, y+22), (255, 90, 138, 41), 7)
        c.text(PAD_X, y+5, time.strftime('%H:%M', time.localtime(e.get('at', 0))), 11, T3, 400, mono=True)
        c.text(PAD_X+44, y+4, name, 12.5, RARITY.get(r, RARITY['Common']), 680 if r == 'Impossible' else 540, max_w=INNER-44)
        y += 22
    return c.image.resize((round(WIDTH*scale), round(HEIGHT*scale)), Image.Resampling.LANCZOS)
