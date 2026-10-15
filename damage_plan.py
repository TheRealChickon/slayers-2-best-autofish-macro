"""Configurable five-M1, two-move, conditional ultimate rotation."""

import math
import re


DEFAULT_ROTATION = {
    'enabled': ['shock_wave', 'followup', 'ultimate'],
    'keys': {'shock_wave': 'C', 'followup': 'Z', 'ultimate_prep': 'X', 'ultimate': 'B'},
    'names': {'shock_wave': 'Shock Wave', 'followup': 'Follow-up', 'ultimate': 'Special ultimate'},
    'm1_interval': .42, 'post_m1_wait': .75,
    'shock_wave_seconds': 1.0, 'followup_seconds': 1.0,
    'ultimate_cooldown_seconds': 60.0, 'ultimate_hold_seconds': 2.0,
    'ultimate_prep_tap_seconds': .025, 'ultimate_prep_wait_seconds': .5, 'combo_gap': 1.65,
}


def validate_rotation(value):
    if not isinstance(value, dict):
        raise ValueError('Damage rotation must be an object')
    result = {**DEFAULT_ROTATION, **value}
    enabled = result['enabled']
    if not isinstance(enabled, list) or len(enabled) != len(set(enabled)) or any(
            role not in ('shock_wave', 'followup', 'ultimate') for role in enabled):
        raise ValueError('Enabled damage moves must be a unique list of shock_wave, followup and ultimate')
    keys = {**DEFAULT_ROTATION['keys'], **value.get('keys', {})}
    names = {**DEFAULT_ROTATION['names'], **value.get('names', {})}
    if set(keys) != set(DEFAULT_ROTATION['keys']):
        raise ValueError('Damage rotation needs four key roles')
    for role, key in keys.items():
        key = str(key).upper().strip()
        if not re.fullmatch(r'[A-Z0-9]', key) or key == 'M':
            raise ValueError(f'{role} needs one letter or digit key, except menu key M')
        keys[role] = key
    if len(set(keys.values())) != 4:
        raise ValueError('Damage rotation keys must be distinct')
    for role, name in names.items():
        if not isinstance(name, str) or not name.strip() or len(name) > 60:
            raise ValueError(f'{role} needs a short move name')
        names[role] = name.strip()
    bounds = {'m1_interval': (.15, 2), 'post_m1_wait': (.5, 1.),
              'shock_wave_seconds': (.1, 15), 'followup_seconds': (.1, 15),
              'ultimate_cooldown_seconds': (1, 600), 'ultimate_hold_seconds': (.1, 15),
              'ultimate_prep_tap_seconds': (.01, .05),
              'ultimate_prep_wait_seconds': (.5, 2), 'combo_gap': (.5, 5)}
    for field, (minimum, maximum) in bounds.items():
        number = float(result[field])
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError(f'{field} must be between {minimum} and {maximum} seconds')
        result[field] = number
    result['keys'], result['names'], result['enabled'] = keys, names, list(enabled)
    return result


class DamageRotation:
    """Schedules one action at a time; X is emitted only together with B."""

    def __init__(self, settings):
        self.settings = validate_rotation(settings)
        self.last_ultimate = float('-inf')
        self.resync(0)

    def resync(self, now):
        self.phase, self.next_at, self.m1_index = 'm1', now+2.5, 0

    def due(self, now, ultimate_ready=False, shock_wave_ready=True, followup_ready=True):
        if now < self.next_at:
            return None
        s = self.settings
        if self.phase == 'm1':
            self.m1_index += 1
            if self.m1_index == 5:
                self.phase, self.next_at = 'shock_wave', now+s['post_m1_wait']
            else:
                self.next_at = now+s['m1_interval']
            return ('m1', self.m1_index)
        if self.phase == 'shock_wave':
            self.phase, self.next_at = 'followup', now+s['shock_wave_seconds']
            if 'shock_wave' not in s['enabled'] or not shock_wave_ready:
                self.next_at = now
                return ('skip_shock_wave', None)
            return ('shock_wave', None)
        if self.phase == 'followup':
            self.phase, self.next_at = 'ultimate', now+s['followup_seconds']
            if 'followup' not in s['enabled'] or not followup_ready:
                self.next_at = now
                return ('skip_followup', None)
            return ('followup', None)
        if self.phase == 'ultimate':
            self.phase = 'gap'
            if ('ultimate' in s['enabled'] and ultimate_ready and
                    now-self.last_ultimate >= s['ultimate_cooldown_seconds']):
                self.last_ultimate = now
                self.next_at = (now+s['ultimate_prep_tap_seconds']+
                                s['ultimate_prep_wait_seconds']+
                                s['ultimate_hold_seconds']+s['combo_gap'])
                return ('ultimate_pair', None)
            self.next_at = now+s['combo_gap']
            return ('skip_ultimate', None)
        self.phase, self.m1_index = 'm1', 0
        return ('cycle_end', None)
