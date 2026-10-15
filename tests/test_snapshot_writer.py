import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from snapshot_writer import SnapshotWriter


class SnapshotWriting(unittest.TestCase):
    def test_deferred_writer_owns_pixels_and_preserves_archive_latest_order(self):
        started=threading.Event();release=threading.Event();writes=[]
        original=np.full((8,8,3),17,np.uint8)
        def write(frame,archive,latest):
            started.set();release.wait(2);writes.append((int(frame[0,0,0]),archive,latest))
        with patch.object(SnapshotWriter,'write',side_effect=write),SnapshotWriter() as writer:
            writer.save(original,'first.jpg','latest.jpg',defer=True)
            self.assertTrue(started.wait(1))
            self.assertFalse(writer.pending.done())
            original[:]=99;release.set()
            writer.save(original,'second.jpg','latest.jpg')
        self.assertEqual(writes,[(17,'first.jpg','latest.jpg'),(99,'second.jpg','latest.jpg')])

    def test_one_pending_frame_and_exit_drains_the_last_snapshot(self):
        writes=[]
        with patch.object(SnapshotWriter,'write',side_effect=lambda *args:writes.append(args[1])),SnapshotWriter() as writer:
            writer.save(np.zeros((8,8,3),np.uint8),'one.jpg','latest.jpg',defer=True)
            writer.save(np.zeros((8,8,3),np.uint8),'two.jpg','latest.jpg',defer=True)
        self.assertEqual(writes,['one.jpg','two.jpg'])
        self.assertIsNone(writer.pending)

    def test_deferred_failure_is_reported_at_the_next_barrier(self):
        writer=SnapshotWriter()
        with patch.object(SnapshotWriter,'write',side_effect=OSError('image storage failed')):
            writer.save(np.zeros((8,8,3),np.uint8),'one.jpg','latest.jpg',defer=True)
            with self.assertRaisesRegex(OSError,'image storage failed'):writer.wait()
        writer.__exit__(None,None,None)

    def test_writer_uses_requested_paths_and_existing_jpeg_quality(self):
        frame=np.zeros((8,8,3),np.uint8)
        with patch('snapshot_writer.cv2.imwrite') as save:
            SnapshotWriter.write(frame,Path('archive.jpg'),Path('latest.jpg'))
        self.assertEqual([call.args[0] for call in save.call_args_list],['archive.jpg','latest.jpg'])
        self.assertEqual([call.args[2][-1] for call in save.call_args_list],[88,80])

    def test_slow_evidence_encoding_is_deferred_with_owned_frame_before_image_write(self):
        started=threading.Event();release=threading.Event();calls=[]
        original=np.full((8,8,3),17,np.uint8)
        def observe(frame):
            started.set();release.wait(2);calls.append(('evidence',int(frame[0,0,0])))
        def write(frame,*unused):calls.append(('image',int(frame[0,0,0])))
        with patch.object(SnapshotWriter,'write',side_effect=write),SnapshotWriter() as writer:
            writer.save(original,'receipt.jpg','latest.jpg',defer=True,observe=observe)
            self.assertTrue(started.wait(1))
            self.assertFalse(writer.pending.done())
            self.assertEqual(calls,[])
            original[:]=99;release.set();writer.wait()
        self.assertEqual(calls,[('evidence',17),('image',17)])

    def test_evidence_encoding_failure_reaches_barrier_without_writing_image(self):
        with patch.object(SnapshotWriter,'write') as write,SnapshotWriter() as writer:
            def fail(unused):raise OSError('evidence storage failed')
            writer.save(np.zeros((8,8,3),np.uint8),'receipt.jpg','latest.jpg',defer=True,observe=fail)
            with self.assertRaisesRegex(OSError,'evidence storage failed'):writer.wait()
            write.assert_not_called()


if __name__=='__main__':unittest.main()
