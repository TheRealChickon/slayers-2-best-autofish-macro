"""Shared damage pace labels for the CLI and terminal dashboard."""
import time


def skill_lines(damage):
    samples = damage.get('skill_samples') or {}
    labels = [('m1_string', 'Five M1s'), ('shock_wave', 'C'),
              ('followup', 'Z'), ('ultimate', 'X+B combined')]
    lines = ['Damage per use (isolated title samples):']
    for role, label in labels:
        sample = samples.get(role)
        if sample:
            stamp = time.strftime('%H:%M', time.localtime(sample['at']))
            lines.append(f"  {label:<14} {sample['damage']:,} damage (sample {stamp})")
        else:
            lines.append(f'  {label:<14} Not measured')
    lines.append('Remeasure after build changes: autofish damage --measure-skills')
    return lines


def pace_labels(damage, now=None):
    now = time.time() if now is None else now
    verified = damage.get('last_verified')
    age = max(0, now-verified) if verified else None
    stale = age is None or age > 420
    rate = damage.get('recent_dph')
    window = damage.get('pace_window_seconds', 0)
    pace = (f'{rate:,.0f} damage/hour ({window/60:.1f}m sample)'
            if rate is not None else 'Awaiting two title readings')
    if stale and rate is not None:
        pace += ' [stale]'
    finish = damage.get('estimated_finish_at')
    eta = damage.get('recent_eta_seconds')
    moving = damage.get('running') and damage.get('stage') in (
        'attacking', 'waiting_animation', 'checking_damage')
    if finish is not None and eta is not None and not stale and moving:
        minutes = int((eta+59)//60)
        timing = f'{minutes//60}h {minutes%60:02d}m; around '+time.strftime('%a %H:%M', time.localtime(finish))+' local'
    else:
        timing = 'Awaiting current running pace' if rate is None or stale or not moving else 'No progress in sample'
    sample = f'{int(age)}s ago' if age is not None else 'Not verified yet'
    return pace, timing, sample
