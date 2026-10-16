"""Run-scoped views and durable archives, independent of lifetime counters."""
import json
import time
from pathlib import Path
from discord_hourly import atomic_json, read_json


def current(root):
    row=read_json(Path(root)/'current-run.json')
    if row:return row
    supervisor=read_json(Path(root)/'supervisor.json')
    started=supervisor.get('started')
    if not started:return {}
    return {'id':time.strftime('%Y%m%d-%H%M%S',time.localtime(started)),
            'started':started,'ended':None if supervisor.get('running') else supervisor.get('updated'),
            'legacy':True}


def begin(root, resume=False):
    root=Path(root);old=current(root)
    if resume and old:
        row={**old,'ended':None,'reason':'','legacy':False}
    else:
        if old:
            finish(root,old.get('reason','Previous run ended'),old.get('ended') or time.time(),old)
        started=time.time()
        # Lifetime fishing seconds at the start, so views can show this run's own time.
        active=(read_json(root/'totals.json') or {}).get('active_seconds')
        row={'id':time.strftime('%Y%m%d-%H%M%S',time.localtime(started)),
             'started':started,'ended':None,'reason':'','legacy':False,
             **({'active_at_start':active} if isinstance(active,(int,float)) else {})}
    directory=root/'runs'/row['id'];directory.mkdir(parents=True,exist_ok=True)
    atomic_json(directory/'run.json',row);atomic_json(root/'current-run.json',row)
    return row


_RANGES={}


def _parse(path):
    parsed=[]
    with path.open('rb') as stream:
        for line in stream:
            if not line.endswith(b'\n'):continue
            try:row=json.loads(line)
            except ValueError:continue
            parsed.append(row)
    return parsed


def rows(root, run):
    root=Path(root);start=run.get('started',0);end=run.get('ended') or float('inf')
    result=[]
    paths=sorted(root.glob('events-*.jsonl'))+[root/'recovery.jsonl',root/'controls.jsonl']
    for path in paths:
        # Each file's time range is remembered while the file is unchanged, so files
        # outside the window are skipped without parsing. Rod Lab used to re-parse
        # every log (35 MB, 1,000+ files) once per rod session.
        try:
            stat=path.stat()
            key=(stat.st_mtime_ns,stat.st_size)
            known=_RANGES.get(str(path))
            if known and known[0]==key and (known[2]<start or known[1]>end):continue
            parsed=_parse(path)
            times=[row.get('at',0) for row in parsed]
            _RANGES[str(path)]=(key,min(times,default=float('inf')),max(times,default=float('-inf')))
            for row in parsed:
                if start<=row.get('at',0)<=end:result.append({**row,'source':path.name})
        except OSError:continue
    return sorted(result,key=lambda row:row.get('at',0))


def finish(root, reason, ended=None, run=None):
    root=Path(root);row={**(run or current(root))}
    if not row:return
    row.update(ended=ended or time.time(),reason=reason)
    directory=root/'runs'/row['id'];directory.mkdir(parents=True,exist_ok=True)
    events=rows(root,row)
    (directory/'events.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in events),encoding='utf-8')
    (directory/'events.log').write_text(''.join(time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(r['at']))+' '+r.get('event','')+' '+str(r.get('text') or r.get('reason') or r.get('message') or '')+'\n' for r in events),encoding='utf-8')
    atomic_json(directory/'run.json',row)
    if current(root).get('id')==row['id']:atomic_json(root/'current-run.json',row)
    return row


def list_runs(root):
    root=Path(root);result={}
    for path in (root/'runs').glob('*/run.json'):
        row=read_json(path)
        if row.get('id'):result[row['id']]=row
    row=current(root)
    if row:result[row['id']]=row
    return sorted(result.values(),key=lambda row:row['started'],reverse=True)


def select(root, value='current'):
    if value in ('current','latest',None):return current(root)
    for row in list_runs(root):
        if row['id']==value:return row
    raise ValueError('Unknown run ID; use autofish runs')


def log_attachment(root, start, end, limit=1500000):
    # No configuration, credentials, launch arguments or screenshots here.
    data=''.join(json.dumps(r)+'\n' for r in rows(root,{'started':start,'ended':end})).encode('utf-8')
    if len(data)>limit:
        import gzip
        compressed=gzip.compress(data)
        if len(compressed)<7000000:return ('run-events.jsonl.gz','application/gzip',compressed)
        data=b'{"event":"attachment_truncated","message":"Latest complete log lines; full run retained locally"}\n'+data[-limit:].split(b'\n',1)[-1]
    return ('run-events.jsonl','application/x-ndjson',data)
