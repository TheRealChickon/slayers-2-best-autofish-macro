"""Input schedule and progress policy for stationary statue damage farming."""

from collections import deque


class DamageCycle:
    """C precedes a five-hit M1 string, as requested by the player."""

    def __init__(self, m1_interval=.42, combo_gap=1.65, skill_settle=.65):
        self.m1_interval = m1_interval
        self.combo_gap = combo_gap
        self.skill_settle = skill_settle
        self.phase = 'ready'
        self.next_at = 0.
        self.clicks = 0
        self.last_c = float('-inf')
        self.skill_this_cycle = False

    def resync(self, now):
        # An interrupted sequence must expire before another click.
        self.phase = 'ready'
        self.next_at = now + max(2.5, self.combo_gap)
        self.clicks = 0
        self.skill_this_cycle = False

    def due(self, now, c_ready):
        if now < self.next_at:
            return None
        if self.phase == 'gap':
            self.phase = 'ready'
            self.clicks = 0
            return 'cycle_end'
        if self.phase == 'ready':
            self.skill_this_cycle = False
            if c_ready and now-self.last_c >= 8:
                self.phase = 'skill_settle'
                self.last_c = now
                self.skill_this_cycle = True
                self.next_at = now + self.skill_settle
                return 'c'
            self.phase = 'm1'
        if self.phase == 'skill_settle':
            self.phase = 'm1'
        if self.phase == 'm1':
            self.clicks += 1
            if self.clicks == 5:
                self.phase = 'gap'
                self.next_at = now + self.combo_gap
            else:
                self.next_at = now + self.m1_interval
            return 'm1'
        return None


class ProgressGuard:
    """Require repeatable combo growth, with bounded reset attempts."""

    def __init__(self):
        self.previous = None
        self.low_candidate = None
        self.low_count = 0
        self.cycle_hits = 0
        self.cycle_visible = False
        self.best_plain_cycle = 0
        self.poor_cycles = 0
        self.reset_times = deque()

    def observe(self, value):
        if value is None:
            return 0
        self.cycle_visible = True
        if self.previous is None:
            gain = value if value <= 5 else 0
        elif value >= self.previous:
            gain = value-self.previous
            if gain > 10:
                return 0  # An impossible jump is an OCR error.
            self.low_candidate = None
            self.low_count = 0
        else:
            # A single low read is usually an OCR flicker. Accept a genuine
            # counter restart only after two nearby low observations.
            if value < self.previous*.7:
                self.low_count = self.low_count+1 if self.low_candidate is not None and abs(value-self.low_candidate)<=4 else 1
                self.low_candidate = value
                if self.low_count >= 2:
                    self.previous = value
                    self.low_candidate = None
                    self.low_count = 0
            return 0
        self.previous = value
        self.cycle_hits += gain
        return gain

    def finish_cycle(self, skill_used):
        hits = self.cycle_hits
        visible = self.cycle_visible
        # Shockwave may add many ticks; compare the five-M1 strings only when
        # no skill was used in that cycle.
        if not skill_used:
            if hits >= 3:
                self.best_plain_cycle = max(self.best_plain_cycle, min(5, hits))
            floor = max(2, round(self.best_plain_cycle*.5))
            self.poor_cycles = self.poor_cycles + 1 if not visible or hits < floor else 0
        self.cycle_hits = 0
        self.cycle_visible = False
        return self.poor_cycles >= 3

    def reset_allowed(self, now):
        while self.reset_times and now-self.reset_times[0] > 600:
            self.reset_times.popleft()
        if len(self.reset_times) >= 3:
            return False
        self.reset_times.append(now)
        self.poor_cycles = 0
        self.previous = None
        self.low_candidate = None
        self.low_count = 0
        self.cycle_hits = 0
        self.cycle_visible = False
        return True
