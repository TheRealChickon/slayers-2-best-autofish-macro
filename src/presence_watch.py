"""Roblox presence is a second signal; API failures never imply a disconnect."""
import json, threading, time, urllib.request
from pathlib import Path
from metrics import RUN,read,write
from app_config import load_config

def query():
    config=load_config();user_id=config['user_id'];account=config['account_username']
    if not user_id:return {'checked_at':time.time(),'account':'','ok':False,'disabled':True,'state':'Not configured'}
    req=urllib.request.Request('https://presence.roblox.com/v1/presence/users',data=json.dumps({'userIds':[user_id]}).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=8) as response:data=json.load(response)
    rows=[x for x in data.get('userPresences',[]) if x.get('userId')==user_id]
    if len(rows)!=1:raise ValueError('Presence response did not contain the requested account')
    kind=rows[0].get('userPresenceType')
    if kind not in (0,1,2,3):raise ValueError('Unknown presence value')
    return {'checked_at':time.time(),'account':account,'user_id':user_id,'type':kind,'state':{0:'Offline',1:'Online, outside a game',2:'In game',3:'In Studio'}[kind],'ok':True}

def recovery_needed(presence,absent_since,supervisor,worker,now):
    return (presence.get('ok') and presence.get('type')!=2 and absent_since is not None
            and now-absent_since>=45 and supervisor.get('running') and supervisor.get('stage')=='fishing'
            and not supervisor.get('manual_paused') and not worker.get('manual_paused')
            and worker.get('stage') not in ('paused_manual','paused_focus')
            and not (worker.get('stage')=='inventory' and now-worker.get('updated',0)<20)
            and now-worker.get('last_game_activity',now)>75)

def watch(done):
    absent_since=None
    while not done.is_set():
        if (RUN/'STOP').exists():return
        try:
            state=query();now=time.time()
            absent_since=None if not state.get('ok') or state.get('type')==2 else absent_since or now
            state['absent_since']=absent_since
            if not (RUN/'F8_PAUSE').exists() and recovery_needed(state,absent_since,read('supervisor.json'),read('status.json'),now):
                (RUN/'RECOVER').write_text('Roblox presence remained outside game and fishing activity stopped')
                state['recovery_requested']=True
            write('presence.json',state)
        except Exception as error:
            absent_since=None;write('presence.json',{'checked_at':time.time(),'account':load_config()['account_username'],'ok':False,'state':'Unavailable','error':str(error)[:300]})
        done.wait(45)

def start():
    done=threading.Event();thread=threading.Thread(target=watch,args=(done,),daemon=True,name='RobloxPresence');thread.start();return done

if __name__=='__main__':print(json.dumps(query(),indent=2))
