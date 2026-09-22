"""Incremental, bounded activity stream shared by both frontends."""
import json
import re
import time
from metrics import RUN


def describe(row):
    kind = row.get('event', '')
    if kind == 'cast':return f'Cast {row.get("cast", "")}'
    if kind == 'minigame':return f'Hook {row.get("cycle", "")} · tracking'
    if kind == 'minigame_ended':
        pct = row.get('percent')
        return f'Hook {row.get("cycle", "")} · {str(pct)+"%" if pct is not None else "finished"}'
    if kind == 'reward_observed':return 'Collected ' + row.get('text', 'item')
    if kind == 'pickup_hold':return f'Collecting · attempt {row.get("attempt", 1)}'
    if kind == 'screen':return 'Recovery · ' + row.get('kind', 'checking').replace('_',' ')
    return row.get('message') or row.get('reason') or kind.replace('_', ' ').capitalize()


class LiveFeed:
    def __init__(self):
        self.started = None
        self.offsets = {}
        self.rows = []
        self.version = 0
        self.state = None

    def update(self, started, state=None):
        if started != self.started:
            self.__init__()
            self.started = started
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
                    kind = row.get('event', '')
                    if kind in ('tracking_reacquired',):continue
                    group = 'catches' if kind == 'reward_observed' else 'recovery' if path.name=='recovery.jsonl' else 'fishing'
                    level = 'warn' if any(term in kind for term in ('error','stopped','no_minigame','wrong_interaction','retry','exhausted')) else 'good' if kind in ('reward_observed','equipped_rod','rod_equipped') else 'normal'
                    self.rows.append({'at':row.get('at',0),'kind':kind,'group':group,'level':level,
                        'text':re.sub(r'[\x00-\x1f\x7f]', ' ', describe(row))})
                    changed = True
                self.offsets[path] = stream.tell()
        if state is not None and state != self.state:
            self.state = state
            self.rows.append({'at':time.time(),'kind':'state','group':'state','level':'state','text':state})
            changed = True
        if changed:
            self.rows.sort(key=lambda row:row['at'])
            self.rows = self.rows[-4000:]
            self.version += 1
        return changed

    def filtered(self, query='', category='All'):
        return [row for row in self.rows if query.lower() in row['text'].lower() and
            (category=='All' or category=='Catches' and row['group']=='catches' or
             category=='Recovery' and row['group']=='recovery' or
             category=='Warnings' and row['level']=='warn')]
