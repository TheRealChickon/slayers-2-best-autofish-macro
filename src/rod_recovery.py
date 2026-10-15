"""A vision fault stays recoverable, with bounded rejoins and released input."""


class RodRecovery:
    def __init__(self):
        self.failures=0
        self.last_rejoin=-float('inf')

    def progress(self):
        self.failures=0

    def choose(self,now,here=False):
        self.failures+=1
        if self.failures<=2:return 'local',3
        # Full farmer may restore its saved spawn. Farm here must retain
        # its server until recover() actually observes a disconnect.
        if not here and now-self.last_rejoin>=600:
            self.last_rejoin=now
            return 'rejoin',3
        return 'wait',min(60,10*self.failures)
