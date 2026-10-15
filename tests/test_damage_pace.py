import unittest

from damage_measure import DamageMeasurements
from damage_view import pace_labels


class DamagePaceTests(unittest.TestCase):
    def test_elapsed_pace_includes_time_outside_active_counter(self):
        sample = DamageMeasurements(10_000_000, 1000, 60)
        sample.observe(1000, 1000)
        self.assertIsNone(sample.summary()['recent_dph'])
        sample.observe(31_000, 1300)
        result = sample.summary()
        self.assertEqual(result['recent_dph'], 360_000)
        self.assertEqual(result['recent_eta_seconds'], 99_690)
        self.assertEqual(result['estimated_finish_at'], 100_990)

    def test_recent_window_moves_past_old_speed(self):
        sample = DamageMeasurements(100_000)
        for at, value in [(1000, 0), (1300, 3000), (1600, 6000), (1900, 12000)]:
            sample.observe(value, at)
        self.assertEqual(sample.summary()['recent_dph'], 54_000)
        sample.observe(12000, 1900)
        self.assertEqual(len(sample.samples), 3)

    def test_stale_or_paused_data_does_not_promise_finish_time(self):
        damage = dict(running=True, stage='attacking', last_verified=1300,
                      recent_dph=360000, pace_window_seconds=300,
                      recent_eta_seconds=7200, estimated_finish_at=8500)
        self.assertIn('2h 00m', pace_labels(damage, 1300)[1])
        self.assertIn('[stale]', pace_labels(damage, 1800)[0])
        self.assertNotIn('around', pace_labels(damage, 1800)[1])
        damage['running'] = False
        self.assertNotIn('around', pace_labels(damage, 1300)[1])

    def test_zero_damage_is_zero_rate_without_eta(self):
        sample = DamageMeasurements(1000, 100)
        sample.observe(100, 1000)
        sample.observe(100, 1300)
        self.assertEqual(sample.summary()['recent_dph'], 0)
        self.assertIsNone(sample.summary()['estimated_finish_at'])


if __name__ == '__main__':
    unittest.main()
