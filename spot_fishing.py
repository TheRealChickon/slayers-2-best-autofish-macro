"""Bounded local fishing cycle; no navigation, inventory, or reconnect actions."""
from pickup_policy import Pickup


class SpotCycle:
    def __init__(self, emit):
        self.emit = emit
        self.armed = False
        self.paused = True
        self.stage = 'select_spot'
        self.since = 0
        self.casts = self.rewards = self.misses = self.tries = 0
        self.last_reward = ''
        self.pending_reward = False
        self.recorded = False
        self.recheck_wait = 1.2
        self.not_before_cast = 0
        self.empty_since = None
        self.collect_seen = None

    def arm(self, now):
        if self.stage in ('tracking', 'pickup', 'cast_press'):
            self.emit('spot_rejected', message='Finish this cast before restarting.')
            return False
        self.armed = True
        self.paused = False
        self.misses = self.tries = 0
        self.recheck_wait = 1.2
        self.stage, self.since = 'checking_spot', now
        self.emit('spot_selected', message='Fishing ready; keeping your mouse and camera as they are.')
        return True

    def toggle(self, now):
        if self.armed and not self.paused and self.stage != 'spot_attention':
            self.paused = True
            self.emit('spot_paused', message='Paused with F8; press F8 to resume.')
        else:
            if not self.armed or self.stage == 'spot_attention':
                self.arm(now)
            else:
                self.resume(now)
            self.paused = False
            self.emit('spot_resumed', message='F8 enabled fishing; checking the scene.')
        return not self.paused

    def resume(self, now):
        # Re-observe before a new press; never complete an interrupted cast/T
        # hold using stale timing or a prompt seen before focus was lost.
        self.recheck_wait = (30 if self.stage=='cast_press' else
                             max(1.2,30-(now-self.since)) if self.stage=='waiting' else
                             max(1.2,self.recheck_wait-(now-self.since)) if self.stage=='checking_spot' else 1.2)
        self.stage = 'checking_spot' if self.armed else 'select_spot'
        self.since = now
        self.tries = 0
        self.empty_since = None
        self.collect_seen = None

    def tracking(self, now):
        if self.stage != 'tracking':
            self.stage, self.since = 'tracking', now
            self.pending_reward = True
            self.recorded = False
            self.misses = self.tries = 0
            self.recheck_wait = 1.2
            self.not_before_cast = 0
            self.empty_since = None

    def cancel_unstarted_press(self, now):
        self.stage, self.since = 'checking_spot', now
        self.recheck_wait = 1.2
        self.not_before_cast = now+1.2

    def ended(self, now):
        if self.stage == 'tracking':
            self.stage, self.since = 'pickup_wait', now
            self.emit('minigame_ended', percent=None)

    def step(self, now, evidence=None, stable=False, world=False, equipped=False):
        """Return one explicit action. All time is foreground active time."""
        evidence = evidence or Pickup('empty')
        elapsed = now-self.since
        if not self.armed or self.paused:
            return 'release'
        if not world or not stable or evidence.kind!='empty':
            self.empty_since=None
        elif self.empty_since is None:
            self.empty_since=now
        if stable and evidence.kind=='collect':self.collect_seen=now
        if not world:
            if self.stage != 'spot_blocked':
                self.emit('spot_blocked', message='Waiting for the fishing scene; no rejoin will be attempted.')
            self.stage, self.since = 'spot_blocked', now
            return 'release'
        if self.stage == 'spot_blocked':
            self.resume(now)
            return 'release'
        if evidence.kind in ('other', 'ambiguous'):
            self.stage, self.since = 'checking_spot', now
            return 'release'
        if self.stage == 'spot_attention':
            return 'release'  # F8 rearms after bounded retries.
        if stable and evidence.kind == 'reward' and self.pending_reward and not self.recorded:
            # Avoid interpreting a quantity-shaped prompt as a completed hold.
            if self.stage != 'pickup' or elapsed >= 1.8:
                self.rewards += 1
                self.last_reward = evidence.text
                self.recorded = True
                self.pending_reward = False
                self.emit('reward_observed', text=evidence.text, reward_id=f'spot:{self.casts}:{self.rewards}')
                self.stage, self.since = 'cooldown', now
                return 'release'
        if self.stage == 'cast_press':
            if elapsed >= .16:
                self.casts += 1
                self.emit('cast', cast=self.casts)
                self.stage, self.since = 'waiting', now
                return 'release'
            return 'hold'
        if self.stage == 'waiting':
            if elapsed > 30:
                self.misses += 1
                self.emit('no_minigame', count=self.misses)
                self.stage = 'spot_attention' if self.misses >= 3 else 'checking_spot'
                self.since = now
            return 'release'
        if self.stage == 'pickup':
            # A confirmed hold can survive one OCR miss, but never keep T
            # pressed after its prompt has disappeared for multiple scans.
            if elapsed >= 4 or (evidence.kind=='empty' and
                                (self.collect_seen is None or now-self.collect_seen>.8)):
                self.stage, self.since = 'pickup_wait', now
                return 'release'
            return 'collect'
        if self.stage == 'cooldown':
            if elapsed > 1:
                self.stage, self.since = 'checking_spot', now
            return 'release'
        if self.stage in ('checking_spot', 'pickup_wait'):
            if stable and evidence.kind == 'collect' and elapsed > .35:
                if self.tries >= 3:
                    self.stage = 'spot_attention'
                    self.emit('pickup_exhausted', message='Pickup still visible after three attempts. Check the spot, then press F8.')
                    return 'release'
                self.tries += 1
                self.pending_reward = True
                self.stage, self.since = 'pickup', now
                self.emit('pickup_hold', attempt=self.tries)
                return 'collect'
            wait = max(4 if self.pending_reward else 1.2,self.recheck_wait)
            if elapsed > wait and stable and evidence.kind == 'empty':
                if now<self.not_before_cast:
                    return 'release'
                if self.pending_reward and (self.empty_since is None or now-self.empty_since<6):
                    return 'release'
                if not equipped:
                    return 'release'  # Player equips the rod; never click the hotbar.
                if self.pending_reward:
                    self.emit('empty_round', message='No reward prompt after repeated scans; continuing.')
                self.pending_reward = False
                self.recorded = False
                self.tries = 0
                self.recheck_wait = 1.2
                self.stage, self.since = 'cast_press', now
                self.not_before_cast = now+30
                return 'cast'
        return 'release'
