"""Persistent opt-in intent; bounded restarts after physical-user inactivity."""
import json
import os
import subprocess
import sys
import time
import psutil
from app_config import ROOT,load_config,save_config,data_directory
from discord_hourly import atomic_json,read_json
from unattended_focus import PhysicalActivity


def can_restart(config,physical_idle,client_present,manual=False,failure_code=''):
    return (config['overnight_enabled'] and config['overnight_autofocus'] and (client_present or failure_code in ('client_lost','disconnect')) and not manual
            and physical_idle>=45 and failure_code not in ('user_required','unstable_fishing_position','session_limit','manual_stop'))


def ensure_guard():
    import control_actions as actions
    if actions.alive('overnight-guard-pid.json') or actions.alive('overnight-guard-start.json'):return
    root=data_directory()
    with (root/'overnight-guard.log').open('a') as out:
        p=subprocess.Popen([sys.executable,str(ROOT/'overnight_guard.py')],stdout=out,stderr=out,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),cwd=ROOT)
    atomic_json(root/'overnight-guard-start.json',{'pid':p.pid,'created':psutil.Process(p.pid).create_time()})


def main():
    from fishing_assistant import find_window
    import control_actions as actions
    root=data_directory()
    if actions.alive('overnight-guard-pid.json'):return
    atomic_json(root/'overnight-guard-pid.json',{'pid':os.getpid(),'created':psutil.Process().create_time()})
    physical=PhysicalActivity();physical.start();attempts=[];next_retry=0
    try:
        while True:
            config=load_config()
            if not (config['overnight_enabled'] or config['overnight_auto_enable_idle']):break
            idle=time.monotonic()-physical.last
            manual=(root/'PAUSE').exists() or (root/'F8_PAUSE').exists()
            if (root/'STOP').exists():manual|=(root/'STOP').read_text().strip()!='Supervisor stopped'
            try:find_window();client=True
            except RuntimeError:client=False
            if (not config['overnight_enabled'] and config['overnight_auto_enable_idle'] and config['overnight_autofocus']
                    and idle>=config['overnight_idle_minutes']*60 and client and not manual):
                save_config({'overnight_enabled':True});config=load_config()
                actions.event('overnight_auto_enabled','Overnight enabled after physical-user inactivity.')
            supervisor=read_json(root/'supervisor.json')
            code=supervisor.get('failure_code','')
            now=time.time();attempts=[t for t in attempts if now-t<5400]
            live=actions.alive() or actions.starting()
            ownership_idle=physical.last_other_input is None or time.monotonic()-physical.last_other_input>=config['overnight_focus_grace_seconds']
            if not live and ownership_idle and can_restart(config,idle,client,manual,code) and now>=next_retry:
                if len(attempts)<3:
                    attempts.append(now);next_retry=now+(30,60,180)[len(attempts)-1]
                    actions.event('overnight_restart','Overnight restarting an inactive controller after bounded checks.')
                    actions.resume(config['mode'] if config['mode'] in ('full','here') else 'full',automatic=True)
                else:
                    actions.event('overnight_attention','Three controller restarts in 90 minutes; automatic restart suspended.')
                    break
            atomic_json(root/'overnight-guard-status.json',{'running':True,'pid':os.getpid(),'updated':now,
                        'enabled':config['overnight_enabled'],'auto_enable_idle':config['overnight_auto_enable_idle'],
                        'physical_idle_seconds':round(idle,1),'client_present':client,'manual_hold':manual,
                        'restart_attempts':len(attempts),'failure_code':code})
            time.sleep(3)
    finally:
        physical.stop()
        atomic_json(root/'overnight-guard-status.json',{'running':False,'pid':os.getpid(),'updated':time.time()})


if __name__=='__main__':main()
