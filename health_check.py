"""Small read-only health report for the five-minute monitor."""
import json,time
from pathlib import Path
import psutil
from fishing_assistant import is_reward_banner

from metrics import RUN
def read(name):
    try:return json.loads((RUN/name).read_text())
    except (OSError,ValueError):return {}
now=time.time();supervisor=read('supervisor.json');worker=read('status.json')
events=[]
for f in RUN.glob('events-*.jsonl'):
    if f.stat().st_mtime<now-600:continue
    for line in f.read_text().splitlines():
        try:r=json.loads(line)
        except ValueError:continue
        if r.get('at',0)>now-300:events.append(r)
result={'checked_at':now,'supervisor':supervisor,'worker':worker,'stop_requested':(RUN/'STOP').exists(),'supervisor_alive':psutil.pid_exists(supervisor.get('pid',0)),'worker_alive':psutil.pid_exists(worker.get('pid',0)),'recent_5min':{'minigames_started':sum(r.get('event')=='minigame' for r in events),'completed_100_percent':sum(r.get('event')=='minigame_ended' and r.get('percent')==100 for r in events),'failed_rounds':sum(r.get('event')=='minigame_ended' and r.get('percent') not in (None,100) for r in events),'reward_banners':sum(r.get('event')=='reward_observed' and is_reward_banner(r.get('text','')) for r in events),'errors':[r for r in events if r.get('event')=='stopped']}}
issues=[]
if not result['stop_requested']:
    if not result['supervisor_alive'] or not supervisor.get('running'):issues.append('Supervisor stopped')
    elif supervisor.get('stage')=='fishing' and (not result['worker_alive'] or now-worker.get('updated',0)>15):issues.append('Fishing worker missing or stale')
    elif supervisor.get('stage')=='paused_focus' and supervisor.get('mode','full')=='full':issues.append('Paused because Roblox is not foreground')
    elif supervisor.get('stage')=='recovering' and now-supervisor.get('updated',0)>200:issues.append('Recovery stalled')
    if supervisor.get('running') and supervisor.get('mode','full')=='full' and worker.get('elapsed',0)>300 and not result['recent_5min']['reward_banners']:issues.append('No confirmed collected reward in five minutes')
result['totals']=read('totals.json')
result['presence']=read('presence.json')
presence=result['presence']
if supervisor.get('running') and supervisor.get('mode','full')=='full' and not result['stop_requested'] and presence.get('ok') and now-presence.get('checked_at',0)<180 and presence.get('type')!=2:
    if now-worker.get('last_game_activity',now)>75 and not (worker.get('stage')=='inventory' and now-worker.get('updated',0)<20):issues.append('Roblox presence reports account outside a game and fishing activity has stopped')
result['issues']=issues
print(json.dumps(result,indent=2))
