"""Local appearance anchors plus forward/backward optical-flow tracking.

References contain only manually verified boss pixels. The caller must also
verify Sanemi's live header; this tracker alone does not establish identity.
"""
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np


@dataclass(frozen=True)
class Target:
    box: tuple
    confidence: float
    source: str

    @property
    def center(self):
        x, y, w, h = self.box
        return x+w/2, y+h/2


class BossTracker:
    def __init__(self, reference_directory, threshold=.72):
        self.templates = []
        for path in sorted(Path(reference_directory).glob('head-*.png')):
            template = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if template is not None and min(template.shape) >= 12 and template.std() > 12:
                self.templates.append(template)
        self.threshold = threshold
        self.previous = self.points = self.target = None
        self.last_anchor = 0.

    def clear(self):
        self.previous = self.points = self.target = None

    @staticmethod
    def gray(frame):
        return cv2.cvtColor(cv2.resize(frame, (1280, 720)), cv2.COLOR_BGR2GRAY)

    def acquire(self, frame, now):
        if not self.templates:
            self.clear()
            return None
        gray = self.gray(frame)
        # Exclude fixed name/health HUD, minimap, hotbar and left-side notices.
        roi = gray[175:600, 100:1230]
        candidates = []
        for template in self.templates:
            for scale in (.55, .75, 1., 1.3, 1.65, 2.):
                size = (round(template.shape[1]*scale), round(template.shape[0]*scale))
                if min(size) < 10 or size[0] > roi.shape[1] or size[1] > roi.shape[0]:
                    continue
                resized = cv2.resize(template, size)
                correlation = cv2.matchTemplate(roi, resized, cv2.TM_CCOEFF_NORMED)
                # Check the second distinct peak too. A single max per scale
                # silently accepts two equally good lookalikes in one frame.
                for _ in range(2):
                    _, score, _, (x, y) = cv2.minMaxLoc(correlation)
                    if score < self.threshold:
                        break
                    candidates.append(Target(((x+100)*2, (y+175)*2, size[0]*2, size[1]*2), score, 'appearance'))
                    correlation[max(0,y-size[1]):y+size[1]+1,
                                max(0,x-size[0]):x+size[0]+1] = -1
        candidates.sort(key=lambda target: target.confidence, reverse=True)
        if not candidates:
            self.clear()
            return None
        best = candidates[0]
        # Similar scores at distinct positions are ambiguous, even if one wins.
        for other in candidates[1:]:
            distance = np.linalg.norm(np.array(best.center)-other.center)
            if other.confidence > best.confidence-.035 and distance > max(best.box[2:]):
                self.clear()
                return None
        self.target = best
        self.last_anchor = now
        self.seed_points(gray)
        return best

    def seed_points(self, gray):
        x, y, w, h = (round(value/2) for value in self.target.box)
        mask = np.zeros_like(gray)
        mask[max(0,y):min(720,y+h),max(0,x):min(1280,x+w)] = 255
        self.points = cv2.goodFeaturesToTrack(gray, maxCorners=35, qualityLevel=.025,
                                             minDistance=3, mask=mask, blockSize=3)
        self.previous = gray

    def from_label(self, frame, label, now, label_height=None):
        """Confirm the distinctive light hair directly below a world name.

        This handles head rotations unseen by the saved appearance anchors.
        The caller has already checked the exact boss header and unique world
        name. Dark player hair, the minimap and the fixed boss portrait cannot
        satisfy this world-space geometry.
        """
        if label is None:
            return None
        lx, ly = label
        scale = max(.25,min(1.5,(label_height or 32)/32))
        x, y = max(0, round(lx-170*scale)), max(350, round(ly+45*scale))
        roi = frame[y:min(1200,y+round(150*scale)), x:min(2560,x+round(340*scale))]
        if min(roi.shape[:2]) < 20:
            return None
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # Fog desaturates grass below the usual saturation threshold. Hair is
        # neutral or blue/pink-lit; reject chromatic green even in bright fog.
        neutral = (hsv[:,:,1] < 25) | (hsv[:,:,0] < 35) | (hsv[:,:,0] > 90)
        mask = ((hsv[:,:,1] < 95) & (hsv[:,:,2] > 100) & neutral).astype('uint8')*255
        # The party widget overlaps left-side targets and can join its white
        # horizontal line to the hair component. Ignore those fixed UI pixels.
        if x < 315 and y < 715:
            mask[max(0,620-y):max(0,715-y),:315-x] = 0
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5,5), 'uint8'))
        count, _, stats, centers = cv2.connectedComponentsWithStats(mask)
        candidates = []
        for n in range(1, count):
            bx, by, w, h, area = stats[n]
            cx, cy = centers[n]
            if (area >= 2200*scale**2 and 85*scale <= w <= 325*scale and 55*scale <= h <= 220*scale+1
                    and abs(x+cx-lx) < 110*scale and by < 140*scale and area/(w*h) > .35):
                head_h = min(h, round(w*.85))
                piece = roi[by:by+head_h,bx:bx+w]
                if cv2.cvtColor(piece,cv2.COLOR_BGR2GRAY).std() < 12:
                    continue
                candidates.append(Target((int(x+bx),int(y+by),int(w),int(head_h)),
                                         min(.94, .8+area/(w*h)*.12), 'name_and_light_hair'))
        if len(candidates) != 1:
            return None
        self.target = candidates[0]
        self.last_anchor = now
        self.seed_points(self.gray(frame))
        return self.target

    def update(self, frame, now, identity_verified=True):
        if not identity_verified:
            self.clear()
            return None
        if self.target is None or self.points is None or len(self.points) < 6 or now-self.last_anchor > .8:
            return self.acquire(frame, now)
        gray = self.gray(frame)
        new, status, _ = cv2.calcOpticalFlowPyrLK(self.previous, gray, self.points, None,
                                                winSize=(25,25), maxLevel=3)
        if new is None:
            return self.acquire(frame, now)
        back, reverse, _ = cv2.calcOpticalFlowPyrLK(gray, self.previous, new, None,
                                                  winSize=(25,25), maxLevel=3)
        if back is None:
            return self.acquire(frame, now)
        good = (status.ravel()==1) & (reverse.ravel()==1) & (np.linalg.norm(back-self.points,axis=2).ravel()<1.5)
        if good.sum() < 6 or good.mean() < .55:
            return self.acquire(frame, now)
        before, after = self.points[good], new[good]
        matrix, inliers = cv2.estimateAffinePartial2D(before, after, method=cv2.RANSAC,
                                                    ransacReprojThreshold=2)
        if matrix is None or inliers.mean() < .7:
            return self.acquire(frame, now)
        scale = np.hypot(matrix[0,0], matrix[0,1])
        if not .8 <= scale <= 1.25:
            return self.acquire(frame, now)
        x,y,w,h = self.target.box
        center = matrix @ np.array([(x+w/2)/2,(y+h/2)/2,1.])
        w,h = w*scale,h*scale
        box = (center[0]*2-w/2,center[1]*2-h/2,w,h)
        if not (200 < center[0]*2 < 2460 and 350 < center[1]*2 < 1200):
            self.clear()
            return None
        self.target = Target(box, self.target.confidence*.98, 'optical_flow')
        self.previous, self.points = gray, after.reshape(-1,1,2)
        return self.target
