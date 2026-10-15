"""Autofish Settings entry points for the separate shrine-route bot."""
import json
import os
import subprocess
from pathlib import Path

import psutil
import app_config
import control_actions as actions


SPEC=app_config.ROOT/'baitbot.local.json'


def installation():
    try:values=json.loads(SPEC.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError) as error:
        raise ValueError('BaitBot is not connected to this installation') from error
    if not isinstance(values,dict):raise ValueError('Invalid BaitBot installation')
    paths={}
    for key in ('python','script','route_dir','dependencies'):
        value=values.get(key)
        if not isinstance(value,str) or not value:raise ValueError('BaitBot installation is missing '+key)
        path=Path(value).resolve()
        if not (path.is_file() if key in ('python','script') else path.is_dir()):
            raise ValueError('BaitBot installation is missing '+key)
        paths[key]=path
    return paths


def command(operation,reserve=None,buffer=None,continue_route=False):
    if operation not in ('check','status','stop','run','test'):raise ValueError('Invalid BaitBot operation')
    cfg=app_config.load_config()
    reserve=cfg['bait_reserve'] if reserve is None else reserve
    buffer=cfg['bait_refill_buffer'] if buffer is None else buffer
    if type(reserve) is not int or not 1<=reserve<=100000:raise ValueError('Fish Head reserve must be 1–100,000')
    if type(buffer) is not int or not 0<=buffer<=10000:raise ValueError('Refill buffer must be 0–10,000')
    if continue_route and operation!='test':raise ValueError('Continue route is only available for a route test')
    paths=installation()
    args=[str(paths['python']),str(paths['script']),'--route-dir',str(paths['route_dir']),
          '--config-file',str(app_config.CONFIG.resolve()),operation,
          '--reserve',str(reserve),'--buffer',str(buffer)]
    if continue_route:args.append('--continue-route')
    env=dict(os.environ)
    env['PYTHONPATH']=str(paths['dependencies'])
    env['PYTHONIOENCODING']='utf-8'
    env['FISHING_DATA_DIR']=str(app_config.data_directory())
    return args,env,paths


def invoke(operation):
    args,env,paths=command(operation)
    completed=subprocess.run(args,env=env,cwd=paths['script'].parent,capture_output=True,
                             text=True,encoding='utf-8',errors='replace',timeout=30,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    if operation=='stop':
        if completed.returncode:raise ValueError(completed.stderr.strip() or completed.stdout.strip())
        return 'BaitBot Stop requested; fishing controls retained'
    try:result=json.loads(completed.stdout)
    except ValueError as error:
        raise ValueError(completed.stderr.strip() or completed.stdout.strip() or 'BaitBot returned no status') from error
    if not isinstance(result,dict):raise ValueError('BaitBot returned invalid status')
    if completed.returncode and operation!='check':
        raise ValueError(result.get('reason') or 'BaitBot status failed')
    return result


def check():
    report=invoke('check')
    if not report.get('ready_for_trip'):
        raise ValueError('Bait route needs calibration: '+'; '.join(report.get('errors') or ['Unknown route']))
    return 'Bait route ready for a standalone trip'+(' · live verified' if report.get('live_verified') else ' · live trip unverified')


def launch(operation='run',reserve=None,buffer=None,continue_route=False):
    args,env,paths=command(operation,reserve,buffer,continue_route)
    if operation not in ('run','test'):raise ValueError('Choose run or test')
    if operation=='run':check()
    with actions.guard():
        actions.refuse_peer_controller()
        if actions.starting() or any(actions.alive(name) for name in (
                'supervisor-pid.json','pid.json','bait-driver-pid.json','route-recorder-pid.json','calibration-pid.json')):
            raise ValueError('Pause the current controller and wait for it to stop before running BaitBot')
        folder=app_config.data_directory();folder.mkdir(parents=True,exist_ok=True)
        with (folder/'baitbot-stdout.log').open('a',encoding='utf-8') as out,\
                (folder/'baitbot-stderr.log').open('a',encoding='utf-8') as err:
            subprocess.Popen(args,env=env,cwd=paths['script'].parent,stdout=out,stderr=err,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    return 'BaitBot launched; BaitBot status shows progress. Stop bait restock releases its input.'


def summary():
    """Small local reads for Settings; never starts a child or captures Roblox."""
    try:paths=installation()
    except ValueError:return 'Not connected'
    folder=paths['route_dir']
    try:route=json.loads((folder/'route.json').read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return 'Route missing'
    candidates=[p for p in (folder/'test-result.json',folder/'bait-restock-status.json') if p.is_file()]
    if candidates:
        try:
            result=json.loads(max(candidates,key=lambda p:p.stat().st_mtime_ns).read_text())
            if isinstance(result,dict) and (result.get('running') is True or result.get('status')=='running'):
                if abs(psutil.Process(result['pid']).create_time()-result['created'])<1:return 'Running · '+str(result.get('checking') or result.get('stage','route'))
        except (OSError,ValueError,TypeError,KeyError,psutil.Error):pass
    return 'Route incomplete' if not isinstance(route,dict) or route.get('incomplete') else 'Check route before running'


def status():
    result=invoke('status')
    where=result.get('checking') or result.get('failed_stage') or result.get('stage') or 'Not started'
    reason=result.get('reason') or result.get('status') or 'stopped'
    return str(where)+' · '+str(reason)


def add_parser(sub):
    parser=sub.add_parser('baitbot',help='Standalone shrine route: reset, Fish Heads, return')
    parser.add_argument('operation',choices=('check','run','test','status','stop'),nargs='?',default='status')
    parser.add_argument('--reserve',type=int)
    parser.add_argument('--buffer',type=int)
    parser.add_argument('--continue-route',action='store_true')


def execute(args):
    if args.operation in ('run','test'):
        print(launch(args.operation,args.reserve,args.buffer,args.continue_route));return 0
    if args.continue_route or args.reserve is not None or args.buffer is not None:
        raise ValueError('Reserve, buffer and continue-route apply only to run/test')
    if args.operation=='stop':print(invoke('stop'));return 0
    result=invoke(args.operation)
    print(json.dumps(result,indent=2))
    return 1 if args.operation=='check' and not result.get('ready_for_trip') else 0
