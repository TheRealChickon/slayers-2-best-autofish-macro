"""Spatial pickup evidence; an absent prompt never authorizes a blind T hold."""
import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Pickup:
    kind: str
    text: str = ''
    center: tuple = (0, 0)


def classify(rows):
    rows = [r for r in rows if r.get('score', 0) >= .80]
    collect = [r for r in rows if re.search(r'\b(?:collect|ollect|llect)\b', r['text'], re.I)]
    other = [r for r in rows if re.search(r'\bwall\b|climb|\bpurchase\b|\bfisherman\b|would you like', r['text'], re.I)]
    # Quantity labels need an item name, not a lone X1 elsewhere in the scene.
    rewards = [r for r in rows if re.search(r'\b(?:x\s*\d+|new)\b', r['text'], re.I)
               and len(re.sub(r'\b(?:x\s*\d+|new)\b|[^a-z]', '', r['text'].lower())) >= 3
               and r not in collect and r not in other]
    if collect and other:
        return Pickup('ambiguous', ' | '.join(r['text'] for r in collect+other))
    candidates, kind = (other, 'other') if other else (collect, 'collect') if collect else (rewards, 'reward')
    if not candidates:
        return Pickup('empty')
    row = max(candidates, key=lambda r: r['score'])
    return Pickup(kind, row['text'], tuple(row['center']))


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
