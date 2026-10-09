import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prompt_ocr import read_cached_prompt


def row(text,score,x):
    return [[[x,10],[x+20,10],[x+20,30],[x,30]],text,score]


class PromptOCRTests(unittest.TestCase):
    def test_two_strong_prompt_cues_skip_the_large_detector(self):
        rows=[row('T',.99,10),row('Collect',.99,50)]
        normal=Mock();fast=Mock(return_value=(rows,None));guard=Mock()
        result,used=read_cached_prompt('image',normal,fast,guard=guard)
        self.assertIs(result,rows);self.assertTrue(used)
        normal.assert_not_called();guard.assert_called_once()

    def test_weak_ambiguous_empty_and_rewards_use_normal_fallback(self):
        for rows in ([],[row('Collect',.91,50)],[row('Golden Fish X1',.99,50)],
                     [row('T',.99,10),row('Collect',.99,50),row('Wall Climb',.99,80)]):
            with self.subTest(rows=rows):
                normal=Mock(return_value=([],None));fast=Mock(return_value=(rows,None));guard=Mock()
                result,used=read_cached_prompt('image',normal,fast,True,guard)
                self.assertFalse(used);normal.assert_called_once_with('image',use_cls=False)
                self.assertEqual(guard.call_count,2)

    def test_human_or_geometry_interruption_aborts_before_fallback(self):
        normal=Mock();fast=Mock(return_value=([],None))
        with self.assertRaises(RuntimeError):
            read_cached_prompt('image',normal,fast,guard=Mock(side_effect=RuntimeError('human activity')))
        normal.assert_not_called()


if __name__=='__main__':unittest.main()
