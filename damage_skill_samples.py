"""Isolated title-counter samples; never infer skill damage from mixed combat."""


def stable_total(inspect, wait):
    previous = inspect()
    for _ in range(3):
        wait(3)
        current = inspect()
        if current == previous:
            return current
        if current < previous:
            raise ValueError('Title decreased during skill sampling')
        previous = current
    raise ValueError('Damage was still changing without attacks; sample rejected')


def sample_skill(inspect, wait, perform, settle_seconds):
    before = stable_total(inspect, wait)
    perform()
    wait(settle_seconds)
    after = stable_total(inspect, wait)
    if after <= before:
        raise ValueError('No positive isolated damage was measured')
    return {'damage': after-before, 'before': before, 'after': after}
