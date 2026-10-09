import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fishing_readonly import FishingReader


class ReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        process=Mock();process.is_running.return_value=True;process.create_time.return_value=100
        self.reader=FishingReader(self.root,clock=lambda:200,process=Mock(return_value=process))

    def save(self,name,value):
        (self.root/name).write_text(json.dumps(value))

    def events(self,rows):
        (self.root/'events-20261009-092103.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))

    def test_process_identity_and_age_are_required_not_saved_running(self):
        self.save('status.json',{'pid':7,'running':True,'updated':199,'session':'20261009-092103','stage':'tracking','webhook':'SECRET'})
        self.save('pid.json',{'pid':7,'created':100})
        state=self.reader.status()
        self.assertTrue(state['worker']['verified_running'])
        self.assertNotIn('SECRET',json.dumps(state))
        self.save('pid.json',{'pid':7,'created':50})
        self.assertFalse(self.reader.status()['worker']['verified_running'])
        self.save('status.json',{'pid':7,'running':True,'updated':180})
        self.assertFalse(self.reader.status()['worker']['fresh'])

    def test_current_run_bounds_and_safe_fields(self):
        self.save('current-run.json',{'id':'20261009-092103','started':150,'ended':190,'token':'SECRET'})
        self.events([{'at':149,'event':'cast'}, {'at':160,'event':'reward_observed','text':'Golden Fish X1','webhook':'SECRET'},
                     {'at':170,'event':'stopped','reason':'https://secret.invalid/token','code':'tracking_lost'},
                     {'at':180,'event':'debug','credentials':'SECRET'}, {'at':195,'event':'cast'}])
        result=self.reader.recent_events(seconds=100)
        self.assertEqual([row['at'] for row in result['events']],[160,170])
        self.assertEqual(result['events'][0]['text'],'Golden Fish X1')
        self.assertNotIn('secret',json.dumps(result).lower())

    def test_argument_bounds_and_path_strings_are_rejected(self):
        for value in (0,201,True,'../../config.local.json'):
            with self.assertRaises(ValueError):self.reader.recent_events(limit=value)
        for value in (0,3601,True,'config.local.json'):
            with self.assertRaises(ValueError):self.reader.metrics(seconds=value)

    def test_malformed_and_oversized_files_fail_closed(self):
        (self.root/'status.json').write_text('not json')
        self.assertFalse(self.reader.status()['worker']['available'])
        (self.root/'status.json').write_text('x'*(self.reader.json_limit+1))
        self.assertEqual(self.reader._json('status.json'),{})
        self.assertEqual(self.reader._bytes('../config.local.json')[0],b'')

    def test_tail_and_response_limits_remain_visible(self):
        self.reader.tail_limit=150
        self.events([{'at':150+i,'event':'cast','cast':i} for i in range(30)])
        result=self.reader.recent_events(limit=1,seconds=100)
        self.assertEqual(len(result['events']),1)
        self.assertTrue(result['coverage']['tail_clipped'])
        self.assertGreater(result['rows_omitted'],0)

    def test_metrics_are_samples_and_reading_does_not_mutate_files(self):
        self.events([{'at':160,'event':'pickup_hold','scan_seconds':.1,'prompt_to_hold_seconds':.01},
                     {'at':170,'event':'pickup_hold','scan_seconds':.3,'prompt_to_hold_seconds':.03},
                     {'at':180,'event':'reward_observed','text':'Coral X1'}])
        before={p.name:p.read_bytes() for p in self.root.iterdir()}
        metrics=self.reader.metrics(seconds=100)
        self.assertEqual(metrics['sample_event_counts']['reward_observed'],1)
        self.assertEqual(metrics['scan']['median_seconds'],.2)
        self.reader.status();self.reader.recent_events(seconds=100)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})
        self.assertIn('not complete run totals',metrics['scope'])


if __name__=='__main__':unittest.main()
