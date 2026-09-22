"""Game-style inventory and explicit fishing controls."""
import ctypes
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import math
import tkinter as tk
from tkinter import ttk
import psutil
import win32api
import win32gui
from metrics import RUN, write
from fishing_assistant import ROOT, find_window, rectangle
from item_journal import Journal
from status_view import snapshot, duration
import control_actions as actions
from app_config import load_config, save_config, resolve_account
from live_feed import LiveFeed
from ui_motion import SoftButton, tween, mix

BG = '#0b1013'
SIDE = '#181919'
PANEL = '#242727'
LINE = '#434640'
TEXT = '#f3f4f2'
MUTED = '#979d9a'
GOLD = '#e8ba40'
GREEN = '#9cdb70'
RED = '#e29287'
TITLE = 'Fishing'
FONT = 'Segoe UI'
FISH = {'OuwFish', 'OuwFwesh', 'Sea Horse', 'Golden Fish', 'Zebra Fish', 'Clown Fish'}
ART = {'Coral': 'coral', 'Sea Horse': 'sea-horse', 'Silk Thread': 'silk-thread', 'Metal Scraps': 'metal-scraps', 'Ore': 'ore'}


def rounded(canvas, x1, y1, x2, y2, radius=8, **kwargs):
    return canvas.create_polygon(x1+radius,y1,x2-radius,y1,x2,y1,x2,y1+radius,x2,y2-radius,
        x2,y2,x2-radius,y2,x1+radius,y2,x1,y2,x1,y2-radius,x1,y1+radius,x1,y1,
        smooth=True, splinesteps=20, **kwargs)


class Window:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(TITLE)
        self.root.configure(bg=BG)
        self.root.minsize(940, 650)
        self.place_window()
        self.jobs = queue.Queue()
        self.busy = False
        self.journal = Journal()
        self.feed = LiveFeed()
        self.feed_version = -1
        self.reduced_motion = load_config()['reduced_motion']
        self.display_counts = {}
        self.toast_until = 0
        self.page_generation = 0
        self.last_version = -1
        self.messages = []
        self.page = 'Inventory'
        self.category = 'All'
        self.export_pending = False
        self.export_warned = False
        self.data = {}
        self.art = {name: tk.PhotoImage(file=str(ROOT/'assets'/'items'/(file+'.png'))) for name,file in ART.items()}
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('Treeview', background=BG, fieldbackground=BG, foreground=TEXT,
                        rowheight=32, borderwidth=0, font=(FONT,10))
        style.layout('Treeview', [('Treeview.treearea', {'sticky':'nswe'})])
        style.configure('Treeview.Heading', background=PANEL, foreground=MUTED,
                        font=(FONT,10,'bold'), relief='flat')
        style.map('Treeview', background=[('selected','#484330')], foreground=[('selected',TEXT)])
        style.configure('Vertical.TScrollbar', background=LINE, troughcolor=BG,
                        bordercolor=BG, arrowcolor=MUTED)
        self.build_sidebar()
        self.main = tk.Frame(self.root, bg=BG)
        self.main.pack(side='left', fill='both', expand=True, padx=30, pady=24)
        top = tk.Frame(self.main,bg=BG)
        top.pack(fill='x',pady=(0,5))
        self.heading = tk.Label(top,text='Inventory',bg=BG,fg=TEXT,font=(FONT,23,'bold'))
        # Navigation already names the page; no duplicate heading.
        self.pulse = tk.Canvas(top,width=12,height=12,bg=BG,highlightthickness=0)
        self.pulse.pack(side='left',padx=(0,8))
        self.pulse_dot = self.pulse.create_oval(2,2,10,10,fill=MUTED,outline='')
        self.badge = tk.Label(top,text='Stopped',bg=BG,fg=MUTED,font=(FONT,11,'bold'),padx=0,pady=7)
        self.badge.pack(side='left')
        self.subtitle = tk.Label(self.main,text='Collected this run',bg=BG,fg=MUTED,font=(FONT,10),anchor='w')
        self.button(top,'>_ CLI',self.open_cli,MUTED,BG,padx=9,pady=5).pack(side='right')
        self.toolbar = tk.Frame(self.main,bg=BG)
        self.toolbar.pack(fill='x',pady=(12,18))
        self.chips = {}
        for name in ('All','Fish','Materials','Unread'):
            b = self.button(self.toolbar,name,lambda n=name:self.select_category(n),TEXT,PANEL,padx=12,pady=5)
            b.pack(side='left',padx=(0,7))
            self.chips[name] = b
        search_box = tk.Frame(self.toolbar,bg=PANEL)
        search_box.pack(side='right')
        tk.Label(search_box,text='⌕',bg=PANEL,fg=MUTED,font=(FONT,17)).pack(side='left',padx=(8,3))
        self.filter = tk.StringVar()
        self.filter.trace_add('write',lambda *_:self.render_items())
        self.search = tk.Entry(search_box,textvariable=self.filter,width=17,bg=PANEL,fg=TEXT,
                               insertbackground=GOLD,relief='flat',font=(FONT,11))
        self.search.pack(side='left',ipady=6,padx=(0,10))
        self.search.configure(highlightthickness=0)
        self.deck = tk.Frame(self.main,bg=BG)
        self.deck.pack(fill='both',expand=True)
        self.inventory = tk.Frame(self.deck,bg=BG)
        self.grid_canvas = tk.Canvas(self.inventory,bg=BG,highlightthickness=0,height=400)
        grid_scroll = ttk.Scrollbar(self.inventory,orient='vertical',command=self.grid_canvas.yview)
        self.grid_canvas.configure(yscrollcommand=grid_scroll.set)
        grid_scroll.pack(side='right',fill='y')
        self.grid_canvas.pack(fill='both',expand=True)
        self.grid_canvas.bind('<Configure>',lambda e:self.draw_inventory())
        self.grid_canvas.bind('<MouseWheel>',lambda e:self.grid_canvas.yview_scroll(-int(e.delta/120),'units'))
        self.loot_page = tk.Frame(self.deck,bg=BG)
        self.log = self.tree(self.loot_page,[('time','Time',90),('item','Item',190),('quantity','Qty',45),('raw','Original screen text',225)])
        self.log.tag_configure('special',foreground=GOLD)
        self.activity_page = tk.Frame(self.deck,bg=BG)
        self.activity = tk.Text(self.activity_page,bg=BG,fg=MUTED,font=(FONT,10),wrap='word',
                                relief='flat',padx=4,pady=6,state='disabled')
        activity_scroll = ttk.Scrollbar(self.activity_page,command=self.activity.yview)
        self.activity.configure(yscrollcommand=activity_scroll.set)
        activity_scroll.pack(side='right',fill='y')
        self.activity.pack(fill='both',expand=True)
        for tag,col in [('normal',MUTED),('good',GREEN),('warn',GOLD),('error',RED)]:
            self.activity.tag_configure(tag,foreground=col)
        self.note = tk.Label(self.main,bg=BG,fg=MUTED,font=(FONT,9),anchor='w')
        self.settings_page = tk.Frame(self.deck,bg=BG)
        self.build_settings()
        # The bottom strip stays compact and borderless.
        bait_row = tk.Frame(self.main,bg=BG)
        bait_row.pack(fill='x',pady=(14,4))
        self.bait = tk.Label(bait_row,bg=BG,fg=TEXT,font=(FONT,11,'bold'))
        self.bait.pack(side='left')
        self.rate = tk.Label(bait_row,bg=BG,fg=MUTED,font=(FONT,10))
        self.rate.pack(side='right')
        bait_row.pack_configure(pady=(12,14))
        controls = tk.Frame(self.main,bg=BG)
        controls.pack(fill='x')
        self.continue_button = self.button(controls,'Continue',self.resume,'#182611','#91d258',padx=31)
        self.continue_button.pack(side='left',padx=(0,9))
        self.pause_button = self.button(controls,'Pause',self.pause,TEXT,PANEL)
        self.pause_button.pack(side='left',padx=(0,9))
        self.stop_button = self.button(controls,'Stop',self.stop,RED,'#332522')
        self.stop_button.pack(side='left')
        self.button(controls,'Export log',self.open_csv,MUTED,BG,padx=8).pack(side='right')
        self.status = tk.Label(self.main,text='Reading saved run…',bg=BG,fg=MUTED,font=(FONT,9),anchor='w',wraplength=740,justify='left')
        self.status.pack(fill='x',pady=(12,0))
        self.select_page('Inventory')
        for key in ('<F9>','<F12>','<Escape>'):
            self.root.bind(key,lambda event:self.stop())
        self.root.update_idletasks()
        try:
            value=ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(win32gui.GetParent(self.root.winfo_id()),20,ctypes.byref(value),4)
        except Exception:
            pass
        self.root.after(50,self.refresh)
        self.root.after(150,lambda:self.select_page(self.page))
        self.animate_status()

    def build_sidebar(self):
        side=tk.Frame(self.root,bg=SIDE,width=190)
        side.pack(side='left',fill='y')
        side.pack_propagate(False)
        tk.Label(side,text='Fishing',bg=SIDE,fg=TEXT,font=(FONT,19,'bold'),anchor='w').pack(fill='x',padx=25,pady=(31,1))
        tk.Frame(side,bg=SIDE,height=26).pack(fill='x')
        self.nav={}
        for name,label in [('Inventory','◇   Inventory'),('Item log','≡   Item log'),('Recovery','↻   Live log'),('Settings','⚙   Settings')]:
            b=self.button(side,label,lambda n=name:self.select_page(n),MUTED,SIDE,padx=25,pady=12)
            b.configure(anchor='w',font=(FONT,12))
            b.pack(fill='x',pady=2)
            self.nav[name]=b
        self.nav_line=tk.Frame(side,bg=GOLD,width=2,height=28)
        self.nav_line.place(x=0,y=107)
        footer=tk.Frame(side,bg=SIDE)
        footer.pack(side='bottom',fill='x',padx=25,pady=24)
        self.presence=tk.Label(footer,bg=SIDE,fg=MUTED,font=(FONT,9),wraplength=168,justify='left',anchor='w')
        self.presence.pack(fill='x',pady=(0,13))
        tk.Label(footer,text='F9  Stop',bg=SIDE,fg=MUTED,font=(FONT,9),anchor='w').pack(fill='x')
        stats=tk.Frame(side,bg=SIDE)
        stats.pack(side='bottom',fill='x',padx=25,pady=(30,20))

        self.values={}
        for key,label in [('items','Items'),('hooks','Hooks'),('joins','Rejoins'),('launches','Game launches'),('time','Fishing time')]:
            row=tk.Frame(stats,bg=SIDE)
            row.pack(fill='x',pady=4)
            tk.Label(row,text=label,bg=SIDE,fg=MUTED,font=(FONT,10)).pack(side='left')
            var=tk.StringVar(value='—')
            self.values[key]=var
            tk.Label(row,textvariable=var,bg=SIDE,fg=GOLD if key=='items' else TEXT,font=(FONT,11,'bold')).pack(side='right')

    def place_window(self):
        monitors=[win32api.GetMonitorInfo(m[0])['Work'] for m in win32api.EnumDisplayMonitors()]
        try:
            r=rectangle(find_window());cx=(r[0]+r[2])/2;cy=(r[1]+r[3])/2
            other=[m for m in monitors if not(m[0]<=cx<m[2] and m[1]<=cy<m[3])]
        except Exception:
            other=[]
        area=(other or monitors)[0];w=min(1060,area[2]-area[0]-70);h=min(750,area[3]-area[1]-90)
        self.root.geometry(f'{w}x{h}+{area[0]+(area[2]-area[0]-w)//2}+{area[1]+(area[3]-area[1]-h)//2}')

    def button(self,parent,label,callback,fg=TEXT,bg=PANEL,padx=22,pady=9):
        return SoftButton(parent,text=label,command=callback,bg=bg,fg=fg,activebackground=LINE,
                         activeforeground=TEXT,disabledforeground='#727773',font=(FONT,10,'bold'),
                         padx=padx,pady=pady,cursor='hand2',takefocus=True,motion=lambda:not self.reduced_motion)

    @staticmethod
    def tree(parent,columns):
        tree=ttk.Treeview(parent,columns=[x[0] for x in columns],show='headings',height=8)
        for key,label,width in columns:
            tree.heading(key,text=label)
            tree.column(key,width=width,minwidth=40,anchor='e' if key=='quantity' else 'w',stretch=key in ('item','raw'))
        scroll=ttk.Scrollbar(parent,orient='vertical',command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');tree.pack(side='left',fill='both',expand=True)
        return tree

    def select_page(self,page):
        self.page=page
        for name,button in self.nav.items():
            button.configure(fg=GOLD if name==page else MUTED,bg='#383224' if name==page else SIDE)
        for frame in (self.inventory,self.loot_page,self.activity_page,self.settings_page):
            frame.place_forget()
        frame={'Inventory':self.inventory,'Item log':self.loot_page,'Recovery':self.activity_page,'Settings':self.settings_page}[page]
        frame.place(x=0,y=0,relwidth=1,relheight=1)
        self.page_generation+=1;generation=self.page_generation
        tween(frame,lambda t:frame.place_configure(x=round(14*(1-t))) if generation==self.page_generation else None,enabled=not self.reduced_motion)
        self.root.update_idletasks()
        current=self.nav_line.winfo_y();target=self.nav[page].winfo_y()+12
        tween(self.nav_line,lambda t:self.nav_line.place_configure(y=round(current+(target-current)*t)),enabled=not self.reduced_motion)
        self.heading.configure(text=page)
        self.subtitle.configure(text={'Inventory':'Collected this run · Select an item to see its drops',
            'Item log':'Every confirmed collection · Original screen text retained',
            'Recovery':'','Settings':''}[page])
        self.toolbar.pack_forget()
        if page in ('Inventory','Item log'):
            self.toolbar.pack(fill='x',pady=(12,18),before=self.deck)
        self.render_items()

    def select_category(self,name):
        self.category=name
        self.render_items()

    @staticmethod
    def category_for(name):
        return 'Unread' if name=='Unidentified item' or name.endswith('(partial)') else 'Fish' if name in FISH else 'Materials'

    def matches(self,name,raw=''):
        return (self.category=='All' or self.category_for(name)==self.category) and self.filter.get().lower() in (name+' '+raw).lower()

    def draw_inventory(self):
        if not hasattr(self,'grid_canvas'):
            return
        c=self.grid_canvas;c.delete('all')
        width=max(650,c.winfo_width());cols=max(4,width//139)
        tilew=(width-12)/cols;tileh=149
        rows=[(name,qty) for name,qty in self.journal.counts.most_common() if self.matches(name)]
        # Unknown OCR variants remain individual entries in the log, but share a tile.
        if self.category in ('All','Unread') and not self.filter.get():
            unknown=sum(qty for name,qty in rows if self.category_for(name)=='Unread')
            rows=[(name,qty) for name,qty in rows if self.category_for(name)!='Unread']
            if unknown:rows.append(('Unread names',unknown))
        for i,(name,qty) in enumerate(rows):
            x=(i%cols)*tilew;y=(i//cols)*tileh;cx=x+tilew/2;left=cx-49
            rare=name in ('Golden Fish','Clown Fish','Zebra Fish')
            border=GOLD if rare else '#737769' if name!='Unread names' else LINE
            rounded(c,left,y+4,left+98,y+103,7,fill='#282d2d',outline='',width=0)
            if name in self.art:
                c.create_image(cx,y+54,image=self.art[name])
            elif name in FISH:
                self.draw_fish(c,cx,y+59,name)
            else:
                c.create_text(cx,y+59,text='?',fill=MUTED,font=(FONT,30,'bold'))
            # Cover the complete old count badge in the recorded thumbnail.
            rounded(c,left+37,y+12,left+95,y+45,12,fill='#f3f5f1',outline='')
            c.create_text(left+66,y+28,text=f'x{qty}',fill='#24302b',font=(FONT,10,'bold'))
            c.create_text(cx,y+116,text=name,fill=TEXT,font=(FONT,10,'bold'),width=tilew-10,anchor='n')
            hit=c.create_rectangle(x,y,x+tilew-5,y+tileh-3,fill='',outline='')
            # Bind every primitive in the tile so art and labels are clickable.
            tag=f'item_{i}'
            for element in c.find_enclosed(x-1,y-1,x+tilew,y+tileh):c.addtag_withtag(tag,element)
            c.tag_bind(tag,'<Button-1>',lambda e,n=name:self.show_item(n))
            c.tag_bind(tag,'<Enter>',lambda e:c.configure(cursor='hand2'))
            c.tag_bind(tag,'<Leave>',lambda e:c.configure(cursor=''))
        if not rows:c.create_text(width/2,80,text='No matching items',fill=MUTED,font=(FONT,13))
        c.configure(scrollregion=(0,0,width,max(1,(len(rows)+cols-1)//cols)*tileh))

    @staticmethod
    def draw_fish(c,x,y,name):
        colors={'OuwFish':('#ca9550','#f5d795'),'OuwFwesh':('#548d9b','#a5d2d5'),
                'Golden Fish':('#d4a641','#f9e29c'),'Zebra Fish':('#929c9b','#e4e9e5'),
                'Clown Fish':('#d9894a','#ffd7a3')}
        body,light=colors.get(name,('#63968a','#cee2d6'))
        c.create_polygon(x-16,y,x-37,y-17,x-35,y+18,fill=body,outline=light,width=1)
        c.create_polygon(x-4,y-14,x+8,y-27,x+14,y-12,fill=body,outline=light)
        c.create_oval(x-23,y-17,x+32,y+17,fill=body,outline=light,width=2)
        c.create_arc(x-13,y-12,x+16,y+15,start=110,extent=150,style='arc',outline=light,width=2)
        if name in ('Clown Fish','Zebra Fish'):
            for dx in (-9,5):c.create_line(x+dx,y-13,x+dx+4,y+13,fill=light,width=5)
        c.create_oval(x+18,y-7,x+23,y-2,fill='#172025',outline='')

    def show_item(self,name):
        self.category='Unread' if name=='Unread names' else 'All'
        self.filter.set('' if name=='Unread names' else name)
        self.select_page('Item log')

    def render_items(self):
        if not hasattr(self,'log'):
            return
        for name,b in self.chips.items():
            count=sum(q for n,q in self.journal.counts.items() if name=='All' or self.category_for(n)==name)
            b.configure(text=f'{name} ({count})',bg=TEXT if self.category==name else PANEL,fg='#151b1b' if self.category==name else TEXT)
        self.draw_inventory()
        at_bottom=self.log.yview()[1]>.98 if self.log.get_children() else True
        position=self.log.yview()[0] if self.log.get_children() else 0
        self.log.delete(*self.log.get_children())
        for row in self.journal.items:
            if self.matches(row['item'],row['raw']):
                self.log.insert('','end',values=(time.strftime('%H:%M:%S',time.localtime(row['at'])),row['item'],row['quantity'],row['raw']),
                    tags=('special',) if row['item'] in ('Golden Fish','Clown Fish','Zebra Fish') else ())
        self.log.yview_moveto(1 if at_bottom else position)
        self.render_activity()

    def render_activity(self):
        if not hasattr(self,'activity'):return
        bottom=self.activity.yview()[1]>.98 or self.feed_version<0
        position=self.activity.yview()[0]
        self.activity.configure(state='normal');self.activity.delete('1.0','end')
        rows=self.feed.rows[-500:]+[{'at':r['at'],'text':r['message'],'level':r['kind']} for r in self.messages]
        for row in sorted(rows,key=lambda r:r['at']):
            tag=row['level'] if row['level'] in ('good','warn','error') else 'normal'
            self.activity.insert('end',time.strftime('%H:%M:%S',time.localtime(row['at']))+'   '+row['text']+'\n',tag)
        self.activity.configure(state='disabled')
        if bottom:self.activity.see('end')
        else:self.activity.yview_moveto(position)

    def animate_status(self):
        live=self.data.get('running') and self.data.get('state') not in ('Waiting for Roblox','Stopping','Pausing')
        if self.reduced_motion or not live:color=GREEN if live else MUTED
        else:color=mix('#385038',GREEN,(math.sin(time.monotonic()*3)+1)/2)
        self.pulse.itemconfigure(self.pulse_dot,fill=color)
        self.root.after(70,self.animate_status)

    def build_settings(self):
        config=load_config();self.setting_vars={}
        for key,label in [('account_username','Roblox username'),('rod_slot','Rod slot')]:
            row=tk.Frame(self.settings_page,bg=BG);row.pack(fill='x',pady=(10,18))
            tk.Label(row,text=label,bg=BG,fg=MUTED,font=(FONT,10),width=18,anchor='w').pack(side='left')
            var=tk.StringVar(value=str(config[key]));self.setting_vars[key]=var
            tk.Entry(row,textvariable=var,bg=PANEL,fg=TEXT,insertbackground=GOLD,relief='flat',highlightthickness=0,font=(FONT,11),width=25).pack(side='left',ipady=7)
        for key,label in [('auto_rod','Auto equip rod'),('reduced_motion','Reduce motion')]:
            var=tk.BooleanVar(value=config[key]);self.setting_vars[key]=var
            tk.Checkbutton(self.settings_page,text=label,variable=var,bg=BG,fg=TEXT,selectcolor=PANEL,activebackground=BG,activeforeground=TEXT,highlightthickness=0,borderwidth=0,font=(FONT,11)).pack(anchor='w',pady=10)
        self.button(self.settings_page,'Save',self.save_settings,GREEN,PANEL).pack(anchor='w',pady=24)
        self.button(self.settings_page,'Setup guide',lambda:os.startfile(str(ROOT/'README.md')),MUTED,BG,padx=0).pack(anchor='w')

    def save_settings(self):
        values={key:var.get() for key,var in self.setting_vars.items()}
        def save():
            account=resolve_account(values['account_username'])
            save_config(dict(account,rod_slot=int(values['rod_slot']),auto_rod=values['auto_rod'],reduced_motion=values['reduced_motion']))
            return 'Settings saved'
        self.run_action(save)

    def message(self,text,tag='normal'):
        self.messages.append({'at':time.time(),'kind':tag,'message':text})
        self.toast_until=time.monotonic()+7
        self.status.configure(text=text,fg=RED if tag=='error' else MUTED)
        self.render_activity()

    def run_action(self,fn):
        if self.busy:return
        self.busy=True
        def job():
            try:self.jobs.put((True,fn()))
            except Exception as e:self.jobs.put((False,str(e)))
        threading.Thread(target=job,daemon=True).start()

    def pause(self):self.run_action(actions.pause)
    def stop(self):
        # Stop remains available while Continue is being dispatched.
        try:self.message(actions.stop(),'warn')
        except Exception as e:self.message(str(e),'error')
    def resume(self):self.run_action(actions.resume)

    def open_csv(self):
        try:
            source=self.journal.export();dest=ROOT/'Logs'/f'Item-log-view-{time.strftime("%Y%m%d-%H%M%S")}.csv'
            shutil.copyfile(source,dest);os.startfile(str(dest));self.message('Opened a CSV snapshot. Live logging continues.')
        except Exception as e:self.message(str(e),'error')

    def open_cli(self):
        # Use the same installed environment, with a visible console.
        python=os.path.join(os.path.dirname(sys.executable),'python.exe')
        subprocess.Popen([python,str(ROOT/'fishing_cli.py'),'--color','tui'],cwd=str(ROOT),creationflags=subprocess.CREATE_NEW_CONSOLE)

    def refresh(self):
        try:
            while not self.jobs.empty():
                ok,message=self.jobs.get();self.busy=False;self.message(message,'good' if ok else 'error')
            self.data=snapshot(self.journal);d=self.data
            state=d['state'];live=d['running'] or d['starting'];stopping=d['stop_requested']
            self.badge.configure(text=state,fg=GREEN if live and not stopping and state!='Waiting for Roblox' else GOLD if d['paused'] else MUTED)
            if time.monotonic()>self.toast_until:self.status.configure(text='')
            self.reduced_motion=load_config()['reduced_motion']
            self.feed.update(d['started'],state)
            if self.feed.version!=self.feed_version:
                self.render_activity();self.feed_version=self.feed.version
            if self.journal.version!=self.last_version:
                self.render_items();self.last_version=self.journal.version;self.export_pending=True
            if self.export_pending:
                try:self.journal.export();self.export_pending=False;self.export_warned=False
                except OSError:
                    if not self.export_warned:self.message('Close the open CSV to refresh its saved copy. Live logging continues.','warn');self.export_warned=True
            for key,value in {'items':f'{d["items"]:,}','hooks':f'{d["hooks"]:,}','joins':str(d['server_rejoins']),
                              'launches':str(d['game_launches']),'time':duration(d['active_seconds'])}.items():
                self.values[key].set(value)
            remain=d['bait_remaining_estimate'];hours=d['bait_hours_remaining_estimate']
            self.bait.configure(text=f'~{remain:,} bait' if remain is not None else 'Bait —')
            self.rate.configure(text=f'~{d["hooks_per_hour"]:.0f} / hour'+(f'  ·  ~{hours:.1f} hours left' if hours is not None else ''))
            self.presence.configure(text=d['presence'] if d['presence_fresh'] else '')
            self.note.configure(text=f'{d["logged_collections"]:,} collections  ·  {d["unread_items"]} items with partial/unread names')
            self.pause_button.configure(state='normal' if live and not stopping and not self.busy else 'disabled')
            self.continue_button.configure(state='disabled' if self.busy or (live and stopping) else 'normal')
            self.stop_button.configure(state='normal' if live or d['paused'] or self.busy else 'disabled')
        except Exception as e:
            self.badge.configure(text='Retrying display',fg=GOLD)
            self.status.configure(text=str(e))
        self.root.after(700,self.refresh)


def main():
    RUN.mkdir(parents=True,exist_ok=True)
    if actions.alive('controls-pid.json'):
        h=win32gui.FindWindow(None,TITLE)
        if h:win32gui.ShowWindow(h,9);win32gui.SetForegroundWindow(h)
        return
    write('controls-pid.json',{'pid':os.getpid(),'created':psutil.Process().create_time()})
    window=Window();window.root.mainloop()


if __name__=='__main__':main()
