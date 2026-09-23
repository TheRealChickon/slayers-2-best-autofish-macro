import sys
import unittest
from pathlib import Path
import cv2
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app_config import ROOT
from rod_detector import locate_rod,selected_rod,unselected_rod,RodReady


class RodVariants(unittest.TestCase):
    def frame(self, rare_selected, common_selected=None, rare_x=1550):
        frame=np.full((1440,2560,3),(30,20,10),np.uint8)
        variant='equipped' if rare_selected else 'unequipped'
        icon=cv2.imread(str(ROOT/f'assets/rare-rod-{variant}.png'))
        y=1351;x=rare_x
        if rare_selected:cv2.circle(frame,(round(x+35.5),round(y+33.5)),39,(170,170,170),2)
        frame[y:y+icon.shape[0],x:x+icon.shape[1]]=icon
        if common_selected is not None:
            icon=cv2.imread(str(ROOT/('assets/rod-icon.png' if common_selected else 'assets/rod-unequipped.png')))
            if common_selected:cv2.circle(frame,(1180,1385),39,(170,170,170),2)
            frame[1366:1366+icon.shape[0],1150:1150+icon.shape[1]]=icon
        return frame

    def test_rare_equipped_and_unequipped_in_different_hotbar_positions(self):
        for x in (1050,1550):
            for selected in (False,True):
                with self.subTest(x=x,selected=selected):
                    rod=locate_rod(self.frame(selected,rare_x=x))
                    self.assertEqual(rod['name'],'rare')
                    self.assertEqual(selected_rod(rod),selected)
                    self.assertAlmostEqual(rod['x'],x+35.5,delta=2)

    def test_selected_rod_wins_over_other_rods_template_score(self):
        self.assertEqual(locate_rod(self.frame(True,False))['name'],'rare')
        self.assertEqual(locate_rod(self.frame(False,True))['name'],'common')
        self.assertEqual(locate_rod(self.frame(False,False))['name'],'rare')

    def test_1080p_resampling_preserves_equipped_check(self):
        for selected in (False,True):
            frame=self.frame(selected)
            normalized=cv2.resize(cv2.resize(frame,(1920,1080)),(2560,1440))
            rod=locate_rod(normalized)
            self.assertEqual(rod['name'],'rare')
            self.assertEqual(selected_rod(rod),selected)

    def test_tinted_or_dim_selected_ring_still_requires_circle_geometry(self):
        for selected in (True,False):
            for tint in ((40,0,-10),(-10,10,20),(-20,-20,-20)):
                with self.subTest(selected=selected,tint=tint):
                    frame=np.clip(self.frame(selected).astype(np.int16)+np.array(tint),0,255).astype(np.uint8)
                    self.assertEqual(selected_rod(locate_rod(frame)),selected)

    def test_selected_ring_without_recognized_rod_is_not_a_rod(self):
        frame=np.full((1440,2560,3),30,np.uint8)
        cv2.circle(frame,(1470,1385),39,(180,180,180),2)
        self.assertIsNone(locate_rod(frame))

    def test_changing_rod_in_the_same_slot_requires_fresh_readiness(self):
        gate=RodReady();rod={'name':'common','equipped':True,'score':.95,'ring':.9,'x':1470,'y':1385}
        gate.observe(rod,1);gate.observe(rod,1.4)
        self.assertTrue(gate.observe(rod,1.8))
        rare={**rod,'name':'rare'}
        self.assertFalse(gate.matches(rare))
        self.assertFalse(gate.observe(rare,2.2))

    def test_legendary_icon_and_selected_ring(self):
        for selected in (False,True):
            with self.subTest(selected=selected):
                frame=np.full((1440,2560,3),(25,25,25),np.uint8)
                if selected:cv2.circle(frame,(1472,1386),39,(170,170,170),2)
                suffix='equipped' if selected else 'unequipped'
                icon=cv2.imread(str(ROOT/f'assets/legendary-rod-{suffix}.png'))
                frame[1352:1426,1436:1512]=icon
                rod=locate_rod(frame)
                self.assertEqual(rod['name'],'legendary')
                self.assertEqual(selected_rod(rod),selected)
                self.assertEqual(unselected_rod(rod),not selected)

    def test_weak_rod_match_never_authorizes_equipping(self):
        self.assertFalse(unselected_rod({'name':'rare','equipped':False,'score':.734,'ring':.02}))

    def test_legendary_1080p_selected_ring(self):
        frame=np.full((1440,2560,3),(25,25,25),np.uint8)
        cv2.circle(frame,(1472,1386),39,(170,170,170),2)
        frame[1352:1426,1436:1512]=cv2.imread(str(ROOT/'assets/legendary-rod-equipped.png'))
        normalized=cv2.resize(cv2.resize(frame,(1920,1080)),(2560,1440))
        self.assertTrue(selected_rod(locate_rod(normalized)))
