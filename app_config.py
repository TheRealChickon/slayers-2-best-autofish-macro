"""Portable settings. Local account details never belong in the source repository."""
import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'config.local.json'
DEFAULTS = {'data_dir': 'data', 'account_username': '', 'user_id': None,
            'rod_slot': 5, 'auto_rod': True, 'reduced_motion': False, 'inventory_check': True,
            'place_id': 16205713724, 'mode': 'full'}


def load_config():
    values = dict(DEFAULTS)
    if CONFIG.exists():
        values.update(json.loads(CONFIG.read_text(encoding='utf-8-sig')))
    if not 1 <= int(values['rod_slot']) <= 9:
        raise ValueError('Rod slot must be between 1 and 9')
    values['rod_slot'] = int(values['rod_slot'])
    if values['mode'] not in ('full', 'assist'):
        raise ValueError('Mode must be full or assist')
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
    if values['mode'] not in ('full', 'assist'):
        raise ValueError('Mode must be full or assist')
    if not 1 <= int(values['rod_slot']) <= 9:raise ValueError('Rod slot must be between 1 and 9')
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
