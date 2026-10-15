"""One bounded image writer; capture, input, counters and evidence stay on the worker."""
from concurrent.futures import ThreadPoolExecutor
import cv2


class SnapshotWriter:
    def __init__(self):
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='fishing-image')
        self.pending=None

    def __enter__(self):return self

    def wait(self):
        if self.pending is not None:
            pending=self.pending;self.pending=None
            pending.result()

    @staticmethod
    def write(frame,archive,latest):
        cv2.imwrite(str(archive),frame,[cv2.IMWRITE_JPEG_QUALITY,88])
        cv2.imwrite(str(latest),frame,[cv2.IMWRITE_JPEG_QUALITY,80])

    def write_observed(self,frame,archive,latest,observe):
        if observe is not None:observe(frame)
        self.write(frame,archive,latest)

    def save(self,frame,archive,latest,defer=False,observe=None):
        # Keep one owned frame at most, and preserve archive/latest ordering.
        # An optional evidence encoder shares this serial writer. Callers wait
        # before reading that evidence, so it cannot race a fault report.
        self.wait()
        if defer:
            self.pending=self.executor.submit(self.write_observed,frame.copy(),archive,latest,observe)
        else:self.write_observed(frame,archive,latest,observe)

    def __exit__(self,kind,value,traceback):
        try:self.wait()
        finally:self.executor.shutdown(wait=True)
