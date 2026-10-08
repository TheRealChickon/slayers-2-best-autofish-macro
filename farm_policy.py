"""Keep in-place farming local unless there is positive disconnect evidence."""


def startup_rejoin(mode,requested=True):
    return mode!='here' and requested


class HereRecovery:
    def __init__(self):self.attempts=0
    def choose(self,code):
        if code in ('manual_stop','session_limit','user_required','unstable_fishing_position'):return 'stop'
        if code=='focus':return 'wait_focus'
        if code in ('disconnect','client_lost'):
            self.attempts=0;return 'rejoin'
        self.attempts+=1
        return 'local' if self.attempts<=3 else 'attention'

    def progress(self):self.attempts=0
