"""Spatial chest/item prompts; reward text alone never authorizes a T press."""
from dataclasses import dataclass
import math
import re


@dataclass(frozen=True)
class LootPrompt:
    name: str
    action: str
    center: tuple


def prompt_from_rows(rows):
    rows = [row for row in rows if row['score'] >= .8]
    keys = [row for row in rows if row['text'].strip().upper() == 'T']
    actions = [row for row in rows if row['text'].strip().lower() in ('open','claim','collect')]
    candidates=[]
    for action in actions:
        nearby=[row for row in rows if row not in actions and row not in keys and
                abs(row['x']-action['x']) < 500 and abs(row['y']-action['y']) < 110]
        names=[row for row in nearby if re.search(r'chest|coin pouch|refinement ore|metal scraps|brave soul|silk thread|haor?i?|katana|uniform|\bwen\b',row['text'],re.I)]
        if len(names)!=1:continue
        name=names[0]
        radius=max(330,330+name.get('height',0)*6)
        if not any(math.hypot(key['x']-name['x'],key['y']-name['y']) < radius for key in keys):continue
        candidates.append(LootPrompt(name['text'],action['text'].lower(),(name['x'],name['y'])))
    return candidates[0] if len(candidates)==1 else None


def reward_from_rows(rows):
    """Pair one xN toast with its adjacent item name, excluding world prompts."""
    rewards=[]
    for amount in rows:
        match=re.fullmatch(r'x\s*(\d{1,2})',amount['text'].strip(),re.I)
        if not match or amount['score'] < .75:continue
        names=[row for row in rows if row['score'] >= .85 and
               0 < amount['y']-row['y'] < 65 and abs(row['x']-amount['x']) < 160 and
               re.search(r'pouch|ore|scraps|haori|katana|uniform|soul|silk thread',row['text'],re.I)]
        if len(names)==1:rewards.append((names[0]['text'].strip(),int(match.group(1))))
    return rewards
