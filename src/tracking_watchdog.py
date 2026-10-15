"""Detect a frozen minigame from marker motion, not just elapsed round time."""


class TrackingWatchdog:
    def __init__(self, frozen_seconds=12):
        self.frozen_seconds = frozen_seconds
        self.reset()

    def reset(self):
        self.signature = None
        self.changed_at = None

    def observe(self, detection, now):
        if detection is None:
            self.reset()
            return False
        signature = tuple(detection[k] for k in ('ball', 'target', 'height', 'ball_height'))
        if self.signature is None or any(abs(a-b) > .75 for a,b in zip(signature,self.signature)):
            self.signature, self.changed_at = signature, now
        return now-self.changed_at >= self.frozen_seconds
