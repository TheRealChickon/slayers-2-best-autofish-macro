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
from app_config import data_directory, load_config, resolve_account, save_config, MODES
from cast_point import capture_pointer, validate as validate_cast_point
from cli_effects import CatchEffects
from cli_scene import scene_frame
from item_journal import Journal
from live_feed import LiveFeed, event_tone, state_tone
from metrics import read, write
from status_view import duration, estimate, snapshot
from bait_warning import warning as bait_warning
import damage_build
from damage_view import pace_labels, skill_lines

ESC = '\033['
RESET = ESC + '0m'
TONES = {'text': '223;228;212', 'dim': '126;151;146', 'gold': '220;177;103',
         'green': '159;202;157', 'red': '221;120;103', 'cyan': '106;187;193',
         'ore': '186;145;107', 'selected': '255;223;158'}
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


class Terminal:
    pages = ('Run', 'Items', 'Live log', 'Setup', 'Build')
    categories = ('All', 'Catches', 'Recovery', 'Warnings')
    run_modes = ('assist', 'spot', 'full', 'damage', 'boss')
    mode_details = {
        'assist': ('green', 'you cast / auto reel'),
        'spot': ('cyan', 'cast / reel / collect'),
        'full': ('gold', 'spawn / rejoin'),
        'damage': ('ore', '5 M1 / two moves / ready ultimate'),
        'boss': ('ore', 'Sanemi observation / no attacks'),
    }
    settings_keys = ('Username', 'Mode', 'Rod slot', 'Auto rod', 'Camera', 'Heading',
                     'Fishing titles', 'Cast point', 'Capture pointer',
                     'Position correction', 'Save reference', 'Disable reference', 'Motion')
    setting_help = {
        'Username':'Roblox account for presence and reconnect checks.',
        'Mode':'Full rejoins; Fish here stays put; Minigame only reels; Damage hits the statue.',
        'Rod slot':'Hotbar number of your fishing rod (1–9).',
        'Auto rod':'Full farmer checks the hotbar and equips an unselected rod.',
        'Camera':'Keep your view, or zoom fully in. At rails, the avatar may block first person.',
        'Heading':'Compass direction to restore after rejoining. Off disables it.',
        'Fishing titles':'Auto best checks completed Fishing titles once at startup; unreadable sets stay put.',
        'Cast point':'Full farmer water target in 2560×1440 reference coordinates.',
        'Capture pointer':'In four seconds, save the current mouse position as cast point.',
        'Position correction':'Use a saved scene reference to fix small spawn drift.',
        'Save reference':'Capture your current fishing scene while the farmer is paused.',
        'Disable reference':'Turn off camera and position correction.',
        'Motion':'Reduce terminal effects and animations.'}

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
        self.build_report = {}
        self.build_at = 0
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
        if self.page == 4 and time.monotonic() - self.build_at >= 5:
            self.build_report = damage_build.report()
            self.build_at = time.monotonic()
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
        if self.page == 4:
            self.build_report = damage_build.report()
            self.build_at = time.monotonic()

    def edit(self, key, value=''):
        self.editing, self.buffer = key, str(value)

    def finish_edit(self):
        key, value = self.editing, self.buffer.strip()
        self.editing, self.buffer = None, ''
        try:
            if key == 'Search': self.query = value; self.selection = self.scroll = 0
            elif key == 'Username':
                def account():
                    save_config(resolve_account(value)); return 'Account saved'
                self.job(account)
            elif key == 'Rod slot': save_config({'rod_slot': int(value)})
            elif key == 'Heading':
                save_config({'camera_heading':None if value.lower() in ('off','none','') else float(value)})
                self.toast('Saved fishing heading')
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
            elif key == 'Discord webhook':
                from discord_hourly import configure_secret
                configure_secret(data_directory(), value)
                self.toast('Discord webhook saved')
            elif key == 'Gauntlet mastery':
                damage_build.save_mastery(value)
                self.build_report = damage_build.report()
                self.toast('Gauntlet mastery saved')
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
            if key == 'Test webhook':
                from discord_hourly import load_secret, request_webhook
                def verify():
                    code,_=request_webhook(load_secret(data_directory()))
                    return f'Discord reachable (HTTP {code}); no post sent'
                self.job(verify)
                return
            if key == 'Remove webhook':
                from discord_hourly import SECRET_FILE
                (data_directory()/SECRET_FILE).unlink(missing_ok=True)
                self.toast('Discord webhook removed')
                return
            if key == 'Discord webhook':
                self.edit(key)
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
            if key in ('Auto rod', 'Motion', 'Fishing titles'):
                option = {'Auto rod':'auto_rod','Motion':'reduced_motion','Fishing titles':'auto_fishing_titles'}[key]
                save_config({option: not self.config[option]}); self.config = load_config()
            elif key=='Camera':
                save_config({'camera_mode':'first_person' if self.config['camera_mode']=='keep' else 'keep'})
                self.config=load_config()
            else:
                value = {'Username': self.config['account_username'], 'Rod slot': self.config['rod_slot'],
                         'Heading':self.config['camera_heading'] if self.config['camera_heading'] is not None else 'Off',
                         'Bait left': self.data.get('bait_remaining_estimate') or 0,
                         'Plan hours': self.hours,
                         'Cast point': ', '.join(map(str, self.config['cast_point']))}[key]
                self.edit(key, value)

    def key(self, key):
        if self.editing:
            self.effects.secret = ''
            if key == 'ENTER': self.finish_edit()
            elif key == 'CANCEL': self.editing, self.buffer = None, ''
            elif key == 'BACKSPACE': self.buffer = self.buffer[:-1]
            elif len(key) == 1 and key.isprintable(): self.buffer += key
            return
        self.effects.key(key, time.monotonic())
        if key.lower() == 'q': self.alive = False
        elif key in ('RIGHT', 'TAB'): self.switch(self.page+1)
        elif key in ('LEFT', 'BACKTAB'): self.switch(self.page-1)
        elif key in ('1', '2', '3', '4', '5'): self.switch(int(key)-1)
        elif key == 'ENTER': self.activate()
        elif key == '/' and self.page in (1, 2): self.edit('Search', self.query)
        elif key.lower() == 'c': self.job(actions.resume)
        elif key.lower() == 'p': self.job(actions.pause)
        elif key.lower() == 's':
            # Stop must remain available even while another command is pending.
            try: self.toast(actions.stop())
            except Exception as error: self.toast(error, False)
        elif self.page == 4 and key.lower() == 'm':
            self.edit('Gauntlet mastery', self.build_report.get('mastery') or '')
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
            elif self.page == 4:
                count = len(damage_build.text_lines(self.build_report))
                limit = max(0, count-max(1, self.height-12))
                self.scroll = 0 if key == 'HOME' else limit if key == 'END' else max(0, min(limit, self.scroll+step))
            else:
                count = len(self.run_modes)+3 if self.page == 0 else len(self.settings_keys) if self.page == 3 else len(self.item_rows())
                self.selection = 0 if key == 'HOME' else max(0, count-1) if key == 'END' else max(0, min(count-1, self.selection+step))

    def body(self, available):
        d = self.data
        if self.page == 0:
            if d.get('mode') == 'boss':
                from boss_view import boss_lines
                rows = [tint(d['state'], 'gold'), *boss_lines(d.get('boss') or {}), '']
                action_start = len(rows)
                rows += [tint('› ' if self.selection == i else '  ', 'selected')+
                         tint(MODES[mode]+'  /  '+self.mode_details[mode][1], 'gold' if self.selection==i else 'dim')
                         for i,mode in enumerate(self.run_modes)]
                rows += [tint('› ' if self.selection == i else '  ', 'selected')+label
                         for i,label in enumerate(('Pause','Stop','Export log'),start=len(self.run_modes))]
                return rows[max(0,action_start+self.selection-available+1):][:available]
            if d.get('mode') == 'damage':
                damage = d.get('damage', {})
                pace, finish, sample = pace_labels(damage)
                rows = [tint('STATUE', 'dim')+'  '+tint(d['state'], 'gold'),
                        tint('COMBO', 'dim')+f"  {damage.get('combo') or '—'}    "+
                        tint('HITS', 'dim')+f"  {damage.get('observed_hits', 0):,}",
                        tint('M1', 'dim')+f"  {damage.get('m1_clicks', 0):,}    "+
                        tint('C / Z / B', 'dim')+'  '+ ' / '.join(str((damage.get('move_uses') or {}).get(role, 0)) for role in ('shock_wave', 'followup', 'ultimate')),
                        tint('TITLE', 'dim')+f"  {damage.get('title_progress', 0):,} / {damage.get('title_target', 0):,}    "+
                        tint('RESETS', 'dim')+f"  {damage.get('resets', 0)}",
                        tint('DPH', 'dim')+'  '+pace,
                        tint('LEFT', 'dim')+f"  {damage.get('remaining_damage', 0):,} damage    "+tint('CHECKED', 'dim')+'  '+sample,
                        tint('FINISH', 'dim')+'  '+finish,
                        *skill_lines(damage)[1:5], '']
                rows += [tint('› ' if self.selection == i else '  ', 'selected')+
                         tint(MODES[mode]+'  /  '+self.mode_details[mode][1], 'gold' if self.selection==i else 'dim')
                         for i,mode in enumerate(self.run_modes)]
                rows += [tint('› ' if self.selection == i else '  ', 'selected')+label
                         for i,label in enumerate(('Pause','Stop','Export log'),start=len(self.run_modes))]
                return rows[:available]
            amount = estimate(d, self.hours)
            rows = [tint('CATCH', 'dim') + '  ' + tint(f"{d['items']:,}", 'gold') +
                    tint('     HOOK', 'dim') + f"  {d['hooks']:,}" +
                    tint('     TIME', 'dim') + f"  {duration(d['active_seconds'])}",
                    tint('LAST ', 'dim') + '  ' + (d['last_item'] or '—')]
            recent=d.get('recent')
            if recent:
                rows.append(tint('PACE ', 'dim') + '  ' +
                            tint(f"{recent['hooks_per_minute']:.2f} hooks/min   ·   {recent['items_per_minute']:.2f} items/min",'cyan'))
            bait=(f"~{d['bait_remaining_estimate']:,} left" if d['bait_remaining_estimate'] is not None else 'unknown')
            rows += [tint(f"BAIT   {bait}   /   {self.hours:g}h needs " + (f'~{amount:,}' if amount is not None else 'a rate sample'),'dim'), '']
            alert=bait_warning(d) if d.get('running') or d.get('starting') else None
            if alert:rows += [tint(alert,'red')]
            if d.get('reason'):rows[0:0]=[tint(d['reason'], 'gold'), '']
            rows += [tint('CHOOSE THE HAND ON THE ROD', 'dim')]
            action_start=len(rows)
            for i, mode in enumerate(self.run_modes):
                accent, detail = self.mode_details[mode]
                marker = '› ' if self.selection == i else '  '
                active = '  ◉' if d['running'] and d.get('mode') == mode else ''
                rows.append(tint(marker + f'{MODES[mode]:<17}', 'selected' if self.selection == i else accent)
                            + tint(detail + active, accent if self.selection == i else 'dim'))
            rows += [tint('› ' + label, 'selected') if self.selection == i else '  ' + label
                     for i, label in enumerate(('Pause', 'Stop', 'Export log'), start=len(self.run_modes))]
            # Keep the chosen mode/control visible in a short terminal.
            start=max(0,action_start+self.selection-available+1)
            rows=rows[start:]
            if available > len(rows)+2:
                rows += ['', tint('RECENT', 'dim')]
                rows += [tint(time.strftime('%H:%M:%S', time.localtime(r['at']))+'  ', 'dim')+tint(r['text'],event_tone(r)) for r in self.feed.rows[-max(0, available-len(rows)):]]
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
        if self.page == 4:
            report = self.build_report or damage_build.report()
            raw = damage_build.text_lines(report)
            rows = []
            for line in raw:
                tone = ('gold' if line.startswith(('DAMAGE', 'BEST KNOWN', 'WEAPON', 'LIVE COMPARISON'))
                        else 'cyan' if line.startswith(('Same gear', 'Measured'))
                        else 'red' if '[NOT IN SNAPSHOT]' in line else 'dim' if line.startswith(('-', 'Mastery estimate', 'A weapon', 'This is'))
                        else 'text')
                rows.append(tint(line, tone))
            self.scroll = min(self.scroll, max(0, len(rows)-available))
            return rows[self.scroll:self.scroll+available]
        settings = [('Username', self.config['account_username'] or 'Not set'),
                    ('Mode',MODES[self.config['mode']]), ('Rod slot', self.config['rod_slot']),
                    ('Auto equip rod', 'On' if self.config['auto_rod'] else 'Off'),
                    ('Camera', 'First person' if self.config['camera_mode']=='first_person' else 'Keep current'),
                    ('Heading', f"{self.config['camera_heading']:g}°" if self.config['camera_heading'] is not None else 'Off'),
                    ('Fishing titles', 'Auto best' if self.config['auto_fishing_titles'] else 'Keep equipped'),
                    ('Cast point', f"{self.config['cast_point'][0]}, {self.config['cast_point'][1]}  ·  Full farmer"),
                    ('Capture pointer', 'Reads Roblox pointer in 4 seconds'),
                    ('Position correction','On' if self.reference_position else 'Off'),
                    ('Save fishing reference','Enter while paused'),('Disable reference','Enter while paused'),
                    ('Motion', 'Reduced' if self.config['reduced_motion'] else 'On')]
        rows=[tint(f"{'›' if i == self.selection else ' '}  {label:<23} {value}", 'selected' if i==self.selection else 'text') for i,(label,value) in enumerate(settings)]
        return rows+['',tint(self.setting_help[self.settings_keys[self.selection]],'dim')]

    def render(self, width, height):
        self.height = height
        d = self.data
        if width < 65 or height < 22:
            return ['Fishing  /  '+d.get('state', ''), '', 'Enlarge the terminal to at least 65 columns × 22 rows.', '', 'Q close   C continue   P pause   S stop']
        active = d['running'] and not d['stop_requested'] and not d.get('manual_paused') and d['state'] != 'Waiting for Roblox'
        spin = '●' if self.config['reduced_motion'] or not active else '◐◓◑◒'[int(time.monotonic()*5)%4]
        state = tint(spin+' '+d['state'],state_tone(d['state'],active))
        mode = '  /  '+MODES.get(d.get('mode'),'Full farmer')
        signal_width = min(width-4, 106)
        marker = signal_width//2 if self.config['reduced_motion'] or not active else int(time.monotonic()*7) % signal_width
        signal = ''.join('◆' if i == marker else '≈' if i % 5 == 0 else '─' for i in range(signal_width))
        tab_names = ('RUN', 'CATCHES', 'RADIO', 'RIG', 'DAMAGE') if width >= 90 else ('RUN', 'CATCH', 'LOG', 'RIG', 'M1')
        tab_gap = '    ' if width >= 90 else '  '
        lines = ['', '  '+tint('AUTOFISH  /  FIELD TERMINAL', 'gold')+'    '+tint(time.strftime('%H:%M'), 'dim'),
                 '  '+state+mode+'    '+tint(d['presence'], 'dim'), '',
                 '  '+tab_gap.join(tint(f'{i+1:02d} {name}', 'gold' if i==self.page else 'dim') for i,name in enumerate(tab_names)),
                 '  '+tint(signal, 'cyan'), '']
        effect_rows = self.effects.rows(width-4, time.monotonic(), self.config['reduced_motion'])
        if effect_rows:
            lines[4:7] = ['  '+''.join(tint(text, tone) for text, tone in row) for row in effect_rows]
        available = height-12
        offset = 0 if self.config['reduced_motion'] else round(3*max(0, 1-(time.monotonic()-self.changed_at)/.18))
        lines += ['  '+' '*offset+line for line in self.body(available)[:available]]
        lines += [''] * max(0, height-5-len(lines))
        if self.editing:
            visible='•'*len(self.buffer) if self.editing=='Discord webhook' else self.buffer
            lines.append('  '+tint(self.editing+' › ', 'gold')+visible+'▏')
            help_text = 'Enter save   Ctrl+G cancel'
        else:
            lines.append('  '+(self.notice if time.monotonic()<self.notice_until else tint('Working…', 'gold') if self.busy else ''))
            help_text = ('← → pages   ↑ ↓ choose   Enter select' if self.page in (0,3)
                         else '↑ ↓ scroll   / search   Enter inspect' if self.page==1
                         else '↑ ↓ scroll   / search   F follow   G filter' if self.page==2
                         else 'M set mastery   ↑ ↓ scroll   1–5 pages')
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
        """Cast or reel across the whole terminal, then restore the dashboard."""
        if self.config['reduced_motion']:
            return
        size = shutil.get_terminal_size((100, 32))
        if size.columns < 65 or size.lines < 22:
            return
        frames = 18 if phase == 'opening' else 14
        for index in range(frames):
            art = scene_frame(size.columns, size.lines, index/(frames-1), phase)
            sys.stdout.write((ESC+'2J' if index == 0 else '') +
                             ''.join(f'{ESC}{row+1};1H'+line
                                     for row, line in enumerate(art)))
            sys.stdout.flush()
            time.sleep(.045)
        if phase == 'opening':
            self.refresh()
            self.last_lines = self.render(size.columns, size.lines)
            sys.stdout.write(ESC+'2J'+''.join(f'{ESC}{row+1};1H'+line
                                             for row, line in enumerate(self.last_lines)))
            sys.stdout.flush()
