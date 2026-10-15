import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import landmarks
import metrics
import performance
from faults import FaultRecorder, FishingFault, RecoveryPolicy
from pickup_policy import PickupGate, classify, classify_toast


def row(text,x=1250,y=700):return {'text':text,'score':.95,'center':(x,y)}


class PickupEvidence(unittest.TestCase):
    def test_inventory_stack_and_ambiguous_amounts_are_not_rewards(self):
        for text in ('X2964 Bait','Bait X100','Ore X0','Ore X01','Ore X1 X2'):
            self.assertEqual(classify([row(text)]).kind,'empty',text)
        for text in ('Ore X1','Ore X99','Lost Mask NEW'):
            self.assertEqual(classify([row(text)]).kind,'reward',text)

    def test_inventory_headers_block_quantity_and_collect_candidates(self):
        for header in ('All (188)','All classes (188)','Equipped (11)','Fishing (13)'):
            self.assertEqual(classify([row(header,x=800,y=180),row('Ore X1')]).kind,'empty')
            self.assertEqual(classify([row(header,x=800,y=180),row('Collect')]).kind,'empty')

    def test_separate_quantity_and_item_rows_form_one_reward(self):
        quantity=row('x1',y=729);quantity['score']=.75
        evidence=classify([row('Silk Thread'),quantity])
        self.assertEqual(evidence.kind,'reward');self.assertIn('Silk Thread',evidence.text)
        self.assertEqual(classify([quantity]).kind,'empty')

    def test_quantity_elsewhere_cannot_confirm_a_pickup(self):
        self.assertEqual(classify([row('Silk Thread'),row('x1',x=600,y=1000)]).kind,'empty')
        self.assertEqual(classify([row('Silk Thread'),row('Collect',y=720),row('x1',x=600,y=1000)]).kind,'collect')

    def test_competing_world_interactions_block_holding_t(self):
        self.assertEqual(classify([row('Collect'),row('Wall Climb',x=1700)]).kind,'ambiguous')
        self.assertEqual(classify([row('Wall Climb')]).kind,'other')
        self.assertEqual(classify([]).kind,'empty')

    def test_player_legendary_fisherman_title_is_not_an_interaction(self):
        self.assertEqual(classify([row('Legendary Fisherman',y=610)]).kind,'empty')
        self.assertEqual(classify([row('Legendary Fisherman',y=610),row('Collect',y=830)]).kind,'collect')
        self.assertEqual(classify([row('Legendary Fisherman',y=610),row('Wall Climb',y=830)]).kind,'other')

    def test_prompt_must_repeat_in_same_area_before_authorizing_input(self):
        gate=PickupGate()
        self.assertFalse(gate.observe(classify([row('Collect')]),1))
        self.assertFalse(gate.observe(classify([row('Collect',x=1600)]),1.5))
        self.assertTrue(gate.observe(classify([row('Collect',x=1604)]),1.9))
        self.assertFalse(gate.observe(classify([row('Collect',x=1604)]),4))

    def test_narrow_toast_recovers_recorded_rewards_without_accepting_a_prompt(self):
        # OCR examples from the 20-minute pickup recording: the wide scan
        # missed these toasts although all three items were visibly collected.
        for name,amount,confidence in [('Ore','1',.91),('Coral','X1',.85),('Silk Thread','x1',.61)]:
            quantity=row(amount,x=1300,y=730);quantity['score']=confidence
            self.assertEqual(classify_toast([row(name),quantity]).text,f'{name} X1')
            self.assertEqual(classify_toast([row(name),quantity,row('Collect')]).kind,'empty')
            self.assertEqual(classify_toast([row(name)]).kind,'empty')
            self.assertEqual(classify_toast([row(name),row(amount,x=1800,y=1000)]).kind,'empty')


class RecoveryDecisions(unittest.TestCase):
    def test_local_repairs_are_bounded_and_manual_stop_is_final(self):
        policy=RecoveryPolicy()
        self.assertEqual(policy.choose('no_minigame',0,True),'rejoin')
        self.assertEqual(policy.choose('pickup_other',0,False),'rejoin')
        self.assertEqual(policy.choose('pickup_other',0,True),'local')
        self.assertEqual(policy.choose('pickup_other',60,True),'rejoin')
        self.assertEqual(policy.choose('alignment_drift',121,True),'local')
        self.assertEqual(policy.choose('focus',122,True),'wait_focus')
        self.assertEqual(policy.choose('manual_stop',123,True),'stop')
        self.assertEqual(policy.choose('unexpected',300,True),'rejoin')

    def test_evidence_storage_remains_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            recorder=FaultRecorder(temp,'test')
            frame=np.zeros((40,80,3),np.uint8)
            for i in range(12):recorder.observe(frame,str(i));recorder.save('test',str(i))
            root=Path(temp)/'diagnostics'
            saved=json.loads((root/'index.json').read_text())
            self.assertEqual(len(saved),8)
            self.assertEqual(saved[-1]['sequence'],12)
            self.assertLessEqual(len(list(root.glob('*.jpg'))),32)


class LandmarkVision(unittest.TestCase):
    def test_zero_camera_step_never_clicks_and_interruption_releases_right_button(self):
        import fishing_assistant
        driver=Mock()
        with patch.object(fishing_assistant,'USER') as user:
            landmarks.camera(driver,0,0)
            user.mouse_event.assert_not_called();driver.move.assert_not_called()
            driver.sleep.side_effect=[None,RuntimeError('Lost focus')]
            with self.assertRaises(RuntimeError):landmarks.camera(driver,12,0)
            self.assertEqual([call.args[0] for call in user.mouse_event.call_args_list],[8,16])

    def test_compass_accepts_degree_symbol_but_rejects_clipped_number(self):
        driver=Mock();box=[[160,20],[240,20],[240,110],[160,110]]
        driver.ocr.return_value=([[box,'135°',.97],[box,'5�',.99]],None)
        self.assertEqual(landmarks.heading(driver,np.zeros((1440,2560,3),np.uint8)),135)

    def test_compass_correction_converges_without_character_movement(self):
        driver=Mock();angle=[180.];steps=[]
        def camera(_,dx,dy):
            steps.append((dx,dy));angle[0]=(angle[0]+dx*.18)%360
        with patch.object(landmarks,'heading',side_effect=lambda *_:angle[0]),patch.object(landmarks,'camera',side_effect=camera):
            distance=landmarks.restore_heading(driver,90)
        self.assertLess(abs(angle[0]-90),4)
        self.assertLessEqual(distance,1100)
        self.assertTrue(all(abs(dx)<=60 and dy==0 for dx,dy in steps))
        driver.key.assert_not_called()

    def test_matches_translation_but_rejects_missing_scenery(self):
        rng=np.random.default_rng(9)
        frame=rng.integers(0,256,(720,1280,3),dtype=np.uint8)
        frame=cv2.GaussianBlur(frame,(3,3),0)
        matcher=landmarks.Matcher(frame,landmarks.DEFAULT_BOXES)
        shifted=cv2.warpAffine(frame,np.float32([[1,0,7],[0,1,-4]]),(1280,720))
        result=matcher.measure(shifted)
        self.assertIsNotNone(result)
        self.assertLess(np.max(np.abs(result['error']-np.tile([7,-4],9))),1)
        matcher.refresh_features(shifted)
        twice=cv2.warpAffine(frame,np.float32([[1,0,14],[0,1,-8]]),(1280,720))
        result=matcher.measure(twice)
        self.assertLess(np.max(np.abs(result['error']-np.tile([14,-8],9))),1)
        self.assertIsNone(matcher.measure(np.zeros_like(frame)))

    def test_corrections_are_small_and_position_is_opt_in(self):
        matrix=np.tile(np.eye(4),(5,1));matrix[:,:2]*=2;matrix[:,2:]*=500
        error=np.ones(20)*1000
        step=landmarks.limited_step(matrix,error,False)
        self.assertTrue(np.all(step[2:]==0));self.assertLessEqual(max(abs(step[:2])),24)
        step=landmarks.limited_step(matrix,error,True)
        self.assertLessEqual(max(abs(step[2:])),.04000001)
        with self.assertRaises(FishingFault):landmarks.limited_step(np.zeros((20,4)),error,True)

    def test_no_input_when_landmarks_are_missing(self):
        driver=Mock()
        with patch.object(landmarks,'profile',return_value={'enabled':True}),patch.object(landmarks,'load_matcher'),patch.object(landmarks,'observation',side_effect=FishingFault('alignment','missing')),patch.object(landmarks,'apply_step') as move:
            with patch.object(landmarks,'write'):
                self.assertTrue(landmarks.align(driver)['skipped'])
            move.assert_not_called()

    def test_worsening_step_is_reverted_and_not_repeated(self):
        driver=Mock();state=lambda value:{'error':np.ones(18)*value,'rms':value,'matches':[10,10,10]}
        saved={'enabled':True,'jacobian':np.ones((18,4)).tolist(),'position_enabled':True}
        with patch.object(landmarks,'profile',return_value=saved),patch.object(landmarks,'load_matcher'),patch.object(landmarks,'observation',side_effect=[state(10),state(14),state(10)]),patch.object(landmarks,'limited_step',return_value=np.array([10,0,0,0])),patch.object(landmarks,'apply_step') as move:
            with self.assertRaises(FishingFault):landmarks.align(driver)
            self.assertEqual(move.call_count,2)
            np.testing.assert_equal(move.call_args.args[1],[-10,0,0,0])


class RecentPace(unittest.TestCase):
    def test_rates_include_recovery_time_and_count_item_quantities(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(metrics,'RUN',Path(temp)):
            recorder=performance.PerformanceRecorder(1)
            recorder.tick('fishing',{'stage':'tracking'},{'rounds':10},now=100)
            recorder.tick('recovering',{}, {'rounds':12},now=105)
            recorder.tick('fishing',{'stage':'pickup'},{'rounds':12},now=110)
            journal=SimpleNamespace(started=1,items=[{'at':108,'quantity':3},{'at':90,'quantity':30}])
            result=performance.recent(journal,now=110)
            self.assertEqual(result['hooks_per_minute'],12)
            self.assertEqual(result['items_per_minute'],18)
            self.assertEqual(result['recovery_seconds'],5)
            self.assertFalse(performance.recent(journal,now=130)['fresh'])


if __name__=='__main__':unittest.main()
