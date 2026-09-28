"""Spatial chest/item prompts; reward text alone never authorizes a T press."""
from dataclasses import dataclass
from pathlib import Path
import math
import re
import cv2
import numpy as np

LOOT_MARKER=cv2.imread(str(Path(__file__).resolve().parent/'assets'/'boss-loot-marker.png'),0)
POUCH_MARKER=cv2.imread(str(Path(__file__).resolve().parent/'assets'/'boss-pouch-marker.png'),0)


def chest_targets(frame):
    """Orange chest frame around a dark green lid; navigation evidence only."""
    if frame.shape[:2]!=(1440,2560):return []
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    hue,sat,value=cv2.split(hsv)
    mask=((hue>=7)&(hue<=27)&(sat>110)&(value>35)&(value<200)).astype(np.uint8)*255
    mask[:500]=0;mask[1150:]=0;mask[:,:200]=0;mask[:,2140:]=0
    mask[500:780,:450]=0
    mask[730:,1140:1440]=0
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    _,_,stats,_=cv2.connectedComponentsWithStats(mask)
    pieces=[(x,y,x+w,y+h) for x,y,w,h,area in stats[1:]
            if 60<=w<=350 and 35<=h<=220 and area>500 and .08<area/(w*h)<.85]
    groups=[]
    for piece in pieces:
        for i,(x,y,r,b) in enumerate(groups):
            if min(b,piece[3])-max(y,piece[1])>25 and piece[0]<r+60 and piece[2]>x-60:
                groups[i]=(min(x,piece[0]),min(y,piece[1]),max(r,piece[2]),max(b,piece[3]))
                break
        else:groups.append(piece)
    found=[]
    for x,y,r,b in groups:
        if not (90<r-x<450 and .8<(r-x)/(b-y)<3.5):continue
        green=(hue[y:b,x:r]>30)&(hue[y:b,x:r]<100)&(sat[y:b,x:r]>30)&(value[y:b,x:r]>25)&(value[y:b,x:r]<160)
        if np.count_nonzero(green)<150:continue
        found.append(((x+r)/2,(y+b)/2,1.))
    return found


def loot_glows(frame):
    """Colored drop glow can guide an approach before its circle is visible."""
    if frame.shape[:2]!=(1440,2560):return []
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    hue,sat,value=cv2.split(hsv)
    # Pink ground petals can resemble pouch glow. Pouches therefore still
    # require their circle; only the compact blue-white ore glow is used here.
    color=(hue>85)&(hue<115)&(sat>65)&(value>200)
    bright=(value>230)&(sat<150)
    mask=(color|bright).astype(np.uint8)*255
    mask[:540]=0;mask[1230:]=0;mask[:,:200]=0;mask[:,2140:]=0
    mask[650:1150,1160:1410]=0;mask[620:735,:340]=0
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((7,7),np.uint8))
    n,labels,stats,centers=cv2.connectedComponentsWithStats(mask)
    found=[]
    for i in range(1,n):
        x,y,w,h,area=stats[i]
        if not (8<=w<=120 and 8<=h<=150 and 35<=area<=5000):continue
        if not .35<w/h<1.4:continue
        component=labels[y:y+h,x:x+w]==i
        if np.count_nonzero(color[y:y+h,x:x+w]&component)<25:continue
        if np.count_nonzero(bright[y:y+h,x:x+w]&component)<15:continue
        # Boundary fragments can be sky, a notification or the player's aura.
        if x<=205 or x+w>=2135 or y<=545 or y+h>=1225:continue
        if x+w>=1155 and x<=1415 and y+h>=645 and y<=1155:continue
        found.append((float(centers[i][0]),float(y+h),1.))
    return found


def loot_markers(frame, threshold=.84):
    """Ground pickup circles guide movement only, never an interaction."""
    if frame.shape[:2]!=(1440,2560) or LOOT_MARKER is None:return []
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    roi=gray[420:1230,200:2140].copy()
    # Exclude the player, party widget, notifications and the fixed HUD.
    roi[230:730,960:1210]=0
    roi[200:315,:140]=0
    found=[]
    bases=[base for base in (LOOT_MARKER,POUCH_MARKER) if base is not None]
    for base,scale in ((base,scale) for base in bases for scale in (.45,.5,.6,.7,.8,.9,.95,1.,1.05,1.1,1.25,1.5)):
        template=cv2.resize(base,None,fx=scale,fy=scale)
        scores=cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED)
        for _ in range(6):
            _,score,_,(x,y)=cv2.minMaxLoc(scores)
            if score<(max(.89,threshold) if scale<.6 else threshold):break
            scores[max(0,y-35):y+36,max(0,x-35):x+36]=-1
            cx=round(x+template.shape[1]/2+200)
            cy=round(y+template.shape[0]/2+420)
            radius=max(2,round(3*scale))
            core=frame[cy-radius:cy+radius+1,cx-radius:cx+radius+1].mean(axis=(0,1))
            # The dark gray circular overlay differs from white text holes
            # and green grass patterns that can correlate at small scales.
            if core.max()>140 or core.max()-core.min()>38:continue
            top,left=max(420,cy-140),max(200,cx-95)
            patch=frame[top:min(1230,cy+45),left:min(2140,cx+95)]
            hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
            glow=(hsv[:,:,2]>230)&((hsv[:,:,1]<100)|((hsv[:,:,0]>135)&(hsv[:,:,0]<175)))
            # The marker's own pale ring is not independent drop evidence.
            radius=round(max(template.shape)/2)+3
            glow[max(0,cy-top-radius):cy-top+radius+1,max(0,cx-left-radius):cx-left+radius+1]=False
            if np.count_nonzero(glow)<25:continue
            found.append((cx,cy,float(score)))
    selected=[]
    for item in sorted(found,key=lambda a:a[2],reverse=True):
        if not any(math.hypot(item[0]-other[0],item[1]-other[1])<40 for other in selected):
            selected.append(item)
    return selected


@dataclass(frozen=True)
class LootPrompt:
    name: str
    action: str
    center: tuple


def prompt_from_rows(rows):
    rows = [row for row in rows if row['score'] >= .8]
    keys = [row for row in rows if row['text'].strip().upper() == 'T']
    actions = [row for row in rows if row['text'].strip().lower() in ('open','claim','collect')]
    candidates=[]
    for action in actions:
        nearby=[row for row in rows if row not in actions and row not in keys and
                abs(row['x']-action['x']) < 500 and abs(row['y']-action['y']) < 110]
        names=[row for row in nearby if re.search(r'chest|coin pouch|refinement ore|metal scraps|brave soul|silk thread|haor?i?|katana|uniform|armou?r|\bwen\b',row['text'],re.I)]
        if len(names)!=1:continue
        name=names[0]
        radius=max(330,330+name.get('height',0)*6)
        if not any(math.hypot(key['x']-name['x'],key['y']-name['y']) < radius for key in keys):continue
        candidates.append(LootPrompt(name['text'],action['text'].lower(),(name['x'],name['y'])))
    return candidates[0] if len(candidates)==1 else None


def reward_name(text):
    """Normalize observed toast OCR aliases without accepting arbitrary names."""
    normalized=re.sub(r'[^a-z]','',text.lower())
    # The pouch artwork's W and a cursor over 'ch' produced wCoin Poud in
    # a verified Coin Pouch x2 toast. Keep the alias narrowly scoped.
    if normalized in ('coinpouch','wcoinpouch','coinpoud','wcoinpoud'):
        return 'Coin Pouch'
    if normalized in ('refinementore','refinemertore'):
        return 'Refinement Ore'
    return text.strip() if re.search(r'pouch|ore|scraps|haori|katana|uniform|armou?r|soul|silk thread',text,re.I) else None


def reward_from_rows(rows):
    """Pair one xN toast with its adjacent item name, excluding world prompts."""
    rewards=[]
    for amount in rows:
        match=re.fullmatch(r'x\s*(\d{1,2})',amount['text'].strip(),re.I)
        if not match or amount['score'] < .75:continue
        names=[row for row in rows if row['score'] >= .85 and
               0 < amount['y']-row['y'] < 65 and abs(row['x']-amount['x']) < 160 and
               reward_name(row['text'])]
        if len(names)==1:rewards.append((reward_name(names[0]['text']),int(match.group(1))))
    return rewards
