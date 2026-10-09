"""Client-relative world pixels plus uniformly scaled, anchored UI crops."""
import cv2
import numpy as np
import mss
import time
from mss.exception import ScreenShotError
from faults import FishingFault


class ScreenSpace:
    width, height = 2560, 1440

    def __init__(self, rect):
        self.rect = tuple(rect)
        l,t,r,b = rect
        self.actual_width, self.actual_height = r-l, b-t
        if self.actual_width < 960 or self.actual_height < 540:
            raise ValueError('Roblox client is too small for reliable vision; use at least 960 x 540 client pixels')
        self.sx, self.sy = self.actual_width/self.width, self.actual_height/self.height
        self.ui_scale = min(self.sx, self.sy)

    def point(self, x, y):
        return round(self.rect[0]+x*self.sx), round(self.rect[1]+y*self.sy)

    def unpoint(self, x, y):
        return (x-self.rect[0])/self.sx, (y-self.rect[1])/self.sy

    def capture_ui(self, sct, box):
        """Keep UI marker shape at its fractional client anchor on any aspect.

        Separate marker and Exit-template checks must agree before reeling.
        Coordinates alone never authorize input on an unfamiliar game layout.
        """
        return self.capture(sct, box, uniform=True)

    def capture(self, sct, box=None, uniform=False):
        x,y,w,h = box or (0,0,self.width,self.height)
        if uniform:
            cx,cy = self.point(x+w/2,y+h/2)
            left,top = round(cx-w*self.ui_scale/2),round(cy-h*self.ui_scale/2)
            right,bottom = round(cx+w*self.ui_scale/2),round(cy+h*self.ui_scale/2)
        else:
            left,top = self.point(x,y)
            right,bottom = self.point(x+w,y+h)
        if not (self.rect[0]<=left<right<=self.rect[2] and self.rect[1]<=top<bottom<=self.rect[3]):
            raise ValueError('Vision crop is outside the current Roblox client')
        region={'left':left,'top':top,'width':right-left,'height':bottom-top}
        try:shot=sct.grab(region)
        except ScreenShotError as original:
            # Rebuild stale GDI handles after a display/client transition.
            # This does not power on a monitor or inject game input.
            shot=None
            for delay in (.03,.08):
                time.sleep(delay)
                try:
                    with mss.MSS() as fresh:shot=fresh.grab(region)
                    break
                except ScreenShotError:continue
            if shot is None:raise FishingFault('capture_unavailable','Roblox screen capture unavailable; input released, local retry required',error=str(original)) from original
        frame=np.array(shot)[:,:,:3]
        return frame if frame.shape[:2]==(h,w) else cv2.resize(frame,(w,h),interpolation=cv2.INTER_LINEAR)
