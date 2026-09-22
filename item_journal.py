"""Rebuild the visible journal from every confirmed item event in this run."""
import collections,csv,json,re,time,shutil
from pathlib import Path
from fishing_assistant import ROOT,RUN,is_reward_banner

def item_name(raw,prompt=''):
    def clean(value):
        value=re.sub(r'\bx\s*\d+\b|\bnew\b|\bT\b|collect|ollect|llect|\blect\b','',value,flags=re.I)
        return re.sub(r'[^a-z0-9]','',value.lower())
    known={'coral':'Coral','silkthread':'Silk Thread','metalscraps':'Metal Scraps','seahorse':'Sea Horse','ouwfwesh':'OuwFwesh','ouwfish':'OuwFish','goldenfish':'Golden Fish','zebrafish':'Zebra Fish','clownfish':'Clown Fish','ore':'Ore'}
    value=clean(raw);hint=clean(prompt)
    if value in known:return known[value]
    if hint in known:return known[hint]
    for key,label in known.items():
        if len(key)>=4 and value.endswith(key):return label
    aliases={'wfwesh':'OuwFwesh','uwfwesh':'OuwFwesh','quwfwesh':'OuwFwesh','uwfish':'OuwFish','wfish':'OuwFish','etalscraps':'Metal Scraps','ilkthread':'Silk Thread'}
    if value in aliases:return aliases[value]
    if not value:return 'Unidentified item'
    name=re.sub(r'\bx\s*\d+\b|\bnew!?\b','',raw,flags=re.I).strip(' !')
    return name+' (partial)' if name else 'Unidentified item'

class Journal:
    def __init__(self):
        self.started=None;self.offsets={};self.prompts={};self.cycles={};self.items=[];self.activity=[];self.counts=collections.Counter();self.launches=0;self.joins=0;self.version=0

    def update(self,started):
        if started!=self.started:
            self.__init__();self.started=started
        paths=sorted(RUN.glob('events-*.jsonl'))+[RUN/'recovery.jsonl',RUN/'controls.jsonl']
        changed=False
        for path in paths:
            if not path.exists():continue
            key=str(path);offset=self.offsets.get(key,0)
            if path.stat().st_size<offset:offset=0
            with path.open('rb') as f:
                f.seek(offset)
                while True:
                    position=f.tell();line=f.readline()
                    if not line or not line.endswith(b'\n'):f.seek(position);break
                    try:row=json.loads(line)
                    except ValueError:continue
                    if row.get('at',0)<(started or 0):continue
                    kind=row.get('event','')
                    if kind=='minigame':self.cycles[key]=row.get('cycle')
                    cycle=(key,row.get('cycle',self.cycles.get(key)))
                    if kind=='pickup_hold':self.prompts[cycle]=row.get('text','')
                    if kind=='reward_observed' and is_reward_banner(row.get('text','')):
                        raw=row.get('text','');m=re.search(r'\bx\s*(\d+)\b',raw,re.I);qty=int(m[1]) if m else 1
                        item={'at':row['at'],'item':item_name(raw,self.prompts.get(cycle,'')),'quantity':qty,'raw':raw,'session':path.stem.removeprefix('events-')}
                        self.items.append(item);self.counts[item['item']]+=qty;changed=True
                    if kind=='launching_game':self.launches+=1;changed=True
                    if kind=='equipped_rod':self.joins+=1;changed=True
                    if path.name in ('recovery.jsonl','controls.jsonl') and kind not in ('screen','disconnect_observed'):
                        message=row.get('message') or row.get('reason') or kind.replace('_',' ')
                        self.activity.append({'at':row['at'],'kind':kind,'message':message});changed=True
                self.offsets[key]=f.tell()
        if changed:
            self.items.sort(key=lambda row:row['at']);self.activity.sort(key=lambda row:row['at']);self.version+=1
        return changed

    def export(self,directory=ROOT):
        directory=Path(directory)
        with (directory/'Item-log.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.writer(f);w.writerow(['Time (local)','Item','Quantity','Original screen text','Session'])
            for row in self.items:w.writerow([time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(row['at'])),row['item'],row['quantity'],row['raw'],row['session']])
        with (directory/'Item-totals.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.writer(f);w.writerow(['Item','Quantity'])
            w.writerows(self.counts.most_common())
        if self.started:
            archive=directory/'Logs';archive.mkdir(exist_ok=True)
            stamp=time.strftime('%Y%m%d-%H%M%S',time.localtime(self.started))
            shutil.copyfile(directory/'Item-log.csv',archive/f'Items-{stamp}.csv')
        return directory/'Item-log.csv'
