"""Bounded local evidence for failed input/vision/recovery decisions."""
import collections
import json
import time
from pathlib import Path
import cv2


class FishingFault(RuntimeError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def reason_code(reason):
    text = reason.lower()
    for word, code in (('stopped by', 'manual_stop'), ('session_limit', 'session_limit'),
                       ('lost focus', 'focus'), ('moved or resized', 'window'), ('window changed', 'window'),
                       ('disconnect', 'disconnect'), ('presence', 'disconnect'), ('non-fishing', 'pickup_other'),
                       ('pickup prompt', 'pickup_timeout'), ('three casts', 'no_minigame'),
                       ('marker detection', 'tracking_lost'), ('alignment', 'alignment')):
        if word in text: return code
    return 'unexpected'


class FaultRecorder:
    def __init__(self, root, session):
        self.root, self.session = Path(root)/'diagnostics', session
        self.frames = collections.deque(maxlen=4)

    def observe(self, frame, stage):
        small = cv2.resize(frame, (1280,720))
        ok, data = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY,65])
        if ok: self.frames.append((time.time(),stage,data.tobytes()))

    def save(self, code, message, **details):
        self.root.mkdir(parents=True, exist_ok=True)
        manifest = self.root/'index.json'
        try: history = json.loads(manifest.read_text())
        except (OSError, ValueError): history = []
        sequence = max((r.get('sequence',0) for r in history), default=0)+1
        slot = sequence % 8
        frames = []
        for i, (at,stage,data) in enumerate(self.frames):
            name = f'fault-{slot}-{i}.jpg'
            (self.root/name).write_bytes(data)
            frames.append({'at':at,'stage':stage,'file':name})
        row = {'sequence':sequence,'at':time.time(),'session':self.session,'code':code,
               'message':message,'details':details,'frames':frames}
        history = [r for r in history if r['sequence']%8 != slot]+[row]
        temporary = manifest.with_suffix('.tmp')
        temporary.write_text(json.dumps(history[-8:], indent=2)); temporary.replace(manifest)
        return row


class RecoveryPolicy:
    """One local repair per two minutes; persistent trouble escalates to rejoin."""
    LOCAL = {'pickup_other','pickup_timeout','no_minigame','tracking_lost','window','alignment_drift'}

    def __init__(self): self.last_local = -float('inf')

    def choose(self, code, now, reference_ready):
        if code in ('manual_stop','session_limit'): return 'stop'
        if code == 'focus': return 'wait_focus'
        if code in self.LOCAL and (reference_ready or code in ('window','no_minigame')) and now-self.last_local >= 120:
            self.last_local = now
            return 'local'
        return 'rejoin'
