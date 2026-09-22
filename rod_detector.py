"""Locate the rod in the visible hotbar and inspect its selected ring."""
from functools import lru_cache
import cv2
import numpy as np
from app_config import ROOT


@lru_cache(maxsize=1)
def templates():
    return [cv2.imread(str(ROOT/'assets'/name), cv2.IMREAD_GRAYSCALE)
            for name in ('rod-icon.png','rod-unequipped.png')]


def locate_rod(frame):
    if frame.shape[:2] != (1440,2560):return None
    bar = cv2.cvtColor(frame[1320:1430,500:2060],cv2.COLOR_BGR2GRAY)
    matches=[]
    for appearance,icon in enumerate(templates()):
        if icon is None:continue
        _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(bar,icon,cv2.TM_CCOEFF_NORMED))
        matches.append((score,point,appearance))
    if not matches:return None
    score,point,appearance=max(matches)
    if score < .72:return None
    x,y = point[0]+500+30,point[1]+1320+19
    yy,xx=np.ogrid[:1440,:2560]
    # Ring outside the artwork; only the selected hotbar slot has this outline.
    radius=(xx-x)**2+(yy-y)**2
    mask=(radius>=38**2)&(radius<=40**2)
    pixels=frame[mask]
    neutral=(pixels.max(axis=1)-pixels.min(axis=1)<45)&(pixels.mean(axis=1)>75)
    ring=float(neutral.mean())
    return {'x':x,'y':y,'score':round(score,3),'equipped':appearance==0 and ring>.15,'ring':round(ring,3)}


def selected_rod(rod):
    """Stricter evidence for unattended clicks than for finding an icon."""
    return bool(rod and rod.get('equipped') and rod.get('score',0)>=.88 and rod.get('ring',0)>=.30)


class RodReady:
    def __init__(self):
        self.reset()

    def reset(self):
        self.rod=None;self.count=0;self.first=self.last=0

    def matches(self, rod):
        return (selected_rod(rod) and self.rod is not None
                and abs(rod['x']-self.rod['x'])<=4 and abs(rod['y']-self.rod['y'])<=4)

    def observe(self, rod, now):
        if not selected_rod(rod):
            self.reset();return False
        if not self.matches(rod) or now-self.last>1.5:
            self.first=now;self.count=0
        if now>self.last:self.count+=1
        self.rod=rod;self.last=now
        return self.count>=3 and now-self.first>=.5
