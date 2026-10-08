"""Map the game's 16:9 client area to a stable vision coordinate system."""
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
            raise ValueError('Roblox is too small; use a 16:9 game window of at least 960 × 540')
        # A maximized 1440p/1080p window loses client pixels to the title bar
        # and taskbar. Those clients are valid; don't mistake chrome for a
        # different display aspect ratio during reconnect/fullscreen changes.
        if abs(self.actual_width-self.actual_height*16/9) > self.actual_width*.08:
            raise ValueError(f'Unsupported Roblox client {self.actual_width} × {self.actual_height}; use a widescreen window (2560 × 1440 supported)')
        self.sx, self.sy = self.actual_width/self.width, self.actual_height/self.height

    def point(self, x, y):
        return round(self.rect[0]+x*self.sx), round(self.rect[1]+y*self.sy)

    def capture(self, sct, box=None):
        x,y,w,h = box or (0,0,self.width,self.height)
        left,top = self.point(x,y)
        right,bottom = self.point(x+w,y+h)
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
