"""Bounded fishing telemetry adapter. No input, control, networking, or writes.

An MCP host configures one local data root at startup. Tool arguments never
accept filesystem paths, commands, credentials, or a control operation.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import statistics
import time
import psutil

SESSION = re.compile(r'^\d{8}-\d{6}$')
EVENTS = {'cast','minigame','minigame_ended','reward_observed','pickup_hold',
          'pickup_prompt_seen','empty_round','capture_reset','input_paused',
          'input_resumed','client_reacquired','stopped'}
NUMBERS = ('at','cycle','cast','attempt','seconds','percent','scan_seconds',
           'prompt_to_hold_seconds','paused_seconds','resets')
COUNTERS = ('casts','cycles','reward_banners_observed','failed_rounds',
            'unknown_rounds','capture_resets','pending_alerts','recoveries')


def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def label(value):
    return value if isinstance(value,str) and re.fullmatch(r'[a-zA-Z0-9_ -]{1,70}',value) else None


class FishingReader:
    json_limit = 65536
    tail_limit = 131072
    file_limit = 4

    def __init__(self, root, clock=time.time, process=psutil.Process):
        self.root = Path(root).resolve()
        self.clock, self.process = clock, process

    def _bytes(self, name, tail=False):
        path = self.root/name
        if path.is_symlink() or path.resolve().parent != self.root:
            return b'',False
        bound = self.tail_limit if tail else self.json_limit
        try:
            if os.name == 'nt':
                # Let the farmer atomically replace an open status file.
                import win32file, win32con
                handle=win32file.CreateFile(str(path),win32con.GENERIC_READ,
                    win32con.FILE_SHARE_READ|win32con.FILE_SHARE_WRITE|win32con.FILE_SHARE_DELETE,
                    None,win32con.OPEN_EXISTING,win32con.FILE_ATTRIBUTE_NORMAL,None)
                try:
                    size=win32file.GetFileSize(handle)
                    if not tail and size>bound:return b'',True
                    start=max(0,size-bound) if tail else 0
                    win32file.SetFilePointer(handle,start,win32con.FILE_BEGIN)
                    data=win32file.ReadFile(handle,min(bound,size-start))[1] if size>start else b''
                finally:handle.Close()
            else:
                with path.open('rb') as stream:
                    size=os.fstat(stream.fileno()).st_size
                    if not tail and size>bound:return b'',True
                    start=max(0,size-bound) if tail else 0
                    stream.seek(start);data=stream.read(bound)
            # The first row may begin before the bounded tail.
            return (data.split(b'\n',1)[-1] if start and b'\n' in data else b'' if start else data),bool(start)
        except (OSError,psutil.Error):
            return b'',False
        except Exception as error:
            if os.name=='nt':
                import pywintypes
                if isinstance(error,pywintypes.error):return b'',False
            raise

    def _json(self,name):
        data,truncated=self._bytes(name)
        try:value=json.loads(data)
        except (ValueError,UnicodeDecodeError):return {}
        return value if isinstance(value,dict) and not truncated else {}

    def _process_state(self,saved,lock):
        pid=saved.get('pid')
        state={'alive':None,'identity_matches':False}
        if not isinstance(pid,int) or isinstance(pid,bool) or pid<=0:return state
        try:
            process=self.process(pid)
            state['alive']=process.is_running()
            state['identity_matches']=(pid==lock.get('pid') and number(lock.get('created'))
                                       and abs(process.create_time()-lock['created'])<1)
        except psutil.NoSuchProcess:state['alive']=False
        except (psutil.AccessDenied,OSError):pass
        return state

    def status(self):
        now=self.clock();result={'observed_at':now,'read_only':True}
        sources=(('worker','status.json','pid.json',5),
                 ('supervisor','supervisor.json','supervisor-pid.json',10),
                 ('watcher','monitor-status.json','monitor-pid.json',10),
                 ('overnight_guard','overnight-guard-status.json','overnight-guard-pid.json',10))
        for key,file,lock,age_limit in sources:
            saved=self._json(file);row=self._process_state(saved,self._json(lock))
            row['available']=bool(saved)
            for field in ('pid','updated','started',*COUNTERS):
                if number(saved.get(field)):row[field]=saved[field]
            for field in ('running','held_mouse','held_t','manual_paused','overnight_enabled','manual_hold'):
                if isinstance(saved.get(field),bool):row[field]=saved[field]
            for field in ('stage','mode','failure_code'):
                if label(saved.get(field)):row[field]=saved[field]
            if SESSION.fullmatch(str(saved.get('session',''))):row['session']=saved['session']
            age=max(0,now-saved['updated']) if number(saved.get('updated')) and saved['updated']<=now+1 else None
            row['age_seconds']=round(age,3) if age is not None else None
            row['fresh']=age is not None and age<=age_limit
            row['verified_running']=bool(row['alive'] and row['identity_matches'] and row['fresh'] and saved.get('running'))
            result[key]=row
        run=self._json('current-run.json')
        result['run']={key:run[key] for key in ('started','ended') if number(run.get(key))}
        if SESSION.fullmatch(str(run.get('id',''))):result['run']['id']=run['id']
        result['manual_flags']={name:(self.root/name).is_file() for name in ('STOP','PAUSE','F8_PAUSE')}
        return result

    def _event_sample(self,seconds):
        now=self.clock();run=self._json('current-run.json')
        start=max(now-seconds,run['started']) if number(run.get('started')) else now-seconds
        end=min(now,run['ended']) if number(run.get('ended')) else now
        try:
            paths=[path for path in self.root.glob('events-*.jsonl')
                   if SESSION.fullmatch(path.stem.removeprefix('events-')) and not path.is_symlink()]
            paths.sort(key=lambda path:path.stat().st_mtime,reverse=True)
        except OSError:paths=[]
        rows=[];truncated=False;oldest=None
        for path in paths[:self.file_limit]:
            data,clipped=self._bytes(path.name,tail=True);truncated |= clipped
            for line in data.splitlines():
                try:row=json.loads(line)
                except (ValueError,UnicodeDecodeError):continue
                if not isinstance(row,dict) or not number(row.get('at')):continue
                at=row['at'];oldest=at if oldest is None else min(oldest,at)
                if not start<=at<=end or row.get('event') not in EVENTS:continue
                safe={'event':row['event'],'session':path.stem.removeprefix('events-')}
                safe.update({key:row[key] for key in NUMBERS if number(row.get(key))})
                if row['event']=='reward_observed':
                    text=row.get('text','')
                    if isinstance(text,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9 ()_-]{0,90} [xX]\d{1,2}',text):safe['text']=text
                for key in ('stage','code'):
                    if label(row.get(key)):safe[key]=row[key]
                rows.append(safe)
        rows.sort(key=lambda row:row['at'])
        # Limits describe scope honestly, rather than claiming complete run totals.
        return rows,{'requested_start':start,'end':end,'oldest_scanned_event':oldest,
                     'tail_clipped':truncated,'files_scanned':min(len(paths),self.file_limit),
                     'file_limit_reached':len(paths)>self.file_limit}

    def recent_events(self,limit=50,seconds=900):
        if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=200:
            raise ValueError('limit must be 1-200')
        if isinstance(seconds,bool) or not isinstance(seconds,int) or not 30<=seconds<=3600:
            raise ValueError('seconds must be 30-3600')
        rows,coverage=self._event_sample(seconds)
        return {'observed_at':self.clock(),'read_only':True,'events':rows[-limit:],
                'rows_omitted':max(0,len(rows)-limit),'coverage':coverage}

    def metrics(self,seconds=900):
        if isinstance(seconds,bool) or not isinstance(seconds,int) or not 30<=seconds<=3600:
            raise ValueError('seconds must be 30-3600')
        rows,coverage=self._event_sample(seconds)
        counts={event:sum(row['event']==event for row in rows)
                for event in ('cast','minigame','reward_observed','empty_round','capture_reset')}
        def timing(field):
            values=[row[field] for row in rows if number(row.get(field)) and 0<=row[field]<=120]
            if not values:return {'samples':0,'median_seconds':None,'p95_seconds':None}
            values.sort()
            return {'samples':len(values),'median_seconds':round(statistics.median(values),4),
                    'p95_seconds':round(values[max(0,math.ceil(len(values)*.95)-1)],4)}
        return {'observed_at':self.clock(),'read_only':True,'sample_event_counts':counts,
                'scan':timing('scan_seconds'),'prompt_to_hold':timing('prompt_to_hold_seconds'),
                'coverage':coverage,'scope':'Bounded recent event sample; these are not complete run totals or active-time rates.'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('status','events','metrics'))
    parser.add_argument('--data-dir',type=Path,required=True,help='Local operator configuration; never expose this as an MCP tool argument')
    parser.add_argument('--limit',type=int,default=50)
    parser.add_argument('--seconds',type=int,default=900)
    args=parser.parse_args(argv);reader=FishingReader(args.data_dir)
    result=reader.status() if args.operation=='status' else reader.recent_events(args.limit,args.seconds) if args.operation=='events' else reader.metrics(args.seconds)
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__=='__main__':main()
