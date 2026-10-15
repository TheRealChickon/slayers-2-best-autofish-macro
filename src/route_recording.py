"""Local teaching recordings. This module never sends game input or replays a route."""
import datetime
import json
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from discord_hourly import atomic_json


def video_frame(frame, size=(1280, 720)):
    height, width = frame.shape[:2]
    scale = min(size[0] / width, size[1] / height)
    fitted = (round(width * scale), round(height * scale))
    left, top = (size[0] - fitted[0]) // 2, (size[1] - fitted[1]) // 2
    result = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    result[top:top + fitted[1], left:left + fitted[0]] = cv2.resize(frame, fitted)
    return result, [left, top, *fitted]


class RouteSession:
    """An explicit recording timeline, with focus gaps and balanced input holds."""

    def __init__(self, root, target, rect, frame, clock=time.monotonic, fps=15):
        self.clock, self.fps = clock, fps
        self.origin = self.segment_started = clock()
        self.active_seconds = 0.0
        self.state = 'recording'
        self.keys, self.buttons = {}, {}
        self.rect = tuple(rect)
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        self.path = Path(root) / 'bait-routes' / (stamp + '-' + uuid.uuid4().hex[:6])
        self.path.mkdir(parents=True)
        (self.path / 'checkpoints').mkdir()
        self.events = (self.path / 'events.jsonl').open('w', encoding='utf-8', buffering=1)
        self.frames = (self.path / 'frames.jsonl').open('w', encoding='utf-8', buffering=1)
        self.writer = None
        self.metadata = {
            'schema_version': 1, 'purpose': 'bait_restock_teaching',
            'started_at': time.time(), 'target': target, 'initial_client_rect': list(rect),
            'return_method': 'manual_reset_to_saved_spawn', 'outbound_via': 'shrine_teleport',
            'state': self.state, 'video_size': [1280, 720], 'video_fps': fps,
            'frame_count': 0, 'input_count': 0, 'checkpoints': [], 'interruptions': [],
            'files': {'events': 'events.jsonl', 'frames': 'frames.jsonl', 'video': 'video.mp4'},
            'timing': 't is active recording seconds; wall_t includes pauses; frames.jsonl maps video frames to observations',
            'mouse': 'cursor positions use native client pixels and normalized coordinates; raw_mouse holds device deltas for camera reconstruction',
            'automation_ready': False,
        }
        try:
            self.writer = cv2.VideoWriter(str(self.path / 'video.mp4'),
                cv2.VideoWriter_fourcc(*'mp4v'), fps, (1280, 720))
            if not self.writer.isOpened():
                raise RuntimeError('Video encoder unavailable; recording could not start')
            self.emit('recording_started')
            self.checkpoint(frame, 'fishing_start')
            self.capture(frame)
            self.save()
        except Exception:
            self.finish(False, 'Recording initialization failed')
            raise

    def elapsed(self, at=None):
        at = self.clock() if at is None else at
        return self.active_seconds + (max(0, at - self.segment_started) if self.state == 'recording' else 0)

    def emit(self, kind, at=None, **details):
        at = self.clock() if at is None else at
        self.events.write(json.dumps({'t': round(self.elapsed(at), 6),
            'wall_t': round(max(0, at - self.origin), 6), 'kind': kind, **details}) + '\n')

    def add_input(self, kind, at=None, **details):
        at = self.clock() if at is None else at
        if self.state != 'recording' or at < self.segment_started:
            return False
        if kind == 'key':
            vk = details['vk']
            if details['down']:
                if vk in self.keys:
                    return False  # Autorepeat is represented by the held key.
                self.keys[vk] = details
            elif self.keys.pop(vk, None) is None:
                return False
        elif kind == 'mouse_button':
            button = details['button']
            if details['down']:
                if button in self.buttons:
                    return False
                self.buttons[button] = details
            elif self.buttons.pop(button, None) is None:
                return False
        if 'desktop_x' in details:
            x, y = details.pop('desktop_x') - self.rect[0], details.pop('desktop_y') - self.rect[1]
            width, height = self.rect[2] - self.rect[0], self.rect[3] - self.rect[1]
            details.update(client_x=x, client_y=y, normalized_x=x / width, normalized_y=y / height)
        self.emit(kind, at, **details)
        self.metadata['input_count'] += 1
        return True

    def release_holds(self):
        # Journal-only releases: no keyboard/mouse injection occurs here.
        for key in list(self.keys.values()):
            self.emit('key', **dict(key, down=False, synthetic=True, reason='recording_boundary'))
        for button in list(self.buttons.values()):
            self.emit('mouse_button', **dict(button, down=False, synthetic=True, reason='recording_boundary'))
        self.keys.clear()
        self.buttons.clear()

    def pause(self, reason):
        if self.state != 'recording':
            return
        self.release_holds()
        self.emit('recording_paused', reason=reason)
        self.active_seconds = self.elapsed()
        self.state = 'paused'
        self.metadata['interruptions'].append({'t': round(self.active_seconds, 6), 'reason': reason})
        self.save()

    def resume(self, rect):
        if self.state != 'paused':
            return
        self.rect = tuple(rect)
        self.segment_started = self.clock()
        self.state = 'recording'
        self.emit('recording_resumed', client_rect=list(rect))
        self.save()

    def checkpoint(self, frame, name=None):
        if self.state != 'recording':
            raise RuntimeError('Resume recording before adding a checkpoint')
        index = len(self.metadata['checkpoints'])
        name = name or f'checkpoint_{index:03d}'
        relative = f'checkpoints/{index:03d}-{name}.png'
        if not cv2.imwrite(str(self.path / relative), frame):
            raise RuntimeError('Could not save the checkpoint image')
        row = {'name': name, 't': round(self.elapsed(), 6), 'image': relative,
               'client_rect': list(self.rect), 'native_size': [frame.shape[1], frame.shape[0]]}
        self.metadata['checkpoints'].append(row)
        self.emit('checkpoint', **row)
        self.save()
        return row

    def capture(self, frame):
        if self.state != 'recording':
            return
        fitted, viewport = video_frame(frame)
        self.writer.write(fitted)
        index = self.metadata['frame_count']
        self.frames.write(json.dumps({'frame': index, 'video_t': index / self.fps,
            't': round(self.elapsed(), 6), 'wall_t': round(self.clock() - self.origin, 6),
            'client_rect': list(self.rect), 'video_viewport': viewport}) + '\n')
        self.metadata['frame_count'] += 1

    def save(self):
        self.metadata.update(state=self.state, active_seconds=round(self.elapsed(), 6),
                             wall_seconds=round(self.clock() - self.origin, 6))
        atomic_json(self.path / 'route.json', self.metadata)

    def finish(self, complete=True, reason='Finished by user'):
        if self.state == 'finished':
            return self.path
        try:
            self.release_holds()
            self.emit('recording_finished', complete=complete, reason=reason)
            self.active_seconds = self.elapsed()
            self.state = 'finished'
            self.metadata.update(complete=complete, finish_reason=reason, ended_at=time.time())
            self.save()
        finally:
            if self.writer is not None:
                self.writer.release()
            self.events.close()
            self.frames.close()
        return self.path
