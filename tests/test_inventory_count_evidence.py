import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import inventory_watch as inventory


class InventoryCountEvidenceTests(unittest.TestCase):
    def scanner(self,frame,text):
        scanner=object.__new__(inventory.InventoryScanner)
        scanner.driver=Mock();scanner.driver.deadline=None
        scanner.driver.text.return_value=[] if text is None else [(None,text,.99)]
        scanner.progress=Mock();scanner.event=Mock();scanner.close=Mock()
        scanner.open=Mock(return_value=frame);scanner.read_name=Mock()
        return scanner

    def test_rejected_count_records_existing_frame_without_scanning_items(self):
        frame=np.full((1440,2560,3),80,np.uint8)
        for text,total,reason in [('All (187)',187,'outside_first_page_limit'),(None,None,'unreadable_header')]:
            with self.subTest(text=text),tempfile.TemporaryDirectory() as folder:
                scanner=self.scanner(frame,text)
                with patch.object(inventory,'RUN',Path(folder)),patch.object(inventory,'write') as write:
                    with self.assertRaisesRegex(ValueError,'not fully visible'):scanner.scan()
                details=write.call_args.args[1]
                self.assertEqual(details['parsed_total'],total);self.assertEqual(details['reason'],reason)
                self.assertTrue(details['frame_saved']);self.assertTrue((Path(folder)/details['frame']).exists())
                scanner.read_name.assert_not_called();scanner.driver.capture.assert_not_called()
                scanner.open.assert_called_once();scanner.close.assert_called_once()
                self.assertIsNone(scanner.driver.deadline)

    def test_diagnostic_write_failure_retains_bounded_warning_and_menu_close(self):
        scanner=self.scanner(np.zeros((1440,2560,3),np.uint8),'All (187)')
        with patch.object(inventory.cv2,'imwrite',side_effect=OSError('diagnostic storage unavailable')):
            with self.assertRaisesRegex(ValueError,'not fully visible'):scanner.scan()
        scanner.close.assert_called_once();scanner.read_name.assert_not_called()
        self.assertIsNone(scanner.driver.deadline)


if __name__=='__main__':unittest.main()
