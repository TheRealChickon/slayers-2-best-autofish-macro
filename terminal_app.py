"""Keyboard terminal client. Closing the client never stops the supervisor."""
import math
import msvcrt
import queue
import re
import shutil
import sys
import threading
import time

import control_actions as actions
from app_config import load_config, resolve_account, save_config, MODES
from cast_point import capture_pointer, validate as validate_cast_point
from cli_effects import CatchEffects
from item_journal import Journal
from live_feed import LiveFeed, event_tone, state_tone
from metrics import read, write
from status_view import duration, estimate, snapshot

ESC = '\033['
RESET = ESC + '0m'
TONES = {'text': '234;236;226', 'dim': '128;142;137', 'gold': '232;186;64',
         'green': '156;219;112', 'red': '226;146;135', 'cyan': '111;193;207',
         'ore': '194;150;106', 'selected': '245;224;165'}
ANSI = re.compile(r'\x1b\[[0-9;]*m')


def tint(value, tone='text'):
    return ESC + '38;2;' + TONES[tone] + 'm' + str(value) + RESET


def clip(line, width):
    """Clip visible characters without breaking a color escape."""
    pieces, count = [], 0
    for piece in re.split(r'(\x1b\[[0-9;]*m)', line):
        if ANSI.fullmatch(piece):
            pieces.append(piece)
        elif count < width:
            pieces.append(piece[:width-count]); count += min(len(piece), width-count)
    return ''.join(pieces) + RESET


def rod_scene_frame(width, progress, phase):
    """Three header rows: a cast on open, a reel-in on close."""
    width = max(1, min(width-1, 110))
    cells = [[(' ', 'dim') for _ in range(width)] for _ in range(3)]

    def put(row, column, symbol, tone):
        if 0 <= row < 3 and 0 <= column < width:
            cells[row][column] = (symbol, tone)

    for offset, letter in enumerate('FISHING'):
        put(1, 2+offset, letter, 'gold')
    base = min(29, max(20, width//3))
    tip = base+9+round(2*math.sin(math.pi*progress))
    for row, column in ((2, base), (1, base+4), (0, tip-2)):
        put(row, column, '╱', 'gold')
        put(row, column+1, '╱', 'gold')
    put(2, base-3, '━', 'gold')
    put(2, base-2, '◉', 'gold')
    put(2, base-1, '╱', 'gold')
    for column in range(tip+5, width-1, 2):
        put(2, column, '≈', 'cyan')

    travel = progress if phase == 'opening' else 1-progress
    travel = travel*travel*(3-2*travel)
    float_x = round(tip+3 + (width-7-tip-3)*travel)
    for column in range(tip, float_x):
        put(0, column, '─', 'dim')
    put(0, float_x, '╎', 'dim')
    put(1, float_x, '●', 'red')
    if phase == 'opening' and progress > .72:
        put(1, float_x-2, '✦', 'cyan')
        put(1, float_x+2, '✦', 'cyan')
    elif phase == 'closing' and progress < .28:
        put(1, float_x-2, '·', 'cyan')
        put(1, float_x+2, '·', 'cyan')

    result = []
    for row in cells:
        runs = []
        for character, tone in row:
            if runs and runs[-1][1] == tone:
                runs[-1] = (runs[-1][0]+character, tone)
            else:
                runs.append((character, tone))
        result.append(''.join(tint(text, tone) for text, tone in runs))
    return result


class Terminal:
    pages = ('Run', 'Items', 'Live log', 'Setup')
    categories = ('All', 'Catches', 'Recovery', 'Warnings')
    run_modes = ('assist', 'spot', 'full')
    mode_details = {
        'assist': ('green', 'You cast + collect  ·  bot reels'),
        'spot': ('cyan', 'You pick the spot  ·  bot casts + collects'),
        'full': ('gold', 'Saved spawn  ·  bot rejoins + fishes'),
    }
    settings_keys = ('Username', 'Rod slot', 'Auto rod', 'Motion', 'Bait left',
                     'Plan hours', 'Mode', 'Cast point', 'Capture pointer',
                     'Position correction', 'Save reference', 'Disable reference')

    def __init__(self):
        self.journal, self.feed = Journal(), LiveFeed()
        self.data, self.config = {}, load_config()
        self.page = self.selection = self.scroll = 0
        self.query = ''
        self.category = 0
        self.follow = True
        self.editing = None
        self.buffer = ''
        self.alive = True
        self.jobs = queue.Queue()
        self.busy = False
        self.notice = ''
        self.notice_until = 0
        self.hours = 8.0
        self.height = 30
        self.last_lines = []
        self.changed_at = time.monotonic()
        self.effects = CatchEffects()
        import landmark_controls
        self.reference_position=landmark_controls.status()['position_enabled']

    def refresh(self):
        while not self.jobs.empty():
            ok, text = self.jobs.get()
            self.busy = False
            self.toast(text, ok)
        self.data = snapshot(self.journal)
        self.config = load_config()
        self.effects.observe(self.journal.items, self.data['started'], time.time(), time.monotonic())
        self.feed.update(self.data['started'], self.data['state'])
        if self.page == 1:
            self.selection = min(self.selection, max(0, len(self.item_rows())-1))

    def toast(self, text, ok=True):
        self.notice = tint(str(text).replace('\n', ' '), 'green' if ok else 'red')
        self.notice_until = time.monotonic() + 8

    def job(self, fn):
        if self.busy:
            self.toast('A command is still finishing.', False); return
        self.busy = True
        def run():
            try: self.jobs.put((True, fn()))
            except Exception as error: self.jobs.put((False, str(error)))
        threading.Thread(target=run, daemon=True).start()

    def item_rows(self):
        return [(name, qty) for name, qty in self.journal.counts.most_common()
                if self.query.lower() in name.lower()]

    def switch(self, page):
        self.page = page % len(self.pages)
        self.selection = self.scroll = 0
        self.query = ''
        self.changed_at = time.monotonic()

    def edit(self, key, value=''):
        self.editing, self.buffer = key, str(value)

    def finish_edit(self):
        key, value = self.editing, self.buffer.strip()
        self.editing = None
        try:
            if key == 'Search': self.query = value; self.selection = self.scroll = 0
            elif key == 'Username':
                def account():
                    save_config(resolve_account(value)); return 'Account saved'
                self.job(account)
            elif key == 'Rod slot': save_config({'rod_slot': int(value)})
            elif key == 'Cast point':
                save_config({'cast_point': validate_cast_point(value)})
                self.toast('Full farmer cast point saved')
            elif key == 'Plan hours':
                hours = float(value)
                if not math.isfinite(hours) or hours <= 0: raise ValueError('Enter positive hours')
                self.hours = hours
            elif key == 'Bait left':
                remaining = int(value)
                if remaining < 0: raise ValueError('Bait cannot be negative')
                stock = read('bait.json')
                stock['starting_stock'] = remaining + read('totals.json').get('rounds', 0)
                write('bait.json', stock); self.toast('Bait estimate updated')
        except (ValueError, OSError) as error: self.toast(error, False)

    def activate(self):
        if self.page == 0:
            if self.selection < len(self.run_modes):
                mode=self.run_modes[self.selection]
                self.job(lambda:actions.resume(mode))
            else:
                self.job((actions.pause, actions.stop,
                          lambda: 'Saved ' + str(self.journal.export()))[self.selection-len(self.run_modes)])
        elif self.page == 1:
            rows = self.item_rows()
            if rows:
                name = rows[self.selection][0]
                self.switch(2); self.query = name; self.category = 1; self.follow = True
        elif self.page == 3:
            key = self.settings_keys[self.selection]
            if key == 'Capture pointer':
                self.toast('Move the pointer over Roblox water; capturing in 4 seconds')
                def capture():
                    time.sleep(4)
                    point = capture_pointer()
                    save_config({'cast_point': point})
                    return f'Cast point saved: {point[0]}, {point[1]}'
                self.job(capture)
                return
            if key=='Position correction':self.reference_position=not self.reference_position;return
            if key in ('Save reference','Disable reference'):
                import landmark_controls
                position=self.reference_position
                self.job((lambda:landmark_controls.setup(position)) if key=='Save reference' else landmark_controls.disable)
                return
            if key == 'Mode':
                if self.data.get('running') or self.data.get('starting'):
                    self.toast('Pause before switching modes.',False);return
                modes=list(MODES)
                save_config({'mode':modes[(modes.index(self.config['mode'])+1)%len(modes)]})
                self.config=load_config();return
            if key in ('Auto rod', 'Motion'):
                option = 'auto_rod' if key == 'Auto rod' else 'reduced_motion'
                save_config({option: not self.config[option]}); self.config = load_config()
            else:
                value = {'Username': self.config['account_username'], 'Rod slot': self.config['rod_slot'],
                         'Bait left': self.data.get('bait_remaining_estimate') or 0,
                         'Plan hours': self.hours,
                         'Cast point': ', '.join(map(str, self.config['cast_point']))}[key]
                self.edit(key, value)

    def key(self, key):
        if self.editing:
            self.effects.secret = ''
            if key == 'ENTER': self.finish_edit()
            elif key == 'CANCEL': self.editing = None
            elif key == 'BACKSPACE': self.buffer = self.buffer[:-1]
            elif len(key) == 1 and key.isprintable(): self.buffer += key
            return
        self.effects.key(key, time.monotonic())
        if key.lower() == 'q': self.alive = False
        elif key in ('RIGHT', 'TAB'): self.switch(self.page+1)
        elif key in ('LEFT', 'BACKTAB'): self.switch(self.page-1)
        elif key in ('1', '2', '3', '4'): self.switch(int(key)-1)
        elif key == 'ENTER': self.activate()
        elif key == '/' and self.page in (1, 2): self.edit('Search', self.query)
        elif key.lower() == 'c': self.job(actions.resume)
        elif key.lower() == 'p': self.job(actions.pause)
        elif key.lower() == 's':
            # Stop must remain available even while another command is pending.
            try: self.toast(actions.stop())
            except Exception as error: self.toast(error, False)
        elif self.page == 2 and key.lower() == 'f': self.follow = not self.follow
        elif self.page == 2 and key.lower() == 'g': self.category = (self.category+1) % 4; self.scroll = 0
        elif key in ('UP', 'DOWN', 'PGUP', 'PGDN', 'HOME', 'END'):
            step = -1 if key == 'UP' else 1 if key == 'DOWN' else -(self.height-12) if key == 'PGUP' else self.height-12
            if self.page == 2:
                rows = self.feed.filtered(self.query, self.categories[self.category])
                limit = max(0, len(rows)-max(1, self.height-12))
                if self.follow: self.scroll = limit
                self.follow = key == 'END'
                self.scroll = 0 if key == 'HOME' else limit if key == 'END' else max(0, min(limit, self.scroll+step))
            else:
                count = len(self.run_modes)+3 if self.page == 0 else len(self.settings_keys) if self.page == 3 else len(self.item_rows())
                self.selection = 0 if key == 'HOME' else max(0, count-1) if key == 'END' else max(0, min(count-1, self.selection+step))

    def body(self, available):
        d = self.data
        if self.page == 0:
            amount = estimate(d, self.hours)
            rows = [tint(f"{d['items']:,} items", 'gold') + f"       {d['hooks']:,} hooks       {duration(d['active_seconds'])}", '',
                    f"{d['server_rejoins']} rejoins     {d['game_launches']} game launches     {d['failed_rounds']} failed rounds",
                    tint('Last catch  ', 'dim') + (d['last_item'] or '—'), '',
                    f"Bait ~{d['bait_remaining_estimate']:,}" if d['bait_remaining_estimate'] is not None else 'Bait —',
                    tint(f"~{d['hooks_per_hour']:.0f} / hour   •   {self.hours:g}h plan: " + (f'~{amount:,} bait' if amount is not None else 'collecting a sample'), 'dim'), '']
            recent=d.get('recent')
            if recent:
                rows[4:4]=[tint(f"{recent['hooks_per_minute']:.2f} hooks/min   {recent['items_per_minute']:.2f} items/min   {recent['recovery_seconds']:.0f}s recovery / {recent['window_seconds']/60:.0f}m",'cyan')]
            if d.get('reason'):rows[0:0]=[tint(d['reason'], 'gold'), '']
            action_start=len(rows)
            for i, mode in enumerate(self.run_modes):
                accent, detail = self.mode_details[mode]
                marker = '› ' if self.selection == i else '  '
                active = '  ● LIVE' if d['running'] and d.get('mode') == mode else ''
                rows.append(tint(marker + MODES[mode], 'selected' if self.selection == i else accent)
                            + tint('  /  ' + detail + active, accent if self.selection == i else 'dim'))
            rows += [tint('› ' + label, 'selected') if self.selection == i else '  ' + label
                     for i, label in enumerate(('Pause', 'Stop', 'Export log'), start=len(self.run_modes))]
            # Keep the chosen mode/control visible in a short terminal.
            start=max(0,action_start+self.selection-available+1)
            rows=rows[start:]
            rows += ['', tint('Recent', 'dim')]
            rows += [tint(time.strftime('%H:%M:%S', time.localtime(r['at']))+'  ', 'dim')+tint(r['text'],event_tone(r)) for r in self.feed.rows[-max(0, available-len(rows)):]] if available > len(rows) else []
            return rows
        if self.page == 1:
            rows = self.item_rows()
            visible = max(1, available-2)
            self.scroll = min(self.scroll, self.selection)
            if self.selection >= self.scroll + visible: self.scroll = self.selection-visible+1
            result = [tint(f'{len(rows)} items  '+(f' / {self.query}' if self.query else ''), 'dim'), '']
            result += [tint(f"{'›' if i == self.selection else ' '}  {name:<30} ×{qty:,}", 'selected' if i==self.selection else 'text')
                       for i, (name, qty) in enumerate(rows) if self.scroll <= i < self.scroll+visible]
            return result or ['No matching items']
        if self.page == 2:
            rows = self.feed.filtered(self.query, self.categories[self.category])
            visible = max(1, available-2)
            self.scroll = max(0, len(rows)-visible) if self.follow else min(self.scroll, max(0, len(rows)-visible))
            result = [tint(self.categories[self.category] + ('   ● Following' if self.follow else '   History') + (f'   / {self.query}' if self.query else ''), 'gold'), '']
            result += [tint(time.strftime('%H:%M:%S', time.localtime(r['at']))+'  ', 'dim')+
                       tint(r['text'],event_tone(r))
                       for r in rows[self.scroll:self.scroll+visible]]
            return result
        settings = [('Username', self.config['account_username'] or 'Not set'), ('Rod slot', self.config['rod_slot']),
                    ('Auto equip rod', 'On' if self.config['auto_rod'] else 'Off'), ('Motion', 'Reduced' if self.config['reduced_motion'] else 'On'),
                    ('Bait left', d['bait_remaining_estimate'] if d['bait_remaining_estimate'] is not None else 'Unknown'), ('Plan hours', f'{self.hours:g}'),
                    ('Mode',MODES[self.config['mode']]),
                    ('Cast point', f"{self.config['cast_point'][0]}, {self.config['cast_point'][1]}  ·  Full farmer"),
                    ('Capture pointer', 'Reads Roblox pointer in 4 seconds'),
                    ('Position correction','On' if self.reference_position else 'Off'),
                    ('Save fishing reference','Enter while paused'),('Disable reference','Enter while paused')]
        return [tint(f"{'›' if i == self.selection else ' '}  {label:<23} {value}", 'selected' if i==self.selection else 'text') for i,(label,value) in enumerate(settings)]

    def render(self, width, height):
        self.height = height
        d = self.data
        if width < 65 or height < 22:
            return ['Fishing  /  '+d.get('state', ''), '', 'Enlarge the terminal to at least 65 columns × 22 rows.', '', 'Q close   C continue   P pause   S stop']
        active = d['running'] and not d['stop_requested'] and not d.get('manual_paused') and d['state'] != 'Waiting for Roblox'
        spin = '●' if self.config['reduced_motion'] or not active else '◐◓◑◒'[int(time.monotonic()*5)%4]
        state = tint(spin+' '+d['state'],state_tone(d['state'],active))
        mode = '  /  '+MODES.get(d.get('mode'),'Full farmer')
        lines = ['', '  '+tint('FISHING'+mode, 'gold')+'     '+state+'     '+tint(d['presence'], 'dim'), '',
                 '  '+'     '.join(tint(f'{i+1} {name}', 'gold' if i==self.page else 'dim') for i,name in enumerate(self.pages)), '',
                 '  '+tint('─'*min(width-4, 110), 'dim'), '']
        effect_rows = self.effects.rows(width-4, time.monotonic(), self.config['reduced_motion'])
        if effect_rows:
            lines[4:7] = ['  '+''.join(tint(text, tone) for text, tone in row) for row in effect_rows]
        available = height-12
        offset = 0 if self.config['reduced_motion'] else round(3*max(0, 1-(time.monotonic()-self.changed_at)/.18))
        lines += ['  '+' '*offset+line for line in self.body(available)[:available]]
        lines += [''] * max(0, height-5-len(lines))
        if self.editing:
            lines.append('  '+tint(self.editing+' › ', 'gold')+self.buffer+'▏')
            help_text = 'Enter save   Ctrl+G cancel'
        else:
            lines.append('  '+(self.notice if time.monotonic()<self.notice_until else tint('Working…', 'gold') if self.busy else ''))
            help_text = '← → tabs   ↑ ↓ select   Enter open' if self.page in (0,3) else '↑ ↓ scroll   / search   Enter inspect' if self.page==1 else '↑ ↓ scroll   / search   F follow   G filter'
        lines += ['  '+tint(help_text, 'dim'), '  '+tint('C continue   P pause   S stop   Q close view', 'dim'), '']
        return [clip(line, width-1) for line in lines[:height-1]]

    def run(self):
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise RuntimeError('Open Fishing CLI in a terminal for the interactive view. Use status --json for scripts.')
        # Restore the original console even if a display refresh fails.
        sys.stdout.write('\033]0;Fishing CLI\007'+ESC+'?1049h'+ESC+'?25l'+ESC+'2J')
        sys.stdout.flush()
        next_update = 0
        try:
            self.transition('opening')
            while self.alive:
                while msvcrt.kbhit():
                    key = msvcrt.getwch()
                    if key in ('\x00', '\xe0'):
                        key = {'H':'UP','P':'DOWN','K':'LEFT','M':'RIGHT','I':'PGUP','Q':'PGDN','G':'HOME','O':'END','\x0f':'BACKTAB'}.get(msvcrt.getwch(), '')
                    else: key = {'\r':'ENTER','\t':'TAB','\b':'BACKSPACE','\x07':'CANCEL'}.get(key,key)
                    if key == '\x03': self.alive = False
                    else: self.key(key)
                now = time.monotonic()
                if now >= next_update: self.refresh(); next_update = now+.7
                size = shutil.get_terminal_size((100,32))
                lines = self.render(size.columns, size.lines)
                output = []
                for i, line in enumerate(lines):
                    if i >= len(self.last_lines) or self.last_lines[i] != line:
                        output.append(f'{ESC}{i+1};1H{ESC}2K'+line)
                for i in range(len(lines),len(self.last_lines)): output.append(f'{ESC}{i+1};1H{ESC}2K')
                if output: sys.stdout.write(''.join(output)); sys.stdout.flush()
                self.last_lines = lines
                time.sleep(.07)
        finally:
            try:
                self.transition('closing')
            finally:
                sys.stdout.write(RESET+ESC+'?25h'+ESC+'?1049l'); sys.stdout.flush()
        return 0

    def transition(self, phase):
        """Animate the rod in the dashboard header, without a loading screen."""
        if self.config['reduced_motion']:
            return
        size = shutil.get_terminal_size((100, 32))
        if size.columns < 65 or size.lines < 22:
            return
        if phase == 'opening':
            self.refresh()
            self.last_lines = self.render(size.columns, size.lines)
            sys.stdout.write(''.join(f'{ESC}{i+1};1H{ESC}2K'+line
                                     for i, line in enumerate(self.last_lines)))
            sys.stdout.flush()
        frames = 12 if phase == 'opening' else 9
        for index in range(frames):
            art = rod_scene_frame(size.columns, index/(frames-1), phase)
            sys.stdout.write(''.join(f'{ESC}{row+1};1H{ESC}2K'+line
                                     for row, line in enumerate(art)))
            sys.stdout.flush()
            time.sleep(.05)
        if phase == 'opening':
            sys.stdout.write(''.join(f'{ESC}{row+1};1H{ESC}2K'+self.last_lines[row]
                                     for row in range(min(3, len(self.last_lines)))))
            sys.stdout.flush()
