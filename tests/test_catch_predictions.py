import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from catch_predictions import calculate


class Predictions(unittest.TestCase):
    def test_inventory_stack_does_not_inflate_catches_or_projections(self):
        rows=[self.row(0,'started'),
              self.row(1,'reward_observed',cycle=1,text='X2964 Bait'),
              self.row(2,'reward_observed',cycle=2,text='Bait X100'),
              self.row(3,'reward_observed',cycle=3,text='Golden Fish X2'),
              self.row(4,'reward_observed',cycle=4,text='Lost Mask NEW')]
        result=calculate(rows,{'started':0},now=700,live_source='events-20261009-010000.jsonl')
        self.assertEqual(result['unique_catches'],2)
        self.assertEqual(result['quantity'],3)
        self.assertFalse(any('bait' in i['name'].lower() for i in result['items']))

    def row(self,at,event,session='20261009-010000',**kw):
        return {'at':at,'event':event,'source':'events-'+session+'.jsonl',**kw}

    def test_retries_case_variants_and_inventory_recovery_do_not_count_twice(self):
        rows=[self.row(1,'started'),self.row(2,'reward_observed',cycle=1,text='Golden Fish X1',reward_id='20261009-010000:1:1'),
              self.row(3,'reward_observed',cycle=1,text='Golden Fish x1',reward_id='20261009-010000:1:2'),
              self.row(4,'inventory_recovered',reward_id='20261009-010000:1:inventory',item='Golden Fish',quantity=1),
              self.row(5,'stopped'),self.row(6,'started',session='20261009-010100'),
              self.row(7,'reward_observed',session='20261009-010100',cycle=1,text='Golden Fish X1',reward_id='20261009-010100:1:1')]
        result=calculate(rows,{'id':'run','started':0},now=10,live_source='events-20261009-010100.jsonl')
        self.assertEqual(result['unique_catches'],2);self.assertEqual(result['quantity'],2)
        self.assertEqual(result['active_seconds'],8);self.assertEqual(result['elapsed_seconds'],10)
        self.assertEqual(result['known_price_subtotal_wen'],132);self.assertIsNone(result['actual_sold_proceeds_wen'])
        self.assertFalse(result['projection_available'])

    def test_focus_pauses_and_overlapping_workers_cannot_inflate_active_time(self):
        rows=[self.row(0,'started'),self.row(100,'input_paused'),self.row(200,'input_resumed'),self.row(300,'stopped'),
              self.row(50,'started',session='20261009-010100'),self.row(75,'stopped',session='20261009-010100')]
        self.assertEqual(calculate(rows,{'started':0},now=400)['active_seconds'],200)

    def test_current_prices_unknown_prices_and_actual_sales_are_separate(self):
        rows=[self.row(0,'started')]
        for i,name in enumerate(('OuwFish','OuwFwesh','Coral','Clown Fish','Golden Fish','Crustadon','Krathulon','Ore'),1):
            rows.append(self.row(i,'reward_observed',cycle=i,text=name+' X1'))
        rows.append(self.row(9,'sale_confirmed',confirmed=True,proceeds_wen=500))
        result=calculate(rows,{'started':0},now=700,live_source='events-20261009-010000.jsonl')
        self.assertEqual(result['known_price_subtotal_wen'],231);self.assertEqual(result['unknown_price_quantity'],3)
        self.assertEqual(result['actual_sold_proceeds_wen'],500)
        self.assertTrue(all(i['unit_price_wen'] is None for i in result['items'] if i['name'] in ('Crustadon','Krathulon','Ore')))

    def test_projection_requires_sample_and_excludes_outside_run_events(self):
        rows=[self.row(0,'started'),self.row(-1,'reward_observed',cycle=99,text='Golden Fish X50')]
        rows.extend(self.row(i,'reward_observed',cycle=i,text='Coral X1') for i in range(1,21))
        rows.append(self.row(901,'reward_observed',cycle=30,text='Golden Fish X1'))
        rows.append(self.row(900,'stopped'))
        result=calculate(rows,{'started':0,'ended':900},hours=8,now=1000)
        self.assertEqual(result['quantity'],20);self.assertTrue(result['projection_available'])
        self.assertEqual(result['items'][0]['projected_quantity'],640)
        self.assertEqual(result['items'][0]['projected_npc_value_wen'],21120)

    def test_orphan_worker_does_not_fill_inactive_gap_or_enable_projection(self):
        rows=[self.row(0,'started'),self.row(100,'reward_observed',cycle=1,text='Coral X1'),
              self.row(1800,'started',session='20261009-010100'),
              self.row(3600,'stopped',session='20261009-010100')]
        result=calculate(rows,{'started':0},now=4000)
        self.assertEqual(result['active_seconds'],1900)
        self.assertFalse(result['projection_available'])
        self.assertTrue(any('Incomplete worker' in w for w in result['warnings']))
        rows.insert(2,{'at':150,'event':'worker_exit','source':'recovery.jsonl'})
        result=calculate(rows,{'started':0},now=4000)
        self.assertEqual(result['active_seconds'],1950)
        self.assertFalse(any('Incomplete worker' in w for w in result['warnings']))

    def test_confirmed_sale_retries_are_deduplicated(self):
        rows=[self.row(1,'sale_confirmed',sale_id='sale-1',confirmed=True,proceeds_wen=66),
              self.row(2,'sale_confirmed',sale_id='sale-1',confirmed=True,proceeds_wen=66)]
        self.assertEqual(calculate(rows,{'started':0},now=10)['actual_sold_proceeds_wen'],66)


if __name__=='__main__':unittest.main()
