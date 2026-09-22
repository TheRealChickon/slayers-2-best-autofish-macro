"""Fishing markers in normalized client pixels, independent of red scene tint."""
import cv2
import numpy as np


def detect(roi):
    if roi is None or roi.shape[:2] != (600, 140):
        return None
    b, g, r = cv2.split(roi.astype(np.int16))
    # The transparent green/yellow target can have R > G over red scenery.
    # HSV hue then leaves the old green range. Its green-versus-blue contrast
    # and rectangular outline survive, so red is deliberately not a veto.
    tint = np.uint8((g - b > 18) & (g > 48)) * 255
    tint = cv2.morphologyEx(tint, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    targets = []
    hue=cv2.inRange(cv2.cvtColor(roi,cv2.COLOR_BGR2HSV),np.array([20,65,48]),np.array([100,255,255]))
    for mask in (hue,tint):
        for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
            x, y, w, h = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)
            if 54 <= w <= 95 and 22 <= h <= 130 and 12 <= x <= 50 and abs(x+w/2-70) < 15 and area > 450:
                candidate=(area/(w*h), y+h/2, h)
                if not any(abs(candidate[1]-old[1])<5 for old in targets):targets.append(candidate)
    if not targets:
        # Brown/green scenery can connect the rectangle to the whole image.
        # Isolate the known target width, then retain horizontal runs: scattered
        # background pixels disappear without requiring an isolated contour.
        bounded=tint.copy()
        bounded[:,:31]=0;bounded[:,109:]=0
        bounded=cv2.morphologyEx(bounded,cv2.MORPH_OPEN,np.ones((1,51),np.uint8))
        for contour in cv2.findContours(bounded,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
            x,y,w,h=cv2.boundingRect(contour)
            area=cv2.contourArea(contour)
            if 65<=w<=78 and 22<=h<=130 and y>=28 and y+h<=552 and area/(w*h)>.70:
                targets.append((area/(w*h),y+h/2,h))
    if not targets:
        # A connected patch of scenery can swallow the color component. Look
        # for a closed rectangle with the same UI geometry, then require green
        # contrast on its horizontal borders; edges alone never authorize input.
        edges = cv2.Canny(np.clip(g-b+100, 0, 255).astype(np.uint8), 22, 55)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        for contour in cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0]:
            x, y, w, h = cv2.boundingRect(contour)
            if not (54 <= w <= 95 and 22 <= h <= 130 and 12 <= x <= 50 and abs(x+w/2-70) < 15):
                continue
            top = tint[max(0,y-1):y+4, x+5:x+w-5]
            bottom = tint[y+h-4:min(600,y+h+1), x+5:x+w-5]
            if top.size and bottom.size and (top.max(axis=0)>0).mean() > .65 and (bottom.max(axis=0)>0).mean() > .65:
                targets.append((.5, y+h/2, h))
    # A white marker tinted slightly pink still has three bright channels.
    low, high = roi.min(axis=2), roi.max(axis=2)
    white = np.uint8((low >= 135) & (high >= 185) & (high.astype(np.int16)-low < 100))*255
    # The target's border may cross the marker and split it into two bright
    # halves. Join that narrow line so tracking uses the whole marker center.
    white=cv2.morphologyEx(white,cv2.MORPH_CLOSE,np.ones((5,3),np.uint8))
    balls = []
    neutral=cv2.inRange(roi,np.array([178]*3),np.array([255]*3))
    for mask in (neutral,white):
        for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
            x, y, w, h = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)
            if 14 <= w <= 45 and 14 <= h <= 48 and 42 <= x <= 87 and .6 <= w/h <= 1.7 and area > 150:
                balls.append((area, y+h/2, h))
    if not balls:
        # During the UI fade, blue/red scenery can tint the white marker below
        # a fixed brightness threshold. Compare it with the same row beside it.
        gray=roi.astype(np.float32).mean(axis=2)
        baseline=(np.median(gray[:,38:49],axis=1)+np.median(gray[:,92:103],axis=1))/2
        contrast=np.uint8((gray-baseline[:,None]>35)&(roi.max(axis=2)>=100))*255
        contrast[:,:48]=0;contrast[:,91:]=0
        contrast=cv2.morphologyEx(contrast,cv2.MORPH_CLOSE,np.ones((5,3),np.uint8))
        for contour in cv2.findContours(contrast,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
            x,y,w,h=cv2.boundingRect(contour);area=cv2.contourArea(contour)
            if 14<=w<=40 and 14<=h<=48 and 48<=x<=70 and .6<=w/h<=1.7 and area>150:
                balls.append((area,y+h/2,h))
    if not targets or not balls:
        return None
    # Disagreeing rectangles are ambiguous; wait for the next frame.
    targets.sort(reverse=True)
    if len(targets)>1 and abs(targets[0][1]-targets[1][1])>12 and abs(targets[0][0]-targets[1][0])<.15:
        return None
    _, target, height = targets[0]
    _, ball, ball_height = max(balls)
    return {'target':target, 'height':height, 'ball':ball, 'ball_height':ball_height,
            'inside':abs(ball-target)<(height-ball_height)/2+3}


def ui_visible(crop, template):
    # Edge matching tolerates background color through the translucent exit UI.
    score = cv2.minMaxLoc(cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED))[1]
    if score > .80:
        return True
    edge = lambda im: cv2.Canny(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), 70, 150)
    return cv2.minMaxLoc(cv2.matchTemplate(edge(crop), edge(template), cv2.TM_CCOEFF_NORMED))[1] > .72
