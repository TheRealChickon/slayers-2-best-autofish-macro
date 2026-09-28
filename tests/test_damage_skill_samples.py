import unittest
from unittest.mock import Mock
from damage_skill_samples import sample_skill
from damage_view import skill_lines


class SkillSamplesTests(unittest.TestCase):
    def test_waits_for_delayed_damage_and_measures_only_isolated_delta(self):
        inspect = Mock(side_effect=[100, 100, 350, 400, 400])
        perform, wait = Mock(), Mock()
        result = sample_skill(inspect, wait, perform, 20)
        self.assertEqual(result, {'damage': 300, 'before': 100, 'after': 400})
        perform.assert_called_once()
        self.assertIn(((20,), {}), wait.call_args_list)

    def test_changing_baseline_never_casts(self):
        perform = Mock()
        with self.assertRaises(ValueError):
            sample_skill(Mock(side_effect=[100, 101, 102, 103]), Mock(), perform, 15)
        perform.assert_not_called()

    def test_zero_damage_is_not_published_as_a_successful_sample(self):
        with self.assertRaises(ValueError):
            sample_skill(Mock(return_value=100), Mock(), Mock(), 15)

    def test_combined_ultimate_is_labeled_and_unknowns_are_explicit(self):
        lines = skill_lines({'skill_samples': {'ultimate': {'damage': 1234, 'at': 1000}}})
        self.assertTrue(any('X+B combined' in line and '1,234' in line for line in lines))
        self.assertTrue(any('C ' in line and 'Not measured' in line for line in lines))
