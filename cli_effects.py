"""Transient terminal decorations. No game input, files, or journal mutations."""
import math
from dataclasses import dataclass


# These are the app's existing highlighted catches, not official rarity tiers.
SPECIAL_CATCHES = {'Golden Fish': 'gold', 'Clown Fish': 'green',
                   'Zebra Fish': 'cyan', 'Ore': 'ore'}


@dataclass(frozen=True)
class Effect:
    kind: str
    title: str
    tone: str
    started: float
    duration: float


class CatchEffects:
    def __init__(self):
        self.run = None
        self.seeded = False
        self.seen = set()
        self.active = None
        self.secret = ''
        self.key_at = 0

    @staticmethod
    def identity(row):
        if row.get('reward_id'):
            return (row.get('session'), row['reward_id'])
        # Item names can be corrected later. That must not replay the catch.
        return (row.get('session'), row['at'], row.get('raw'), row['quantity'])

    def observe(self, rows, run, wall_time, now):
        keys = {self.identity(row) for row in rows}
        if not self.seeded or run != self.run:
            self.seeded, self.run, self.seen = True, run, keys
            self.active = None
            return
        for row in rows:
            if (self.identity(row) not in self.seen and row['item'] in SPECIAL_CATCHES
                    and 0 <= wall_time - row['at'] <= 15):
                self.catch(row['item'], row['quantity'], now)
        self.seen.update(keys)

    def catch(self, name, quantity, now):
        # One slot: a newer catch replaces the effect, never builds a backlog.
        self.active = Effect('ore' if name == 'Ore' else 'catch',
                             f'{name}  ×{quantity}', SPECIAL_CATCHES[name], now,
                             3.6 if name == 'Ore' else 4.8)

    def key(self, key, now):
        if now - self.key_at > 2:
            self.secret = ''
        self.key_at = now
        candidate = self.secret + key.lower()
        self.secret = candidate if 'blub'.startswith(candidate) else ('b' if key.lower() == 'b' else '')
        if self.secret == 'blub':
            self.active = Effect('egg', 'CATFISH!', 'cyan', now, 5.5)
            self.secret = ''

    def current(self, now):
        if self.active and now - self.active.started >= self.active.duration:
            self.active = None
        return self.active

    def rows(self, width, now, reduced_motion=False):
        effect = self.current(now)
        if effect is None:
            return None
        width = max(1, min(width, 110))
        grid = [[(' ', 'dim') for _ in range(width)] for _ in range(3)]

        def put(y, x, text, tone):
            for i, char in enumerate(text):
                if 0 <= x+i < width:
                    grid[y][x+i] = (char, tone)

        def centered(y, text, tone):
            put(y, (width-len(text))//2, text, tone)

        elapsed = max(0, now-effect.started)
        if reduced_motion:
            centered(1, effect.title, effect.tone)
        elif effect.kind == 'egg':
            # A very literal catfish visits, then swims away.
            phase = elapsed/effect.duration
            anchor = round((width-30)/2 + 5*math.sin(elapsed*1.4))
            if phase > .78:
                anchor += round((phase-.78)/.22*(width+15))
            for y, line in enumerate((r' /\_/\ ', '( o.o )  ><>', ' > ^ <')):
                put(y, anchor, line, 'cyan')
            put(1, anchor+17, 'CATFISH!', 'gold')
        elif effect.kind == 'ore':
            # A compact mineral glint, distinct from the swimming fish effect.
            center = width//2
            rise = round(3*min(1, elapsed/.45))
            put(max(0, 2-rise), center-1, '◆', 'ore')
            for offset, symbol in ((-9, '·'), (-5, '✦'), (6, '✦'), (10, '·')):
                if .2 < (elapsed + abs(offset)*.09) % 1.2 < .8:
                    put((abs(offset)+int(elapsed*3)) % 3, center+offset, symbol, 'ore')
            centered(1, effect.title, 'ore')
            centered(2, '⌁' * min(9, width), 'dim')
        else:
            # Gentle travel and sparse sparkles; no screen clearing or flashing.
            center = (width-8)//2
            x = round(-8 + (center+8)*min(1, elapsed/.65))
            if elapsed > effect.duration-.65:
                x = round(center+(width-center)*(elapsed-effect.duration+.65)/.65)
            for i in range(12):
                column = (i*29+7) % width
                phase = (elapsed*.8+i*.37) % 1
                if phase < .65:
                    put(i%2*2, column, '+' if phase < .18 else '·', effect.tone if phase < .38 else 'dim')
            put(0, x, '><(((o>', effect.tone)
            centered(1, effect.title, effect.tone)
            wave = ''.join('~' if (i+int(elapsed*4)) % 7 < 2 else ' ' for i in range(min(25, width)))
            centered(2, wave, 'dim')

        # Coalesce color runs so terminal frames stay small.
        result = []
        for row in grid:
            segments = []
            for char, tone in row:
                if segments and segments[-1][1] == tone:
                    segments[-1] = (segments[-1][0]+char, tone)
                else:
                    segments.append((char, tone))
            result.append(segments)
        return result
