"""Per-rod catch statistics, Angler crate trades and a local comparison page.

Each rod change closes the open rod session and starts a new one, so catches
are attributed to the rod that was equipped. Statistics are read-only
calculations from the existing event logs; nothing here controls Roblox.
"""
import html
import json
import time
from pathlib import Path

from app_config import data_directory, load_config, save_config
from catch_predictions import PRICES, NAMES, calculate
from discord_hourly import atomic_json, read_json
import run_log

SESSIONS_FILE = 'rod-sessions.json'
PAGE_FILE = 'rod-lab.html'
RODS = ('Legendary', 'Rare', 'Uncommon', 'Common')
# Rarity of each fish; anything else (ores, materials, gear) is not a fish.
RARITY = {'ouwfish': 'Common', 'ouwfwesh': 'Common', 'coral': 'Common', 'seahorse': 'Common',
          'clownfish': 'Uncommon', 'goldenfish': 'Uncommon', 'zebrafish': 'Uncommon',
          'crustadon': 'Legendary', 'krathulon': 'Legendary'}
# Angler crate trades confirmed by the user on 2026-10-15. Base gold per crate; the
# 1,580 / 2,070 the user saw included a temporary 2x money boost, which applies to
# the crate quest only (never to direct merchant sales). 1 Ore = 1 minute of 2x.
CRATES = {
    'B': {'gold': 790, 'needs': {'ouwfish': 2, 'seahorse': 2, 'coral': 2, 'ouwfwesh': 2}},
    'A': {'gold': 1035, 'needs': {'ouwfish': 3, 'seahorse': 3, 'coral': 3, 'ouwfwesh': 3, 'clownfish': 1, 'zebrafish': 1}},
}
BOOST_MULTIPLIER = 2
ORE_ITEMS = {'ore': 'Ore', 'refinementore': 'Refinement Ore', 'mythicrefinementore': 'Mythic Refinement Ore'}
# Crate turn-ins per boosted minute: not measured yet (pending from the user).
CRATES_PER_BOOST_MINUTE = 10


def crate_multiplier():
    return BOOST_MULTIPLIER if load_config().get('money_boost', True) else 1
# Known rod buffs; editable in config under rod_buffs.
DEFAULT_BUFFS = {'Legendary': {'enchant': 10, 'fish_luck': 1.5, 'fishing_luck_factor': 1.2, 'bite_speed': 3.0, 'catch_tier': 'Items'},
                 'Rare': {'enchant': 0, 'fish_luck': .25, 'bite_speed': 1.5, 'catch_tier': 'Rare'},
                 'Common': {'enchant': 0, 'catch_tier': 'Common'}}
# Rod enchant (refine) level -> luck multiplier, from the in-game refine screen
# (user, 2026-10-15). One refine step costs 125 Wen + 2 Refinement Ore.
ENCHANT_LUCK = {0: 1.0, 1: 1.05, 2: 1.1, 3: 1.2, 4: 1.3, 5: 1.4, 6: 1.55, 7: 1.7, 8: 1.9, 9: 2.0, 10: 3.0}


def enchant_luck(level):
    table = {**ENCHANT_LUCK, **{int(k): v for k, v in (load_config().get('enchant_luck') or {}).items()}}
    return table.get(int(level))


def key_of(name):
    return ''.join(ch for ch in str(name).lower() if ch.isalnum())


def sessions(root=None):
    root = Path(root or data_directory())
    return read_json(root/SESSIONS_FILE).get('sessions', [])


def set_rod(rod, at=None, root=None):
    """Close the open session and start one for `rod`; also saves it as the active rod."""
    rod = str(rod).strip()
    if not rod or len(rod) > 40:
        raise ValueError('Rod name must be 1–40 characters')
    root = Path(root or data_directory()); at = time.time() if at is None else at
    rows = sessions(root)
    if rows and rows[-1].get('ended') is None:
        if rows[-1]['rod'] == rod:
            save_config({'active_rod': rod}); return rows[-1]
        rows[-1]['ended'] = at
    import os, sys
    row = {'rod': rod, 'started': at, 'ended': None, 'by': f"{os.getpid()} {Path(sys.argv[0]).name if sys.argv and sys.argv[0] else '?'}"}
    rows.append(row)
    atomic_json(root/SESSIONS_FILE, {'sessions': rows})
    save_config({'active_rod': rod})
    return row


def best_crates(counts, multiplier=None):
    """Gold-maximising mix of crate A, crate B and direct sales for these fish counts."""
    m = crate_multiplier() if multiplier is None else multiplier
    def direct(left):
        return sum(PRICES.get(k, 0)*v for k, v in left.items())
    best = None
    limit_a = min(counts.get(k, 0)//n for k, n in CRATES['A']['needs'].items())
    for a in range(limit_a+1):
        left = dict(counts)
        for k, n in CRATES['A']['needs'].items(): left[k] = left.get(k, 0)-a*n
        b = min(left.get(k, 0)//n for k, n in CRATES['B']['needs'].items())
        for k, n in CRATES['B']['needs'].items(): left[k] -= b*n
        crate_gold = m*(a*CRATES['A']['gold']+b*CRATES['B']['gold'])
        gold = crate_gold+direct(left)
        if best is None or gold > best['gold']:
            best = {'gold': gold, 'crate_a': a, 'crate_b': b, 'direct_gold': direct(left),
                    'crate_gold': crate_gold, 'left': left, 'multiplier': m}
    # The common that runs out first and caps crate B.
    best['limit'] = min(CRATES['B']['needs'], key=lambda k: counts.get(k, 0))
    return best


def session_stats(root, session, now=None):
    now = time.time() if now is None else now
    window = {'started': session['started'], 'ended': session.get('ended') or now}
    rows = run_log.rows(root, window)
    result = calculate(rows, window, 1, now)
    events = [r for r in rows if str(r.get('source', '')).startswith('events-')]
    hooks = sum(r.get('event') == 'minigame' for r in events)
    # Fishing time = gaps between worker events of under 60 s (pauses and rejoins excluded).
    times = sorted(r.get('at', 0) for r in events)
    active = sum(b-a for a, b in zip(times, times[1:]) if b-a < 60)
    counts = {}; other = 0; ores = {}
    for item in result.get('items', []):
        key = key_of(item['name'])
        if key in RARITY: counts[key] = counts.get(key, 0)+item['quantity']
        else: other += item['quantity']
        if key in ORE_ITEMS: ores[key] = ores.get(key, 0)+item['quantity']
    fish = sum(counts.values())
    direct = sum(PRICES[k]*v for k, v in counts.items())
    crates = best_crates(counts)
    hours = active/3600 if active else 0
    by_rarity = {}
    for k, v in counts.items(): by_rarity[RARITY[k]] = by_rarity.get(RARITY[k], 0)+v
    return {'rod': session['rod'], 'started': session['started'], 'ended': session.get('ended'),
            'active_hours': round(hours, 2), 'hooks': hooks,
            'hooks_per_minute': round(hooks/(active/60), 2) if active >= 120 else None,
            'fish': fish, 'other_items': other, 'counts': counts, 'by_rarity': by_rarity,
            'ores': ores, 'titles': titles_at(root, window['ended']),
            'direct_gold': direct, 'crate': crates,
            'direct_gold_per_hour': round(direct/hours) if hours >= .05 else None,
            'crate_gold_per_hour': round(crates['gold']/hours) if hours >= .05 else None}


def title_buffs(root):
    import title_manager
    try: catalog = json.loads((Path(root)/title_manager.CATALOG_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError): catalog = {}
    return title_manager.known_buffs(catalog)


def titles_at(root, at):
    """Fishing titles equipped at `at`, from the farmer's last title check."""
    titles = None
    try:
        with (Path(root)/'recovery.jsonl').open('rb') as stream:
            for line in stream:
                if b'fishing_titles_' not in line: continue
                try: row = json.loads(line)
                except ValueError: continue
                if row.get('at', 0) > at: break
                if row.get('event') == 'fishing_titles_equipped': titles = row.get('best')
                elif row.get('event') == 'fishing_titles_checked': titles = row.get('equipped')
    except OSError:
        pass
    return titles


def by_rod(root=None, now=None):
    """Combine every session of each rod into one row."""
    root = Path(root or data_directory())
    rows = {}
    for session in sessions(root):
        s = session_stats(root, session, now)
        row = rows.setdefault(s['rod'], {'rod': s['rod'], 'sessions': 0, 'active_hours': 0., 'hooks': 0,
                                         'counts': {}, 'other_items': 0, 'ores': {}, 'titles': None})
        row['sessions'] += 1; row['active_hours'] += s['active_hours']; row['hooks'] += s['hooks']
        row['other_items'] += s['other_items']
        for k, v in s['counts'].items(): row['counts'][k] = row['counts'].get(k, 0)+v
        for k, v in s['ores'].items(): row['ores'][k] = row['ores'].get(k, 0)+v
        row['titles'] = s['titles'] or row['titles']
    saved = load_config().get('rod_buffs') or {}
    buffs = {rod: {**DEFAULT_BUFFS.get(rod, {}), **saved.get(rod, {})} for rod in {*DEFAULT_BUFFS, *saved}}
    for row in rows.values():
        hours = row['active_hours']; counts = row['counts']; fish = sum(counts.values())
        row['fish'] = fish
        row['hooks_per_minute'] = round(row['hooks']/(hours*60), 2) if hours >= .05 else None
        row['by_rarity'] = {}
        for k, v in counts.items(): row['by_rarity'][RARITY[k]] = row['by_rarity'].get(RARITY[k], 0)+v
        row['drop_percent'] = {k: round(100*v/fish, 1) for k, v in counts.items()} if fish else {}
        row['rarity_percent'] = {k: round(100*v/fish, 1) for k, v in row['by_rarity'].items()} if fish else {}
        row['direct_gold'] = sum(PRICES[k]*v for k, v in counts.items())
        row['crate'] = best_crates(counts)
        row['direct_gold_per_hour'] = round(row['direct_gold']/hours) if hours >= .05 else None
        row['crate_gold_per_hour'] = round(row['crate']['gold']/hours) if hours >= .05 else None
        row['best'] = 'Crates' if row['crate']['gold'] > row['direct_gold'] else 'Sell directly'
        row['buffs'] = dict(buffs.get(row['rod'], {}))
        if 'enchant' in row['buffs']:
            luck = enchant_luck(row['buffs']['enchant'])
            row['buffs']['enchant'] = f"+{row['buffs']['enchant']} ({luck}x luck)" if luck else f"+{row['buffs']['enchant']} (luck pending)"
    return sorted(rows.values(), key=lambda r: -(r['crate_gold_per_hour'] or 0))


TEMPLATE = Path(__file__).resolve().parent/'rodlab_template.html'
LOCAL_REFRESH_SECONDS = 60


def export_data(root=None, now=None):
    """Everything the Rod Lab dashboard draws, as plain JSON-ready data."""
    root = Path(root or data_directory())
    rods = by_rod(root, now)
    bait = bait_hours = None
    try:
        import status_view
        snap = status_view.snapshot()
        bait, bait_hours = snap.get('bait_remaining_estimate'), snap.get('bait_hours_remaining_estimate')
    except Exception:
        pass
    saved = load_config().get('rod_buffs') or {}
    return {'generated': time.strftime('%d %b %H:%M', time.localtime(now)), 'prices': PRICES, 'names': NAMES, 'rarity': RARITY,
            'crates': {k: {'gold': v['gold'], 'needs': v['needs']} for k, v in CRATES.items()},
            'boost': {'multiplier': BOOST_MULTIPLIER, 'on': bool(load_config().get('money_boost', True)),
                      'crates_per_minute': CRATES_PER_BOOST_MINUTE, 'ore_minutes': 1},
            'title_buffs': title_buffs(root),
            'enchant_luck': {str(k): v for k, v in {**ENCHANT_LUCK, **{int(a): b for a, b in (load_config().get('enchant_luck') or {}).items()}}.items()},
            'bait_left': bait, 'bait_hours': bait_hours,
            'rods': [{'rod': r['rod'], 'active_hours': r['active_hours'], 'hooks': r['hooks'], 'fish': r['fish'], 'counts': r['counts'],
                      'ores': r['ores'], 'titles': r['titles'],
                      'enchant_level': {**DEFAULT_BUFFS.get(r['rod'], {}), **saved.get(r['rod'], {})}.get('enchant', 0)} for r in rods],
            'runs': [{k: s[k] for k in ('rod', 'started', 'active_hours', 'hooks', 'fish', 'counts', 'ores', 'titles')}
                     for s in (session_stats(root, x, now) for x in sessions(root))]}


def font_faces():
    """Geist faces embedded as data URIs so the page looks the same offline."""
    import base64
    fonts = Path(__file__).resolve().parent/'assets'/'fonts'
    css = []
    for family, name, weights in (('Geist', 'Geist-latin.woff2', '400 700'), ('Geist Mono', 'GeistMono-latin.woff2', '400 500')):
        try: data = base64.b64encode((fonts/name).read_bytes()).decode()
        except OSError: continue
        css.append(f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weights};font-display:swap;"
                   f"src:url(data:font/woff2;base64,{data}) format('woff2')}}")
    return chr(10).join(css)


def dashboard(data, local=True):
    """Rod Lab HTML from the shared template. local=True adds a page wrapper and auto-refresh."""
    body = TEMPLATE.read_text(encoding='utf-8').replace('/*DATA*/', json.dumps(data)).replace('/*FONTS*/', font_faces())
    if not local:
        return body  # the published artifact supplies its own document wrapper
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="refresh" content="{LOCAL_REFRESH_SECONDS}"></head><body>{body}</body></html>')


def page(root=None, now=None):
    """Write the local Rod Lab next to the run data and return its path."""
    root = Path(root or data_directory())
    path = root/PAGE_FILE
    tmp = path.with_suffix('.tmp')
    tmp.write_text(dashboard(export_data(root, now)), encoding='utf-8')
    tmp.replace(path)
    return path


def watch(seconds=LOCAL_REFRESH_SECONDS, hours=12):
    """Keep the local page current while it is open; the page reloads itself."""
    until = time.time()+hours*3600
    while time.time() < until:
        try: page()
        except Exception: pass
        time.sleep(seconds)


def ensure_watch():
    import subprocess, sys
    import control_actions as actions
    if actions.alive('rodlab-watch-pid.json'): return
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent/'autofish.py'), 'rods', 'watch'],
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    import psutil
    atomic_json(data_directory()/'rodlab-watch-pid.json', {'pid': proc.pid, 'created': psutil.Process(proc.pid).create_time()})


def add_parser(sub):
    rods = sub.add_parser('rods', help='Per-rod catch stats, Angler crates and the comparison page')
    rods.add_argument('operation', nargs='?', choices=('status', 'set', 'page', 'watch'), default='status')
    rods.add_argument('rod', nargs='?', help='Rod name for set, e.g. Rare')


def command(args):
    if args.operation == 'set':
        if not args.rod: raise ValueError('Name the rod, e.g. autofish rods set Rare')
        row = set_rod(args.rod)
        print(f"Active rod: {row['rod']} (since {time.strftime('%H:%M', time.localtime(row['started']))})")
        return 0
    if args.operation == 'page':
        import os
        path = page(); ensure_watch(); print(path); os.startfile(str(path)); return 0
    if args.operation == 'watch':
        watch(); return 0
    print(json.dumps(by_rod(), indent=2)); return 0
