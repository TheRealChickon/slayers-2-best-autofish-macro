"""Read-only per-run pace, timing and gold figures for the CLI and Discord.

Timings come from the worker's own events: minigame end -> first readable
prompt -> T hold -> confirmed reward -> next cast. Gold uses the NPC sell
prices in catch_predictions and only counts priced fish.
"""
import statistics
import time
from pathlib import Path

RECENT_CYCLES = 60
_cache = {}


def _median(values):
    values = [v for v in values if v is not None and 0 <= v < 60]
    return round(statistics.median(values), 2) if values else None


def cycle_timings(rows, limit=RECENT_CYCLES):
    """Median phase durations over the latest `limit` hooked rounds."""
    cycles = []
    current = None
    for row in rows:
        if not str(row.get('source', '')).startswith('events-'):
            continue
        kind, at = row.get('event'), row.get('at', 0)
        if kind == 'cast':
            if current is not None:
                current['next_cast'] = at
                cycles.append(current)
            current = {'cast': at}
        elif current is None:
            continue
        elif kind == 'minigame':
            current.setdefault('hooked', at)
        elif kind == 'minigame_ended':
            current.setdefault('end', at); current.setdefault('percent', row.get('percent'))
        elif kind == 'pickup_prompt_seen':
            current.setdefault('prompt', at)
        elif kind == 'pickup_hold':
            current.setdefault('hold', at); current['holds'] = current.get('holds', 0)+1
        elif kind in ('reward_observed', 'inventory_recovered'):
            current.setdefault('reward', at)
        elif kind == 'empty_round':
            current.setdefault('empty', at)
    cycles = [c for c in cycles if 'end' in c][-limit:]
    gap = lambda c, a, b: c[b]-c[a] if a in c and b in c else None
    rewarded = [c for c in cycles if 'reward' in c]
    failed = [c for c in cycles if c.get('percent') not in (None, 100)]
    empty = [c for c in cycles if 'empty' in c and c not in failed]
    return {
        'sample': len(cycles),
        'end_to_prompt': _median(gap(c, 'end', 'prompt') for c in cycles),
        'end_to_hold': _median(gap(c, 'end', 'hold') for c in rewarded),
        'hold_to_reward': _median(gap(c, 'hold', 'reward') for c in rewarded),
        'reward_to_cast': _median(gap(c, 'reward', 'next_cast') for c in rewarded),
        'empty_to_cast': _median(gap(c, 'end', 'next_cast') for c in empty),
        'fail_to_cast': _median(gap(c, 'end', 'next_cast') for c in failed),
        'cast_to_bite': _median(gap(c, 'cast', 'hooked') for c in cycles),
        'cycle': _median(gap(c, 'cast', 'next_cast') for c in cycles),
        'second_holds': sum(c.get('holds', 0) > 1 for c in rewarded),
        'rewarded': len(rewarded),
    }


def compute(root, run, now=None, ttl=10.):
    """Cached for `ttl` seconds; the CLI refreshes far more often than logs change."""
    now = time.time() if now is None else now
    key = (str(root), run.get('id'))
    cached = _cache.get(key)
    if cached and time.monotonic()-cached[0] < ttl:
        return cached[1]
    from run_log import rows as run_rows
    from catch_predictions import calculate
    rows = run_rows(Path(root), run) if run else []
    prediction = calculate(rows, run, 1, now) if run else {}
    active = prediction.get('active_seconds') or 0
    gold = prediction.get('known_price_subtotal_wen')
    events = [r for r in rows if str(r.get('source', '')).startswith('events-')]
    counts = {}
    for r in events:
        counts[r.get('event')] = counts.get(r.get('event'), 0)+1
    result = {
        'run_id': run.get('id'), 'active_seconds': active,
        'rounds': counts.get('minigame', 0), 'casts': counts.get('cast', 0),
        'failed': sum(r.get('event') == 'minigame_ended' and r.get('percent') not in (None, 100) for r in events),
        'empty': counts.get('empty_round', 0),
        'catches': prediction.get('unique_catches', 0),
        'gold': gold, 'gold_per_hour': gold*3600/active if gold is not None and active >= 120 else None,
        'unpriced_units': prediction.get('unknown_price_quantity', 0),
        'items': prediction.get('items', []),
        'timings': cycle_timings(rows),
    }
    _cache[key] = (time.monotonic(), result)
    return result
