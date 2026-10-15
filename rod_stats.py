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
PAGE_FILE = 'rod-stats.html'
RODS = ('Legendary', 'Rare', 'Uncommon', 'Common')
# Rarity of each fish; anything else (ores, materials, gear) is not a fish.
RARITY = {'ouwfish': 'Common', 'ouwfwesh': 'Common', 'coral': 'Common', 'seahorse': 'Common',
          'clownfish': 'Uncommon', 'goldenfish': 'Uncommon', 'zebrafish': 'Uncommon',
          'crustadon': 'Legendary', 'krathulon': 'Legendary'}
# Angler crate trades confirmed by the user on 2026-10-15 (gold paid per crate).
CRATES = {
    'B': {'gold': 1580, 'needs': {'ouwfish': 2, 'seahorse': 2, 'coral': 2, 'ouwfwesh': 2}},
    'A': {'gold': 2070, 'needs': {'ouwfish': 3, 'seahorse': 3, 'coral': 3, 'ouwfwesh': 3, 'clownfish': 1, 'zebrafish': 1}},
}
# Known rod buffs; editable in config under rod_buffs.
DEFAULT_BUFFS = {'Legendary': {'fish_luck': 1.5, 'fishing_luck_factor': 1.2, 'bite_speed': 3.0}, 'Rare': {}}


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
    row = {'rod': rod, 'started': at, 'ended': None}
    rows.append(row)
    atomic_json(root/SESSIONS_FILE, {'sessions': rows})
    save_config({'active_rod': rod})
    return row


def best_crates(counts):
    """Gold-maximising mix of crate A, crate B and direct sales for these fish counts."""
    def direct(left):
        return sum(PRICES.get(k, 0)*v for k, v in left.items())
    best = None
    limit_a = min(counts.get(k, 0)//n for k, n in CRATES['A']['needs'].items())
    for a in range(limit_a+1):
        left = dict(counts)
        for k, n in CRATES['A']['needs'].items(): left[k] = left.get(k, 0)-a*n
        b = min(left.get(k, 0)//n for k, n in CRATES['B']['needs'].items())
        for k, n in CRATES['B']['needs'].items(): left[k] -= b*n
        gold = a*CRATES['A']['gold']+b*CRATES['B']['gold']+direct(left)
        if best is None or gold > best['gold']:
            best = {'gold': gold, 'crate_a': a, 'crate_b': b, 'direct_gold': direct(left)}
    return best


def session_stats(root, session, now=None):
    now = time.time() if now is None else now
    window = {'started': session['started'], 'ended': session.get('ended') or now}
    rows = run_log.rows(root, window)
    result = calculate(rows, window, 1, now)
<<<<<<< HEAD
    active = result.get('active_seconds') or 0
    hooks = sum(r.get('event') == 'minigame' for r in rows if str(r.get('source', '')).startswith('events-'))
=======
    events = [r for r in rows if str(r.get('source', '')).startswith('events-')]
    hooks = sum(r.get('event') == 'minigame' for r in events)
    # Fishing time = gaps between worker events of under 60 s (pauses and rejoins excluded).
    times = sorted(r.get('at', 0) for r in events)
    active = sum(b-a for a, b in zip(times, times[1:]) if b-a < 60)
>>>>>>> feature/overnight-defaults-cli-20261014
    counts = {}; other = 0
    for item in result.get('items', []):
        key = key_of(item['name'])
        if key in RARITY: counts[key] = counts.get(key, 0)+item['quantity']
        else: other += item['quantity']
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
            'direct_gold': direct, 'crate': crates,
            'direct_gold_per_hour': round(direct/hours) if hours >= .05 else None,
            'crate_gold_per_hour': round(crates['gold']/hours) if hours >= .05 else None}


def by_rod(root=None, now=None):
    """Combine every session of each rod into one row."""
    root = Path(root or data_directory())
    rows = {}
    for session in sessions(root):
        s = session_stats(root, session, now)
        row = rows.setdefault(s['rod'], {'rod': s['rod'], 'sessions': 0, 'active_hours': 0., 'hooks': 0,
                                         'counts': {}, 'other_items': 0})
        row['sessions'] += 1; row['active_hours'] += s['active_hours']; row['hooks'] += s['hooks']
        row['other_items'] += s['other_items']
        for k, v in s['counts'].items(): row['counts'][k] = row['counts'].get(k, 0)+v
    buffs = {**DEFAULT_BUFFS, **(load_config().get('rod_buffs') or {})}
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
        row['buffs'] = buffs.get(row['rod'], {})
    return sorted(rows.values(), key=lambda r: -(r['crate_gold_per_hour'] or 0))


def page(root=None, now=None):
    """Write the comparison page next to the run data and return its path."""
    root = Path(root or data_directory())
    rods = by_rod(root, now)
    fish_keys = [k for k in RARITY if any(k in r['counts'] for r in rods)]
    esc = html.escape
    def cell(v, suffix=''):
        return '—' if v is None else (f'{v:,}' if isinstance(v, int) else str(v))+suffix
    head = ''.join(f'<th>{esc(NAMES.get(k, k))}<br><small>{RARITY[k]}</small></th>' for k in fish_keys)
    body = []
    for r in rods:
        buffs = ', '.join(f'{k.replace("_", " ")} {v}×' for k, v in r['buffs'].items()) or 'not recorded'
        drops = ''.join(f"<td>{r['drop_percent'].get(k, 0)}%<br><small>{r['counts'].get(k, 0):,}</small></td>" for k in fish_keys)
        rarity = ' · '.join(f"{k} {v}%" for k, v in sorted(r['rarity_percent'].items()))
        c = r['crate']
        body.append(f"<tr><th>{esc(r['rod'])}<br><small>{esc(buffs)}</small></th><td>{r['active_hours']:.1f}h<br><small>{r['hooks']:,} hooks</small></td>"
                    f"<td>{cell(r['hooks_per_minute'])}</td>{drops}<td>{esc(rarity)}<br><small>n = {r['fish']:,} fish</small></td>"
                    f"<td>{cell(r['direct_gold_per_hour'])}</td><td><b>{cell(r['crate_gold_per_hour'])}</b><br><small>{c['crate_b']} B + {c['crate_a']} A</small></td>"
                    f"<td>{esc(r['best'])}</td></tr>")
    crates = ''.join(f"<li>Crate {name}: {', '.join(f'{n}× {NAMES.get(k, k)}' for k, n in c['needs'].items())} → {c['gold']:,} gold</li>"
                     for name, c in CRATES.items())
    prices = ' · '.join(f'{NAMES.get(k, k)} {v}' for k, v in PRICES.items())
    document = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rod Comparison</title><style>
:root{{--bg:#101614;--fg:#dfe4d4;--dim:#7e9792;--gold:#dcb167;--line:#25302d}}
@media (prefers-color-scheme: light){{:root:not([data-theme="dark"]){{--bg:#f6f4ee;--fg:#1e2622;--dim:#5f6f6b;--gold:#8a5d12;--line:#d8d4c8}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0;padding:24px 16px}}
h1{{color:var(--gold);font-size:22px;margin:0 0 4px}} p,li{{color:var(--dim)}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;min-width:100%}}
th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top;white-space:nowrap}}
thead th{{color:var(--dim);font-weight:500}} small{{color:var(--dim)}}
</style></head><body>
<h1>Rod comparison</h1><p>Generated {time.strftime('%Y-%m-%d %H:%M')} from the farmer's own catch logs. Drop % = share of fish caught (ores and materials excluded); n is the sample size.</p>
<div class="wrap"><table><thead><tr><th>Rod</th><th>Fished</th><th>Hooks/min</th>{head}<th>By rarity</th><th>Gold/h selling</th><th>Gold/h with crates</th><th>Best</th></tr></thead>
<tbody>{''.join(body) or '<tr><td colspan="9">No rod sessions yet.</td></tr>'}</tbody></table></div>
<h2>Angler crates</h2><ul>{crates}</ul>
<p>Sell prices (gold): {esc(prices)}. Crate gold/h uses the best mix of crates and direct sales for that rod's catches.</p>
<p>Predicted drop % from luck values needs at least two rods with known luck and a few hundred fish each; until then only observed rates are shown.</p>
</body></html>"""
    path = root/PAGE_FILE
    path.write_text(document, encoding='utf-8')
    return path


def add_parser(sub):
    rods = sub.add_parser('rods', help='Per-rod catch stats, Angler crates and the comparison page')
    rods.add_argument('operation', nargs='?', choices=('status', 'set', 'page'), default='status')
    rods.add_argument('rod', nargs='?', help='Rod name for set, e.g. Rare')


def command(args):
    if args.operation == 'set':
        if not args.rod: raise ValueError('Name the rod, e.g. autofish rods set Rare')
        row = set_rod(args.rod)
        print(f"Active rod: {row['rod']} (since {time.strftime('%H:%M', time.localtime(row['started']))})")
        return 0
    if args.operation == 'page':
        import os
        path = page(); print(path); os.startfile(str(path)); return 0
    print(json.dumps(by_rod(), indent=2)); return 0
