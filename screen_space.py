"""Map the game's 16:9 client area to a stable vision coordinate system."""
import cv2
import numpy as np


class ScreenSpace:
    width, height = 2560, 1440

    def __init__(self, rect):
        self.rect = tuple(rect)
        l,t,r,b = rect
        self.actual_width, self.actual_height = r-l, b-t
        if self.actual_width < 960 or self.actual_height < 540:
            raise ValueError('Roblox is too small; use a 16:9 game window of at least 960 × 540')
        if abs(self.actual_width/self.actual_height - 16/9) > .025:
            raise ValueError('Use a 16:9 Roblox window (for example 1920 × 1080); this window has a different shape')
        self.sx, self.sy = self.actual_width/self.width, self.actual_height/self.height

    def point(self, x, y):
        return round(self.rect[0]+x*self.sx), round(self.rect[1]+y*self.sy)

    def capture(self, sct, box=None):
        x,y,w,h = box or (0,0,self.width,self.height)
        left,top = self.point(x,y)
        right,bottom = self.point(x+w,y+h)
        frame=np.array(sct.grab({'left':left,'top':top,'width':right-left,'height':bottom-top}))[:,:,:3]
        return frame if frame.shape[:2]==(h,w) else cv2.resize(frame,(w,h),interpolation=cv2.INTER_LINEAR)
