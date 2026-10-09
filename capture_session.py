"""Own and replace invalid GDI resources without restarting the game."""
import time
import mss
import numpy as np
from mss.exception import ScreenShotError
from faults import FishingFault


class CaptureSession:
    def __init__(self, event=lambda *args, **kw: None):
        self.source = mss.MSS()
        self.event = event
        self.resets = 0
        self.last_error = ''
        self.blank_color = None
        self.closed = False

    def check_open(self):
        # In particular, diagnostics must not recreate a closed context.
        if self.closed:
            raise FishingFault('capture_unavailable',
                               'Capture session is closed; no new capture attempted',
                               capture_closed=True)

    def reset(self):
        self.check_open()
        try:
            self.source.close()
        except ScreenShotError:
            pass
        self.source = mss.MSS()
        self.resets += 1

    def grab(self, region):
        self.check_open()
        failures = []
        for attempt in range(3):
            try:
                self.blank_color = None
                shot = self.source.grab(region)
                if region['width'] >= 960 and region['height'] >= 540:
                    sample = np.asarray(shot)[::24, ::24, :3]
                    self.blank_color = (
                        'white' if sample.size and np.all(sample >= 250, axis=2).mean() > .995 else
                        'black' if sample.size and np.all(sample <= 2, axis=2).mean() > .995 else None)
                    if self.blank_color:
                        raise ScreenShotError('Blank game capture; no reliable visual state')
                return shot
            except ScreenShotError as error:
                self.last_error = str(error)
                failure = {'attempt': attempt + 1, 'message': self.last_error,
                           'blank_color': self.blank_color, 'region': dict(region)}
                # Keep useful MSS metadata, not native handle arguments.
                details = getattr(error, 'details', {})
                if isinstance(details, dict):
                    if isinstance(details.get('func'), str):
                        failure['capture_api'] = details['func']
                    if isinstance(details.get('error_code'), int):
                        failure['capture_error_code'] = details['error_code']
                failures.append(failure)
                if attempt == 2:
                    raise FishingFault('capture_unavailable',
                                       'Game capture unavailable; waiting locally with input released',
                                       capture_error=self.last_error, resets=self.resets,
                                       blank_color=self.blank_color, capture_attempts=failures) from error
                self.reset()
                self.event('capture_reset', resets=self.resets, **failure)
                time.sleep(.03)

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.source.close()
        except ScreenShotError:
            pass

    def __enter__(self):
        self.check_open()
        return self

    def __exit__(self, *args):
        self.close()
