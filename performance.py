"""Recent wall-clock throughput and time by phase, sampled by the supervisor."""
import collections
import time
from metrics import read, write


def phase(supervisor, worker):
    if supervisor == 'paused_focus': return 'focus_wait'
    if supervisor != 'fishing': return 'recovery'
    return {'tracking':'minigame','waiting_marker':'minigame','waiting':'bite_wait','casting':'casting','cast_press':'casting','equipping':'casting','equip_wait':'casting',
            'assist_waiting':'manual_wait','select_spot':'manual_wait','spot_paused':'manual_wait','waiting_rod':'manual_wait','spot_blocked':'manual_wait','spot_attention':'manual_wait','checking_spot':'pickup',
            'pickup_wait':'pickup','pickup':'pickup','pickup_retry_wait':'pickup','inventory':'inventory',
            'cooldown':'cooldown'}.get(worker.get('stage'), 'starting')


class PerformanceRecorder:
    def __init__(self, started):
        self.started = started
        old = read('performance.json')
        self.samples = collections.deque(old.get('samples',[]) if old.get('started') == started else [], maxlen=361)
        self.last = None
        self.phases = collections.Counter()
        self.next_write = 0

    def tick(self, stage, worker, totals, now=None):
        now = time.time() if now is None else now
        current = phase(stage,worker)
        if self.last is not None:
            # Never turn time between supervisor instances into fishing time.
            self.phases[self.previous] += max(0,min(10,now-self.last))
        self.last, self.previous = now,current
        if now < self.next_write: return
        self.next_write = now+5
        self.samples.append({'at':now,'hooks':totals.get('rounds',0),'collections':totals.get('rewards',0),
                             'phase_seconds':dict(self.phases)})
        self.phases.clear()
        write('performance.json',{'started':self.started,'updated':now,'samples':list(self.samples)})


def recent(journal, now=None, seconds=900):
    now = time.time() if now is None else now
    saved = read('performance.json')
    if saved.get('started') != journal.started: return None
    samples = [s for s in saved.get('samples',[]) if now-seconds <= s['at'] <= now]
    if len(samples)<2: return None
    start, end = samples[0]['at'],samples[-1]['at']
    elapsed = end-start
    if elapsed<=0: return None
    phases = collections.Counter()
    for sample in samples[1:]: phases.update(sample.get('phase_seconds',{}))
    items = sum(r['quantity'] for r in journal.items if start < r['at'] <= end)
    return {'window_seconds':round(elapsed,1),'fresh':now-end<15,
            'hooks_per_minute':round(max(0,samples[-1]['hooks']-samples[0]['hooks'])*60/elapsed,2),
            'items_per_minute':round(items*60/elapsed,2),
            'phase_seconds':{k:round(v,1) for k,v in phases.items()},
            'recovery_seconds':round(phases['recovery'],1)}
