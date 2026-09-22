"""Read-only view shared by the game-style window and the command line."""
import math
import time
from metrics import RUN, read
from item_journal import Journal
from performance import recent
from app_config import load_config
import control_actions as actions


def duration(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 3600}h {seconds % 3600 // 60:02d}m'


def snapshot(journal=None):
    journal = journal if journal is not None else Journal()
    totals, supervisor, worker, bait, presence = [read(name + '.json') for name in
        ('totals', 'supervisor', 'status', 'bait', 'presence')]
    journal.update(totals.get('started'))
    live = actions.alive()
    starting = actions.starting() and not live
    paused, stop = (RUN / 'PAUSE').exists(), (RUN / 'STOP').exists()
    stage = supervisor.get('stage', 'starting')
    if (live or starting) and stop:
        state = 'Pausing' if paused else 'Stopping'
    elif starting:
        state = 'Starting'
    elif live:
        fishing_states = {'tracking':'Assisting minigame' if supervisor.get('mode')=='assist' else 'Fishing',
                          'pickup':'Collecting','waiting':'Waiting for a bite','casting':'Casting',
                          'inventory':'Reading inventory','assist_waiting':'Waiting for your cast',
                          'select_spot':'Equip rod, aim, then F8','checking_spot':'Checking fishing spot',
                          'spot_paused':'Paused — F8 to resume',
                          'waiting_rod':'Waiting for equipped rod',
                          'spot_blocked':'Waiting for fishing scene','spot_attention':'Check the spot, then press F8',
                          'waiting_marker':'Waiting for a clear marker','pickup_wait':'Checking pickup',
                          'cast_press':'Casting','equipping':'Equipping rod','equip_wait':'Equipping rod','cooldown':'Next cast'}
        state = ('Waiting for Roblox' if stage=='paused_focus' else fishing_states.get(worker.get('stage'),'Fishing')
                 if stage=='fishing' else stage.replace('_',' ').title())
    else:
        state = 'Paused' if paused else 'Stopped'
    rounds, seconds = totals.get('rounds', 0), totals.get('active_seconds', 0)
    rate = rounds * 3600 / seconds if seconds > 0 else 0
    stock = bait.get('starting_stock')
    remaining = max(0, stock - rounds) if stock is not None else None
    fresh = presence.get('ok') and time.time() - presence.get('checked_at', 0) < 120
    unknown = sum(qty for name, qty in journal.counts.items()
                  if name == 'Unidentified item' or name.endswith('(partial)'))
    return {
        'state': state, 'mode': supervisor.get('mode','full') if live else load_config()['mode'], 'running': live, 'starting': starting, 'stop_requested': stop,
        'paused': paused, 'started': totals.get('started'), 'updated': totals.get('updated'),
        'collections': totals.get('rewards', 0), 'items': sum(journal.counts.values()),
        'logged_collections': len(journal.items), 'unread_items': unknown,
        'hooks': rounds, 'casts': totals.get('casts', 0), 'failed_rounds': totals.get('failed', 0),
        'server_rejoins': max(0, journal.joins - 1), 'game_launches': journal.launches,
        'active_seconds': seconds, 'last_item': journal.items[-1]['item'] if journal.items else None,
        'bait_remaining_estimate': remaining, 'hooks_per_hour': rate,
        'bait_hours_remaining_estimate': remaining / rate if remaining is not None and rate else None,
        'presence': 'Not configured' if presence.get('disabled') else presence.get('state', 'Unknown') if fresh else
                    'Not polled while stopped' if not live else 'Checking',
        'presence_fresh': bool(fresh),
        'recent': recent(journal), 'alignment': read('alignment.json'),
        'spot_armed':worker.get('spot_armed',False),
        'spot_paused':worker.get('spot_paused',False),
    }


def estimate(data, hours):
    return math.ceil(data['hooks_per_hour'] * hours) if data['hooks_per_hour'] else None
