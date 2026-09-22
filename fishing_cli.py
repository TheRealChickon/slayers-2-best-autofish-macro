"""Fishing CLI. Opening it only reads status; Continue explicitly starts input."""
import argparse
import ctypes
import json
import os
import shlex
import sys
import time
from item_journal import Journal
from status_view import snapshot, duration, estimate
from live_feed import event_tone, state_tone
import control_actions as actions

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
    return [
        c('FISHING', 'gold') + '  /  ' + c(data['state'].upper(), tone),
        '',
        f"  Collected       {c(format(data['items'], ','), 'green')} items / {data['collections']:,} collections",
        f"  Hooks / casts   {data['hooks']:,} / {data['casts']:,}",
        f"  Fishing time    {duration(data['active_seconds'])}",
        f"  Server rejoins  {data['server_rejoins']} completed after the first join",
        f"  Game launches   {data['game_launches']} attempts",
        f"  Last item       {data['last_item'] or '-'}",
        '',
        f"  Bait estimate   {'~' + format(remain, ',') + ' left' if remain is not None else 'Starting stock unknown'}",
        f"  Consumption     ~{data['hooks_per_hour']:.0f} bait/hour" + (f' / ~{hours:.1f} hours left' if hours is not None else ''),
        c('                  One bait per hook; fishing continues without bait.', 'gray'),
        f"  Presence        {data['presence']}",
        c(f"  Item log        {data['logged_collections']:,} collections; {data['unread_items']} items with partial/unread names", 'gray'),
    ]


def parser():
    p = argparse.ArgumentParser(prog='fishing', description='Fishing status, item journal and explicit controls.')
    p.add_argument('--no-color', action='store_true', help='Disable terminal colors')
    p.add_argument('--color', action='store_true', help='Use ANSI colors even when NO_COLOR is inherited')
    sub = p.add_subparsers(dest='command')
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
    sub.add_parser('continue', aliases=['resume'], help='Explicitly rejoin/resume the saved run')
    sub.add_parser('stop', help='Stop game input and retain counters')
    sub.add_parser('export', help='Save the complete item log and totals as CSV')
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
    if command == 'api':
        from control_api import dispatch
        response, code = dispatch(args.operation, args.request_id, args.limit)
        print(json.dumps(response, ensure_ascii=True), flush=True)
        return code
    if command in ('pause', 'stop', 'continue', 'resume'):
        action = {'pause': actions.pause, 'stop': actions.stop, 'continue': actions.resume, 'resume': actions.resume}[command]
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
    print(color('\nCommands: status, watch, items, logs, pause, continue, stop, plan --hours 8, export', 'gray', colors))
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


def main(argv=None):
    args = parser().parse_args(argv)
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
