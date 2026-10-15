"""Buy a bounded amount of Fish Heads at the current seller; no route replay."""
import argparse
import json
import os
import re
import time
from pathlib import Path

import cv2
import numpy as np
import psutil
from pynput import keyboard
from types import SimpleNamespace

from metrics import RUN, read, write
from recovery import Recovery, UserStop
from fishing_assistant import USER

PRICE = 9
MAX_BATCH = 99


def amount(value):
    text = str(value).lower().replace(',', '').strip()
    if not re.fullmatch(r'[0-9]+k?', text):
        raise argparse.ArgumentTypeError('Use a whole number or a k suffix, such as 200k')
    number = int(text.rstrip('k')) * (1000 if text.endswith('k') else 1)
    if not 1 <= number <= 10000000:
        raise argparse.ArgumentTypeError('Amount must be 1 through 10,000,000')
    return number


def plan(quantity=None, budget=None):
    if (quantity is None) == (budget is None):
        raise ValueError('Choose exactly one of --quantity or --budget')
    requested = quantity if quantity is not None else budget // PRICE
    if type(requested) is not int or not 1 <= requested <= 1000000:
        raise ValueError('Requested amount must buy 1 through 1,000,000 Fish Heads')
    return [min(MAX_BATCH, requested-i) for i in range(0, requested, MAX_BATCH)]


def markers():
    result = []
    for name in ('STOP', 'PAUSE', 'F8_PAUSE'):
        path = RUN/name
        try:
            stat = path.stat(); result.append((name, stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            result.append((name, None, None))
    return result


class Buyer(Recovery):
    def __init__(self):
        import control_actions as actions
        self.lease = {'pid': os.getpid(), 'created': psutil.Process().create_time()}
        with actions.guard():
            actions.refuse_peer_controller()
            if any(actions.alive(name) for name in ('supervisor-pid.json', 'pid.json',
                    'control-start.json', 'calibration-pid.json', 'route-recorder-pid.json',
                    'bait-driver-pid.json')):
                raise UserStop('Pause the other controller before buying bait')
            write('bait-driver-pid.json', self.lease)
        self.initial_markers = markers()
        self.cancelled = False
        self.deadline = time.monotonic()+3600
        try:
            super().__init__()
            self.inp.gate.close()
            self.inp.gate = SimpleNamespace(check=self.check_stop)
            self.inp.physical_stop_owned = True
            self.listener = keyboard.Listener(win32_event_filter=self.hotkey)
            self.listener.start()
        except BaseException:
            self.close(); raise

    def hotkey(self, message, data):
        if not data.flags & 0x10 and message in (0x100, 0x104) and data.vkCode in (27,119,120,123):
            self.cancelled = True
        return False

    def check_stop(self):
        if self.cancelled or markers() != self.initial_markers:
            self.inp.release(); raise UserStop('Bait purchase stopped by Pause/Stop/F8/Escape')
        if time.monotonic()>self.deadline:
            raise UserStop('Bait purchase time limit reached')

    def sleep(self, seconds, focus=True):
        until = time.monotonic()+seconds
        while time.monotonic()<until:
            self.guard() if focus else self.check_stop()
            time.sleep(.015)

    def select(self, focus=False):
        if focus:
            import control_actions as actions
            actions.focus_game()
        super().select(False)

    def tap(self, x, y):
        self.move(x,y); self.sleep(.055)
        self.inp.hold(True)
        try: self.sleep(.06)
        finally: self.inp.hold(False)
        self.sleep(.08)

    def click(self,x,y,hold=.09):
        # Keep the hover movement Roblox needs while avoiding the recovery
        # menu's three longer settling delays for these stable shop controls.
        self.move(x,y); self.sleep(.16)
        self.move(x+1,y); self.sleep(.05)
        self.move(x,y); self.sleep(.08)
        self.inp.hold(True)
        try: self.sleep(hold)
        finally: self.inp.hold(False)
        self.sleep(.08)

    def close(self):
        try:
            if hasattr(self,'inp'):
                self.inp.release()
                if hasattr(self.inp.gate,'close'): self.inp.gate.close()
            if hasattr(self,'listener'):
                self.listener.stop(); self.listener.join(1)
            if hasattr(self,'sct'): self.sct.close()
        finally:
            if read('bait-driver-pid.json') == self.lease:
                (RUN/'bait-driver-pid.json').unlink(missing_ok=True)


def words(d, frame):
    rows=[]
    def line(box,center):
        x,y,w,h=box; tile=frame[y:y+h,x:x+w]
        ys,xs=np.where(np.all(tile>170,axis=2))
        if len(xs)<8: return
        tile=tile[max(0,ys.min()-3):ys.max()+4,max(0,xs.min()-3):xs.max()+4]
        recognized,_=d.ocr(tile,use_det=False,use_cls=False)
        if recognized and len(recognized)==1 and recognized[0][1]>=.90:
            rows.append({'text':recognized[0][0],'center':center,'score':recognized[0][1]})
    line((1070,1118,420,37),(1280,1136))
    if not any('baitmongernori' in re.sub(r'\s+','',r['text']).lower() for r in rows):
        rows.extend(d.text(frame,(1020,1108,560,60)))
    # Observe rounded grey option buttons, then recognize each single line.
    # This avoids repeatedly detecting the entire dialogue and item cards.
    crop=frame[1150:1320,1590:2000]
    diff=crop.max(axis=2).astype(int)-crop.min(axis=2)
    mask=((diff<8)&(crop[:,:,1]>25)&(crop[:,:,1]<180)).astype(np.uint8)*255
    _,_,stats,_=cv2.connectedComponentsWithStats(mask)
    for x,y,w,h,area in stats:
        if 130<w<410 and 24<h<65 and area>2000:
            x=int(x)+1590; y=int(y)+1150; w=int(w); h=int(h)
            line((x,y,w,h),(x+w//2,y+h//2))
    return rows


def find(rows, label):
    clean=lambda value:re.sub(r'\s+','',value).lower()
    matches=[r for r in rows if clean(r['text'])==clean(label)]
    if len(matches)==1: return matches[0]['center']
    return None


def currency(d, frame):
    crop=frame[1025:1085,1530:1710]
    mask=(crop[:,:,1]>160)&(crop[:,:,2]>150)&(crop[:,:,0]<140)
    ys,xs=np.where(mask)
    if not len(xs): raise ValueError('Gold display is missing; purchase withheld')
    crop=crop[max(0,ys.min()-3):ys.max()+4,max(0,xs.min()-3):xs.max()+4]
    readings=[]
    for scale in (2,3):
        # This crop is one known number line. Recognition without detection
        # avoids splitting digits into overlapping boxes and is much faster.
        rows,_=d.ocr(cv2.resize(crop,None,fx=scale,fy=scale),use_det=False,use_cls=False)
        values=[int(re.sub(r'[,\s]','',text)) for text,score in rows or []
                if score>=.90 and re.fullmatch(r'[\d,\s]{1,12}',text)]
        readings.append(values[0] if len(values)==1 else None)
    if readings[0] is None or readings[0]!=readings[1]:
        cv2.imwrite(str(RUN/'bait-buy-gold.png'),frame)
        raise ValueError('Gold is unreadable; purchase withheld')
    return readings[0]


def read_gold(d, frame=None):
    # The gold counter can show a transient value for a few seconds after a
    # debit (2026-10-14: 489,830 for 242,276); keep reading until it settles.
    until=time.monotonic()+15
    while time.monotonic()<until:
        try: return currency(d,frame if frame is not None else d.capture())
        except ValueError:
            frame=None; d.sleep(.12)
    raise ValueError('Gold stayed unreadable; no further purchase was sent')


def wait_rows(d, predicate, timeout=6, advance=False):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        d.move(1510,1350); d.sleep(.04)
        frame=d.capture(); rows=words(d,frame)
        if not any('baitmongernori' in re.sub(r'\W+','',r['text']).lower() for r in rows):
            # A transition may briefly hide the seller heading. Do not click
            # that frame, and retain a diagnostic if it does not return.
            d.sleep(.12)
            continue
        if predicate(rows): return frame,rows
        if advance:
            # The lower dialogue body advances text. It is outside all
            # purchase options and never submits Deal or buys another batch.
            d.tap(1280,1240)
        else: d.sleep(.12)
    cv2.imwrite(str(RUN/'bait-buy-unresolved.png'),d.capture())
    raise ValueError('Seller dialogue did not reach the expected state')


def choose(d, quantity):
    frame,rows=wait_rows(d,lambda r:find(r,'Buy the selection') is not None,advance=True)
    d.click(1030,935,hold=.09)
    d.sleep(.12)
    frame=d.capture(); rows=words(d,frame)
    cv2.imwrite(str(RUN/'bait-buy-selection.png'),frame)
    labels=' '.join(r['text'].lower() for r in d.text(frame,(760,1010,440,85)))
    if 'fishhead' not in re.sub(r'\s+','',labels):
        raise ValueError('Selected bait is not visibly Fish Head')
    # Fish Head selected tile exposes MAX and an editable quantity.
    if quantity==99:
        d.click(1030,935,hold=.09)
    else:
        d.click(1030,901,hold=.09)
        # Quantity editing uses the existing tagged input wrapper.
        USER.keybd_event(17,USER.MapVirtualKeyW(17,0),0,0)
        try: d.key('a',.03)
        finally: USER.keybd_event(17,USER.MapVirtualKeyW(17,0),2,0)
        for char in str(quantity): d.key(char,.025)
        d.key(chr(13),.025)
    d.sleep(.15)
    frame=d.capture(); rows=words(d,frame)
    target=find(rows,'Buy the selection')
    if not target: raise ValueError('Buy option is unreadable')
    d.click(*target,hold=.09)
    frame,rows=wait_rows(d,lambda r:find(r,'Deal') is not None,advance=True)
    text=' '.join(r['text'] for r in d.text(frame,(1000,1205,600,65)))
    if not quote_matches(text,quantity):
        cv2.imwrite(str(RUN/'bait-buy-quote.png'),frame)
        raise ValueError('Seller quote does not match the requested quantity and gold cost: '+text)
    return find(rows,'Deal')


def quote_matches(text,quantity):
    compact=re.sub(r'[,\s]','',text)
    return bool(re.search(rf'(?<!\d){quantity}piece',compact,re.I) and
                re.search(rf'willbe[^0-9]{{0,8}}{quantity*PRICE}(?!\d)',compact,re.I))


def ready_shop(d):
    frame=d.capture(); rows=words(d,frame)
    # A previous attempt can have stopped before submitting its quote.
    # Cancel that quote explicitly; never confirm it on a fresh invocation.
    target=find(rows,'Let me look again')
    if target: d.click(*target,hold=.09)
    return wait_rows(d,lambda r:find(r,'Buy the selection') is not None,advance=True)


def purchase(d, batches, result, save):
    for index,quantity in enumerate(batches):
        target=choose(d,quantity)
        before=result['gold_remaining']
        pending={**result,'stage':'confirming','batch':index+1,'pending':True,
                 'pending_quantity':quantity,'pending_price':quantity*PRICE,'gold_before':before}
        save(pending)
        d.click(*target,hold=.09)
        # Only this one input submits the transaction. Never retry Deal.
        _,rows=wait_rows(d,lambda r:find(r,'Buy more') is not None,advance=True)
        target=find(rows,'Buy more'); d.click(*target,hold=.09)
        frame,_=wait_rows(d,lambda r:find(r,'Buy the selection') is not None,advance=True)
        after=read_gold(d,frame)
        if after!=before-quantity*PRICE:
            raise ValueError('Gold debit is uncertain; no further purchase was sent')
        result.update(bought=result['bought']+quantity,spent=result['spent']+quantity*PRICE,
                      gold_remaining=after,batches_done=index+1,pending=False,stage='buying')
        save(result)
        if index%10==0 or index+1==len(batches):
            print(f"Bought {result['bought']:,}; spent {result['spent']:,}; gold {after:,}",flush=True)
    return result


def buy(quantity=None,budget=None,check=False,resume=False):
    batches=plan(quantity,budget) if not check and not resume else []
    previous=read('bait-buy-status.json')
    if previous.get('pending') and not resume and not check:
        raise ValueError('Previous purchase is unresolved; inspect the inventory before another buy')
    if resume and (not previous.get('quantity') or previous.get('stage')=='complete'):
        raise ValueError('No interrupted purchase to resume')
    d=Buyer()
    result={'stage':'checking','running':True,'started':time.time(),'updated':time.time(),
            'pid':os.getpid(),'created':psutil.Process().create_time(),'item':'Fish Head',
            'bought':0,'spent':0,'pending':False,'budget':budget,'quantity':sum(batches),
            'batches_total':len(batches)}
    def save(value):
        value={**value,'updated':time.time()}; write('bait-buy-status.json',value)
    try:
        d.select(focus=True)
        frame=d.capture(); rows=words(d,frame)
        cv2.imwrite(str(RUN/'bait-buy-start.png'),frame)
        if check:
            result.update(running=False,stage='observed')
            print(json.dumps({'dialogue':rows},indent=2)); return result
        if resume:
            result={**previous,'running':True,'stage':'reconciling',
                    'pid':os.getpid(),'created':psutil.Process().create_time()}
            target=find(rows,'Buy more')
            if target: d.click(*target,hold=.09)
            frame,rows=ready_shop(d)
            after=read_gold(d,frame)
            if result.get('pending'):
                if after!=result['gold_before']-result['pending_price']:
                    raise ValueError('Pending gold debit does not match; purchase remains blocked')
                result.update(bought=result['bought']+result['pending_quantity'],
                    spent=result['spent']+result['pending_price'],gold_remaining=after,pending=False)
            elif after!=result['gold_remaining']:
                raise ValueError('Gold changed since the interrupted purchase')
            if quantity is not None or budget is not None:
                # Explicitly replacing the remaining allowance must happen
                # AFTER reconciliation, so a pending debit is never repeated.
                replacement=sum(plan(quantity,budget))
                result.update(quantity=result['bought']+replacement,
                              budget=result['spent']+budget if budget is not None else None,
                              remaining_budget=budget)
            remaining=result['quantity']-result['bought']
            batches=plan(quantity=remaining) if remaining else []
            result['batches_total']=len(batches)
            save(result)
        else:
            frame,rows=ready_shop(d)
            result['gold_start']=result['gold_remaining']=read_gold(d,frame)
        if sum(batches)*PRICE>result['gold_remaining']:
            raise ValueError('Not enough gold for the requested amount')
        save(result)
        print(f"Buying {sum(batches):,} Fish Heads for {sum(batches)*PRICE:,} gold at the current seller.",flush=True)
        result.pop('reason',None)
        purchase(d,batches,result,save)
        result.update(stage='complete',running=False); save(result)
        return result
    except BaseException as error:
        saved=read('bait-buy-status.json')
        if saved.get('started')==result['started']: result=saved
        result.update(stage='stopped',running=False,reason=str(error)); save(result)
        raise
    finally: d.close()


def add_parser(sub):
    p=sub.add_parser('bait',help='Buy Fish Heads at the current bait seller')
    p.add_argument('operation',choices=('buy','resume','status','check'),nargs='?',default='status')
    choices=p.add_mutually_exclusive_group()
    choices.add_argument('--budget',type=amount,help='Maximum gold to spend, e.g. 200k')
    choices.add_argument('--quantity','--amount',type=amount,help='Number of Fish Heads to buy')
    p.add_argument('--then-full',action='store_true',help='After verified completion, reset/rejoin and start Full farmer')
    p.add_argument('--overnight',action='store_true',help='Enable overnight autofocus and idle activation with --then-full')


def execute(args):
    if args.operation in ('status','check') and (args.quantity is not None or args.budget is not None or args.then_full or args.overnight):
        raise ValueError('Purchase and farmer options require buy or resume')
    if args.overnight and not args.then_full:
        raise ValueError('--overnight requires --then-full')
    if args.operation=='status':
        result=read('bait-buy-status.json')
        if result.get('running'):
            import control_actions as actions
            result={**result,'running':actions.alive('bait-driver-pid.json')}
    else:
        if args.operation=='resume': result=buy(args.quantity,args.budget,resume=True)
        else: result=buy(args.quantity,args.budget,check=args.operation=='check')
    if args.then_full and result.get('stage')=='complete':
        import control_actions as actions
        result={**result,'farmer':actions.restart_full(overnight=args.overnight)}
    print(json.dumps(result,indent=2))
    return 0


def launch(operation='buy',quantity=None,budget=None,then_full=False):
    """Start the same CLI command from the terminal menu, with local logs."""
    import subprocess
    import sys
    from fishing_assistant import ROOT
    if operation=='buy': plan(quantity,budget)
    args=[sys.executable,str(ROOT/'autofish.py'),'bait',operation]
    if budget is not None: args+=['--budget',str(budget)]
    if quantity is not None: args+=['--quantity',str(quantity)]
    if then_full: args+=['--then-full']
    with (RUN/'bait-buy-stdout.log').open('a') as out,(RUN/'bait-buy-stderr.log').open('a') as err:
        subprocess.Popen(args,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
    return 'Bait CLI launched; read Bait purchase status. Pause/Stop/F8 releases input.'
