"""Damage samples based only on the in-game title counter."""


class DamageMeasurements:
    def __init__(self, target, starting_total=0, active_seconds=0):
        self.target = int(target)
        self.starting_total = int(starting_total)
        self.total = int(starting_total)
        self.active_seconds = float(active_seconds)
        self.first_m1 = self.fifth_m1 = self.middle_m1 = None
        self.five_m1 = None
        self.moves = {}
        self.last_verified = None

    def observe(self, value, at):
        value = int(value)
        if not self.total <= value <= self.target:
            raise ValueError('Damage title progress decreased or exceeded the target')
        self.total = value
        self.last_verified = at

    def calibrate_m1(self, first, four, five):
        first, four, five = int(first), int(four), int(five)
        if first <= 0 or four < first or five <= four:
            raise ValueError('First, four-hit and five-hit damage samples did not increase')
        self.first_m1 = first
        self.middle_m1 = (four-first)/3
        self.fifth_m1 = five-four
        self.five_m1 = five

    def calibrate_move(self, name, damage):
        damage = int(damage)
        if damage <= 0:
            raise ValueError(f'{name} did not show a positive damage-title increase')
        self.moves[name] = damage

    def summary(self):
        gained = max(0, self.total-self.starting_total)
        dps = gained/self.active_seconds if self.active_seconds >= 15 and gained else None
        remaining = max(0, self.target-self.total)
        return {'title_progress': self.total, 'title_target': self.target,
                'estimated_damage': gained, 'estimated_dps': round(dps, 2) if dps else None,
                'remaining_damage': remaining,
                'eta_hours': round(remaining/dps/3600, 2) if dps else None,
                'first_m1_damage': self.first_m1, 'middle_m1_damage': self.middle_m1,
                'fifth_m1_damage': self.fifth_m1, 'five_m1_damage': self.five_m1,
                'move_damage': dict(self.moves), 'last_verified': self.last_verified}
