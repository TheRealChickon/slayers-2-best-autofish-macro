"""Read-only personal damage notes from captured stats and M1 measurements."""

import json
import os
import re
import tempfile
from pathlib import Path

from app_config import data_directory


PROFILE_NAME = 'damage-profile.json'


def _damage_stat(item, label, default=None):
    for line in item.get('stats', []):
        match = re.fullmatch(r'\s*\+?([\d.]+)\s*x?\s*\(\s*' + re.escape(label) + r'\s*\)\s*', line, re.I)
        if match:
            return float(match.group(1))
    return default


def haori_comparison(profile, owned):
    """Estimate one-piece M1 swaps from the measured hit and additive HUD factors."""
    calibration = profile.get('calibration') or {}
    stone = owned.get('Stone Haori')
    if not stone or 'Stone Haori' not in profile.get('stat_items', []):
        return None
    measured = calibration.get('m1')
    factor = calibration.get('damage_factor')
    stone_flat = _damage_stat(stone, 'Additional Damage')
    stone_factor = _damage_stat(stone, 'Additional Damage Factor')
    if not all(value is not None for value in (measured, factor, stone_flat, stone_factor)) or factor <= 0:
        return None
    swaps = []
    for name in ('Serpent Haori', 'Flame Haori Style 1'):
        item = owned.get(name)
        if not item:
            continue
        replacement_factor = _damage_stat(item, 'Additional Damage Factor')
        if replacement_factor is None:
            continue
        replacement_flat = _damage_stat(item, 'Additional Damage', 0.0)
        new_factor = factor - (stone_factor - 1) + (replacement_factor - 1)
        new_m1 = (measured / factor - stone_flat + replacement_flat) * new_factor
        swaps.append({'name': name, 'additional_damage': round(replacement_flat - stone_flat, 3),
                      'damage_factor': round(new_factor, 3), 'projected_m1': round(new_m1, 2),
                      'difference': round(new_m1 - measured, 2)})
    if not swaps:
        return None
    return {'current_item': 'Stone Haori', 'measured_m1': measured,
            'measured_factor': factor, 'mastery': calibration.get('mastery'),
            'swaps': swaps,
            'method': 'Swap the item flat damage and add its factor increment to the displayed total; apply the new factor to measured M1 divided by the old factor. HUD 1.23x to 1.28x supports additive stacking.',
            'limit': 'Calculated M1 at the saved mastery if all item bonuses apply; not a live swap measurement.'}


def profile_path(root=None):
    return Path(root) / PROFILE_NAME if root is not None else data_directory() / PROFILE_NAME


def load_profile(root=None):
    path = profile_path(root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def save_mastery(level, root=None):
    level = int(level)
    if not 0 <= level <= 1000:
        raise ValueError('Mastery must be between 0 and 1000')
    path = profile_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = load_profile(root)
    profile['mastery'] = level
    descriptor, temporary = tempfile.mkstemp(prefix='damage-profile-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(profile, stream, indent=2, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return profile


def snapshot_path(root=None):
    directory = Path(root) if root is not None else data_directory()
    for path in (directory / 'wiki-snapshot' / 'site' / 'items.json',
                 directory / 'site' / 'items.json'):
        if path.exists():
            return path
    return None


def report(root=None, mastery=None):
    profile = load_profile(root)
    path = snapshot_path(root)
    snapshot = json.loads(path.read_text(encoding='utf-8')) if path else {}
    owned = {item['name']: item for item in snapshot.get('inventory', [])}
    wanted = list(profile.get('stat_items', []))
    weapon_name = profile.get('weapon', '')
    level = profile.get('mastery') if mastery is None else int(mastery)
    if level is not None and not 0 <= level <= 1000:
        raise ValueError('Mastery must be between 0 and 1000')
    calibration = profile.get('calibration', {})
    projection = None
    if (level is not None and calibration and wanted and
            all(name in owned for name in wanted) and weapon_name in owned):
        # This is a progression estimate for the same equipment, not an optimizer.
        projection = (float(calibration['m1']) +
                      (level - int(calibration['mastery'])) *
                      float(calibration['base_per_mastery']) *
                      float(calibration['damage_factor']))
    return {
        'snapshot_at': snapshot.get('captured_at'),
        'snapshot_path': str(path) if path else None,
        'mastery': level,
        'calibration': calibration,
        'projected_m1': round(projection, 2) if projection is not None else None,
        'projection_note': 'Same loadout; 0.025 base M1 per mastery is inferred from four observed levels.',
        'stat_items': [{'name': name, 'owned': name in owned,
                        'equipped_in_snapshot': bool(owned.get(name, {}).get('equipped')),
                        'stats': owned.get(name, {}).get('stats', [])} for name in wanted],
        'weapon': {'name': weapon_name, 'owned': weapon_name in owned,
                   'refinement': owned.get(weapon_name, {}).get('refinement', 0),
                   'stats': owned.get(weapon_name, {}).get('stats', [])} if weapon_name else None,
        'tests': profile.get('tests', []),
        'haori_comparison': haori_comparison(profile, owned),
        'limits': profile.get('limits', []),
        'profile_found': bool(profile),
    }


def text_lines(data):
    if not data['snapshot_path']:
        return ['No inventory snapshot found. Capture the wiki first: autofish wiki.']
    if not data['profile_found']:
        return ['No personal damage calibration saved.',
                'Use measured M1 and gear stats to create data/damage-profile.json.']
    lines = ['DAMAGE / OWNED GEAR',
             f"Snapshot  {data['snapshot_at'] or 'unknown'}",
             f"Mastery   {data['mastery'] if data['mastery'] is not None else 'not set'}"]
    anchor = data['calibration']
    if anchor:
        lines += [f"Measured  {anchor['m1']:.2f} M1 at mastery {anchor['mastery']}"]
    if (data['projected_m1'] is not None and
            data['mastery'] != anchor.get('mastery')):
        lines += [f"Same gear  ~{data['projected_m1']:.2f} M1 at mastery {data['mastery']} (estimate)"]
    lines += ['', 'BEST KNOWN PURE M1 / FIVE STAT SLOTS']
    for index, item in enumerate(data['stat_items'], 1):
        lines.append(f"{index}. {item['name']}" + ('' if item['owned'] else '  [NOT IN SNAPSHOT]'))
        bonuses = [value for value in item['stats'] if 'Additional Damage' in value]
        if bonuses:
            lines.append('   ' + ' | '.join(bonuses))
    if data['weapon']:
        item = data['weapon']
        lines += ['', 'WEAPON / SEPARATE SLOT',
                  item['name'] + (f" +{item['refinement']}" if item['refinement'] else '')]
        lines += ['   ' + ' | '.join(value for value in item['stats']
                                 if 'Additional Damage' in value)]
    if data['tests']:
        lines += ['', 'LIVE COMPARISON'] + [f"- {test}" for test in data['tests']]
    comparison = data.get('haori_comparison')
    if comparison:
        lines += ['', 'HAORI SWAP / CALCULATED M1']
        for swap in comparison['swaps']:
            lines.append(f"- {swap['name']}: ~{swap['projected_m1']:.2f} M1 ({swap['difference']:+.2f} vs Stone Haori's {comparison['measured_m1']:.2f})")
        lines.append(comparison['limit'])
    lines += ['', 'Mastery estimate is for unchanged gear. Inventory and equipped marks are a saved snapshot.']
    lines += data['limits']
    return lines
