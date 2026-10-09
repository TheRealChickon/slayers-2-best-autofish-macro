"""Incremental, bounded activity stream shared by both frontends."""
import hashlib
import json
import re
import time
from metrics import RUN
from reward_evidence import reward_quantity


def state_tone(state, active=True):
    if not active or state in ('Waiting for Roblox','Paused','Stopped','Pausing','Stopping','Retry Wait'):
        return 'gold'
    return 'cyan' if state in ('Recovering','Restarting','Starting') else 'green'


def event_tone(row):
    """Shared semantic colors for the navigable and streaming CLI views."""
    kind=row.get('kind',row.get('event',''))
    message=row.get('message') or row.get('reason') or row.get('text','')
    if kind in ('stopped','worker_exit','supervisor_stopped'):
        return 'gold' if message.lower().startswith(('stopped by','paused by','session_limit')) else 'red'
    if kind in ('wrong_interaction','disconnect_gui','disconnect_observed') or 'error' in kind:
        return 'red'
    if row.get('level')=='warn' or any(word in kind for word in ('retry','backoff','no_minigame','unreadable','ambiguous','exhausted','attention')):
        return 'gold'
    if row.get('level')=='good' or kind in ('reward_observed','inventory_resolved','inventory_recovered','equipped_rod','rod_equipped','rod_already_equipped','damage_ready','rejoin_success'):
        return 'green'
    if kind=='state':return state_tone(message)
    if row.get('group')=='recovery':return 'cyan'
    return 'text'


def describe(row):
    kind = row.get('event', '')
    if kind == 'cast':return f'Cast {row.get("cast", "")}'
    if kind == 'minigame':return f'Hook {row.get("cycle", "")} · tracking'
    if kind == 'minigame_ended':
        pct = row.get('percent')
        return f'Hook {row.get("cycle", "")} · {str(pct)+"%" if pct is not None else "finished"}'
    if kind == 'reward_observed':
        raw=row.get('text','')
        return ('Collected ' if reward_quantity(raw) is not None else 'Ignored unconfirmed reward read: ') + raw
    if kind == 'inventory_resolved':return 'Identified ' + row.get('item','item') + ' from inventory'
    if kind == 'inventory_recovered':return 'Confirmed ' + row.get('item','item') + ' from inventory · banner missed'
    if kind == 'inventory_checked':return f'Inventory checked · {row.get("items",0)} item types'
    if kind == 'inventory_unreadable' and row.get('retry_minutes'):
        return f'{row.get("message", "Inventory unreadable")} · next eligible check in {row["retry_minutes"]} min'
    if kind == 'recovery_started':return 'Rejoin started' if row.get('force_menu') else 'Checking game and rod'
    if kind == 'equipped_rod':return 'Game ready · rod equipped'
    if kind == 'pickup_hold':return f'Collecting · attempt {row.get("attempt", 1)}'
    if kind == 'alignment_result':return f"Fishing view aligned · {row.get('steps',0)} corrections"
    if kind == 'alignment_step':return 'Adjusting fishing view' + (' and position' if any(row.get('movement_seconds',[])) else '')
    if kind == 'recovery_decision':return f"Recovery · {row.get('code','unknown').replace('_',' ')} → {row.get('action','rejoin').replace('_',' ')}"
    if kind == 'screen':return 'Recovery · ' + row.get('kind', 'checking').replace('_',' ')
    return row.get('message') or row.get('reason') or kind.replace('_', ' ').capitalize()


class LiveFeed:
    def __init__(self):
        self.started = None
        self.offsets = {}
        self.rows = []
        self.version = 0
        self.state = None

    def update(self, started, state=None, ended=None):
        if (started,ended) != (self.started,getattr(self,'ended',None)):
            self.__init__()
            self.started = started
            self.ended = ended
        changed = False
        paths = sorted(RUN.glob('events-*.jsonl')) + [RUN/'recovery.jsonl', RUN/'controls.jsonl']
        for path in paths:
            if not path.exists():continue
            offset = self.offsets.get(path, 0)
            if path.stat().st_size < offset:offset = 0
            with path.open('rb') as stream:
                stream.seek(offset)
                while True:
                    position = stream.tell()
                    line = stream.readline()
                    if not line or not line.endswith(b'\n'):
                        stream.seek(position)
                        break
                    try:row = json.loads(line)
                    except ValueError:continue
                    if row.get('at', 0) < (started or 0):continue
                    if ended is not None and row.get('at',0)>ended:continue
                    kind = row.get('event', '')
                    # Screen/OCR transitions are diagnostics, not new recoveries.
                    # Keep them in raw logs; show actual actions and outcomes here.
                    if kind in ('tracking_reacquired','screen','alignment_check'):continue
                    rejected=kind=='reward_observed' and reward_quantity(row.get('text','')) is None
                    group = 'catches' if not rejected and kind in ('reward_observed','inventory_resolved','inventory_recovered') else 'recovery' if path.name=='recovery.jsonl' or path.name.startswith('events-rejoin-') or kind=='damage_reset' else 'damage' if path.name.startswith('events-damage-') else 'fishing'
                    level = 'warn' if rejected or any(term in kind for term in ('error','stopped','no_minigame','wrong_interaction','retry','exhausted','unreadable','ambiguous','attention')) else 'good' if kind in ('reward_observed','equipped_rod','rod_equipped','inventory_resolved','inventory_recovered','damage_ready','rejoin_success') else 'normal'
                    event_id = hashlib.sha256(json.dumps([started, path.name, position, row], sort_keys=True).encode()).hexdigest()[:24]
                    self.rows.append({'id':event_id,'at':row.get('at',0),'kind':kind,'group':group,'level':level,
                        'text':re.sub(r'[\x00-\x1f\x7f]', ' ', describe(row))})
                    changed = True
                self.offsets[path] = stream.tell()
        if ended is None and state is not None and state != self.state:
            self.state = state
            self.rows.append({'at':time.time(),'kind':'state','group':'state','level':'state','text':state})
            changed = True
        if changed:
            self.rows.sort(key=lambda row:row['at'])
            if ended is None:self.rows = self.rows[-4000:]
            self.version += 1
        return changed

    def filtered(self, query='', category='All'):
        return [row for row in self.rows if query.lower() in row['text'].lower() and
            (category=='All' or category=='Catches' and row['group']=='catches' or
             category=='Recovery' and row['group']=='recovery' or
             category=='Warnings' and row['level']=='warn')]
