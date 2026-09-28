"""Portable settings. Local account details never belong in the source repository."""
import json
import os
import re
import urllib.request
from pathlib import Path
from cast_point import DEFAULT as DEFAULT_CAST_POINT, validate as validate_cast_point
from damage_plan import DEFAULT_ROTATION, validate_rotation
from boss_plan import DEFAULT_BOSS, validate_boss

ROOT = Path(__file__).resolve().parent
MODES = {'full': 'Full farmer', 'assist': 'Minigame only', 'spot': 'Fish here',
         'damage': 'Statue damage', 'boss': 'Sanemi trial'}
CONFIG = ROOT / 'config.local.json'
DEFAULTS = {'data_dir': 'data', 'account_username': '', 'user_id': None,
            'rod_slot': 5, 'auto_rod': True, 'reduced_motion': False, 'inventory_check': True,
            'place_id': 16205713724, 'mode': 'full', 'cast_point': list(DEFAULT_CAST_POINT),
            'spawn_backstep_seconds': 0.0, 'camera_mode': 'keep', 'camera_heading': None,
            'auto_fishing_titles': False, 'damage_rotation': DEFAULT_ROTATION,
            'damage_title': 'Annihilator', 'damage_title_category': 'Combat',
            'damage_target': 10000000, 'damage_check_seconds': 180, 'boss': DEFAULT_BOSS}


def validate_options(values):
    values['boss'] = validate_boss(values['boss'])
    values['damage_rotation'] = validate_rotation(values['damage_rotation'])
    for name in ('damage_title', 'damage_title_category'):
        value = values[name]
        if not isinstance(value, str) or len(value.strip()) > 60:
            raise ValueError(f'{name} must be a title-menu label of at most 60 characters')
        values[name] = value.strip()
    if not values['damage_title_category']:
        raise ValueError('Damage title category is required')
    values['damage_target'] = int(values['damage_target'])
    values['damage_check_seconds'] = int(values['damage_check_seconds'])
    if values['damage_target'] <= 0 or not 30 <= values['damage_check_seconds'] <= 3600:
        raise ValueError('Damage target must be positive; recheck must be 30–3600 seconds')
    if values['camera_mode'] not in ('keep', 'first_person'):
        raise ValueError('Camera mode must be keep or first_person')
    if not isinstance(values['auto_fishing_titles'], bool):
        raise ValueError('Auto fishing titles must be on or off')
    if values['camera_heading'] is not None:
        heading=float(values['camera_heading'])
        if not 0<=heading<360:raise ValueError('Camera heading must be from 0 to 359 degrees')
        values['camera_heading']=heading


def load_config():
    values = dict(DEFAULTS)
    if CONFIG.exists():
        values.update(json.loads(CONFIG.read_text(encoding='utf-8-sig')))
    if not 1 <= int(values['rod_slot']) <= 9:
        raise ValueError('Rod slot must be between 1 and 9')
    values['rod_slot'] = int(values['rod_slot'])
    values['cast_point'] = validate_cast_point(values['cast_point'])
    values['spawn_backstep_seconds'] = float(values['spawn_backstep_seconds'])
    if not 0 <= values['spawn_backstep_seconds'] <= .35:
        raise ValueError('Spawn backstep must be between 0 and 0.35 seconds')
    if values['mode'] not in MODES:
        raise ValueError('Mode must be full, assist, spot, or damage')
    validate_options(values)
    if values['user_id'] is not None:
        values['user_id'] = int(values['user_id'])
        if values['user_id'] <= 0:raise ValueError('User ID must be positive')
    return values


def data_directory():
    value = os.environ.get('FISHING_DATA_DIR') or load_config()['data_dir']
    path = Path(value).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def save_config(changes):
    values = load_config()
    values.update(changes)
    if values['mode'] not in MODES:
        raise ValueError('Mode must be full, assist, spot, or damage')
    validate_options(values)
    if not 1 <= int(values['rod_slot']) <= 9:raise ValueError('Rod slot must be between 1 and 9')
    values['cast_point'] = validate_cast_point(values['cast_point'])
    values['spawn_backstep_seconds'] = float(values['spawn_backstep_seconds'])
    if not 0 <= values['spawn_backstep_seconds'] <= .35:
        raise ValueError('Spawn backstep must be between 0 and 0.35 seconds')
    temporary = CONFIG.with_suffix('.tmp')
    temporary.write_text(json.dumps(values, indent=2), encoding='utf-8')
    os.replace(temporary, CONFIG)
    return values


def resolve_account(username):
    username = username.strip()
    if not username:return {'account_username': '', 'user_id': None}
    if not re.fullmatch(r'[A-Za-z0-9_]{3,20}', username):
        raise ValueError('Enter a Roblox username, not a display name')
    request = urllib.request.Request('https://users.roblox.com/v1/usernames/users',
        data=json.dumps({'usernames':[username], 'excludeBannedUsers':True}).encode(),
        headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request, timeout=12) as response:
        rows = json.load(response).get('data', [])
    if len(rows) != 1:raise ValueError('Roblox username was not found')
    return {'account_username': rows[0]['name'], 'user_id': int(rows[0]['id'])}
