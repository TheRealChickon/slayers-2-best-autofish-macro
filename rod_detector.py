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
    for icon in templates():
        if icon is None:continue
        _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(bar,icon,cv2.TM_CCOEFF_NORMED))
        matches.append((score,point))
    if not matches:return None
    score,point=max(matches)
    if score < .72:return None
    x,y = point[0]+500+30,point[1]+1320+19
    yy,xx=np.ogrid[:1440,:2560]
    # Ring outside the artwork; only the selected hotbar slot has this outline.
    radius=(xx-x)**2+(yy-y)**2
    mask=(radius>=38**2)&(radius<=40**2)
    pixels=frame[mask]
    neutral=(pixels.max(axis=1)-pixels.min(axis=1)<45)&(pixels.mean(axis=1)>75)
    ring=float(neutral.mean())
    return {'x':x,'y':y,'score':round(score,3),'equipped':ring>.38,'ring':round(ring,3)}
