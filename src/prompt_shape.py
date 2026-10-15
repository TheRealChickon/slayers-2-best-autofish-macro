"""Find the white T key disc of a ProximityPrompt without OCR.

The disc is a fixed-size BillboardGui element, so a threshold and a connected
component pass locate it in a few milliseconds. OCR remains the authority for
what the prompt says; this module only reports where a key disc is, which lets
the worker follow an airborne drop and notice the prompt vanishing between the
much slower OCR passes.
"""
import math
import cv2
import numpy as np

# Measured at 2560 x 1440: a 54 px disc with a dark T, filling ~71% of its box.
REFERENCE_DIAMETER = 54
REFERENCE_HEIGHT = 1440


def find_discs(image, client_height=REFERENCE_HEIGHT, step=2):
    """Return disc centres (x, y) in the image's own pixel coordinates."""
    small = image[::step, ::step]
    gray = cv2.cvtColor(small, cv2.COLOR_BGRA2GRAY if small.shape[2] == 4 else cv2.COLOR_BGR2GRAY)
    mask = (gray > 215).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    expected = REFERENCE_DIAMETER*client_height/REFERENCE_HEIGHT/step
    found = []
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if not (.55*expected <= w <= 1.3*expected and .55*expected <= h <= 1.3*expected):
            continue
        if abs(int(w)-int(h)) > max(3, .12*expected):
            continue
        fill = area/float(w*h)
        if not .45 <= fill <= .82:
            continue
        # The key letter leaves a dark stem through the middle of the disc.
        cx, cy = x+w//2, y+h//2
        core = labels[cy-1:cy+2, cx-1:cx+2]
        if (core == index).mean() > .5:
            continue
        found.append(((x+w/2)*step, (y+h/2)*step))
    return found


class DiscTrack:
    """Follow one disc between frames; report motion, settling and absence."""

    def __init__(self, settle_seconds=.10, settle_pixels=4.0):
        self.settle_seconds = settle_seconds
        self.settle_pixels = settle_pixels
        self.reset()

    def reset(self, near=None):
        self.position = None
        self.anchor = None
        self.anchor_at = None
        self.seen_at = None
        self.missing_since = None
        self.near = near

    def observe(self, discs, now):
        reference = self.position or self.near
        if discs:
            disc = (min(discs, key=lambda d: math.dist(d, reference)) if reference is not None
                    else discs[0])
            if reference is not None and self.position is None and math.dist(disc, reference) > 260:
                disc = None
        else:
            disc = None
        if disc is None:
            if self.missing_since is None:
                self.missing_since = now
            return None
        self.missing_since = None
        self.position = disc
        self.seen_at = now
        if self.anchor is None or math.dist(disc, self.anchor) > self.settle_pixels:
            self.anchor, self.anchor_at = disc, now
        return disc

    def settled(self, now):
        return (self.anchor_at is not None and self.missing_since is None
                and now-self.anchor_at >= self.settle_seconds)

    def missing_for(self, now):
        return 0. if self.missing_since is None else now-self.missing_since
