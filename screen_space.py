"""Map the game's 16:9 client area to a stable vision coordinate system."""
import cv2
import numpy as np
import mss
import time
from mss.exception import ScreenShotError
from faults import FishingFault


ASPECT = 16/9
# Maximized 1440p/1080p windows lose client pixels to the title bar and taskbar
# (2560 x 1369 is 6% wider than 16:9). Those clients work; wider differences
# stretch the game's UI too far for the fixed vision boxes.
ASPECT_TOLERANCE = .08
MIN_SIZE = (960, 540)


def client_problem(width, height):
    """Why a Roblox client of this size cannot be read, or None when it can."""
    if width < MIN_SIZE[0] or height < MIN_SIZE[1]:
        return (f'Roblox is {width} × {height}, smaller than the {MIN_SIZE[0]} × {MIN_SIZE[1]} minimum. '
                'Make the Roblox window bigger, or press F11 for fullscreen.')
    if abs(width-height*ASPECT) > width*ASPECT_TOLERANCE:
        return (f'Roblox is {width} × {height}, which is not a 16:9 shape. Autofish resizes the window to 16:9 '
                'by itself; if that did not work, un-maximize Roblox (or press F11 to leave fullscreen) and start again.')
    return None


class ScreenSpace:
    width, height = 2560, 1440

    def __init__(self, rect):
        self.rect = tuple(rect)
        l,t,r,b = rect
        self.actual_width, self.actual_height = r-l, b-t
        problem = client_problem(self.actual_width, self.actual_height)
        if problem:
            raise ValueError(problem)
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
