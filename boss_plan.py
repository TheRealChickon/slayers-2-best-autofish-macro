"""Bounded boss trials; missing vision is never a kill or a stuck character."""
from dataclasses import dataclass
import math


DEFAULT_BOSS = {
    'name': 'Saneri', 'respawn_seconds': 300,
    'm1_interval': .30, 'm1_count': 4, 'skill_gap': .25,
    'block_breaker': None, 'barrage': 'c', 'chase': 'z',
    'reset_after_combo': False, 'spawn_verified': False,
    'target_timeout': 35., 'fight_timeout': 65., 'max_approach_seconds': 4.,
    'near_label_y': 450, 'aim_offset_y': 180,
    'strategy': 'm1_reset', 'max_cycles': 100, 'respawn_wait': 5.,
}


def validate_boss(value):
    if not isinstance(value, dict):
        raise ValueError('Boss settings must be an object')
    config = {**DEFAULT_BOSS, **value}
    if config['name'] not in ('Saneri', 'Sanemi'):
        raise ValueError('Only the Saneri/Sanemi trial is supported')
    if config['strategy'] not in ('m1_reset', 'ultimate_reset', 'm1_c_reset', 'b_m1_c_reset',
                                  'k_m1_reset','block_k_m1_c_reset'):
        raise ValueError('Unknown boss strategy')
    for field, low, high in (('m1_count', 1, 4), ('max_cycles', 1, 10000)):
        if type(config[field]) is not int or not low <= config[field] <= high:
            raise ValueError(f'{field} must be an integer between {low} and {high}')
    for role in ('block_breaker', 'barrage', 'chase'):
        key = config[role]
        if key is not None and key not in ('r', 'x', 'z', 'c', 'b'):
            raise ValueError(f'{role} must use r, x, z, c or b')
    for field, low, high in (
        ('respawn_seconds', 300, 900), ('m1_interval', .15, .8),
        ('skill_gap', .1, 3), ('target_timeout', 2, 45),
        ('fight_timeout', 10, 120), ('max_approach_seconds', .1, 8),
        ('near_label_y', 450, 1000), ('aim_offset_y', -150, 200),
        ('respawn_wait', 3, 12),
    ):
        number = float(config[field])
        if not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f'{field} must be {low}–{high}')
        config[field] = number
    for field in ('reset_after_combo', 'spawn_verified'):
        if not isinstance(config[field], bool):
            raise ValueError(f'{field} must be a boolean')
    if config['reset_after_combo'] and not config['spawn_verified']:
        raise ValueError('Verify /set at the boss before enabling combo resets')
    return config


@dataclass(frozen=True)
class BossObservation:
    name: str | None = None
    hp: float | None = None
    maximum: float | None = None
    target: tuple | None = None
    player_fraction: float | None = None
    blocked: bool = False
    respawn_seconds: int | None = None
    target_height: float | None = None


class FightLedger:
    """Confirm health readings, deduplicate kills, and check reset retention."""
    def __init__(self):
        self.hp = None
        self.pending_hp = None
        self.pending_count = 0
        self.damage = 0.
        self.kills = 0
        self.in_fight = False
        self.last_progress = None
        self.killed_at = None
        self.reset_hp = None
        self.retention = 'untested'
        self.pending_timer = None
        self.timer_read_at = None

    def observe(self, observation, now):
        if observation.blocked or observation.name not in ('Saneri', 'Sanemi'):
            return None
        timer = observation.respawn_seconds
        if timer is not None and 0 <= timer <= 900:
            consistent = (self.pending_timer is not None and self.timer_read_at is not None
                          and 0 <= now-self.timer_read_at < 10
                          and abs((self.pending_timer-timer)-(now-self.timer_read_at)) < 3)
            self.pending_timer, self.timer_read_at = timer, now
            if consistent and self.in_fight:
                if self.hp is not None:
                    self.damage += self.hp
                self.hp = 0
                self.kills += 1
                self.in_fight = False
                self.killed_at = now
                self.reset_hp = None
                return 'kill'
            return None
        self.pending_timer = self.timer_read_at = None
        hp, maximum = observation.hp, observation.maximum
        if hp is None or maximum is None or maximum != 3000 or not 0 <= hp <= maximum:
            return None
        if (self.pending_hp is not None and abs(hp-self.pending_hp) <= 2
                and (hp == 0) == (self.pending_hp == 0)):
            self.pending_count += 1
        else:
            self.pending_hp, self.pending_count = hp, 1
        if self.pending_count < 2:
            return None
        if self.reset_hp is not None:
            # Reset may remove the header temporarily; only reacquisition can
            # establish retention. Never infer it from a missing health bar.
            self.retention = 'retained' if hp <= self.reset_hp+3 else 'healed'
            self.reset_hp = None
        if self.hp is not None and hp < self.hp:
            self.damage += self.hp-hp
            self.last_progress = now
        if hp > 0:
            self.in_fight = True
        killed = hp == 0 and self.in_fight
        if killed:
            self.kills += 1
            self.in_fight = False
            self.killed_at = now
        self.hp = hp
        return 'kill' if killed else 'health'

    def before_reset(self):
        if self.hp is None or self.hp <= 0:
            raise ValueError('A live boss health reading is required for a reset trial')
        self.reset_hp = self.hp
        self.retention = 'checking'
        self.pending_count = 0
        self.pending_hp = None


def can_attack(observation):
    return (not observation.blocked and observation.name in ('Saneri', 'Sanemi')
            and observation.respawn_seconds is None
            and observation.hp is not None and observation.hp > 0
            and observation.target is not None
            and observation.player_fraction is not None and observation.player_fraction > .25)


def combo_roles(config):
    if config['strategy'] == 'ultimate_reset':
        return ['ultimate']
    return ['m1']*config['m1_count'] + (['c'] if config['strategy'] == 'm1_c_reset' else [])
