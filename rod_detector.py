"""Locate the rod in the visible hotbar and inspect its selected ring."""
from functools import lru_cache
import json
import cv2
import numpy as np
from app_config import ROOT


@lru_cache(maxsize=1)
def templates():
    result=[]
    for rod in json.loads((ROOT/'assets/rods.json').read_text()):
        # The unselected hotbar disk is translucent. Daylight scenery can
        # overwhelm a full-icon match even when the rod itself is unchanged.
        plain=next(v for v in rod['variants'] if not v['selected'])
        foreground=cv2.imread(str(ROOT/'assets'/plain['image']))
        mask=(foreground.max(axis=2)>65).astype(np.uint8)*255
        for variant in rod['variants']:
            icon=cv2.imread(str(ROOT/'assets'/variant['image']),cv2.IMREAD_GRAYSCALE)
            if icon is None:continue
            for sx in (1.,.95,1.05):
                for sy in (1.,.95,1.05):
                    result.append({**variant,'name':rod['name'],'priority':rod['priority'],
                                   'scale':sx,'sy':sy,'icon':cv2.resize(icon,None,fx=sx,fy=sy),
                                   'mask':cv2.resize(mask,None,fx=sx,fy=sy,interpolation=cv2.INTER_NEAREST)})
    return result


def selected_ring(frame,x,y,scale=1.,sy=None):
    # A circular brightness edge survives night lighting and scene tint. A
    # handful of pale scenery pixels is not enough: require three quadrants.
    sy=scale if sy is None else sy
    extent=int(46*max(scale,sy)+2)
    left,right=max(0,int(x)-extent),min(frame.shape[1],int(x)+extent+1)
    top,bottom=max(0,int(y)-extent),min(frame.shape[0],int(y)+extent+1)
    gray=frame[top:bottom,left:right].mean(axis=2)
    angles=np.arange(96)*2*np.pi/96
    def sample(radius):
        xx=np.clip(np.round(x-left+np.cos(angles)*radius*scale).astype(int),0,gray.shape[1]-1)
        yy=np.clip(np.round(y-top+np.sin(angles)*radius*sy).astype(int),0,gray.shape[0]-1)
        return gray[yy,xx]
    edge=np.max([sample(r) for r in (37.5,38.5,39.5,40.5)],axis=0)
    outer=np.mean([sample(r) for r in (43,44,45)],axis=0)
    inner=np.mean([sample(r) for r in (33,34,35)],axis=0)
    bright=edge-np.maximum(outer,inner)>8
    coverage=float(bright.mean())
    quadrants=int((bright.reshape(4,24).mean(axis=1)>.5).sum())
    # Downsampled 1080p clients soften the thin circle by roughly one pixel.
    # Keep the three-quadrant shape requirement while allowing that blur.
    return coverage,coverage>.58 and quadrants>=3


def locate_rod(frame):
    if frame.shape[:2] != (1440,2560):return None
    bar = cv2.cvtColor(frame[1320:1430,500:2060],cv2.COLOR_BGR2GRAY)
    matches=[]
    for variant in templates():
        icon=variant['icon'];scale=variant['scale'];sy=variant.get('sy',scale)
        shape_verified=False
        _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(bar,icon,cv2.TM_CCOEFF_NORMED))
        if score<.88:
            # Match the rod foreground, excluding the
            # changing disk background. Keep a higher confidence floor here.
            shape=cv2.matchTemplate(bar,icon,cv2.TM_CCOEFF_NORMED,mask=variant['mask'])
            shape=np.nan_to_num(shape,nan=-1,posinf=-1,neginf=-1)
            _,shape_score,_,shape_point=cv2.minMaxLoc(shape)
            if shape_score>=.90 and shape_score>score:
                score,point=shape_score,shape_point;shape_verified=True
        if score<.72:continue
        x=point[0]+500+variant['anchor'][0]*scale
        y=point[1]+1320+variant['anchor'][1]*sy
        cx,cy=round(x),round(y)
        ring,selected=selected_ring(frame,x,y,scale,sy)
        matches.append({'x':cx,'y':cy,'score':round(score,3),'ring':round(ring,3),
                        'equipped':bool(variant['selected'] and selected),
                        'shape_unselected':bool(shape_verified and not variant['selected'] and not selected),
                        'name':variant['name'],'priority':variant['priority']})
    if not matches:return None
    # Never replace a manually selected rod just because an unselected icon
    # happens to be a more exact template match. Prefer rare when neither is out.
    equipped=[rod for rod in matches if selected_rod(rod)]
    if equipped:return max(equipped,key=lambda rod:rod['score'])
    confident=[rod for rod in matches if rod['score']>=.88]
    return max(confident,key=lambda rod:(rod['priority'],rod['score'])) if confident else max(matches,key=lambda rod:rod['score'])


def selected_rod(rod):
    """Stricter evidence for unattended clicks than for finding an icon."""
    return bool(rod and rod.get('equipped') and rod.get('score',0)>=.88 and rod.get('ring',0)>=.30)


def unselected_rod(rod):
    """Only a clear icon without the selected ring authorizes a rod click."""
    return bool(rod and not rod.get('equipped') and rod.get('score',0)>=.88
                and (rod.get('ring',1)<.30 or rod.get('shape_unselected',False)))


class RodReady:
    def __init__(self):
        self.reset()

    def reset(self):
        self.rod=None;self.count=0;self.first=self.last=0

    def matches(self, rod):
        return (selected_rod(rod) and self.rod is not None
                and rod.get('name')==self.rod.get('name')
                and abs(rod['x']-self.rod['x'])<=4 and abs(rod['y']-self.rod['y'])<=4)

    def observe(self, rod, now):
        if not selected_rod(rod):
            self.reset();return False
        if not self.matches(rod) or now-self.last>1.5:
            self.first=now;self.count=0
        if now>self.last:self.count+=1
        self.rod=rod;self.last=now
        return self.count>=3 and now-self.first>=.5
