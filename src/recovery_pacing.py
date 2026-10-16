"""Observation-based menu pacing; contains no screen capture or input."""
import math
import re


def main_menu_target(rows):
    # The diamond icon is often OCR'd as a leading middle dot in "·PLAY".
    # Require the surrounding main-menu labels and the left-side button area.
    labels={re.sub(r'[^a-z]','',row['text'].lower()) for row in rows}
    if not {'customize','slots'}<=labels:return None
    candidates=[row for row in rows if re.sub(r'[^a-z]','',row['text'].lower())=='play'
                and row.get('score',0)>=.82 and 0<=row['center'][0]<=450 and 400<=row['center'][1]<=1000]
    return candidates[0]['center'] if len(candidates)==1 else None


class MenuPacer:
    def __init__(self):
        self.kind=None;self.target=None;self.since=0;self.samples=0
        self.retry_at={};self.join_grace_until=0

    def observe(self,kind,target,now):
        moved=(target is None)!=(self.target is None)
        if target is not None and self.target is not None:
            moved=math.dist(target,self.target)>6
        if kind!=self.kind or moved:
            self.kind=kind;self.target=target;self.since=now;self.samples=1
        else:self.samples+=1

    def ready(self,action,now,stable_seconds=.3):
        # Two matching observations already prove the screen settled; 0.3 s (was 0.6 s)
        # removes dead time before menu clicks without acting on a half-drawn frame.
        return (self.samples>=2 and now-self.since>=stable_seconds
                and now>=self.retry_at.get(action,0)
                and (self.kind not in ('world_selection','private_join') or now>=self.join_grace_until))

    def acted(self,action,now,delay):
        self.retry_at[action]=now+delay

    def joined(self,now,attempt):
        # A disappearing Join panel is not yet proof of a successful teleport.
        # Observe a short quiet period; repeated rejected joins back off.
        self.join_grace_until=now+min(12,3*2**min(attempt-1,2))


def private_join_target(rows):
    text=' '.join(row['text'].lower() for row in rows)
    if 'privateserver' not in re.sub(r'[^a-z]','',text):return None
    joins=[row['center'] for row in rows if row['text'].strip().lower()=='join']
    return joins[0] if len(joins)==1 else None
