"""Spatial pickup evidence; an absent prompt never authorizes a blind T hold."""
import math
import re
from dataclasses import dataclass
from reward_evidence import reward_quantity

FIRST_COLLECT_HOLD_GRACE_SECONDS = .75


def collect_hold_timeout(attempt):
    return 4.0+(FIRST_COLLECT_HOLD_GRACE_SECONDS if attempt==1 else 0)


@dataclass(frozen=True)
class Pickup:
    kind: str
    text: str = ''
    center: tuple = (0, 0)
    key_center: tuple | None = None


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
    # Inventory headers identify a menu, even when its item quantities and
    # tooltips occupy the same screen region as a fishing reward.
    if any(re.fullmatch(r'(?:all(?: classes)?|equipped|fishing)\s*\(\s*\d+\s*\)',
                        r['text'].strip(),re.I) for r in rows):
        return Pickup('empty')
    def cluster(anchor):
        x,y=anchor['center']
        close=[r for r in rows if abs(r['center'][0]-x)<180 and abs(r['center'][1]-y)<65]
        return ' '.join(r['text'] for r in sorted(close,key=lambda r:r['center'][1]))
    collect = [r for r in rows if re.search(r'\b(?:collect|ollect|llect)\b', r['text'], re.I)]
    # "Legendary Fisherman" is the player's title above the avatar, not a
    # world interaction. Requiring an action word keeps that title from
    # aborting every pickup scan after the legendary rod is obtained.
    other = [r for r in rows if re.search(r'\bwall\b|climb|\bpurchase\b|would you like', r['text'], re.I)]
    # Quantity labels need an item name, not a lone X1 elsewhere in the scene.
    rewards = [r for r in rows if re.search(r'\b(?:x\s*\d+|new)\b', r['text'], re.I)
               and reward_quantity(cluster(r)) is not None
               and len(re.sub(r'\b(?:x\s*\d+|new)\b|[^a-z]', '', cluster(r).lower())) >= 3
               and r not in collect and r not in other]
    if collect and other:
        return Pickup('ambiguous', ' | '.join(r['text'] for r in collect+other))
    candidates, kind = (other, 'other') if other else (collect, 'collect') if collect else (rewards, 'reward')
    if not candidates:
        return Pickup('empty')
    row = max(candidates, key=lambda r: r['score'])
    keys=[r for r in rows if kind=='collect' and r.get('score',0)>=.90
          and r['text'].strip().upper()=='T' and math.dist(r['center'],row['center'])<150]
    return Pickup(kind, cluster(row), tuple(row['center']),
                  tuple(keys[0]['center']) if len(keys)==1 else None)


def classify_toast(rows):
    """Read the small reward toast after T without authorizing any game input."""
    if any(re.search(r'collect|climb|wall|purchase', row['text'], re.I) for row in rows):
        return Pickup('empty')
    blocked = re.compile(r'collect|fisherman|climb|wall|purchase', re.I)
    names = [row for row in rows if row.get('score', 0) >= .90
             and len(re.sub(r'[^a-z]', '', row['text'].lower())) >= 3
             and not blocked.search(row['text'])]
    amounts = []
    for row in rows:
        token = re.sub(r'\s+', '', row['text']).lower()
        match = re.fullmatch(r'(?:x|\?)?(\d{1,3})', token)
        threshold = .85 if token.isdigit() else .65 if token.startswith('?') else .60
        if match and row.get('score', 0) >= threshold:
            amounts.append((row, int(match.group(1))))
    if len(names) != 1 or len(amounts) != 1:
        return Pickup('empty')
    name = names[0]
    amount, quantity = amounts[0]
    if quantity < 1 or quantity > 99 or math.dist(name['center'], amount['center']) > 210:
        return Pickup('empty')
    return Pickup('reward', f"{name['text'].strip()} X{quantity}", tuple(name['center']))


def clear_collect(rows,after_minigame=False):
    """An explicit T beside a strong Collect label supplies two visual cues."""
    if classify(rows).kind!='collect':return False
    keys=[r for r in rows if r.get('score',0)>=.90 and r['text'].strip().upper()=='T']
    labels=[r for r in rows if r.get('score',0)>=.94 and re.fullmatch('collect',r['text'].strip(),re.I)]
    return (len(keys)==len(labels)==1 and math.dist(keys[0]['center'],labels[0]['center'])<150
            or after_minigame and len(labels)==1 and labels[0]['score']>=.97)


class RewardGate:
    def __init__(self):self.confirmed=set()
    def accept(self,cycle):
        if cycle in self.confirmed:return False
        self.confirmed.add(cycle);return True


def waiting_decision(evidence,stable,elapsed,fresh_round=False,percent=None):
    """A completed catch may render its loot later than the result percentage."""
    if stable and evidence.kind in ('collect','reward'):return evidence.kind
    empty_limit=10 if fresh_round and percent==100 else 3.5
    if evidence.kind=='empty' and elapsed>(empty_limit if stable else max(4,empty_limit)):return 'empty'
    if evidence.kind=='other' and elapsed>4:return 'empty'
    if elapsed>max(7,empty_limit+1):return 'timeout'
    return 'wait'


def before_cast_decision(evidence,stable,elapsed,confirmed_reward=None,full_scene=False):
    """Reconcile ground loot before casting; a toast alone is not a new catch."""
    if stable and evidence.kind=='collect':return 'collect'
    # A receipt already confirmed across frames does not need another generic
    # dwell and two more OCR passes. Require the exact same receipt in a fresh
    # full scene so a Collect/other interaction outside the toast crop wins.
    if full_scene and confirmed_reward is not None and same_reward(evidence,confirmed_reward):return 'clear'
    if stable and evidence.kind in ('empty','reward') and elapsed>=.35:return 'clear'
    if elapsed>7:return 'timeout'
    return 'wait'


def retain_collect_hold(evidence,elapsed,confirmed_reward=False,attempt=0):
    """An OCR miss can hide a prompt during its already-authorized hold."""
    return not confirmed_reward and evidence.kind not in ('other','ambiguous') and elapsed<collect_hold_timeout(attempt)


class CollectHoldMotion:
    """One fresh retry when an airborne collect target has moved and settled."""
    def __init__(self):
        self.origin=None;self.key_origin=None;self.previous=None;self.started=0;self.at=0
        self.retry_ready_at=None

    def start(self,evidence,now):
        self.key_origin=evidence.key_center
        self.origin=evidence.key_center or evidence.center;self.previous=None;self.started=self.at=now
        self.retry_ready_at=None

    def observe(self,evidence,stable,now,attempt):
        previous=self.previous;age=now-self.at
        self.previous=evidence;self.at=now
        keyed=self.key_origin is not None and evidence.key_center is not None and previous is not None and previous.key_center is not None
        position=evidence.key_center if keyed else evidence.center
        prior_position=previous.key_center if keyed else previous.center if previous is not None else None
        new_key=(self.key_origin is None and evidence.key_center is not None
                 and previous is not None and previous.key_center is not None
                 and math.dist(evidence.key_center,previous.key_center)<=25)
        ready=(self.origin is not None and (self.key_origin is None or keyed) and attempt==1 and stable
                and evidence.kind=='collect' and previous is not None and previous.kind=='collect'
                and now-self.started>=.65 and age<=1.5
                and (new_key or math.dist(self.origin,position)>(65 if keyed else 180)
                     and math.dist(prior_position,position)<=25))
        if not ready:
            self.retry_ready_at=None;return False
        # A moving/changing Collect prompt often settles before its original
        # hold completes. Give that first hold another .75s while fresh settled
        # evidence continues; a reward can still finish it immediately.
        if self.retry_ready_at is None:self.retry_ready_at=now
        return now>=self.retry_ready_at+(.12 if keyed or new_key else FIRST_COLLECT_HOLD_GRACE_SECONDS)


class CollectReadyGate:
    """Avoid pressing into the airborne prompt that Roblox replaces on landing."""
    def __init__(self):self.previous=None;self.at=0;self.first_seen=None

    def observe(self,evidence,stable,now):
        previous=self.previous;age=now-self.at
        self.previous=evidence;self.at=now
        if evidence.kind!='collect':self.first_seen=None;return False
        if self.first_seen is None:self.first_seen=now
        if not stable or previous is None or previous.kind!='collect' or age>1.5:return False
        if evidence.key_center is not None and previous.key_center is not None:
            return .08<=age and (math.dist(evidence.key_center,previous.key_center)<=18
                                or now-self.first_seen>=.3)
        # Some prompt text occludes T. Retain a bounded, repeated-label fallback.
        return now-self.first_seen>=.6 and math.dist(evidence.center,previous.center)<=25


class PickupGate:
    def __init__(self):
        self.previous = None
        self.at = 0
        self.count = 0

    def observe(self, evidence, now, scan_seconds=0):
        same = (self.previous is not None and self.previous.kind == evidence.kind
                and math.dist(self.previous.center, evidence.center) < 180
                and now-self.at < max(1.5, scan_seconds+.75))
        self.count = self.count+1 if same else 1
        self.previous, self.at = evidence, now
        return self.count >= 2
