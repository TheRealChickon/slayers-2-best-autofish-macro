import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import inventory_watch as inventory


def word(text,x):
    return ([[x,0],[x+20,0],[x+20,12],[x,12]],text,.99)


class InventorySearchEvidenceTests(unittest.TestCase):
    def scanner(self,readings):
        scanner=object.__new__(inventory.InventoryScanner)
        scanner.driver=Mock();scanner.driver.deadline=None
        scanner.driver.text.side_effect=readings
        scanner.event=Mock();scanner.progress=Mock();scanner.close=Mock();scanner.read_name=Mock()
        return scanner

    def test_split_placeholder_uses_screen_order_without_a_second_read(self):
        scanner=self.scanner([[word('here!',140),word('Item name',20)]])
        scanner.confirm_empty_search(np.zeros((1440,2560,3),np.uint8))
        self.assertEqual(scanner.driver.text.call_count,1)
        scanner.event.assert_not_called();scanner.driver.capture.assert_not_called()

    def test_partial_live_read_gets_one_larger_retry(self):
        scanner=self.scanner([[word('Item name',20)],[word('here!',280),word('Item name',40)]])
        scanner.confirm_empty_search(np.zeros((1440,2560,3),np.uint8))
        sizes=[call.args[0].shape for call in scanner.driver.text.call_args_list]
        self.assertEqual(sizes,[(83,330,3),(166,660,3)])
        self.assertEqual(len(scanner.search_evidence['readings']),2)
        scanner.driver.key.assert_not_called();scanner.driver.click.assert_not_called()

    def test_query_and_unclear_placeholder_stay_rejected_with_evidence(self):
        for text in ('Coral','Item name here! Coral','Item name',''):
            with self.subTest(text=text),tempfile.TemporaryDirectory() as folder:
                rows=[word(text,20)] if text else []
                scanner=self.scanner([rows,rows])
                with patch.object(inventory,'RUN',Path(folder)),patch.object(inventory,'write') as write:
                    with self.assertRaisesRegex(ValueError,'unreadable or filtered'):
                        scanner.confirm_empty_search(np.zeros((1440,2560,3),np.uint8))
                details=write.call_args.args[1]
                self.assertEqual(details['reason'],'empty_search_unconfirmed')
                self.assertEqual(len(details['search']['readings']),2)
                self.assertTrue(details['frame_saved']);self.assertTrue((Path(folder)/details['frame']).exists())
                scanner.driver.capture.assert_not_called();scanner.driver.key.assert_not_called();scanner.driver.click.assert_not_called()

    def test_diagnostic_storage_failure_does_not_replace_the_bounded_warning(self):
        scanner=self.scanner([[],[]])
        with patch.object(inventory.cv2,'imwrite',side_effect=OSError('diagnostics unavailable')):
            with self.assertRaisesRegex(ValueError,'unreadable or filtered'):
                scanner.confirm_empty_search(np.zeros((1440,2560,3),np.uint8))

    def test_unclear_search_closes_scan_and_restores_deadline_without_item_reads(self):
        scanner=self.scanner([[],[]]);scanner.driver.deadline=123
        scanner.open=lambda:scanner.confirm_empty_search(np.zeros((1440,2560,3),np.uint8))
        with tempfile.TemporaryDirectory() as folder,patch.object(inventory,'RUN',Path(folder)),patch.object(inventory,'write'):
            with self.assertRaisesRegex(ValueError,'unreadable or filtered'):scanner.scan()
        scanner.close.assert_called_once();scanner.read_name.assert_not_called()
        self.assertEqual(scanner.driver.deadline,123)


if __name__=='__main__':unittest.main()
