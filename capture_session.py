"""Own and replace invalid GDI resources without restarting the game."""
import time
import mss
import numpy as np
from mss.exception import ScreenShotError
from faults import FishingFault


class CaptureSession:
    def __init__(self,event=lambda *args,**kw:None):
        self.source=mss.MSS();self.event=event;self.resets=0;self.last_error='';self.blank_color=None

    def reset(self):
        try:self.source.close()
        except ScreenShotError:pass
        self.source=mss.MSS();self.resets+=1

    def grab(self,region):
        for attempt in range(3):
            try:
                self.blank_color=None
                shot=self.source.grab(region)
                if region['width']>=960 and region['height']>=540:
                    sample=np.asarray(shot)[::24,::24,:3]
                    self.blank_color=('white' if sample.size and np.all(sample>=250,axis=2).mean()>.995 else
                                      'black' if sample.size and np.all(sample<=2,axis=2).mean()>.995 else None)
                    if self.blank_color:
                        raise ScreenShotError('Blank game capture; no reliable visual state')
                return shot
            except ScreenShotError as error:
                self.last_error=str(error)
                if attempt==2:raise FishingFault('capture_unavailable','Game capture unavailable; waiting locally with input released',capture_error=self.last_error,resets=self.resets,blank_color=self.blank_color) from error
                self.reset();self.event('capture_reset',message=self.last_error,resets=self.resets)
                time.sleep(.03)

    def close(self):
        try:self.source.close()
        except ScreenShotError:pass

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
