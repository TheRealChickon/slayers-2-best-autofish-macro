"""A CLI-only warning for starting an unattended full-farmer night run."""
import math
import time


def warning(data, now=None):
    now=now or time.localtime()
    if data.get('mode')!='full' or not (now.tm_hour>=22 or now.tm_hour<6):
        return None
    if data.get('bait_source')!='inventory read':
        return 'Equipped bait has not been read yet; check again after full farmer starts.'
    remaining=data.get('bait_remaining_estimate')
    rate=data.get('hooks_per_hour') or 0
    threshold=max(60,math.ceil(rate*.5))
    if remaining is not None and remaining<threshold:
        return f'Low bait for an overnight run: about {remaining:,} left (under 30 minutes at the observed pace). Fishing continues without bait.'
    return None
