"""Read the visible inventory and reconcile only unambiguous unknown drops."""
import collections
import hashlib
import json
import re
import time
from pathlib import Path
import cv2
import numpy as np
import win32gui
from app_config import load_config
from item_names import item_name, inventory_name
from metrics import RUN, read, write

GRID_X, GRID_Y, STEP = 943, 157, 99.2


def unknown(name):
    return name == 'Unidentified item' or name.endswith('(partial)')


def quantity(text):
    found = re.search(r'\bx\s*(\d+)\b', text, re.I)
    return int(found[1]) if found else 1


def reconcile(before, after, known, pending_quantity):
    """A name is valid only if exactly one unexplained increase matches the drop."""
    positive = {}
    for name in before.keys() | after.keys() | known.keys():
        if 'bait' in name.lower() or name.lower() in ('worm','worms'): continue
        change = after.get(name,0)-before.get(name,0)-known.get(name,0)
        if change < 0: return None  # Incomplete scan, item use, or a changed inventory.
        if change > 0: positive[name] = change
    if len(positive) != 1: return None
    name, amount = next(iter(positive.items()))
    return name if amount == pending_quantity and not unknown(name) else None


class InventoryDriver:
    def __init__(self, hwnd, screen, sct, inp, ocr, user, move):
        self.hwnd,self.screen,self.sct,self.inp,self.ocr,self.user,self.move_pointer = hwnd,screen,sct,inp,ocr,user,move

    def guard(self):
        if any(self.user.GetAsyncKeyState(k)&0x8000 for k in (27,120,123)):
            (RUN/'STOP').write_text('Stopped by physical hotkey')
        if (RUN/'STOP').exists():
            self.inp.release(); raise RuntimeError('Stopped by user during inventory check')
        if not win32gui.IsWindow(self.hwnd) or win32gui.IsIconic(self.hwnd) or win32gui.GetForegroundWindow()!=self.hwnd:
            self.inp.release(); raise RuntimeError('Roblox lost focus; all inputs released')
        l,t,r,b=win32gui.GetClientRect(self.hwnd);x,y=win32gui.ClientToScreen(self.hwnd,(0,0))
        if (x,y,x+r-l,y+b-t)!=self.screen.rect:
            raise RuntimeError('Roblox window changed during inventory check')

    def sleep(self,seconds):
        until=time.monotonic()+seconds
        while time.monotonic()<until:self.guard();time.sleep(.025)

    def capture(self):
        self.guard();return self.screen.capture(self.sct)

    def move(self,x,y):
        self.guard();self.move_pointer(*self.screen.point(x,y))

    def click(self,x,y):
        self.move(x,y);self.sleep(.10);self.move(x+1,y);self.sleep(.06);self.move(x,y);self.sleep(.10);self.inp.hold(True)
        try:self.sleep(.16)
        finally:self.inp.hold(False)
        self.sleep(.2)

    def key(self,key,ctrl=False):
        self.guard();code=ord(key.upper())
        if ctrl:self.user.keybd_event(17,0,0,0)
        self.user.keybd_event(code,self.user.MapVirtualKeyW(code,0),0,0)
        try:self.sleep(.15)
        finally:
            self.user.keybd_event(code,self.user.MapVirtualKeyW(code,0),2,0)
            if ctrl:self.user.keybd_event(17,0,2,0)

    def text(self,frame,min_confidence=.80):
        # Inventory text is always upright. Angle classification can turn x9 into 6x.
        self.guard();rows,_=self.ocr(frame,use_cls=False)
        return [r for r in rows or [] if r[2]>min_confidence]


class InventoryScanner:
    def __init__(self,driver,event=lambda *a,**kw:None,progress=lambda **kw:None):
        self.driver,self.event,self.progress=driver,event,progress
        self.cache_dir=RUN/'inventory-art';self.cache_dir.mkdir(parents=True,exist_ok=True)
        saved=read('inventory-catalog.json')
        self.catalog=saved.get('items',[]) if saved.get('schema')==3 else []
        self.cache=[]
        for entry in self.catalog:
            entry['name']=inventory_name(entry['name'])
            icon=cv2.imread(str(self.cache_dir/entry['file']))
            if icon is not None:self.cache.append((entry,self.descriptor(icon)))

    @staticmethod
    def descriptor(icon):
        # Exclude badges, equipped labels, and the selected tile's outer border.
        return cv2.resize(icon[29:72,8:80],(36,24)).astype(np.float32)

    def cached_name(self,icon):
        descriptor=self.descriptor(icon)
        candidates=[]
        for entry,other in self.cache:
            error=float(np.mean(np.abs(descriptor-other)))
            candidates.append((error,entry['name']))
        candidates.sort()
        if candidates and candidates[0][0]<6 and (len(candidates)<2 or candidates[1][0]-candidates[0][0]>4):
            return candidates[0][1]
        return None

    def learn(self,name,icon):
        file=hashlib.sha1(name.encode()).hexdigest()[:20]+'.png'
        cv2.imwrite(str(self.cache_dir/file),icon)
        entry={'name':name,'file':file}
        self.catalog=[old for old in self.catalog if old['name']!=name]+[entry]
        self.cache=[old for old in self.cache if old[0]['name']!=name]+[(entry,self.descriptor(icon))]
        write('inventory-catalog.json',{'schema':3,'items':self.catalog})

    def inventory_count(self,frame):
        rows=self.driver.text(frame[140:235,660:905])
        text=' '.join(r[1] for r in rows)
        match=re.search(r'All\s*[\(\[]?\s*(\d+)',text,re.I)
        return int(match[1]) if match else None

    def open(self):
        d=self.driver;d.inp.release()
        if self.inventory_count(d.capture()) is None:
            d.key('M');d.sleep(.6)
        # Inventory is the first section in the observed game menu.
        frame=d.capture()
        labels=' '.join(r[1] for r in d.text(frame[340:470,10:340])).lower()
        if 'inventory' not in labels:raise RuntimeError('The inventory menu was not visible; recovery required')
        d.click(155,395);d.click(812,186)
        # Never send movement or drop keys to clear a search. A missed textbox
        # click can let Roblox interpret Ctrl+A as movement underneath the menu.
        d.move(2060,1080);d.sleep(.3)
        frame=d.capture()
        search=''.join(row[1] for row in d.text(frame[80:143,932:1245])).lower()
        if 'itemnamehere' not in re.sub(r'[^a-z]','',search):
            raise ValueError('Clear the inventory search field for automatic item identification')
        return frame

    def read_name(self,x,y):
        d=self.driver;frame=d.capture()
        for attempt in range(4):
            if self.selected(frame,x,y):break
            d.click(x+44,y+44);d.sleep(.35);frame=d.capture()
        if not self.selected(frame,x,y):
            cv2.imwrite(str(RUN/'inventory-selection-unreadable.jpg'),frame)
            return None
        # Verify the target's selected border before trusting the detail panel.
        # A dropped click can otherwise attach the previous item's name to this icon.
        d.sleep(.25);frame=d.capture()
        rows=d.text(cv2.resize(frame[158:287,1940:2540],None,fx=2,fy=2))
        if not rows:
            cv2.imwrite(str(RUN/'inventory-name-unreadable.jpg'),frame)
            return None
        # Rarity and description use smaller type than the item title.
        heights=[max(p[1] for p in row[0])-min(p[1] for p in row[0]) for row in rows]
        largest=max(heights)
        title=[row for row,h in zip(rows,heights) if h>=largest*.65 and min(p[1] for p in row[0])<110]
        # Group words on the same text baseline before sorting left to right.
        lines=[]
        for row in sorted(title,key=lambda r:min(p[1] for p in r[0])):
            top=min(p[1] for p in row[0])
            if not lines or top-lines[-1][0]>30:lines.append((top,[]))
            lines[-1][1].append(row)
        raw=' '.join(row[1] for _,line in lines for row in sorted(line,key=lambda r:min(p[0] for p in r[0]))).strip()
        if not raw or raw.lower() in ('common','uncommon','rare','epic','legendary','mythic'):return None
        canonical=item_name(raw)
        return inventory_name(raw) if unknown(canonical) else canonical

    @staticmethod
    def selected(frame,x,y):
        border=frame[y-4:y+92,x-4:x+92]
        if border.shape!=(96,96,3):return False
        ring=np.ones((96,96),bool);ring[9:-9,9:-9]=False
        return np.count_nonzero(np.all(border>170,axis=2)&ring)>200

    def stack_count(self,icon):
        badge=icon[2:31,35:87]
        bright=np.all(badge>190,axis=2)
        contours=cv2.findContours(bright.astype(np.uint8)*255,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]
        badges=[c for c in contours if cv2.boundingRect(c)[2]>=36 and cv2.boundingRect(c)[3]>=18 and cv2.contourArea(c)>350]
        if not badges:return 1
        readings=[]
        for crop in (badge,icon):
            rows=self.driver.text(cv2.resize(crop,None,fx=3,fy=3),min_confidence=.65)
            text=' '.join(row[1] for row in rows)
            match=re.search(r'[xX×]\s*(\d+)\b',text)
            readings.append(int(match[1]) if match and int(match[1])>0 else None)
        return readings[0] if readings[0] is not None and readings[0]==readings[1] else None

    def scan(self):
        d=self.driver
        try:
            self.progress(done=0,total=0)
            frame=self.open();total=self.inventory_count(frame)
            if total is None or not 1<=total<=100:
                raise ValueError('Inventory is not fully visible; keep the unknown label until a complete comparison is available')
            # A complete first-page snapshot is required. Never infer from an offscreen item.
            result=collections.Counter();read_items=[]
            for index in range(total):
                d.guard();x=round(GRID_X+(index%10)*STEP);y=round(GRID_Y+(index//10)*STEP)
                icon=frame[y:y+88,x:x+88].copy()
                if icon.shape!=(88,88,3):raise ValueError('Inventory grid extends outside the viewport')
                count=self.stack_count(icon)
                if count is None:
                    cv2.imwrite(str(RUN/'inventory-unreadable.jpg'),frame)
                    raise ValueError(f'Inventory quantity unreadable in slot {index+1}')
                name=self.cached_name(icon)
                if not name:
                    name=self.read_name(x,y)
                    if not name:
                        # Unreadable unrelated gear still has a stable visual identity.
                        # It can be compared across snapshots but never used to name a catch.
                        digest=hashlib.sha1(self.descriptor(icon).astype(np.uint8).tobytes()).hexdigest()[:12]
                        name=f'Inventory icon {digest} (partial)'
                    self.learn(name,icon)
                result[name]+=count;read_items.append({'name':name,'quantity':count})
                write('inventory-progress.json',{'at':time.time(),'stage':'scanning','done':index+1,'total':total})
                self.progress(done=index+1,total=total)
            d.move(2060,1080)
            if self.inventory_count(d.capture())!=total:raise ValueError('Inventory changed during the scan')
            write('inventory-catalog.json',{'schema':3,'items':self.catalog})
            write('inventory-progress.json',{'at':time.time(),'stage':'ready','done':total,'total':total})
            cv2.imwrite(str(RUN/'inventory-latest.jpg'),frame)
            write('inventory-slots.json',{'at':time.time(),'items':read_items})
            return dict(result)
        finally:
            frame=d.capture()
            labels=' '.join(r[1] for r in d.text(frame[340:470,10:340])).lower()
            if self.inventory_count(frame) is not None or 'inventory' in labels:
                # Focus and STOP are checked again; never type M into another app.
                d.guard();d.key('M');d.sleep(.5);d.move(1650,800)
                if self.inventory_count(d.capture()) is not None:
                    raise RuntimeError('Inventory menu did not close; recovery required')


class InventoryWatcher:
    def __init__(self,driver,event,progress=lambda **kw:None):
        self.driver,self.event=driver,event
        self.scanner=InventoryScanner(driver,event,progress)
        self.baseline=None;self.known=collections.Counter();self.pending=None
        self.enabled=load_config().get('inventory_check',True)

    def snapshot(self,reason):
        try:
            result=self.scanner.scan()
            self.event('inventory_checked',reason=reason,items=len(result))
            return result
        except ValueError as error:
            self.event('inventory_unreadable',message=str(error))
            write('inventory-progress.json',{'at':time.time(),'stage':'unreadable','message':str(error)})
            return None

    def start(self):
        if not self.enabled:return
        self.baseline=self.snapshot('baseline')
        if self.baseline is not None:write('inventory-baseline.json',{'at':time.time(),'counts':self.baseline})

    def observe(self,raw,prompt,reward_id):
        if not self.enabled:return
        name=item_name(raw,prompt);amount=quantity(raw)
        if unknown(name):self.pending={'reward_id':reward_id,'quantity':amount}
        else:self.known[name]+=amount

    def observe_unconfirmed(self,prompt,reward_id):
        if self.enabled and prompt:
            self.pending={'reward_id':reward_id,'quantity':1,'unconfirmed':True,'raw':prompt}

    def check_pending(self):
        if not self.pending:return
        pending=self.pending;self.pending=None
        after=self.snapshot('unknown drop')
        if after is None:
            # Losing the baseline prevents a later scan from attributing stale gains.
            self.baseline=None;self.known.clear();return
        resolved=reconcile(self.baseline,after,self.known,pending['quantity']) if self.baseline is not None else None
        if resolved:
            self.event('inventory_recovered' if pending.get('unconfirmed') else 'inventory_resolved',
                reward_id=pending['reward_id'],item=resolved,quantity=pending['quantity'],raw=pending.get('raw',''),source='inventory difference')
        else:
            self.event('inventory_ambiguous',reward_id=pending['reward_id'],message='Inventory comparison was inconclusive; original drop retained')
        self.baseline=after;self.known.clear()
        write('inventory-baseline.json',{'at':time.time(),'counts':after})
        if resolved and pending.get('unconfirmed'):return {'item':resolved,'quantity':pending['quantity']}
