"""Spatial pickup evidence; an absent prompt never authorizes a blind T hold."""
import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Pickup:
    kind: str
    text: str = ''
    center: tuple = (0, 0)


def same_reward(first, second):
    """Only the already confirmed toast may remain visible during a recast."""
    key=lambda text:re.sub(r'[^a-z0-9]', '', text.casefold())
    return (first.kind==second.kind=='reward' and bool(key(first.text))
            and key(first.text)==key(second.text))


def classify(rows):
    # Tiny quantity text scores lower than the item name in a wide crop.
    # Keep only exact xN tokens at that lower threshold; a nearby strong item
    # name and the caller's repeated-observation gate are still required.
    rows = [r for r in rows if r.get('score', 0) >= .80 or
            (r.get('score',0)>=.70 and re.fullmatch(r'x\s*\d{1,3}',r['text'].strip(),re.I))]
    def cluster(anchor):
        x,y=anchor['center']
        close=[r for r in rows if abs(r['center'][0]-x)<180 and abs(r['center'][1]-y)<65]
        return ' '.join(r['text'] for r in sorted(close,key=lambda r:r['center'][1]))
    collect = [r for r in rows if re.search(r'\b(?:collect|ollect|llect)\b', r['text'], re.I)]
    other = [r for r in rows if re.search(r'\bwall\b|climb|\bpurchase\b|\bfisherman\b|would you like', r['text'], re.I)]
    # Quantity labels need an item name, not a lone X1 elsewhere in the scene.
    rewards = [r for r in rows if re.search(r'\b(?:x\s*\d+|new)\b', r['text'], re.I)
               and len(re.sub(r'\b(?:x\s*\d+|new)\b|[^a-z]', '', cluster(r).lower())) >= 3
               and r not in collect and r not in other]
    if collect and other:
        return Pickup('ambiguous', ' | '.join(r['text'] for r in collect+other))
    candidates, kind = (other, 'other') if other else (collect, 'collect') if collect else (rewards, 'reward')
    if not candidates:
        return Pickup('empty')
    row = max(candidates, key=lambda r: r['score'])
    return Pickup(kind, cluster(row), tuple(row['center']))


class PickupGate:
    def __init__(self):
        self.previous = None
        self.at = 0
        self.count = 0

    def observe(self, evidence, now):
        same = (self.previous is not None and self.previous.kind == evidence.kind
                and math.dist(self.previous.center, evidence.center) < 180 and now-self.at < 1.5)
        self.count = self.count+1 if same else 1
        self.previous, self.at = evidence, now
        return self.count >= 2
