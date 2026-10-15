"""Explicit paused reference setup shared by CLI and desktop settings."""
import json
import os
import psutil
import time

from metrics import RUN, read, write
import control_actions as controls
import landmarks


def marker_state():
    return [(name,(RUN/name).stat().st_mtime_ns,(RUN/name).read_bytes()) if (RUN/name).exists() else (name,None,None)
            for name in ('STOP','PAUSE')]


def setup(position=False, boxes=None):
    from recovery import Recovery, UserStop
    from fishing_assistant import USER
    record={'pid':os.getpid(),'created':psutil.Process().create_time()}
    with controls.guard():
        if any(controls.alive(name) for name in ('supervisor-pid.json','pid.json','calibration-pid.json','route-recorder-pid.json')) or controls.starting():
            raise RuntimeError('Pause fishing and wait for input to release before saving a reference')
        initial=marker_state();write('calibration-pid.json',record)
    class SetupDriver(Recovery):
        def check_stop(self):
            if marker_state()!=initial or any(USER.GetAsyncKeyState(k)&0x8000 for k in (27,120,123)):
                self.inp.release();raise UserStop('Reference setup stopped')
    driver=None
    try:
        driver=SetupDriver();driver.select(focus=True)
        image=driver.capture()
        if not driver.world_visible(image):raise ValueError('Enter the game and stand at the fishing spot first')
        rows=driver.text(image,(1150,1330,260,110))
        if any('exit' in r['text'].lower() for r in rows):raise ValueError('Finish the current minigame before saving a reference')
        landmarks.calibrate(driver,boxes,position)
        return 'Fishing reference saved'+(' with small position corrections' if position else ' with camera alignment')
    finally:
        if driver:driver.inp.release();driver.sct.close()
        with controls.guard():
            if read('calibration-pid.json')==record:(RUN/'calibration-pid.json').unlink(missing_ok=True)


def disable():
    with controls.guard():
        if controls.alive() or controls.starting() or controls.alive('calibration-pid.json'):
            raise RuntimeError('Pause before changing the fishing reference')
        saved=read('landmark.json');saved['enabled']=False;write('landmark.json',saved)
    return 'Fishing reference disabled; the saved image is retained'


def status():
    saved=landmarks.profile()
    return {'enabled':saved is not None,'position_enabled':bool(saved and saved.get('position_enabled')),
            'saved_at':saved.get('saved_at') if saved else None,'last_alignment':read('alignment.json')}
