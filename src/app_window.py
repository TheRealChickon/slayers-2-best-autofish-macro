"""The Autofish app window: a Rod Lab-style dashboard served only to this PC.

Autofish.exe starts this file. It serves app_template.html on 127.0.0.1 and opens it as an
Edge app window (any browser as a fallback). Every request needs the per-launch token, and
the farmer itself keeps running in its own processes when the window closes.
"""
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import app_config
from app_config import CODE, ROOT, data_directory, load_config, save_config

TEMPLATE = CODE/'app_template.html'
OVERLAY_TEMPLATE = CODE/'overlay_template.html'
STATE_FILE = 'app-window.json'
IDLE_EXIT_SECONDS = 120
MODES = ('full', 'here', 'assist', 'spot')
SWITCHES = {'overnight': 'overnight_enabled', 'auto_idle': 'overnight_auto_enable_idle',
            'auto_titles': 'auto_fishing_titles'}
RODS = ('Legendary', 'Rare', 'Common')  # Common and Basic are the same rod
HOTBAR_KEYS = 5


def version():
    try: return (ROOT/'VERSION').read_text(encoding='utf-8').strip().split('-')[0] or 'dev'
    except OSError: return 'dev'


def catch_rows(counts):
    import rod_stats
    fish = {}
    for name, quantity in counts.items():
        key = rod_stats.key_of(name)
        if key in rod_stats.PRICES: fish[key] = fish.get(key, 0)+quantity
    rows = [{'name': rod_stats.NAMES[k], 'count': v, 'rarity': rod_stats.RARITY[k]} for k, v in fish.items()]
    return sorted(rows, key=lambda r: -r['count']), fish


def current_rod():
    import rod_stats
    try:
        open_sessions = [s for s in rod_stats.sessions() if not s.get('ended')]
        return open_sessions[-1]['rod'] if open_sessions else None
    except Exception:
        return None


def checks(s, config):
    presence = s['presence']
    rows = [{'label': 'Roblox', 'value': presence, 'ok': True if presence == 'In game' else False if presence == 'Offline' and s['running'] else None}]
    rows.append({'label': 'Account', 'value': config['account_username'] or 'Not set', 'ok': True if config['account_username'] else 'warn'})
    gamepass = config.get('spawn_gamepass')
    rows.append({'label': 'Spawn gamepass', 'value': 'Yes' if gamepass else 'No' if gamepass is False else 'Not answered',
                 'ok': True if gamepass else None})
    rows.append({'label': 'Rod slot', 'value': str(config['rod_slot']), 'ok': None})
    rows.append({'label': 'Overnight', 'value': 'On' if config['overnight_enabled'] else 'Off', 'ok': True if config['overnight_enabled'] else None})
    if s['bait_remaining_estimate'] is not None:
        low = s['bait_remaining_estimate'] < config.get('bait_reserve', 0)
        rows.append({'label': 'Bait', 'value': f"{s['bait_remaining_estimate']:,} left", 'ok': 'warn' if low else True})
    if s['unread_items']:
        rows.append({'label': 'Unread items', 'value': str(s['unread_items']), 'ok': 'warn'})
    return rows


def state(journal=None, feed=None):
    """Everything the window draws, from the same sources as `autofish status`."""
    import rod_stats
    from item_journal import Journal
    from live_feed import LiveFeed
    from status_view import snapshot
    journal = journal if journal is not None else Journal()
    s = snapshot(journal)
    config = load_config()
    catch, fish = catch_rows(journal.counts)
    hours = (s['active_seconds'] or 0)/3600
    feed = feed if feed is not None else LiveFeed()
    log_run = s.get('log_run') or {}
    feed.update(log_run.get('started', s['started']), state=s['state'] if s['running'] else None, ended=log_run.get('ended'))
    recent = s.get('recent') or {}
    # The header's Session clock: this run's fishing time when the run recorded its
    # starting total, otherwise the lifetime total (runs started before this field).
    base = log_run.get('active_at_start')
    if isinstance(base, (int, float)) and not log_run.get('ended'):
        s = {**s, 'active_seconds': max(0, (s['active_seconds'] or 0)-base)}
    return {**{k: s[k] for k in ('state', 'mode', 'running', 'starting', 'paused', 'manual_paused', 'reason', 'active_seconds',
                                  'activity_running', 'hooks', 'hooks_per_hour', 'last_item', 'collections', 'bait_remaining_estimate',
                                  'bait_hours_remaining_estimate')},
            'version': version(), 'game': 'Project Slayers 2', 'rod': current_rod(),
            'pace': recent.get('hooks_per_minute') if recent.get('fresh') else None,
            'fish': sum(fish.values()), 'catch': catch,
            'gold_per_hour': round(rod_stats.best_crates(fish)['gold']/hours) if fish and hours >= .1 else None,
            'bait_start': (s['bait_remaining_estimate'] or 0)+s['hooks'] if s['bait_remaining_estimate'] is not None else None,
            'events': feed.rows[-300:],
            'items': [{'item': name, 'quantity': qty, 'rarity': rod_stats.item_rarity(name)} for name, qty in journal.counts.most_common()],
            'checks': checks(s, config),
            'config': {'account_username': config['account_username'], 'spawn_gamepass': config.get('spawn_gamepass'),
                       'rod': config.get('active_rod') or current_rod(), 'webhook': webhook_saved(),
                       'rod_slot': config['rod_slot'], 'cast_point': list(config['cast_point']), **{k: bool(config.get(v)) for k, v in SWITCHES.items()}}}


def webhook_saved():
    from discord_hourly import SECRET_FILE
    return (data_directory()/SECRET_FILE).exists()


def python_console():
    exe = Path(sys.executable)
    return str(exe.with_name('python.exe')) if exe.name.lower() == 'pythonw.exe' else str(exe)


def action(body):
    import control_actions as actions
    name = body.get('action')
    if name == 'start':
        mode = body.get('mode') or load_config()['mode']
        if mode not in MODES: raise ValueError('Unknown mode')
        return actions.resume(mode=mode)
    if name == 'switch_mode':
        mode = body.get('mode')
        if mode not in MODES: raise ValueError('Unknown mode')
        return actions.switch_mode(mode)
    if name == 'resume': return actions.resume()
    if name == 'pause': return actions.pause()
    if name == 'stop': return actions.stop()
    if name == 'terminal':
        subprocess.Popen([python_console(), str(CODE/'fishing_cli.py'), '--color', 'tui'], cwd=str(ROOT),
                         creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))
        return 'Terminal dashboard opened'
    if name == 'capture_cast':
        from cast_point import capture_pointer
        time.sleep(4)
        point = capture_pointer()
        save_config({'cast_point': point})
        return f'Cast point saved: {point[0]}, {point[1]}'
    if name == 'data_folder':
        os.startfile(str(data_directory()))
        return 'Data folder opened'
    raise ValueError('Unknown action')


def settings(body):
    if len(body) != 1: raise ValueError('Change one setting at a time')
    (key, value), = body.items()
    if key == 'spawn_gamepass':
        app_config.set_spawn_gamepass(bool(value))
    elif key == 'account_username':
        save_config(app_config.resolve_account(str(value)))
    elif key == 'rod_slot':
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= HOTBAR_KEYS:
            raise ValueError(f'Rod slot is a number from 1 to {HOTBAR_KEYS}')
        save_config({'rod_slot': value})
    elif key == 'rod':
        if value not in RODS: raise ValueError('Rod is Legendary, Rare or Common')
        import rod_stats
        rod_stats.set_rod(value)
    elif key == 'webhook':
        from discord_hourly import configure_secret
        configure_secret(data_directory(), str(value).strip())
    elif key in SWITCHES:
        save_config({SWITCHES[key]: bool(value)})
    else:
        raise ValueError('Unknown setting')
    return 'Saved'


OVERLAY = None


def overlay():
    global OVERLAY
    if OVERLAY is None:
        from overlay import Overlay
        OVERLAY = Overlay(find_browser())
    return OVERLAY


def gear():
    """What the overlay shows as equipped: rod, its enchant and the fishing titles worn now."""
    import rod_stats
    root = data_directory()
    rod = load_config().get('active_rod') or current_rod()
    saved = (load_config().get('rod_buffs') or {}).get(rod, {})
    enchant = {**rod_stats.DEFAULT_BUFFS.get(rod, {}), **saved}.get('enchant', 0) if rod else 0
    buffs = rod_stats.title_buffs(root)
    titles = rod_stats.titles_at(root, time.time()) or []
    return {'rod': rod, 'enchant': enchant,
            'titles': [{'name': t, 'luck': (buffs.get(t) or {}).get('fishing_luck'), 'bite': (buffs.get(t) or {}).get('bite_speed')} for t in titles]}


def overlay_page(token):
    import rod_stats
    boot = json.dumps({'token': token, 'rarity': rod_stats.ITEM_RARITY})
    return OVERLAY_TEMPLATE.read_text(encoding='utf-8').replace('/*FONTS*/', rod_stats.font_faces()).replace('/*BOOT*/', boot)


def page(token):
    import rod_stats
    boot = json.dumps({'token': token, 'rarity': rod_stats.ITEM_RARITY})
    return TEMPLATE.read_text(encoding='utf-8').replace('/*FONTS*/', rod_stats.font_faces()).replace('/*BOOT*/', boot)


def make_server(token, port=0):
    seen = {'at': time.time()}
    # These readers already track file offsets. Keep them for this server's
    # lifetime, and serialize updates so dashboard and overlay polls cannot
    # replay the entire history or race while appending the same catch.
    from item_journal import Journal
    from live_feed import LiveFeed
    journal, feed = Journal(), LiveFeed()
    state_lock = threading.Lock()

    def read_state():
        with state_lock:
            return {**state(journal, feed), 'overlay': overlay().running}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def allowed(self):
            # Only this PC, only this window: a matching Host stops DNS rebinding and the
            # token (sent as a custom header) stops other web pages from driving the farmer.
            host = self.headers.get('Host', '')
            if host not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'): return False
            query = parse_qs(urlparse(self.path).query)
            given = self.headers.get('X-Autofish-Token') or (query.get('t') or [''])[0]
            return secrets.compare_digest(given, token)

        def send(self, code, body, kind='application/json'):
            data = body if isinstance(body, bytes) else (json.dumps(body) if kind == 'application/json' else body).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', kind+'; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.allowed(): return self.send(403, {'error': 'Forbidden'})
            seen['at'] = time.time()
            path = urlparse(self.path).path
            try:
                if path == '/': return self.send(200, page(token), 'text/html')
                if path == '/rodlab':
                    import rod_stats
                    return self.send(200, rod_stats.dashboard(rod_stats.export_data()), 'text/html')
                if path == '/api/state': return self.send(200, read_state())
                if path == '/overlay': return self.send(200, overlay_page(token), 'text/html')
                if path == '/api/gear': return self.send(200, gear())
            except Exception as error:
                return self.send(500, {'error': str(error)})
            self.send(404, {'error': 'Not found'})

        def do_POST(self):
            if not self.allowed() or 'application/json' not in self.headers.get('Content-Type', ''):
                return self.send(403, {'error': 'Forbidden'})
            seen['at'] = time.time()
            try:
                length = min(int(self.headers.get('Content-Length') or 0), 65536)
                body = json.loads(self.rfile.read(length) or b'{}')
                if not isinstance(body, dict): raise ValueError('Bad request')
                path = urlparse(self.path).path
                if path == '/api/action' and body.get('action') == 'overlay':
                    on = body.get('on', not overlay().running)
                    if on: overlay().start(f'http://127.0.0.1:{self.server.server_port}/overlay?t={token}')
                    else: overlay().stop()
                    message = 'Overlay on' if on else 'Overlay off'
                elif path == '/api/action': message = action(body)
                elif path == '/api/settings': message = settings(body)
                else: return self.send(404, {'error': 'Not found'})
                return self.send(200, {'message': message, 'state': read_state()})
            except Exception as error:
                return self.send(400, {'error': str(error)})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.last_seen = seen
    return server


def find_browser():
    """Edge ships with Windows 10 and 11; Chrome works the same way."""
    roots = [os.environ.get(k) for k in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA')]
    for root in filter(None, roots):
        for rel in (r'Microsoft\Edge\Application\msedge.exe', r'Google\Chrome\Application\chrome.exe'):
            path = Path(root)/rel
            if path.exists(): return str(path)
    return shutil.which('msedge') or shutil.which('chrome')


def open_window(url):
    """Open the app window; returns the browser process to wait on, or None."""
    browser = find_browser()
    if not browser:
        webbrowser.open(url)
        return None
    profile = data_directory()/'app-window-profile'
    return subprocess.Popen([browser, f'--app={url}', f'--user-data-dir={profile}', '--window-size=1240,880',
                             '--no-first-run', '--no-default-browser-check', '--disable-features=Translate'])


def running_window():
    """The window server already serving this install, if any."""
    import urllib.request
    try:
        info = json.loads((data_directory()/STATE_FILE).read_text(encoding='utf-8'))
        request = urllib.request.Request(f"http://127.0.0.1:{info['port']}/api/state",
                                         headers={'X-Autofish-Token': info['token'], 'Host': f"127.0.0.1:{info['port']}"})
        with urllib.request.urlopen(request, timeout=3): pass
        return info
    except Exception:
        return None


def url_for(info):
    return f"http://127.0.0.1:{info['port']}/?t={info['token']}"


def tray_wanted():
    """Closing the window hides Autofish to the tray only while Start when idle is on."""
    try: return bool(load_config().get('overnight_auto_enable_idle')) and os.name == 'nt'
    except Exception: return False


def start_tray(on_open, on_quit):
    try:
        from tray import Tray
        return Tray(ROOT/'assets'/'fishing.ico', 'Autofish: start when idle is on', on_open, on_quit).start()
    except Exception:
        return None


def main():
    existing = running_window()
    if existing:
        open_window(url_for(existing))
        return 0
    token = secrets.token_urlsafe(24)
    server = make_server(token)
    info = {'pid': os.getpid(), 'port': server.server_port, 'token': token}
    path = data_directory()/STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info), encoding='utf-8')
    threading.Thread(target=server.serve_forever, daemon=True).start()
    browser = open_window(url_for(info))
    tray, wanted = None, {'open': False, 'quit': False}
    try:
        while True:
            time.sleep(1)
            if wanted['quit']: break
            if wanted['open']:
                wanted['open'] = False
                if tray is not None: tray.stop(); tray = None
                browser = open_window(url_for(info))
                server.last_seen['at'] = time.time()
                continue
            closed = (browser.poll() is not None and time.time()-server.last_seen['at'] > 10) if browser is not None \
                else time.time()-server.last_seen['at'] > IDLE_EXIT_SECONDS
            if not closed or tray is not None: continue
            # With Start when idle on, closing the window keeps Autofish in the tray so the
            # idle start can still happen; with it off, closing the window quits as before.
            if tray_wanted():
                tray = start_tray(lambda: wanted.__setitem__('open', True), lambda: wanted.__setitem__('quit', True))
                if tray is not None: continue
            break
    finally:
        if tray is not None: tray.stop()
        if OVERLAY is not None: OVERLAY.stop()
        server.shutdown()
        try:
            if json.loads(path.read_text(encoding='utf-8')).get('pid') == os.getpid(): path.unlink()
        except (OSError, ValueError):
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
