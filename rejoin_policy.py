"""Conservative signals and retry pacing for a connection-only controller."""


class RejoinPolicy:
    def __init__(self):
        self.absent_since = None
        self.missing_since = None
        self.retry_at = 0.0
        self.failures = 0

    def presence(self, state, now):
        # A failed API request says nothing about the Roblox client.
        if not state.get('ok') or state.get('type') == 2:
            self.absent_since = None
        elif self.absent_since is None:
            self.absent_since = now

    def decide(self, scene, has_window, now):
        if has_window:
            self.missing_since = None
        elif self.missing_since is None:
            self.missing_since = now
        if now < self.retry_at:
            return None
        if scene == 'disconnect':
            return 'recover'
        if scene == 'lobby':
            return 'recover'
        if not has_window:
            return 'launch' if now-self.missing_since >= 45 else None
        if scene == 'world':
            return None
        if (scene in ('other', 'game_menu') and self.absent_since is not None
                and now-self.absent_since >= 90):
            return 'recover'
        return None

    def inspect_background(self, now):
        return self.absent_since is not None and now-self.absent_since >= 90 and now >= self.retry_at

    def failed(self, now):
        self.failures += 1
        self.retry_at = now + min(180, 15 * (2 ** min(self.failures-1, 4)))
        return self.retry_at-now

    def succeeded(self):
        self.failures = 0
        self.retry_at = 0.0
        self.missing_since = None
        self.absent_since = None
