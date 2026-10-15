"""Counters survive worker restarts; each explicit start creates a new run."""
import json, os, time, tempfile
from pathlib import Path
from app_config import data_directory
if os.name=='nt':
    import win32file, win32con, pywintypes

RUN=data_directory()

def read(name):
    try:
        if os.name=='nt':
            # Status readers must let the writer atomically replace their open file.
            handle=win32file.CreateFile(str(RUN/name),win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ|win32con.FILE_SHARE_WRITE|win32con.FILE_SHARE_DELETE,
                None,win32con.OPEN_EXISTING,win32con.FILE_ATTRIBUTE_NORMAL,None)
            try:return json.loads(win32file.ReadFile(handle,win32file.GetFileSize(handle))[1])
            finally:handle.Close()
        return json.loads((RUN/name).read_text())
    except Exception as error:
        if isinstance(error,(OSError,ValueError)) or (os.name=='nt' and isinstance(error,pywintypes.error)):return {}
        raise

def write(name,value):
    RUN.mkdir(parents=True,exist_ok=True)
    path=RUN/name
    # A Windows reader can briefly prevent replacement of its open JSON file.
    # Retry the atomic swap instead of terminating fishing when a view refreshes.
    fd,temporary=tempfile.mkstemp(prefix=path.stem+'-',suffix='.tmp',dir=RUN)
    tmp=Path(temporary)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(value,f,indent=2)
        for attempt in range(20):
            try:os.replace(tmp,path);return
            except PermissionError:
                if attempt==19:raise
                time.sleep(.01 if attempt<5 else .05)
    finally:
        tmp.unlink(missing_ok=True)

def new_run():
    old=read('totals.json')
    if old:
        with (RUN/'run-history.jsonl').open('a') as f:f.write(json.dumps(old)+'\n')
    write('totals.json',{'started':time.time(),'updated':time.time(),'casts':0,'rounds':0,'rewards':0,'failed':0,'active_seconds':0,'last_reward':''})

class Ledger:
    def __init__(self):
        self.base=read('totals.json')
        if not self.base:new_run();self.base=read('totals.json')
    def update(self,elapsed,casts,rounds,rewards,failed,last_reward):
        state=dict(self.base)
        for key,value in [('active_seconds',elapsed),('casts',casts),('rounds',rounds),('rewards',rewards),('failed',failed)]:state[key]=self.base.get(key,0)+value
        state.update(updated=time.time(),last_reward=last_reward or self.base.get('last_reward',''))
        write('totals.json',state)
