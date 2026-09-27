"""Fishing CLI. Opening it only reads status; Continue explicitly starts input."""
import argparse
import ctypes
import getpass
import json
import os
import shlex
import sys
import time
from item_journal import Journal
from status_view import snapshot, duration, estimate
from live_feed import event_tone, state_tone
import control_actions as actions
from app_config import MODES
from bait_warning import warning as bait_warning

COLORS = {'gold': 33, 'green': 32, 'red': 31, 'cyan': 36, 'gray': 90, 'white': 97, 'text': 97}


def color(text, tone='white', enabled=True):
    return f'\033[{COLORS[tone]}m{text}\033[0m' if enabled else str(text)


def enable_color(force=False):
    if not force and (not sys.stdout.isatty() or 'NO_COLOR' in os.environ):
        return False
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetStdHandle.argtypes = [ctypes.c_int32]
        kernel.GetStdHandle.restype = ctypes.c_void_p
        kernel.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        handle, mode = kernel.GetStdHandle(-11), ctypes.c_uint32()
        return bool(kernel.GetConsoleMode(handle, ctypes.byref(mode)) and
                    kernel.SetConsoleMode(handle, mode.value | 4)) or force
    return True


def status_lines(data, colors=False):
    c = lambda text, tone='white': color(text, tone, colors)
    tone = state_tone(data['state'],data['running'] and not data['stop_requested'])
    remain = data['bait_remaining_estimate']
    hours = data['bait_hours_remaining_estimate']
    recent=data.get('recent')
    rates=(f"  Recent pace     {recent['hooks_per_minute']:.2f} hooks/min · {recent['items_per_minute']:.2f} items/min"
           + f" · {recent['window_seconds']/60:.0f}m window" + ('' if recent['fresh'] else ' (saved)')) if recent else '  Recent pace     Collecting a sample'
    lines = [
        c('FISHING', 'gold') + '  /  ' + c(data['state'].upper(), tone) + '  /  ' + MODES.get(data.get('mode'),'Full farmer'),
        c('  '+data['reason'], 'gold') if data.get('reason') else '',
        '',
        f"  Collected       {c(format(data['items'], ','), 'green')} items / {data['collections']:,} collections",
        f"  Hooks / casts   {data['hooks']:,} / {data['casts']:,}",
        f"  Fishing time    {duration(data['active_seconds'])}",
        f"  Server rejoins  {data['server_rejoins']} completed after the first join",
        f"  Game launches   {data['game_launches']} attempts",
        f"  Last item       {data['last_item'] or '-'}",
        rates,
        ('  Phase time      '+', '.join(f'{key.replace("_"," ")} {value:.0f}s' for key,value in recent['phase_seconds'].items())) if recent else '',
        '',
        f"  Bait            {'~' + format(remain, ',') + ' left' if remain is not None else 'Unknown'} · {data.get('bait_source','unknown')}",
        f"  Consumption     ~{data['hooks_per_hour']:.0f} bait/hour" + (f' / ~{hours:.1f} hours left' if hours is not None else ''),
        c('                  One bait per hook; fishing continues without bait.', 'gray'),
        f"  Presence        {data['presence']}",
        c(f"  Item log        {data['logged_collections']:,} collections; {data['unread_items']} items with partial/unread names", 'gray'),
    ]
    alert=bait_warning(data) if data.get('running') or data.get('starting') else None
    if alert:lines.append(c('  '+alert,'red'))
    return lines


def parser(prog='autofish'):
    p = argparse.ArgumentParser(prog=prog, description='Fishing status, item journal and explicit controls.')
    p.add_argument('--no-color', action='store_true', help='Disable terminal colors')
    p.add_argument('--color', action='store_true', help='Use ANSI colors even when NO_COLOR is inherited')
    sub = p.add_subparsers(dest='command')
    start = sub.add_parser('start', help='Choose a game and mode, then open the dashboard')
    start.add_argument('--game', help='Game ID from autofish games; omit to choose')
    start.add_argument('--mode', choices=tuple(MODES), help='Omit to choose a fishing mode')
    start.add_argument('--no-ui', action='store_true', help='Start and exit without opening the dashboard')
    sub.add_parser('games', help='List supported games and their IDs')
    for name, help_text in [('status', 'Show the saved run and bot status'), ('items', 'Show item totals')]:
        command = sub.add_parser(name, help=help_text)
        command.add_argument('--json', action='store_true', help='Machine-readable JSON')
        if name == 'items':
            command.add_argument('--filter', default='', help='Match part of an item name')
    logs = sub.add_parser('logs', help='Read collection or recovery logs')
    logs.add_argument('--tail', type=int, default=20, metavar='N')
    logs.add_argument('--all', action='store_true')
    logs.add_argument('--follow', '-f', action='store_true', help='Stream new entries; Ctrl+C exits the view')
    logs.add_argument('--activity', action='store_true', help='Show recovery/control events instead of items')
    logs.add_argument('--filter', default='')
    logs.add_argument('--json', action='store_true', help='One JSON object per line')
    watch = sub.add_parser('watch', help='Live colored status; Ctrl+C exits the view')
    watch.add_argument('--interval', type=float, default=2, metavar='SECONDS')
    plan = sub.add_parser('plan', help='Estimate bait for a future session using the observed hook rate')
    plan.add_argument('--hours', type=float, required=True)
    sub.add_parser('pause', help='Release game input and retain counters')
    resume=sub.add_parser('continue', aliases=['resume'], help='Explicitly start the selected mode')
    resume.add_argument('--mode',choices=('full','assist','spot'),help='Full farmer, minigame only, or fish here')
    sub.add_parser('assist',help='Start minigame only; you cast and collect manually')
    sub.add_parser('spot',help='Click, reel and collect; F8 starts/pauses/resumes, losing focus pauses automatically')
    reference=sub.add_parser('reference',help='Save a local fishing view while paused')
    reference.add_argument('operation',choices=('status','save','disable'),nargs='?',default='status')
    reference.add_argument('--position',action='store_true',help='Calibrate small position corrections as well as camera movement')
    reference.add_argument('--boxes',help='JSON list of x,y,width,height boxes in a 1280x720 screenshot; two near surfaces first, then optional distant scenery')
    sub.add_parser('diagnostics',help='Show the last eight failure reports and local screenshot paths')
    sub.add_parser('stop', help='Stop game input and retain counters')
    sub.add_parser('export', help='Save the complete item log and totals as CSV')
    wiki=sub.add_parser('wiki', help='Build and open the local item wiki from saved captures')
    wiki.add_argument('--no-open', action='store_true', help='Build files without opening the browser')
    webhook=sub.add_parser('webhook', help='Set or inspect the hourly Discord webhook')
    webhook.add_argument('operation', choices=('status','set','verify','remove'), nargs='?', default='status')
    tui=sub.add_parser('tui', help='Keyboard interface with live logs and settings')
    tui.add_argument('--page', choices=('run','items','log','setup'), default='run')
    sub.add_parser('shell', help='Interactive command prompt; does not start fishing')
    from control_api import COMMANDS
    api = sub.add_parser('api', help='Versioned JSON interface for local integrations')
    api.add_argument('operation', choices=COMMANDS)
    api.add_argument('--request-id', help='Caller correlation ID; not an idempotency key')
    api.add_argument('--limit', type=int, default=50, help='Recent events, 1–200 (default 50)')
    return p


def log_line(row, activity=False, colors=False):
    stamp = time.strftime('%m-%d %H:%M:%S', time.localtime(row['at']))
    if activity:
        text = f"{stamp}  {row['kind']:<23} {row['message']}"
        tone = event_tone(row)
    else:
        text = f"{stamp}  x{row['quantity']:<3} {row['item']:<26} {row['raw']}"
        tone = 'gold' if any(word in row['item'] for word in ('Golden', 'Clown', 'Zebra')) else 'green'
    return color(text, tone, colors)


def stream_logs(args, journal, colors):
    if args.tail < 0:
        raise ValueError('--tail must be zero or greater')
    seen, previous_run = set(), None
    first = True
    while True:
        data = snapshot(journal)
        if data['started'] != previous_run:
            seen.clear()
            previous_run = data['started']
            first = True
        rows = journal.activity if args.activity else journal.items
        rows = [r for r in rows if args.filter.lower() in json.dumps(r).lower()]
        # Include the occurrence index so two equal-timestamp drops remain distinct.
        keyed = [(json.dumps(row, sort_keys=True) + ':' + str(i), row) for i, row in enumerate(rows)]
        visible = keyed if args.all or not first else keyed[-args.tail:] if args.tail else []
        for key, row in visible:
            if key not in seen:
                print(json.dumps(row) if args.json else log_line(row, args.activity, colors), flush=True)
        seen.update(key for key, row in keyed)
        first = False
        if not args.follow:
            return 0
        time.sleep(1)


def execute(args, colors=False):
    command = args.command or 'status'
    if command=='start':
        from start_picker import start
        return start(args, colors)
    if command=='games':
        from game_catalog import GAMES
        for key,game in GAMES.items():print(f'{key:<24} {game.name}')
        return 0
    if command=='reference':
        import landmark_controls as references
        if args.operation=='save':print(references.setup(args.position,json.loads(args.boxes) if args.boxes else None))
        elif args.operation=='disable':print(references.disable())
        else:print(json.dumps(references.status(),indent=2))
        return 0
    if command=='diagnostics':
        from metrics import RUN
        path=RUN/'diagnostics/index.json'
        print(path)
        print(path.read_text() if path.exists() else 'No failure reports saved')
        return 0
    if command=='wiki':
        from personal_wiki import build
        path,counts=build(open_site=not args.no_open)
        print(f'Wiki: {path}')
        print(f"{counts['inventory']} owned variants · {counts['archive_only']} archive-only entries")
        return 0
    if command=='webhook':
        from app_config import data_directory
        from discord_hourly import SECRET_FILE, configure_secret, load_secret, request_webhook
        run=data_directory()
        if args.operation=='status':
            print('Discord webhook: configured' if (run/SECRET_FILE).exists() else 'Discord webhook: not configured')
        elif args.operation=='set':
            value=getpass.getpass('Discord webhook URL: ') if sys.stdin.isatty() else sys.stdin.read().strip()
            configure_secret(run,value)
            print('Discord webhook saved locally for hourly reports.')
        elif args.operation=='verify':
            code,_=request_webhook(load_secret(run))
            print(f'Discord webhook reachable (HTTP {code}); no message sent.')
        else:
            (run/SECRET_FILE).unlink(missing_ok=True)
            print('Discord webhook removed. Hourly posts will fail until a new one is set.')
        return 0
    if command == 'api':
        from control_api import dispatch
        response, code = dispatch(args.operation, args.request_id, args.limit)
        print(json.dumps(response, ensure_ascii=True), flush=True)
        return code
    if command in ('pause', 'stop', 'continue', 'resume', 'assist', 'spot'):
        action = {'pause': actions.pause, 'stop': actions.stop,
                  'continue':lambda:actions.resume(getattr(args,'mode',None)),
                  'resume':lambda:actions.resume(getattr(args,'mode',None)),
                  'assist':lambda:actions.resume('assist'),
                  'spot':lambda:actions.resume('spot')}[command]
        print(color(action(), 'green' if command in ('continue', 'resume') else 'gold', colors))
        return 0
    if command == 'tui':
        from terminal_app import Terminal
        client=Terminal();client.switch(('run','items','log','setup').index(args.page))
        return client.run()
    if command == 'shell':
        return shell(colors)
    journal = Journal()
    data = snapshot(journal)
    if command == 'status':
        print(json.dumps(data, indent=2) if getattr(args, 'json', False) else '\n'.join(status_lines(data, colors)))
    elif command == 'items':
        rows = [{'item': item, 'quantity': qty} for item, qty in journal.counts.most_common() if args.filter.lower() in item.lower()]
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            print(color('COLLECTED THIS RUN', 'gold', colors))
            for row in rows:
                print(f"  {row['item']:<32} x{row['quantity']:,}")
            print(f"  {'Total':<32} {sum(row['quantity'] for row in rows):,}")
    elif command == 'logs':
        return stream_logs(args, journal, colors)
    elif command == 'export':
        print('Saved ' + str(journal.export()))
    elif command == 'plan':
        if not 0 < args.hours < float('inf'):
            raise ValueError('--hours must be a positive, finite number')
        amount = estimate(data, args.hours)
        print(f'For {args.hours:g} hours: ~{amount:,} bait at {data["hooks_per_hour"]:.0f} hooks/hour.' if amount is not None else 'No hook-rate sample yet.')
        print('Estimate only. Empty rounds use bait too; fishing continues after bait runs out.')
    elif command == 'watch':
        if not 0.5 <= args.interval <= 3600:
            raise ValueError('--interval must be between 0.5 and 3600 seconds')
        while True:
            if colors:
                print('\033[2J\033[H', end='')
            print('\n'.join(status_lines(snapshot(journal), colors)))
            print(color('\nCtrl+C exits this view. Fishing is unchanged.', 'gray', colors), flush=True)
            time.sleep(args.interval)
    return 0


def shell(colors):
    print('\n'.join(status_lines(snapshot(), colors)))
    print(color('\nModes: assist, spot, continue --mode full\nCommands: status, watch, items, logs, pause, continue, stop, webhook, plan --hours 8, export', 'gray', colors))
    print('help shows options. exit closes this prompt and leaves the bot unchanged.\n')
    while True:
        try:
            line = input(color('fishing > ', 'gold', colors)).strip()
        except (KeyboardInterrupt, EOFError):
            print('\nCLI closed. Fishing is unchanged.')
            return 0
        if not line:
            continue
        if line.lower() in ('exit', 'quit', 'q'):
            return 0
        if line.lower() in ('help', '?'):
            parser().print_help()
            continue
        try:
            args = parser().parse_args(shlex.split(line))
            if args.command == 'shell':
                print('Already in the fishing prompt.')
                continue
            execute(args, colors and not args.no_color)
        except KeyboardInterrupt:
            print('\nView closed. Fishing is unchanged.')
        except SystemExit:
            pass  # Bad arguments or --help should not close the interactive prompt.
        except Exception as e:
            print(color(str(e), 'red', colors))


def main(argv=None, prog='autofish'):
    args = parser(prog).parse_args(argv)
    colors = enable_color(args.color) and not args.no_color
    if colors and args.command in ('watch', 'shell', 'tui'):
        print('\033]0;Fishing CLI\007', end='', flush=True)
    try:
        return execute(args, colors)
    except KeyboardInterrupt:
        print('\nView closed. Fishing is unchanged.')
        return 0
    except Exception as e:
        print('Error: ' + str(e), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
