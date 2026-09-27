"""Read-only personal damage notes from a captured inventory and local calibration.

The game does not expose a verified damage formula. Only the unchanged measured
loadout gets an M1 projection; a gear swap requires a new in-game measurement.
"""

import json
import os
import tempfile
from pathlib import Path

from app_config import data_directory


PROFILE_NAME = 'damage-profile.json'


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
    lines += ['', 'Mastery estimate is for unchanged gear. Inventory and equipped marks are a saved snapshot.']
    lines += data['limits']
    return lines
