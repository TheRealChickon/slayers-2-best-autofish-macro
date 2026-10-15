import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from minigame_result import percent_value,read_percent


def rows(text,score=.99):return [(None,text,score)]


class MinigameResultTests(unittest.TestCase):
    def test_clipped_leading_zero_text_is_not_a_failed_round(self):
        for text in ('00%','050%','0100%','101%','-1%','100% 0%','10O%'):
            self.assertIsNone(percent_value(rows(text)))
        for text,value in (('0%',0),('9%',9),('50%',50),('99%',99),('100%',100)):
            self.assertEqual(percent_value(rows(text)),value)

    def test_weak_or_multiple_result_candidates_are_unknown(self):
        self.assertIsNone(percent_value(rows('0%',.84)))
        self.assertIsNone(percent_value(rows('0%')+rows('100%')))

    def test_confirmed_success_uses_one_scan_and_yields_to_manual_guard(self):
        ocr=Mock(return_value=(rows('100%'),None));guard=Mock()
        result,evidence=read_percent(np.zeros((1440,2560,3),np.uint8),ocr,guard)
        self.assertEqual(result,100);self.assertEqual(len(evidence),1)
        ocr.assert_called_once();guard.assert_called_once()
        guard.side_effect=RuntimeError('Stopped by user')
        with self.assertRaisesRegex(RuntimeError,'Stopped by user'):
            read_percent(np.zeros((1440,2560,3),np.uint8),ocr,guard)

    def test_failure_needs_matching_independent_scale_readings(self):
        frame=np.zeros((1440,2560,3),np.uint8)
        for second,expected in (('0%',0),('100%',None),('00%',None)):
            ocr=Mock(side_effect=[(rows('0%'),None),(rows(second),None)])
            result,evidence=read_percent(frame,ocr)
            self.assertEqual(result,expected);self.assertEqual(len(evidence),2)
            self.assertNotEqual(ocr.call_args_list[0].args[0].shape,ocr.call_args_list[1].args[0].shape)


if __name__=='__main__':unittest.main()
