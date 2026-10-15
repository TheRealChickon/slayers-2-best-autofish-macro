"""Keyboard terminal client. Closing the client never stops the supervisor."""
import math
import msvcrt
import os
import queue
import re
import shutil
import sys
import threading
import time

import control_actions as actions
from app_config import data_directory, load_config, resolve_account, save_config, MODES, full_farmer_available, set_spawn_gamepass, FULL_NEEDS_GAMEPASS
from cast_point import capture_pointer, validate as validate_cast_point
from cli_effects import CatchEffects
from cli_scene import scene_frame
from item_journal import Journal
from live_feed import LiveFeed, event_tone, state_tone
from metrics import read, write
from status_view import duration, estimate, snapshot
from bait_warning import warning as bait_warning

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


def pad(line, width):
    """Clip or pad to a visible width, ignoring color escapes."""
    visible = len(ANSI.sub('', line))
    return clip(line, width) if visible > width else line + ' '*(width-visible)


def seconds(value):
    return '—' if value is None else f'{value:.1f}s'


class Terminal:
    pages =('Run', 'Items', 'Logs', 'Settings', 'Predictions')
    categories = ('All', 'Catches', 'Recovery', 'Warnings')
    run_modes = ('assist', 'spot', 'full', 'here', 'rejoin')
    other_modes = ('here', 'spot', 'assist', 'rejoin')
    mode_details = {
        'assist': ('green', 'you cast / auto reel'),
        'spot': ('cyan', 'cast / reel / collect'),
        'full': ('gold', 'spawn / rejoin'),
        'here': ('gold','current server / current location'),
        'rejoin': ('green', 'connection guard only'),
    }
    settings_groups=(('Account',('Username','Spawn gamepass')),('Fishing',('Mode','Rod','Rod stats page','Rod slot','Auto rod','Drop-cast','Fishing titles','Title focus')),
                     ('Overnight',('Overnight enabled','Auto focus','Focus grace seconds','Auto-enable after idle','Idle minutes')),
                     ('Location and camera',('Cast point','Capture pointer','Camera','Heading','Position correction','Save reference','Disable reference')),
                     ('Bait restock',('Fish Head reserve','Refill buffer','Run bait restock','Check bait route','Stop bait restock','BaitBot status','Record bait route','Open bait recordings')),
                     ('Buy bait',('Purchase amount','Amount type','After purchase','Buy bait now','Resume bait purchase','Bait purchase status')),
                     ('Discord reports',('Discord webhook','Test webhook','Remove webhook')),('Display',('Motion',)))
    settings_keys=tuple(key for _,keys in settings_groups for key in keys)
    setting_help = {
        'Username':'Roblox account for presence and reconnect checks.',
        'Spawn gamepass':'Own "Set Spawn Anywhere"? Yes: Full farmer rejoins to fix itself. No: Farm here fishes where you stand.',
        'Mode':'Full fishes and rejoins; Rejoin only restores the connection; other modes work as labeled.',
        'Rod':'Rod you have equipped (Legendary, Rare, …). Changing it starts a new stats session for that rod.',
        'Title focus':'Which buff auto titles pick for the current rod: luck or bite speed. Applies at the next farmer start.',
        'Rod stats page':'Open the per-rod comparison: drop %, gold/h selling vs Angler crates.',
        'Rod slot':'Hotbar number of your fishing rod (1–9).',
        'Auto rod':'Full farmer checks the hotbar and equips an unselected rod.',
        'Drop-cast':'Click to drop the catch, recast at once, and hold T to claim it while the line is out.',
        'Camera':'Keep your view, or zoom fully in. At rails, the avatar may block first person.',
        'Heading':'Compass direction to restore after rejoining. Off disables it.',
        'Fishing titles':'Auto best checks completed Fishing titles once at startup; unreadable sets stay put.',
        'Cast point':'Full farmer water target in 2560×1440 reference coordinates.',
        'Capture pointer':'In four seconds, save the current mouse position as cast point.',
        'Position correction':'Use a saved scene reference to fix small spawn drift.',
        'Save reference':'Capture your current fishing scene while the farmer is paused.',
        'Disable reference':'Turn off camera and position correction.',
        'Motion':'Reduce terminal effects and animations.',
        'Record bait route':'Pause Fishing first. F7 records the selected game; F6 saves checkpoints; F10 finishes. No replay.',
        'Open bait recordings':'Open local game video, timed physical inputs and checkpoint images.'}
    setting_help.update({'Fish Head reserve':'Minimum Fish Heads to keep. The separate shrine-route bot defaults to 2,500.',
        'Refill buffer':'Extra Fish Heads per trip. Defaults to 500, rounded up to whole 99-unit batches.',
        'Run bait restock':'The separate bot resets, teleports to Hidden Mist, walks to Nori, buys and verifies the reset return. Requires a complete route.',
        'Check bait route':'Read-only route readiness check. Reports missing calibration without controlling Roblox.',
        'Stop bait restock':'Stop only the separate BaitBot and release its input.',
        'BaitBot status':'Current standalone trip or last stopping point. Automatic refills await a verified full trip.'})
    setting_help.update({'Purchase amount':'Whole number or k suffix. Budget is gold; quantity is Fish Heads. No purchase until Buy bait now.',
        'Amount type':'Choose gold budget or exact bait quantity.',
        'After purchase':'Optionally reset/rejoin and start Full farmer after every debit is verified.',
        'Buy bait now':'Stand at Baitmonger Nori with the shop open. Enter pauses the farmer if needed and buys straight away.',
        'Resume bait purchase':'Reconcile an interrupted transaction, then finish the ORIGINAL remaining amount.',
        'Bait purchase status':'Read the CLI purchase log and actual controller liveness.'})
    setting_help.update({'Overnight enabled':'Persistent intent: physical input yields; Stop or turning this off prevents auto restart.',
        'Auto focus':'Restore only Roblox Player after physical inactivity and the focus grace; other automation gets a grace period.',
        'Focus grace seconds':'Wait 5–300 seconds after focus loss before attempting safe takeover.',
        'Auto-enable after idle':'Optional future activation after real-user inactivity; no clock/time-of-day condition.',
        'Idle minutes':'Conservative physical-user inactivity interval for optional activation (1–120 minutes).',
        'Discord webhook':'Encrypted locally; reports attach this run’s logs.',
        'Test webhook':'Read-only verification of the configured webhook.',
        'Remove webhook':'Remove the local encrypted webhook.'})

    def __init__(self):
        self.journal, self.feed = Journal(), LiveFeed()
        self.catch_journal = Journal()
        self.data, self.config = {}, load_config()
        self.page = self.selection = self.scroll = 0
        self.query = ''
        self.category = 0
        self.follow = True
        self.log_run_id = 'current'
        self.show_total = False
        self.log_run = {}
        self.editing = None
        self.ask_username = False  # first-run step after answering yes to the gamepass
        self.buffer = ''
        self.alive = True
        self.jobs = queue.Queue()
        self.busy = False
        self.notice = ''
        self.notice_until = 0
        self.hours = 8.0
        self.prediction_hours=8.;self.prediction_at=0.;self.predictions={}
        self.stats={};self.stats_at=-60.;self.width=100
        self.height = 30
        self.last_lines = []
        self.changed_at = time.monotonic()
        self.effects = CatchEffects()
        self.build_report = {}
        self.build_at = 0
        import landmark_controls
        self.reference_position=landmark_controls.status()['position_enabled']
        self.show_other_modes=False

    def run_actions(self):
        """Run page controls as (label, detail, accent, action); Full farmer leads."""
        config=getattr(self,'config',None) or {}
        kind=config.get('bait_buy_kind','budget');amount=config.get('bait_buy_amount',169000)
        bait=f"{amount:,} gold" if kind=='budget' else f"{amount:,} Fish Heads"
        running=(getattr(self,'data',None) or {}).get('running')
        expanded=getattr(self,'show_other_modes',False)
        if full_farmer_available(config):
            rows=[('Continue Full farmer' if running else 'Start Full farmer','rejoin · equip rod · fish','gold',lambda:actions.resume('full')),
                  ('Pause','release input, keep counters','text',actions.pause),
                  ('Stop','hold until Continue','text',actions.stop),
                  ('Reset + start Full farmer','rejoin at the saved spawn','text',actions.restart_full)]
            others=self.other_modes;summary='Farm here, Fish here, Minigame, Rejoin'
        else:
            # Without the spawn gamepass a rejoin lands elsewhere: Farm here leads.
            rows=[('Continue Farm here' if running else 'Start Farm here','fish · catch · claim where you stand','gold',lambda:actions.resume('here')),
                  ('Pause','release input, keep counters','text',actions.pause),
                  ('Stop','hold until Continue','text',actions.stop)]
            others=tuple(mode for mode in self.other_modes if mode!='here');summary='Fish here, Minigame, Rejoin'
        rows+=[('Buy bait now',bait+' · pauses the farmer first','text',self.buy_bait_now),
               ('Other modes','▾ hide' if expanded else '▸ '+summary,'dim',None)]
        if expanded:
            rows+=[('   '+MODES[mode],self.mode_details[mode][1],self.mode_details[mode][0],(lambda mode=mode:actions.resume(mode)))
                   for mode in others]
            if not full_farmer_available(config):
                rows.append(('   Full farmer','needs the Set Spawn Anywhere gamepass','dim',lambda:FULL_NEEDS_GAMEPASS))
            rows.append(('   Export log','save the item log as CSV','dim',lambda:'Saved '+str(self.journal.export())))
        return rows

    def buy_bait_now(self):
        """Pause a running farmer, wait for it to release the controller, then start the buyer."""
        from bait_buy import launch
        config=load_config()
        if actions.alive() or actions.starting():
            actions.pause()
            until=time.monotonic()+20
            while actions.alive() or actions.starting():
                if time.monotonic()>until:raise RuntimeError('Farmer is still stopping; Buy bait again in a moment.')
                time.sleep(.2)
        kind=config.get('bait_buy_kind','budget')
        return launch(then_full=config.get('bait_buy_then_full',False),**{kind:config.get('bait_buy_amount',169000)})

    def refresh(self):
        while not self.jobs.empty():
            ok, text = self.jobs.get()
            self.busy = False
            self.toast(text, ok)
        self.data = snapshot(self.journal)
        current_run=self.data.get('log_run') or {}
        self.catch_journal.update(current_run.get('started',self.data['started']),current_run.get('ended'))
        self.config = load_config()
        if self.page==4 and time.monotonic()-self.prediction_at>=5:
            from catch_predictions import load
            self.predictions=load(data_directory(),self.data.get('log_run') or {},self.prediction_hours)
            self.prediction_at=time.monotonic()
        if self.page==0 and time.monotonic()-self.stats_at>=10:
            self.stats_at=time.monotonic()
            try:
                import session_stats
                self.stats=session_stats.compute(data_directory(),self.data.get('log_run') or {})
            except Exception:self.stats={}
        self.effects.observe(self.journal.items, self.data['started'], time.time(), time.monotonic())
        from run_log import select
        log_run=select(data_directory(),self.log_run_id)
        old_rows=self.feed.filtered(self.query,self.categories[self.category])
        anchor=old_rows[min(self.scroll,len(old_rows)-1)].get('id') if old_rows and not self.follow else None
        changed_run=self.log_run.get('id') and self.log_run['id']!=log_run.get('id')
        self.log_run=log_run
        self.feed.update(log_run.get('started',self.data['started']),self.data['state'] if self.log_run_id=='current' else None,log_run.get('ended'))
        if changed_run:
            self.scroll=0;self.follow=True
        elif anchor:
            rows=self.feed.filtered(self.query,self.categories[self.category])
            self.scroll=next((i for i,r in enumerate(rows) if r.get('id')==anchor),0)
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
        journal=self.journal if self.show_total else self.catch_journal
        return [(name, qty) for name, qty in journal.counts.most_common()
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
        self.editing, self.buffer = None, ''
        try:
            if key == 'Search': self.query = value; self.selection = self.scroll = 0
            elif key == 'Username':
                def account():
                    save_config(resolve_account(value)); return 'Account saved'
                self.job(account)
            elif key == 'Rod slot': save_config({'rod_slot': int(value)})
            elif key == 'Rod':
                import rod_stats
                rod_stats.set_rod(value);self.toast('Now tracking catches for the '+value+' rod')
            elif key in ('Fish Head reserve','Refill buffer'):
                save_config({{'Fish Head reserve':'bait_reserve','Refill buffer':'bait_refill_buffer'}[key]:int(value)})
                self.toast(key+' saved')
            elif key=='Purchase amount':
                from bait_buy import amount
                save_config({'bait_buy_amount':amount(value)})
                self.toast('Purchase amount saved; choose Buy bait now to run')
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
            elif key=='Prediction hours':
                value=float(value)
                if not math.isfinite(value) or not .25<=value<=168:raise ValueError('Enter 0.25–168 hours')
                self.prediction_hours=value;self.prediction_at=0
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
            elif key in ('Focus grace seconds','Idle minutes'):
                save_config({{'Focus grace seconds':'overnight_focus_grace_seconds','Idle minutes':'overnight_idle_minutes'}[key]:int(value)})
        except (ValueError, OSError) as error: self.toast(error, False)

    def activate(self):
        if self.page==4:
            self.edit('Prediction hours',self.prediction_hours);return
        if self.page == 0:
            rows=self.run_actions()
            action=rows[min(self.selection,len(rows)-1)][3]
            if action is None:
                self.show_other_modes=not getattr(self,'show_other_modes',False)
                self.selection=min(self.selection,len(self.run_actions())-1)
            else:self.job(action)
        elif self.page == 1:
            rows = self.item_rows()
            if rows:
                name = rows[self.selection][0]
                self.switch(2); self.query = name; self.category = 1; self.follow = True
        elif self.page == 3:
            key = self.settings_keys[self.selection]
            if key in ('Fish Head reserve','Refill buffer'):
                self.edit(key,self.config[{'Fish Head reserve':'bait_reserve','Refill buffer':'bait_refill_buffer'}[key]]);return
            if key in ('Run bait restock','Check bait route','Stop bait restock','BaitBot status'):
                import baitbot_controls
                self.job({'Run bait restock':baitbot_controls.launch,'Check bait route':baitbot_controls.check,
                          'Stop bait restock':lambda:baitbot_controls.invoke('stop'),
                          'BaitBot status':baitbot_controls.status}[key]);return
            if key=='Rod':self.edit(key,self.config.get('active_rod',''));return
            if key=='Title focus':
                rod=str(self.config.get('active_rod') or 'Any');focus=dict(self.config.get('title_priority') or {})
                focus[rod]='bite' if focus.get(rod,'luck')=='luck' else 'luck'
                save_config({'title_priority':focus});self.config=load_config()
                self.toast(f"{rod} rod: auto titles favour {'bite speed' if focus[rod]=='bite' else 'luck'}");return
            if key=='Rod stats page':
                import rod_stats
                def open_page():
                    path=rod_stats.page();rod_stats.ensure_watch();os.startfile(str(path));return 'Opened '+str(path)
                self.job(open_page);return
            if key=='Purchase amount':self.edit(key,self.config.get('bait_buy_amount',169000));return
            if key=='Amount type':
                save_config({'bait_buy_kind':'quantity' if self.config.get('bait_buy_kind','budget')=='budget' else 'budget'});return
            if key=='After purchase':
                save_config({'bait_buy_then_full':not self.config.get('bait_buy_then_full',False)});return
            if key=='Buy bait now':
                self.job(self.buy_bait_now);return
            if key=='Resume bait purchase':
                from bait_buy import launch
                after=self.config.get('bait_buy_then_full',False)
                self.job(lambda:launch('resume',then_full=after));return
            if key=='Bait purchase status':
                saved=read('bait-buy-status.json')
                self.toast(f"{saved.get('stage','Not started')}: {saved.get('bought',0):,} bought / {saved.get('spent',0):,} gold; "
                           +('running' if actions.alive('bait-driver-pid.json') else saved.get('reason','stopped')));return
            if key=='Record bait route':
                from bait_route_recorder import launch
                self.job(launch);return
            if key=='Open bait recordings':
                path=data_directory()/'bait-routes';path.mkdir(parents=True,exist_ok=True)
                os.startfile(str(path));return
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
                modes=[mode for mode in MODES if mode!='full' or full_farmer_available(self.config)]
                current=modes.index(self.config['mode']) if self.config['mode'] in modes else -1
                save_config({'mode':modes[(current+1)%len(modes)]})
                self.config=load_config();return
            if key=='Spawn gamepass':
                if self.data.get('running') or self.data.get('starting'):
                    self.toast('Pause before changing this.',False);return
                self.config=set_spawn_gamepass(self.config.get('spawn_gamepass') is not True)
                self.toast('Full farmer enabled' if self.config['spawn_gamepass'] else 'Farm here is now the main mode');return
            if key in ('Overnight enabled','Auto focus','Auto-enable after idle'):
                option={'Overnight enabled':'overnight_enabled','Auto focus':'overnight_autofocus','Auto-enable after idle':'overnight_auto_enable_idle'}[key]
                changes={option:not self.config[option]}
                if option=='overnight_enabled' and not changes[option]:changes['overnight_auto_enable_idle']=False
                save_config(changes);self.config=load_config()
                if self.config['overnight_enabled'] or self.config['overnight_auto_enable_idle']:
                    from overnight_guard import ensure_guard
                    ensure_guard()
                return
            if key in ('Focus grace seconds','Idle minutes'):
                self.edit(key,self.config[{'Focus grace seconds':'overnight_focus_grace_seconds','Idle minutes':'overnight_idle_minutes'}[key]]);return
            if key in ('Auto rod', 'Motion', 'Fishing titles', 'Drop-cast'):
                option = {'Auto rod':'auto_rod','Motion':'reduced_motion','Fishing titles':'auto_fishing_titles','Drop-cast':'drop_cast'}[key]
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

    def gamepass_question(self):
        """First-run question; the answer decides which farmer is the main mode."""
        return ['',tint('  FIRST-TIME SETUP','gold'),'',
                tint('  Do you own the "Set Spawn Anywhere" gamepass in Project Slayers 2?','text'),'',
                tint('  It lets you set your spawn at your fishing spot. If Roblox disconnects or','dim'),
                tint('  something gets stuck, Autofish can then rejoin and land right back there.','dim'),'',
                tint('  Y  Yes, I own it','gold')+tint('   Full farmer: fishes and fixes itself by rejoining','text'),
                tint('  N  No','gold')+tint('              Farm here: fishes and claims where you stand;','text'),
                tint('                     if Roblox disconnects it stops instead of rejoining elsewhere','dim'),'',
                tint('  You can change this any time in Settings › Spawn gamepass.','dim'),'',
                tint('  Y yes   N no   S stop farming   Q close','dim')]

    def username_question(self):
        """First-run step after a yes: Full farmer needs the account to rejoin."""
        return ['',tint('  FIRST-TIME SETUP','gold'),'',
                tint('  What is your Roblox username?','text'),'',
                tint('  Full farmer uses it to check you are in the game and to rejoin after a','dim'),
                tint('  disconnect. Use your username, not your display name. It is saved only','dim'),
                tint('  on this PC.','dim'),'',
                tint('  › ','gold')+tint(self.buffer+'▏','text'),'',
                tint('  Enter save   Esc skip for now','dim')]

    def key(self, key):
        if self.config.get('spawn_gamepass') is None and not self.editing:
            if key.lower() in ('y','n'):
                self.config=set_spawn_gamepass(key.lower()=='y')
                self.toast('Full farmer is your main mode' if self.config['spawn_gamepass'] else 'Farm here is your main mode')
                if self.config['spawn_gamepass'] and not self.config.get('account_username'):
                    # Full farmer rejoins through this account, so ask for it straight away.
                    self.ask_username=True;self.edit('Username')
            elif key.lower()=='q':self.alive=False
            elif key.lower()=='s':
                try: self.toast(actions.stop())
                except Exception as error: self.toast(error, False)
            return
        if self.editing:
            self.effects.secret = ''
            if key in ('ENTER','CANCEL') and self.ask_username:
                self.ask_username=False
                if key=='CANCEL' or not self.buffer.strip():
                    self.editing, self.buffer = None, ''
                    self.toast('Add your Roblox username later in Settings › Username');return
            if key == 'ENTER': self.finish_edit()
            elif key == 'CANCEL': self.editing, self.buffer = None, ''
            elif key == 'BACKSPACE': self.buffer = self.buffer[:-1]
            elif len(key) == 1 and key.isprintable(): self.buffer += key
            return
        self.effects.key(key, time.monotonic())
        if key.lower() == 'q': self.alive = False
        elif key in ('RIGHT', 'TAB'): self.switch(self.page+1)
        elif key in ('LEFT', 'BACKTAB'): self.switch(self.page-1)
        elif key in ('1', '2', '3', '4','5'): self.switch(int(key)-1)
        elif key == 'ENTER': self.activate()
        elif key == '/' and self.page in (1, 2): self.edit('Search', self.query)
        elif key.lower() == 'c': self.job(actions.resume)
        elif key.lower() == 'p': self.job(actions.pause)
        elif self.page == 1 and key.lower() == 't':
            self.show_total=not self.show_total
            self.scroll=self.selection=0
            self.refresh()
        elif key.lower() == 's':
            # Stop must remain available even while another command is pending.
            try: self.toast(actions.stop())
            except Exception as error: self.toast(error, False)
        elif self.page == 2 and key.lower() == 'f': self.follow = not self.follow
        elif self.page == 2 and key.lower() == 'g': self.category = (self.category+1) % 4; self.scroll = 0
        elif self.page == 2 and key.lower() == 'r':
            from run_log import list_runs
            current_id=self.data.get('log_run',{}).get('id')
            ids=['current']+[r['id'] for r in list_runs(data_directory()) if r['id']!=current_id]
            self.log_run_id=ids[(ids.index(self.log_run_id)+1)%len(ids)] if self.log_run_id in ids else 'current'
            self.scroll=0;self.follow=True
        elif self.page==4 and key.lower()=='h':self.edit('Prediction hours',self.prediction_hours)
        elif key in ('UP', 'DOWN', 'PGUP', 'PGDN', 'HOME', 'END'):
            step = -1 if key == 'UP' else 1 if key == 'DOWN' else -(self.height-12) if key == 'PGUP' else self.height-12
            if self.page == 4:
                limit=max(0,len(self.prediction_rows())-max(1,self.height-12))
                self.scroll=0 if key=='HOME' else limit if key=='END' else max(0,min(limit,self.scroll+step))
            elif self.page == 2:
                rows = self.feed.filtered(self.query, self.categories[self.category])
                visible=max(1,self.height-14)
                limit = max(0, len(rows)-visible)
                if key in ('PGUP','PGDN'):step=-visible if key=='PGUP' else visible
                if self.follow: self.scroll = limit
                self.follow = key == 'END'
                self.scroll = 0 if key == 'HOME' else limit if key == 'END' else max(0, min(limit, self.scroll+step))
            else:
                count = len(self.run_actions()) if self.page == 0 else len(self.settings_keys) if self.page == 3 else len(self.item_rows())
                self.selection = 0 if key == 'HOME' else max(0, count-1) if key == 'END' else max(0, min(count-1, self.selection+step))

    def run_card(self, d, width):
        """Run stats as titled sections with aligned label/value pairs."""
        s=self.stats or {};t=s.get('timings') or {}
        half=max(24,(width-2)//2)
        pair=lambda label,value,tone='text':pad(tint(f'{label:<13}','dim')+tint(value,tone),half)
        title=lambda text:tint(text,'gold')
        gold=s.get('gold');per_hour=s.get('gold_per_hour')
        sections=[[title('THIS RUN'),
                   '  '+pair('Catches',f"{d['items']:,}",'gold')+pair('Hooks',f"{d['hooks']:,}"),
                   '  '+pair('Fishing time',duration(d['active_seconds']))
                   +pair('Gold','—' if gold is None else f'{gold:,}'+('' if per_hour is None else f'  ~{per_hour:,.0f}/h'),'gold'),
                   '  '+tint(f"{'Last catch':<13}",'dim')+(d['last_item'] or '—')]]
        recent=d.get('recent')
        if recent:
            sections.append([title('PACE')+'   '+tint(f"{recent['hooks_per_minute']:.2f} hooks/min  ·  {recent['items_per_minute']:.2f} items/min",'cyan')])
        if t.get('sample'):
            sections.append([title('ROUND TIMING'),
                             '  '+pair('Cycle',seconds(t['cycle']),'cyan')+pair('Bite',seconds(t['cast_to_bite']),'cyan'),
                             '  '+pair('Hold',seconds(t['end_to_hold']),'cyan')+pair('Collect',seconds(t['hold_to_reward']),'cyan'),
                             '  '+pair('Recast',seconds(t['reward_to_cast']),'cyan')+pair('Empty recast',seconds(t['empty_to_cast']),'cyan')])
        if s:
            sections[-1].append('  '+tint(f"{s['rounds']:,} hooked  ·  {s['empty']} empty  ·  {s['failed']} failed"
                                         +(f"  ·  {t['second_holds']} re-holds" if t.get('sample') else ''),'dim'))
        amount=estimate(d, self.hours)
        bait=(f"~{d['bait_remaining_estimate']:,} left" if d['bait_remaining_estimate'] is not None else 'unknown')
        rows=[title('BAIT')+'   '+tint(f"{bait}  ·  {self.hours:g}h needs "+(f'~{amount:,}' if amount is not None else 'a rate sample'),'dim')]
        alert=bait_warning(d) if d.get('running') or d.get('starting') else None
        if alert:rows.append(tint(alert,'red'))
        sections.append(rows)
        return sections

    def run_page(self, d, available, width):
        """Full farmer front page: stats with room to breathe, controls, recent logs on the right."""
        wide=width>=100
        # Stats and controls need about 70 columns; the recent log takes the rest.
        left_width=min(80,max(68,width//2)) if wide else width
        sections=self.run_card(d,left_width-2)
        if d.get('reason'):sections.insert(0,[tint(d['reason'],'gold')])
        controls=[tint('CONTROLS','gold')]
        for i,(label,detail,accent,_) in enumerate(self.run_actions()):
            chosen=self.selection==i
            active='  ◉' if d.get('running') and i==0 and d.get('mode')=='full' else ''
            controls.append(tint(('› ' if chosen else '  ')+f'{label:<27}','selected' if chosen else accent)
                            +tint(detail+active,'text' if chosen else 'dim'))
        compact=[line for section in sections for line in section]+['']
        spaced=[line for section in sections for line in section+['']]
        # Sections get a blank line between them whenever the controls still fit.
        stats=spaced if len(spaced)+len(controls)<=available else compact
        rows=stats+controls
        start=max(0,len(stats)+1+self.selection-available+1)
        rows=rows[start:]
        feed=lambda count:[tint(time.strftime('%H:%M:%S', time.localtime(r['at']))+'  ', 'dim')+tint(r['text'],event_tone(r))
                           for r in self.feed.rows[-count:]] if count>0 else []
        if wide:
            right=[tint('RECENT','gold')]+feed(available-1)
            return [pad(rows[i] if i<len(rows) else '',left_width)+tint('│ ','dim')+(right[i] if i<len(right) else '')
                    for i in range(available)]
        if available>len(rows)+2:
            rows+=['',tint('RECENT','gold')]+feed(available-len(rows)-2)
        return rows[:available]

    def run_summary(self, d):
        """Run card: what was caught, what it is worth, and where the seconds go."""
        label=lambda text:tint(f'{text:<7}','dim')
        s=self.stats or {}
        gold=s.get('gold');per_hour=s.get('gold_per_hour')
        rows=[label('CATCH')+tint(f"{d['items']:,}",'gold')+tint('   HOOK ','dim')+f"{d['hooks']:,}"
              +tint('   TIME ','dim')+duration(d['active_seconds']),
              label('GOLD')+tint('—' if gold is None else f'{gold:,}','gold')
              +tint('   PER HOUR ','dim')+tint('—' if per_hour is None else f'~{per_hour:,.0f}','gold'),
              label('LAST')+(d['last_item'] or '—')]
        recent=d.get('recent')
        if recent:
            rows.append(label('PACE')+tint(f"{recent['hooks_per_minute']:.2f} hooks/min  ·  {recent['items_per_minute']:.2f} items/min",'cyan'))
        t=s.get('timings') or {}
        if t.get('sample'):
            rows+=[label('SPEED')+tint(f"cycle {seconds(t['cycle'])}  ·  bite {seconds(t['cast_to_bite'])}  ·  hold {seconds(t['end_to_hold'])}",'cyan'),
                   label('')+tint(f"collect {seconds(t['hold_to_reward'])}  ·  recast {seconds(t['reward_to_cast'])}  ·  empty {seconds(t['empty_to_cast'])}",'cyan')]
        if s:
            rows.append(label('ROUNDS')+tint(f"{s['rounds']:,} hooked  ·  {s['empty']} empty  ·  {s['failed']} failed"
                                            +(f"  ·  {t['second_holds']} re-holds" if t.get('sample') else ''),'dim'))
        amount=estimate(d, self.hours)
        bait=(f"~{d['bait_remaining_estimate']:,} left" if d['bait_remaining_estimate'] is not None else 'unknown')
        rows+=[label('BAIT')+tint(f"{bait}  ·  {self.hours:g}h needs "+(f'~{amount:,}' if amount is not None else 'a rate sample'),'dim'),'']
        alert=bait_warning(d) if d.get('running') or d.get('starting') else None
        if alert:rows+=[tint(alert,'red')]
        return rows

    def prediction_rows(self):
        p=self.predictions
        if not p:return ['Reading current-run catch logs…']
        rate='unknown' if p['items_per_hour'] is None else f"{p['items_per_hour']:.1f} items/active hour"
        rows=[tint(f"Run {p['run_id']}  ·  Forecast {p['hours']:g}h  ·  H/Enter duration",'gold'),
              f"Worker-active {duration(p['active_seconds'])}   ·   Elapsed {duration(p['elapsed_seconds'])}",
              f"{p['unique_catches']} unique catches / {p['quantity']} units   ·   Observed {rate}"]
        rows.extend(tint(w,'gold') for w in p['warnings'])
        value='Unknown' if p['known_price_subtotal_wen'] is None else f"{p['known_price_subtotal_wen']:,} gold"
        hourly=p.get('known_price_per_hour_wen')
        projected_value='Unavailable' if p['projected_known_price_subtotal_wen'] is None else f"~{p['projected_known_price_subtotal_wen']:,.0f} gold"
        rows+=['',tint('GOLD','dim')+'  '+tint(value,'gold')+tint('   PER HOUR','dim')+'  '+tint('—' if hourly is None else f'~{hourly:,.0f}','gold')
               +tint(f"   IN {p['hours']:g}H",'dim')+'  '+tint(projected_value,'gold')]
        rows+=['',tint('FISH                     CATCHES / UNITS    /HOUR    PROJECTED   GOLD/EACH     GOLD','dim')]
        for item in p['items']:
            rate='—' if item['items_per_hour'] is None else f"{item['items_per_hour']:.1f}"
            projected='insufficient' if item['projected_quantity'] is None else f"~{item['projected_quantity']:.1f}"
            price='—' if item['unit_price_wen'] is None else str(item['unit_price_wen'])+('*' if item.get('price_inferred') else '')
            earned='—' if item['estimated_npc_value_wen'] is None else f"{item['estimated_npc_value_wen']:,}"
            rows.append(tint(f"{item['name'][:24]:<24} {item['catches']:>6} / {item['quantity']:<5} {rate:>8} {projected:>12} {price:>11} {earned:>8}",
                             'text' if item['unit_price_wen'] is not None else 'dim'))
        sold='No confirmed sales logged' if p['actual_sold_proceeds_wen'] is None else f"{p['actual_sold_proceeds_wen']:,} gold"
        rows+=['',f"Unpriced units (materials, ores): {p['unknown_price_quantity']}  ·  Actual sold proceeds: {sold}",
               tint('Gold = Ginzo NPC sell price × units; fish only. Common 33, Uncommon 66, Legendary 165. * priced by rarity.','dim'),
               tint('Projections assume the observed worker-active pace continues.','dim')]
        return rows

    def body(self, available):
        d = self.data
        if self.page==4:
            rows=self.prediction_rows();self.scroll=min(self.scroll,max(0,len(rows)-available))
            return rows[self.scroll:self.scroll+available]
        if self.page == 0:
            if d.get('mode') == 'rejoin':
                guard = d.get('rejoin') or {}
                rows = [tint('CONNECTION', 'dim')+'  '+tint(d['state'], 'gold'),
                        tint('ACCOUNT', 'dim')+f"  {guard.get('account') or 'Not configured'}",
                        tint('PRESENCE', 'dim')+f"  {d['presence']}",
                        tint('LAST', 'dim')+f"  {guard.get('detail') or 'Waiting to start'}",
                        tint('REJOINS', 'dim')+f"  {guard.get('rejoins', 0):,}"+
                        tint('  ATTEMPTS', 'dim')+f"  {guard.get('attempts', 0):,}"+
                        tint('  LAUNCHES', 'dim')+f"  {guard.get('launches', 0):,}"]
                if guard.get('retry_seconds'):
                    rows.append(tint('RETRY', 'dim')+f"  {guard['retry_seconds']}s")
                rows += [tint('NO CASTS · NO ATTACKS · NO GEAR CHANGES', 'dim'), '']
                action_start = len(rows)
                rows += [tint('› ' if self.selection == i else '  ', 'selected')+
                         tint(label+'  /  '+detail, 'gold' if self.selection==i else 'dim')
                         for i,(label,detail,_,_) in enumerate(self.run_actions())]
                return rows[max(0,action_start+self.selection-available+1):][:available]
            return self.run_page(d,available,getattr(self,'width',100)-4)
        if self.page == 1:
            rows = self.item_rows()
            visible = max(1, available-2)
            self.scroll = min(self.scroll, self.selection)
            if self.selection >= self.scroll + visible: self.scroll = self.selection-visible+1
            result = [tint(('TOTAL' if self.show_total else 'SESSION')+f'  ·  {len(rows)} items  ·  T switch'+(f' / {self.query}' if self.query else ''), 'dim'), '']
            result += [tint(f"{'›' if i == self.selection else ' '}  {name:<30} ×{qty:,}", 'selected' if i==self.selection else 'text')
                       for i, (name, qty) in enumerate(rows) if self.scroll <= i < self.scroll+visible]
            return result or ['No matching items']
        if self.page == 2:
            rows = self.feed.filtered(self.query, self.categories[self.category])
            visible = max(1, available-2)
            self.scroll = max(0, len(rows)-visible) if self.follow else min(self.scroll, max(0, len(rows)-visible))
            run_id=self.data.get('log_run',{}).get('id','current') if self.log_run_id=='current' else self.log_run_id
            count=len(rows);last=min(count,self.scroll+visible);newer=count-last
            position=f'Rows {self.scroll+1 if count else 0}–{last} of {count}'
            position+=f'  ·  {newer} newer  ·  End latest' if newer else '  ·  Latest'
            if getattr(self,'log_run',{}).get('ended') is not None:position='Finished  ·  '+position
            result = [tint(f'Run {run_id}   R previous runs   '+self.categories[self.category] + ('   ● Following' if self.follow else '   History') + (f'   / {self.query}' if self.query else ''), 'gold'),tint(position,'dim')]
            result += [tint(time.strftime('%H:%M:%S', time.localtime(r['at']))+'  ', 'dim')+
                       tint(r['text'],event_tone(r))
                       for r in rows[self.scroll:self.scroll+visible]]
            return result
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
        values={key:value for key,(_,value) in zip(('Username','Mode','Rod slot','Auto rod','Camera','Heading','Fishing titles','Cast point','Capture pointer','Position correction','Save reference','Disable reference','Motion'),settings)}
        values.update({'Rod':self.config.get('active_rod') or 'Not set','Rod stats page':'Enter to open',
            'Spawn gamepass':{True:'Owned · Full farmer',False:'Not owned · Farm here',None:'Not answered'}[self.config.get('spawn_gamepass')],
            'Title focus':('Bite speed' if (self.config.get('title_priority') or {}).get(str(self.config.get('active_rod') or 'Any'),'luck')=='bite' else 'Luck')+f" · {self.config.get('active_rod') or 'any'} rod",
            'Drop-cast':'On · drop, recast, claim' if self.config.get('drop_cast') else 'Off · claim, then recast',
            'Overnight enabled':'On' if self.config['overnight_enabled'] else 'Off',
            'Fish Head reserve':f"{self.config['bait_reserve']:,}",'Refill buffer':f"{self.config['bait_refill_buffer']:,}",
            'Run bait restock':'Reset / shrine / Nori / return','Check bait route':'Enter for readiness',
            'Stop bait restock':'Enter to release bot input',
            'BaitBot status':__import__('baitbot_controls').summary(),
            'Purchase amount':f"{self.config.get('bait_buy_amount',169000):,}",
            'Amount type':'Gold budget' if self.config.get('bait_buy_kind','budget')=='budget' else 'Fish Head quantity',
            'After purchase':'Reset + start Full farmer' if self.config.get('bait_buy_then_full',False) else 'Stay at seller',
            'Buy bait now':'Enter to buy','Resume bait purchase':'Finish interrupted amount',
            'Bait purchase status':read('bait-buy-status.json').get('stage','Not started'),
            'Record bait route':'Enter while paused','Open bait recordings':'Video, inputs and checkpoints',
            'Auto focus':'On' if self.config['overnight_autofocus'] else 'Off',
            'Auto-enable after idle':'On' if self.config['overnight_auto_enable_idle'] else 'Off',
            'Focus grace seconds':self.config['overnight_focus_grace_seconds'],
            'Idle minutes':self.config['overnight_idle_minutes'],'Discord webhook':'Configured' if (data_directory()/'discord-webhook.dpapi').exists() else 'Not set',
            'Test webhook':'Enter to verify','Remove webhook':'Enter to remove'})
        rows=[];index=0;selected_line=0
        for group,keys in self.settings_groups:
            rows.append(tint(group.upper(),'gold'))
            for key in keys:
                if index==self.selection:selected_line=len(rows)
                rows.append(tint(f"{'›' if index==self.selection else ' '}  {key:<25} {values[key]}",'selected' if index==self.selection else 'text'))
                index+=1
            rows.append('')
        visible=max(1,available-2)
        self.scroll=min(self.scroll,selected_line)
        if selected_line>=self.scroll+visible:self.scroll=selected_line-visible+1
        return rows[self.scroll:self.scroll+visible]+['',tint(self.setting_help[self.settings_keys[self.selection]],'dim')]

    def render(self, width, height):
        self.height = height;self.width = width
        d = self.data
        if width < 65 or height < 22:
            return ['Fishing  /  '+d.get('state', ''), '', 'Enlarge the terminal to at least 65 columns × 22 rows.', '', 'Q close   C continue   P pause   S stop']
        if self.config.get('spawn_gamepass') is None:
            return self.gamepass_question()
        if self.ask_username:
            return self.username_question()
        active = d['running'] and not d['stop_requested'] and not d.get('manual_paused') and d['state'] != 'Waiting for Roblox'
        spin = '●' if self.config['reduced_motion'] or not active else '◐◓◑◒'[int(time.monotonic()*5)%4]
        state = tint(spin+' '+d['state'],state_tone(d['state'],active))
        mode = '  /  '+MODES.get(d.get('mode'),'Full farmer')
        signal_width = min(width-4, 106)
        marker = signal_width//2 if self.config['reduced_motion'] or not active else int(time.monotonic()*7) % signal_width
        signal = ''.join('◆' if i == marker else '≈' if i % 5 == 0 else '─' for i in range(signal_width))
        tab_names = ('RUN', 'CATCHES', 'LOGS', 'SETTINGS','PREDICTIONS') if width >= 90 else ('RUN', 'CATCH', 'LOGS', 'SETUP','PREDICT')
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
                         else 'H / Enter forecast hours   1–5 pages')
        if self.page == 1:help_text+='   T '+('session' if self.show_total else 'total')
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
