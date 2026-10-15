"""Local visual reference and bounded corrections; no blind navigation.

Coordinates and visual errors use a 1280x720 reference, independent of resolution.
An account's reference is private local data. No correction runs without it.
"""
import json
import re
import time
from pathlib import Path

import cv2
import numpy as np

from app_config import load_config
from metrics import RUN, read, write
from faults import FishingFault

# Two crate tops near this spawn and the building across the water. Excludes
# the avatar, moving water, compass, chat and hotbar. CLI accepts other boxes.
DEFAULT_BOXES = [[500,540,250,115],[800,535,300,110],[350,155,145,100]]


def account_key():
    config=load_config()
    return {'user_id':config.get('user_id'),'username':config.get('account_username','').lower(),
            'place_id':config['place_id']}


def profile():
    saved=read('landmark.json')
    return saved if saved.get('enabled') and saved.get('account')==account_key() else None


class Matcher:
    def __init__(self, image, boxes):
        self.boxes=boxes
        self.sift=cv2.SIFT_create(nfeatures=2500,contrastThreshold=.009)
        self.groups=[]
        gray=self.gray(image)
        self.reference_gray=gray
        for x,y,w,h in boxes:
            points,descriptors=self.sift.detectAndCompute(gray[y:y+h,x:x+w],None)
            if descriptors is None or len(points)<12:
                raise ValueError('A landmark has too little detail; choose a larger textured area')
            self.groups.append((np.float32([p.pt for p in points])+[x,y],descriptors))
        self.base=np.array([v for x,y,w,h in boxes for v in (x+w/2,y+h/2,x+w*.2,y+h*.2,x+w*.8,y+h*.8)])

    @staticmethod
    def gray(frame):
        gray=cv2.cvtColor(cv2.resize(frame,(1280,720)),cv2.COLOR_BGR2GRAY).astype(np.float32)
        detail=gray-cv2.GaussianBlur(gray,(0,0),3)
        deviation=np.sqrt(cv2.GaussianBlur(detail*detail,(0,0),3))
        return np.clip(128+40*detail/np.maximum(deviation,1),0,255).astype(np.uint8)

    def measure(self, frame):
        gray=self.gray(frame);values=[];quality=[];self.report=[];self.transforms=[]
        for index,(reference,source) in enumerate(self.groups):
            x,y,w,h=self.boxes[index];left=max(0,x-130);top=max(0,y-100)
            crop=gray[top:min(680,y+h+100),left:min(1280,x+w+130)]
            if index>=2:
                # Far geometry changes mostly by translation. Template matching
                # keeps dim building silhouettes stable when only a few SIFT
                # corners survive the game's lighting cycle.
                template=self.reference_gray[y:y+h,x:x+w]
                candidates=[]
                for factor in (.96,.98,1.,1.02,1.04):
                    scaled=cv2.resize(template,None,fx=factor,fy=factor)
                    response=cv2.matchTemplate(crop,scaled,cv2.TM_CCOEFF_NORMED)
                    _,score,_,point=cv2.minMaxLoc(response)
                    candidates.append((score,factor,point))
                score,factor,(px,py)=max(candidates)
                self.report.append({'group':index,'template_score':score})
                if score>=.82:
                    probes=self.base[index*6:index*6+6].reshape(-1,2)
                    projected=(probes-[x,y])*factor+[left+px,top+py]
                    values.extend(projected.ravel());quality.append(round(score,3));continue
                # Both crate surfaces are mandatory. Distant scenery is extra
                # evidence and can vanish into fog or change with long shadows.
                values.extend([float('nan')]*6);quality.append(None);continue
            points,descriptors=self.sift.detectAndCompute(crop,None)
            if descriptors is None:return None
            current=np.float32([p.pt for p in points])+[left,top]
            pairs=cv2.BFMatcher().knnMatch(source,descriptors,k=2)
            matches=[p[0] for p in pairs if len(p)==2 and p[0].distance<.68*p[1].distance]
            self.report.append({'group':index,'matches':len(matches)})
            if len(matches)<7:return None
            a=np.float32([reference[m.queryIdx] for m in matches])
            b=np.float32([current[m.trainIdx] for m in matches])
            matrix,inliers=cv2.estimateAffine2D(a,b,method=cv2.RANSAC,ransacReprojThreshold=2.5,maxIters=1500)
            if matrix is None or inliers is None:return None
            mask=inliers.ravel().astype(bool)
            scale=float(np.hypot(matrix[0,0],matrix[0,1]))
            singular=np.linalg.svd(matrix[:,:2],compute_uv=False)
            self.report[-1].update(inliers=int(mask.sum()),ratio=float(mask.mean()),scale=scale)
            # Repeated crate textures cannot win with just a couple of matches.
            if mask.sum()<7 or mask.mean()<.55 or not .80<min(singular)<=max(singular)<1.25 or np.linalg.det(matrix[:,:2])<=0:return None
            spread=np.ptp(a[mask],axis=0)
            if min(spread)<18:return None
            probes=self.base[index*6:index*6+6].reshape(-1,2)
            projected=probes@matrix[:,:2].T+matrix[:,2]
            if not np.isfinite(projected).all():return None
            self.transforms.append(matrix)
            values.extend(projected.ravel());quality.append(int(mask.sum()))
        error=np.asarray(values)-self.base
        return {'error':error,'rms':float(np.sqrt(np.nanmean(error**2))), 'matches':quality}

    def refresh_features(self, frame):
        """Refresh appearance after a verified match, retaining saved coordinates.

        This is temporary for one correction attempt. It does not overwrite the
        reference or treat the current position as the desired position.
        """
        if len(self.transforms)<2:return
        gray=self.gray(frame)
        for index,matrix in enumerate(self.transforms[:2]):
            x,y,w,h=self.boxes[index]
            corners=np.float32([[x,y],[x+w,y],[x+w,y+h],[x,y+h]])@matrix[:,:2].T+matrix[:,2]
            left,top=np.maximum([0,0],np.floor(corners.min(axis=0)).astype(int))
            right,bottom=np.minimum([1280,720],np.ceil(corners.max(axis=0)).astype(int))
            mask=np.zeros((bottom-top,right-left),np.uint8)
            cv2.fillConvexPoly(mask,np.round(corners-[left,top]).astype(np.int32),255)
            points,descriptors=self.sift.detectAndCompute(gray[top:bottom,left:right],mask)
            if descriptors is None or len(points)<12:continue
            current=np.float32([p.pt for p in points])+[left,top]
            inverse=cv2.invertAffineTransform(matrix)
            original=current@inverse[:,:2].T+inverse[:,2]
            self.groups[index]=(original,descriptors)


def load_matcher(saved):
    image=cv2.imread(str(RUN/'landmark-reference.png'))
    if image is None:raise FishingFault('alignment','Fishing reference image is missing')
    return Matcher(image,saved['boxes'])


def observation(driver, matcher):
    for attempt in range(3):
        first=matcher.measure(driver.capture())
        driver.sleep(.20)
        frame=driver.capture();second=matcher.measure(frame)
        driver.guard()
        if first is not None and second is not None and np.nanmax(np.abs(first['error']-second['error']))<=4:
            matcher.refresh_features(frame)
            return second
        driver.sleep(.25)
    raise FishingFault('alignment','Landmarks are obscured or unstable; movement withheld',matches=matcher.report)


def camera(driver, dx, dy):
    from fishing_assistant import USER
    dx,dy=round(dx),round(dy)
    if abs(dx)>60 or abs(dy)>60:raise ValueError('Camera step exceeds correction limit')
    if dx==0 and dy==0:return
    driver.move(1630,780);driver.sleep(.10);driver.guard()
    USER.mouse_event(8,0,0,0,0)
    try:
        # A brief stationary right-click can toggle Roblox's camera mode.
        # Use a deliberate hold/drag, and never click for a zero correction.
        driver.sleep(.30)
        count=max(1,abs(dx)//3,abs(dy)//3)
        for i in range(count):
            driver.guard()
            USER.mouse_event(1,round((i+1)*dx/count)-round(i*dx/count),round((i+1)*dy/count)-round(i*dy/count),0,0)
            driver.sleep(.012)
    finally:USER.mouse_event(16,0,0,0,0)
    driver.sleep(.6)


def apply_step(driver, step):
    camera(driver,*step[:2])
    for value,positive,negative in zip(step[2:],('A','W'),('D','S')):
        if abs(value)>=.018:
            if abs(value)>.081:raise ValueError('Position step exceeds correction limit')
            driver.key(positive if value>0 else negative,abs(float(value)))
            driver.sleep(.7)


def heading(driver, frame):
    rows,_=driver.ocr(cv2.resize(frame[:40,1230:1330],None,fx=4,fy=4),use_cls=False)
    bearings={'N':0,'E':90,'S':180,'W':270,**{str(n):n for n in range(0,360,45)}}
    candidates=[]
    for box,text,score in rows or []:
        text=re.sub(r'[^A-Z0-9]','',text.upper())
        if text not in bearings or score<.88:continue
        offset=float(np.mean(np.asarray(box)[:,0]))/4-50
        if abs(offset)>28:continue
        candidates.append((abs(offset),(bearings[text]-.9*offset)%360))
    return min(candidates)[1] if candidates else None


def restore_heading(driver, target):
    if target is None:return 0
    travel=0;gain=.12;started=time.monotonic()
    for _ in range(20):
        first=heading(driver,driver.capture());driver.sleep(.1)
        current=heading(driver,driver.capture());driver.guard()
        if first is None or current is None:
            if travel:raise FishingFault('alignment','Compass unreadable during camera correction')
            return travel
        difference=lambda a,b:(a-b+180)%360-180
        if abs(difference(first,current))>3:return travel
        error=difference(target,current)
        if abs(error)<4:return travel
        step=round(np.clip(error/gain,-60,60))
        if travel+abs(step)>1100 or time.monotonic()-started>35:
            raise FishingFault('alignment','Compass correction reached its limit')
        driver.event('camera_heading',current=round(current,1),target=round(target,1),step=step)
        camera(driver,step,0);travel+=abs(step)
        after=heading(driver,driver.capture())
        if after is not None:
            observed=difference(after,current)/step
            if observed<-.015:raise FishingFault('alignment','Compass moved opposite to the expected camera direction')
            if .03<observed<.5:gain=.5*gain+.5*observed
    raise FishingFault('alignment','Compass correction did not converge')


def limited_step(jacobian, error, position=False):
    matrix=np.asarray(jacobian,float)
    columns=4 if position else 2
    if matrix.ndim!=2 or matrix.shape!=(len(error),4) or not np.isfinite(matrix).all():
        raise FishingFault('alignment','Invalid reference calibration')
    valid=np.isfinite(error);matrix=matrix[valid];error=np.asarray(error)[valid]
    if valid.sum()<12:raise FishingFault('alignment','Insufficient landmark geometry for movement')
    scales=np.array([20.,20.,.06,.06])[:columns]
    scaled=matrix[:,:columns]*scales
    if np.linalg.matrix_rank(scaled)<columns or np.linalg.cond(scaled)>120:
        raise FishingFault('alignment','Reference calibration cannot distinguish camera and position')
    normalized=np.linalg.lstsq(scaled,-np.asarray(error),rcond=None)[0]
    step=normalized*scales
    limits=np.array([24.,24.,.04,.04])[:columns]
    step*=min(1.,1./max(1.,float(np.max(np.abs(step)/limits))))
    result=np.zeros(4);result[:columns]=step;result[:2]=np.round(result[:2])
    result[2:][np.abs(result[2:])<.018]=0
    return result


def align(driver, allow_position=True, strict=False):
    saved=profile()
    if saved is None:return {'enabled':False}
    restore_heading(driver,saved.get('heading'))
    matcher=load_matcher(saved)
    try:before=observation(driver,matcher)
    except FishingFault as error:
        if strict:raise
        result={'enabled':True,'at':time.time(),'aligned':False,'skipped':True,'steps':0,'reason':str(error)}
        write('alignment.json',result);driver.event('alignment_skipped',message='Reference obscured; using the saved spawn without corrective input')
        return result
    current=before
    driver.event('alignment_check',error=round(current['rms'],2),matches=current['matches'])
    travel=0.;camera_travel=0.;started=time.monotonic();steps=0
    # Camera first. Position is available only after a successful calibration.
    for iteration in range(7):
        if current['rms']<=6:break
        if time.monotonic()-started>25:break
        position=allow_position and saved.get('position_enabled',False)
        step=limited_step(saved['jacobian'],current['error'],position)
        # Estimate position at the same time, but correct the camera first.
        # Otherwise camera pitch could disguise lateral character movement.
        if iteration<2:step[2:]=0
        if not np.any(step):
            if position and iteration<2:continue
            break
        movement=float(np.sum(np.abs(step[2:])));rotation=float(np.sum(np.abs(step[:2])))
        if travel+movement>.12 or camera_travel+rotation>160:break
        driver.event('alignment_step',camera=step[:2].tolist(),movement_seconds=step[2:].tolist())
        apply_step(driver,step);travel+=movement;camera_travel+=rotation;steps+=1
        following=observation(driver,matcher)
        if following['rms']>current['rms']+1:
            # Only reverse a known small step while all landmarks remain visible.
            apply_step(driver,-step)
            observation(driver,matcher)
            raise FishingFault('alignment','Landmark correction did not improve the view; reverted the step')
        current=following
    result={'enabled':True,'at':time.time(),'before':round(before['rms'],2),'after':round(current['rms'],2),
            'steps':steps,'movement_seconds':round(travel,3),'aligned':current['rms']<=6}
    write('alignment.json',result);driver.event('alignment_result',**result)
    if not result['aligned']:raise FishingFault('alignment','Fishing alignment remains outside tolerance',result=result)
    return result


def calibrate(driver, boxes=None, position=False):
    """Explicit, paused setup. A failed calibration never replaces a working profile."""
    boxes=boxes or DEFAULT_BOXES
    if len(boxes)<2:raise ValueError('Select at least two separate textured surfaces near the fishing spot')
    for x,y,w,h in boxes:
        if min(x,y)<0 or min(w,h)<40 or x+w>1280 or y+h>680:raise ValueError('Invalid landmark box')
    frame=driver.capture();matcher=Matcher(frame,boxes);baseline=observation(driver,matcher)
    if not np.isfinite(baseline['error']).all():
        boxes=boxes[:2];matcher=Matcher(frame,boxes);baseline=observation(driver,matcher)
    cv2.imwrite(str(RUN/'calibration-before.png'),frame)
    if baseline['rms']>2:raise ValueError('The reference is moving; wait for the camera to settle')
    columns=[]
    for index,amount in enumerate((20.,20.,.04,-.04)):
        if index>=2 and not position:
            columns.append(np.zeros(len(matcher.base)));continue
        step=np.zeros(4);step[index]=amount
        driver.event('calibration_step',axis=index,amount=amount)
        before=observation(driver,matcher)
        apply_step(driver,step)
        cv2.imwrite(str(RUN/'calibration-moved.jpg'),driver.capture())
        moved=observation(driver,matcher)
        if np.sqrt(np.mean((moved['error']-before['error'])**2))<2:
            raise FishingFault('alignment','Calibration input was blocked; profile unchanged')
        apply_step(driver,-step)
        restored=observation(driver,matcher)
        driver.event('calibration_return',axis=index,error=round(restored['rms'],2))
        if restored['rms']>10:raise FishingFault('alignment','Calibration did not return to the starting view; profile unchanged')
        column=(moved['error']-before['error'])/amount
        if not np.isfinite(column).all():raise FishingFault('alignment','A calibration landmark disappeared; profile unchanged')
        columns.append(column)
    matrix=np.array(columns).T
    limited_step(matrix,np.zeros(len(matcher.base)),position)
    saved={'version':1,'enabled':True,'account':account_key(),'saved_at':time.time(),'boxes':boxes,
           'position_enabled':position,'jacobian':matrix.tolist(),'heading':heading(driver,frame)}
    # Publish metadata only after the calibrated reference is validated.
    ok,data=cv2.imencode('.png',frame)
    if not ok:raise RuntimeError('Could not encode the fishing reference')
    temporary=RUN/'landmark-reference.tmp';temporary.write_bytes(data.tobytes())
    temporary.replace(RUN/'landmark-reference.png');write('landmark.json',saved)
    driver.event('reference_saved',position=position,boxes=boxes)
    return saved
