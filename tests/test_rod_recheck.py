import sys
import unittest
from pathlib import Path
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import rod_detector as rods
import test_rare_rod as fixtures
from app_config import ROOT


class FreshRodRecheck(unittest.TestCase):
    def frame(self,selected=True,x=1550,common=False):
        return fixtures.RodVariants().frame(selected,common,rare_x=x)

    def test_known_selected_rod_uses_fresh_pixels_at_each_slot(self):
        for x in (1050,1550):
            for normalize in (False,True):
                frame=self.frame(x=x)
                if normalize:frame=cv2.resize(cv2.resize(frame,(1920,1080)),(2560,1440))
                prior=rods.locate_rod(frame)
                fresh=rods.recheck_selected_rod(frame,prior)
                self.assertTrue(rods.selected_rod(fresh))
                self.assertEqual(fresh['name'],'rare')
                self.assertAlmostEqual(fresh['x'],prior['x'],delta=4)

    def test_legendary_and_common_selected_icons(self):
        for name in ('legendary','common'):
            frame=np.full((1440,2560,3),25,np.uint8)
            image='legendary-rod-equipped.png' if name=='legendary' else 'rod-icon.png'
            icon=cv2.imread(str(ROOT/'assets'/image))
            anchor=(35.5,33.5) if name=='legendary' else (30,19)
            x,y=(1436,1352) if name=='legendary' else (1150,1366)
            cv2.circle(frame,(round(x+anchor[0]),round(y+anchor[1])),39,(170,170,170),2)
            frame[y:y+icon.shape[0],x:x+icon.shape[1]]=icon
            prior=rods.locate_rod(frame)
            self.assertTrue(rods.selected_rod(rods.recheck_selected_rod(frame,prior)))

    def test_unchanged_icon_without_selected_ring_does_not_reuse_old_verdict(self):
        frame=self.frame();prior=rods.locate_rod(frame)
        x,y=prior['x'],prior['y']
        yy,xx=np.ogrid[-48:49,-48:49]
        radius=xx*xx+yy*yy
        frame[y-48:y+49,x-48:x+49][(radius>=36**2)&(radius<=47**2)]=(30,20,10)
        self.assertFalse(rods.selected_ring(frame,x,y)[1])
        self.assertIsNone(rods.recheck_selected_rod(frame,prior))

    def test_missing_unselected_or_other_equipped_rod_requires_full_search(self):
        prior=rods.locate_rod(self.frame())
        for frame in (np.zeros((1440,2560,3),np.uint8),self.frame(False),self.frame(False,common=True)):
            self.assertIsNone(rods.recheck_selected_rod(frame,prior))
        self.assertEqual(rods.locate_rod(self.frame(False,common=True))['name'],'common')

    def test_rod_moved_to_another_slot_requires_full_search(self):
        prior=rods.locate_rod(self.frame(x=1050))
        moved=self.frame(x=1550)
        self.assertIsNone(rods.recheck_selected_rod(moved,prior))
        self.assertGreater(rods.locate_rod(moved)['x']-prior['x'],400)

    def test_bright_ring_without_rod_artwork_cannot_pass(self):
        prior=rods.locate_rod(self.frame())
        frame=np.full((1440,2560,3),25,np.uint8)
        cv2.circle(frame,(prior['x'],prior['y']),39,(170,170,170),2)
        self.assertIsNone(rods.recheck_selected_rod(frame,prior))

    def test_absent_weak_or_unselected_previous_evidence_cannot_fast_check(self):
        frame=self.frame();prior=rods.locate_rod(frame)
        for invalid in (None,{**prior,'score':.8},{**prior,'equipped':False},{**prior,'ring':.1}):
            self.assertIsNone(rods.recheck_selected_rod(frame,invalid))
        self.assertIsNone(rods.recheck_selected_rod(cv2.resize(frame,(1920,1080)),prior))


if __name__=='__main__':unittest.main()
