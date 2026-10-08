"""Bound display-surface refreshes; never treat missing pixels as a disconnect."""
class DisplayRepair:
    def __init__(self):
        self.failed_at=None
        self.attempts=[]

    def allowed(self,now,white,enabled,physical_idle,foreground,manual,ownership_idle):
        if not white:
            self.failed_at=None
            return False
        if self.failed_at is None:self.failed_at=now
        self.attempts=[at for at in self.attempts if now-at<5400]
        return (enabled and not manual and foreground and physical_idle>=45 and ownership_idle
                and now-self.failed_at>=10 and len(self.attempts)<2
                and (not self.attempts or now-self.attempts[-1]>=60))

    def attempted(self,now):self.attempts.append(now)
    def progress(self):self.failed_at=None
