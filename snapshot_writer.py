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

    def save(self,frame,archive,latest,defer=False):
        # Keep one owned frame at most, and preserve archive/latest ordering.
        self.wait()
        if defer:
            self.pending=self.executor.submit(self.write,frame.copy(),archive,latest)
        else:self.write(frame,archive,latest)

    def __exit__(self,kind,value,traceback):
        try:self.wait()
        finally:self.executor.shutdown(wait=True)
