"""Capture the local game's item UI while the fishing controller is paused.

The resulting screenshots stay in the selected local data directory. This
command does not start or stop the fishing controller.
"""
import argparse
import json
import hashlib
import re
import time
from pathlib import Path

import cv2
import mss
import numpy as np
import psutil
import win32gui
from rapidocr_onnxruntime import RapidOCR

from fishing_assistant import Input, USER, find_window, move_pointer, rectangle
from inventory_watch import GRID_X, GRID_Y, STEP, InventoryDriver, InventoryScanner
from metrics import RUN
from screen_space import ScreenSpace

INV_Y, INV_ROW = 175, 104.5


def require_paused(live_dir):
    live_dir=Path(live_dir)
    if not (live_dir/'STOP').exists():
        raise RuntimeError('Pause Full farmer before wiki capture')
    for name in ('supervisor.json','status.json'):
        try:
            status=json.loads((live_dir/name).read_text())
        except (OSError,ValueError):
            continue
        if status.get('running') and psutil.pid_exists(status.get('pid',-1)):
            raise RuntimeError(f'{name} still reports a running controller')


def detail_rows(driver,frame):
    crop=frame[150:1230,1930:2550]
    rows=driver.text(crop,min_confidence=.58)
    ordered=sorted(rows,key=lambda r:(min(p[1] for p in r[0]),min(p[0] for p in r[0])))
    return crop,[{'y':round(min(p[1] for p in r[0])),
                  'x':round(min(p[0] for p in r[0])),
                  'text':r[1], 'confidence':round(float(r[2]),3)} for r in ordered]


def selected_inventory_tile(frame,x,y):
    border=frame[y-4:y+92,x-4:x+92]
    if border.shape!=(96,96,3):return False
    ring=np.ones((96,96),bool);ring[9:-9,9:-9]=False
    # Rarity-colored selected borders can be green or gold; the existing
    # all-white check rejects those even when the correct tile is selected.
    return np.count_nonzero(np.all(border>170,axis=2)&ring)>55


def item_title_and_rarity(rows):
    rare={'common','uncommon','rare','epic','legendary','mythic','mythical','secret','impossible'}
    rarity_at=next((i for i,row in enumerate(rows)
                    if i>0 and row['text'].strip().lower() in rare and row['y']<430),None)
    if rarity_at is None:return None,None
    title=' '.join(row['text'] for row in rows[:rarity_at] if row['confidence']>=.65).strip()
    return title or None,rows[rarity_at]['text']


def group_open(frame):
    # The grouped-copy view replaces the search field with a large white
    # circular back button. This patch is deliberately away from item icons.
    return np.count_nonzero(np.all(frame[90:138,948:1000]>140,axis=2))>700


def write_item(output,stem,icon,frame,driver,source,page,slot,variant=None,quantity=None):
    crop,rows=detail_rows(driver,frame)
    title,rarity=item_title_and_rarity(rows)
    if not title:
        cv2.imwrite(str(output/f'{stem}-unreadable.jpg'),frame,[cv2.IMWRITE_JPEG_QUALITY,92])
        print(json.dumps({'slot':slot,'variant':variant,'error':'name_unreadable'}),flush=True)
        return False
    cv2.imwrite(str(output/f'{stem}-icon.png'),icon)
    cv2.imwrite(str(output/f'{stem}-detail.jpg'),crop,[cv2.IMWRITE_JPEG_QUALITY,94])
    match=re.search(r'\+(\d+)\b',title)
    item={'source':source,'page':page,'slot':slot,'variant':variant,'name':title,
          'rarity':rarity,'refinement':int(match[1]) if match else 0,
          'quantity':quantity,'lines':rows,
          'icon':f'{output.name}/{stem}-icon.png',
          'detail_image':f'{output.name}/{stem}-detail.jpg',
          'captured_at':time.time()}
    (output/f'{stem}.json').write_text(json.dumps(item,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'slot':slot,'variant':variant,'name':title,'quantity':quantity}),flush=True)
    return True


def capture_group(driver,live_dir,output,page,slot,main_baseline):
    baseline=driver.capture()
    for variant in range(10):
        require_paused(live_dir)
        x=round(GRID_X+variant*STEP);y=GRID_Y
        icon=baseline[y:y+90,x:x+90]
        if icon.shape!=(90,90,3) or float(icon.mean())<30:break
        driver.click(x+44,y+44);driver.sleep(.11)
        frame=driver.capture()
        stem=f'{page}-{slot:03d}-v{variant:02d}'
        write_item(output,stem,icon,frame,driver,'inventory',page,slot,variant,1)
    driver.click(973,115);driver.sleep(.6)
    if group_open(driver.capture()):raise RuntimeError(f'Could not exit item group {slot}')
    if page.startswith('bottom'):
        # Leaving a duplicate-item group resets the inventory scroll.
        expected=main_baseline[175:265,943:1033]
        for _ in range(3):
            driver.move(1720,900);driver.guard()
            USER.mouse_event(0x0800,0,0,-20*120,0)
            driver.sleep(.75)
            actual=driver.capture()[175:265,943:1033]
            if np.mean(np.abs(expected.astype(np.int16)-actual.astype(np.int16)))<40:
                break
        else:
            raise RuntimeError(f'Could not restore inventory scroll after group {slot}')


def capture_inventory_page(driver,live_dir,page,start=0,end=90):
    if page not in ('top','bottom','bottom-final','top-accurate','bottom-accurate','bottom-verified'):raise ValueError('page must be an inventory page')
    output=RUN/'inventory-captures';output.mkdir(parents=True,exist_ok=True)
    scanner=InventoryScanner(driver)
    driver.sleep(.8)  # Let inertial grid scrolling settle before indexing slots.
    baseline=driver.capture()
    total=scanner.inventory_count(baseline)
    if total is None:raise RuntimeError('Inventory All count is not visible')
    print(json.dumps({'stage':'inventory_page','page':page,'total':total}),flush=True)
    for slot in range(start,end):
        require_paused(live_dir)
        stem=f'{page}-{slot:03d}'
        if (output/f'{stem}.json').exists() or (output/f'{stem}-v00.json').exists():
            continue
        x=round(GRID_X+(slot%10)*STEP);y=round(INV_Y+(slot//10)*INV_ROW)
        icon=baseline[y:y+90,x:x+90]
        if icon.shape!=(90,90,3):continue
        # A clipped bottom row is left for the scrolled page.
        if float(icon.mean())<15:continue
        driver.click(x+44,y+44)
        driver.sleep(.15)
        frame=driver.capture()
        if group_open(frame):
            capture_group(driver,live_dir,output,page,slot,baseline)
            continue
        if not selected_inventory_tile(frame,x,y):
            driver.click(x+44,y+44);driver.sleep(.2);frame=driver.capture()
        if group_open(frame):
            capture_group(driver,live_dir,output,page,slot,baseline)
            continue
        if not selected_inventory_tile(frame,x,y):
            print(json.dumps({'slot':slot,'error':'selection_not_confirmed'}),flush=True)
            continue
        count=scanner.stack_count(icon)
        write_item(output,stem,icon,frame,driver,'inventory',page,slot,quantity=count)


def capture_archive(driver,live_dir,max_pages=20,start_page=0):
    output=RUN/'archive-captures';output.mkdir(parents=True,exist_ok=True)
    previous=None
    for page in range(start_page,start_page+max_pages):
        require_paused(live_dir)
        driver.sleep(.85)
        baseline=driver.capture()
        cv2.imwrite(str(output/f'p{page:02d}-overview.jpg'),baseline,[cv2.IMWRITE_JPEG_QUALITY,88])
        grid=baseline[145:1280,860:2010]
        signature=hashlib.sha256(cv2.resize(grid,(115,113)).tobytes()).hexdigest()
        if signature==previous:
            print(json.dumps({'stage':'archive_end','page':page}),flush=True)
            break
        previous=signature
        print(json.dumps({'stage':'archive_page','page':page,'signature':signature}),flush=True)
        for slot in range(49):
            require_paused(live_dir)
            stem=f'p{page:02d}-{slot:02d}'
            if (output/f'{stem}.json').exists():continue
            x=round(867+(slot%7)*164)
            y=round(151+(slot//7)*164)
            icon=baseline[y:y+155,x:x+155]
            if icon.shape!=(155,155,3) or float(icon.mean())<12:continue
            driver.click(x+77,y+77);driver.sleep(.24)
            frame=driver.capture()
            if not write_item(output,stem,icon,frame,driver,'archive',page,slot):
                driver.sleep(.4)
                write_item(output,stem,icon,driver.capture(),driver,'archive',page,slot)
        driver.move(1720,900);driver.guard()
        USER.mouse_event(0x0800,0,0,-8*120,0)
        driver.sleep(.95)


def capture_equipped(driver,live_dir):
    driver.click(805,253);driver.sleep(.5)
    output=RUN/'equipped-captures';output.mkdir(parents=True,exist_ok=True)
    baseline=driver.capture()
    cv2.imwrite(str(RUN/'equipped-overview.jpg'),baseline,[cv2.IMWRITE_JPEG_QUALITY,94])
    for slot in range(20):
        require_paused(live_dir)
        x=round(GRID_X+(slot%10)*STEP);y=round(INV_Y+(slot//10)*INV_ROW)
        icon=baseline[y:y+90,x:x+90]
        if icon.shape!=(90,90,3) or float(icon.mean())<15:continue
        driver.click(x+44,y+44);driver.sleep(.2)
        frame=driver.capture()
        if group_open(frame):
            print(json.dumps({'slot':slot,'error':'equipped_group_requires_review'}),flush=True)
            driver.click(973,115);driver.sleep(.5)
            continue
        write_item(output,f'equipped-{slot:02d}',icon,frame,driver,'equipped','equipped',slot,quantity=1)


STAT_GEAR=(('Stone Haori',80),('Demonic Lantern',58),('Nichirin Lantern',38),('Bamboo Muzzle',55))


def ensure_inventory_bottom(driver):
    reference=cv2.imread(str(RUN/'inventory-captures'/'bottom-verified-000-icon.png'))
    if reference is None:raise RuntimeError('Inventory reference capture is missing')
    for _ in range(4):
        driver.sleep(.45)
        actual=driver.capture()[175:265,943:1033]
        if np.mean(np.abs(actual.astype(np.int16)-reference.astype(np.int16)))<40:
            return
        driver.move(1720,900);driver.guard()
        USER.mouse_event(0x0800,0,0,-20*120,0)
        driver.sleep(.85)
    raise RuntimeError('Cannot confirm bottom inventory position')


def current_item_and_action(driver):
    frame=driver.capture()
    title,_=item_title_and_rarity(detail_rows(driver,frame)[1])
    action=' '.join(r[1] for r in driver.text(frame[1290:1370,1150:1430],.5)).lower()
    return title,action


def capture_naked_stats(driver):
    # Four occupied stat slots are recorded in equipped-overview.jpg. The
    # fifth is empty. Each mutation is verified and then reversed.
    removed=[]
    InventoryScanner(driver).open()
    ensure_inventory_bottom(driver)
    cv2.imwrite(str(RUN/'stat-gear-before.jpg'),driver.capture(),[cv2.IMWRITE_JPEG_QUALITY,94])
    try:
        for name,slot in STAT_GEAR:
            x=round(GRID_X+(slot%10)*STEP)+44
            y=round(INV_Y+(slot//10)*INV_ROW)+44
            selected,_=current_item_and_action(driver)
            if selected!=name:driver.click(x,y);driver.sleep(.15)
            title,button=current_item_and_action(driver)
            if title!=name or 'uneq' not in button:
                raise RuntimeError(f'Before unequip: expected {name}; got {title}, {button}')
            driver.click(1273,1330);driver.sleep(.3)
            title,button=current_item_and_action(driver)
            if title!=name or 'equip stats' not in button:
                raise RuntimeError(f'After unequip: expected {name}; got {title}, {button}')
            removed.append((name,slot))
        driver.click(100,1045);driver.sleep(.55)
        naked=driver.capture()
        cv2.imwrite(str(RUN/'naked-hud.jpg'),naked,[cv2.IMWRITE_JPEG_QUALITY,96])
        rows=driver.text(naked[1300:1440,0:1050],.45)
        baseline={'label':'Stat gear removed; equipped fishing titles and vanity remain',
                  'image':'naked-hud.jpg',
                  'bottom_left_ocr':[{'text':r[1],'confidence':round(float(r[2]),3)} for r in rows],
                  'stat_gear_temporarily_removed':[name for name,_ in STAT_GEAR],
                  'captured_at':time.time()}
        (RUN/'baseline.json').write_text(json.dumps(baseline,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({'naked_hud':str(RUN/'naked-hud.jpg'),'ocr':baseline['bottom_left_ocr']}),flush=True)
    finally:
        if removed:
            restore_stat_gear(driver)


def restore_stat_gear(driver):
    InventoryScanner(driver).open()
    ensure_inventory_bottom(driver)
    for position,(name,slot) in enumerate(STAT_GEAR):
        x=round(GRID_X+(slot%10)*STEP)+44
        y=round(INV_Y+(slot//10)*INV_ROW)+44
        selected,_=current_item_and_action(driver)
        if selected!=name:driver.click(x,y);driver.sleep(.15)
        title,button=current_item_and_action(driver)
        if title!=name:raise RuntimeError(f'Restore selection failed: expected {name}; got {title}')
        if 'uneq' in button:continue
        if 'equip stats' not in button:raise RuntimeError(f'Restore action missing: {name}: {button}')
        driver.click(round(980+89*position),1260)
        driver.click(1273,1330);driver.sleep(.35)
        title,button=current_item_and_action(driver)
        if title!=name or 'uneq' not in button:
            raise RuntimeError(f'Restore failed: expected {name}; got {title}, {button}')
        print(json.dumps({'restored':name}),flush=True)
    cv2.imwrite(str(RUN/'stat-gear-restored.jpg'),driver.capture(),[cv2.IMWRITE_JPEG_QUALITY,94])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('world','inventory','select-inventory','archive','select-archive','capture-archive-one','scroll','switch-inventory','catalog-inventory','catalog-archive','catalog-equipped','back-group','titles','player-info','close-menu','capture-naked','restore-stat-gear'))
    parser.add_argument('--live-dir',required=True)
    parser.add_argument('--slot',type=int,default=0)
    parser.add_argument('--point-y',type=int)
    parser.add_argument('--ticks',type=int,default=-6)
    parser.add_argument('--page',choices=('top','bottom','bottom-final','top-accurate','bottom-accurate','bottom-verified'),default='top')
    parser.add_argument('--start',type=int,default=0)
    parser.add_argument('--end',type=int,default=90)
    parser.add_argument('--pages',type=int,default=20)
    args=parser.parse_args()
    require_paused(args.live_dir)
    RUN.mkdir(parents=True,exist_ok=True)
    hwnd=find_window()
    if win32gui.GetForegroundWindow()!=hwnd:
        raise RuntimeError('Bring the single Roblox window to the foreground')
    screen=ScreenSpace(rectangle(hwnd))
    with mss.mss() as sct:
        inp=Input(hwnd)
        driver=InventoryDriver(hwnd,screen,sct,inp,RapidOCR(),USER,move_pointer)
        if args.action=='catalog-inventory':
            capture_inventory_page(driver,args.live_dir,args.page,args.start,args.end)
            return
        if args.action=='catalog-archive':
            capture_archive(driver,args.live_dir,args.pages,args.start)
            return
        if args.action=='catalog-equipped':
            capture_equipped(driver,args.live_dir)
            return
        if args.action=='capture-naked':
            capture_naked_stats(driver)
            return
        if args.action=='restore-stat-gear':
            restore_stat_gear(driver)
            return
        if args.action=='inventory':
            frame=InventoryScanner(driver).open()
            name='inventory-probe.jpg'
        elif args.action=='select-inventory':
            if not 0<=args.slot<90:raise ValueError('slot must be 0..89 on the visible grid')
            driver.click(round(943+(args.slot%10)*99.2)+44,round(INV_Y+(args.slot//10)*INV_ROW)+44)
            driver.sleep(.3)
            frame=driver.capture()
            name=f'inventory-slot-{args.slot:03d}.jpg'
        elif args.action=='back-group':
            driver.click(973,115);driver.sleep(.3)
            frame=driver.capture();name='inventory-probe.jpg'
        elif args.action=='archive':
            driver.click(100,785)
            driver.sleep(.5)
            frame=driver.capture()
            name='archive-probe.jpg'
        elif args.action=='titles':
            driver.click(100,720);driver.sleep(.45)
            frame=driver.capture();name='titles-probe.jpg'
        elif args.action=='player-info':
            driver.click(120,590);driver.sleep(.45)
            frame=driver.capture();name='player-info-probe.jpg'
        elif args.action=='close-menu':
            driver.click(100,1045);driver.sleep(.45)
            frame=driver.capture();name='world-probe.jpg'
        elif args.action=='switch-inventory':
            driver.click(100,395)
            driver.sleep(.5)
            frame=driver.capture()
            name='inventory-probe.jpg'
        elif args.action=='select-archive':
            if not 0<=args.slot<63:raise ValueError('archive slot must be 0..62 on the visible grid')
            driver.click(945+(args.slot%7)*164,args.point_y or 232+(args.slot//7)*164)
            driver.sleep(.3)
            frame=driver.capture()
            name=f'archive-slot-{args.slot:03d}.jpg'
        elif args.action=='capture-archive-one':
            if not 0<=args.slot<49:raise ValueError('archive slot must be 0..48')
            baseline=driver.capture()
            x=round(867+(args.slot%7)*164);y=round(151+(args.slot//7)*164)
            icon=baseline[y:y+155,x:x+155]
            other=1 if args.slot==0 else 0
            driver.click(945+other*164,232);driver.sleep(.15)
            driver.click(x+77,args.point_y or y+77)
            driver.sleep(.4)
            output=RUN/'archive-captures';output.mkdir(parents=True,exist_ok=True)
            write_item(output,f'p{args.start:02d}-{args.slot:02d}',icon,driver.capture(),driver,'archive',args.start,args.slot)
            return
        elif args.action=='scroll':
            if not -20<=args.ticks<=20:raise ValueError('ticks must be -20..20')
            driver.move(1720,900)
            driver.guard()
            USER.mouse_event(0x0800,0,0,args.ticks*120,0)
            driver.sleep(.5)
            frame=driver.capture()
            name='scroll-probe.jpg'
        else:
            frame=driver.capture()
            name='world-probe.jpg'
        path=RUN/name
        cv2.imwrite(str(path),frame,[cv2.IMWRITE_JPEG_QUALITY,94])
        print(json.dumps({'path':str(path),'width':frame.shape[1],'height':frame.shape[0],
                          'at':time.time()}))


if __name__=='__main__':main()
