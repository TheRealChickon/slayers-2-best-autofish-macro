"""Boss observations are kept distinct from verified statue title damage."""
def boss_lines(data):
    hp = data.get('boss_hp')
    observation = data.get('observation') or {}
    player = observation.get('player_fraction')
    timer = data.get('respawn_remaining')
    if timer is None: timer = observation.get('respawn_seconds')
    rows = [
        'SANEMI / '+data.get('operation', 'trial').upper(),
        data.get('reason') or data.get('wait_reason') or 'No boss trial recorded',
        f"Boss HP          {f'{hp:,.2f} / 3,000' if hp is not None else 'Unread'}",
        f"Player health    {f'{player:.0%}' if player is not None else 'Unread'}",
        f"Target           {'Located' if observation.get('target') else 'Not located'}",
        f"Respawn timer    {f'{timer//60}:{timer%60:02}' if timer is not None else 'Not shown'}",
        f"Observed HP loss {data.get('observed_damage', 0):,.2f}",
        f"Observed DPH     {data.get('observed_dph', 0):,.0f} (session, including waits)",
        f"Confirmed kills  {data.get('confirmed_kills', 0)}",
        f"Reset retention  {data.get('reset_retention', 'untested')}",
        f"Combos / resets  {data.get('cycles', 0)} / {data.get('resets', 0)}",
        f"Spawn updates    {data.get('spawn_updates', 0)}",
        f"Actions sent     {data.get('actions', 0)}",
        'Unattended farming is not yet validated.',
        'Boss HP loss may include damage from other players.',
    ]
    for name, sample in (data.get('skill_samples') or {}).items():
        rows.append(f"{name}: last {sample['last']:,.1f} / average {sample['average']:,.1f} ({sample['samples']} samples)")
    for name,quantity in (data.get('loot_items') or {}).items():
        rows.append(f'Collected {name}: {quantity}')
    return rows
