"""Rebuild the visible journal from every confirmed item event in this run."""
import collections,csv,json,re,time,shutil
from pathlib import Path
from fishing_assistant import ROOT,RUN,is_reward_banner

from item_names import item_name

class Journal:
    def __init__(self):
        self.started=None;self.offsets={};self.prompts={};self.cycles={};self.items=[];self.activity=[];self.counts=collections.Counter();self.launches=0;self.joins=0;self.version=0;self.by_id={};self.corrections={}

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
                        item={'at':row['at'],'item':item_name(raw,self.prompts.get(cycle,'')),'quantity':qty,'raw':raw,'session':path.stem.removeprefix('events-'),'reward_id':row.get('reward_id')}
                        self.items.append(item);self.counts[item['item']]+=qty;changed=True
                        if item['reward_id']:self.by_id[item['reward_id']]=item
                    if kind=='inventory_resolved' and row.get('reward_id'):
                        self.corrections[row['reward_id']]=row;changed=True
                    if kind=='inventory_recovered' and row.get('reward_id') and row['reward_id'] not in self.by_id:
                        item={'at':row['at'],'item':row['item'],'quantity':row['quantity'],'raw':row.get('raw',''),
                              'session':path.stem.removeprefix('events-'),'reward_id':row['reward_id'],'source':'inventory'}
                        self.items.append(item);self.by_id[item['reward_id']]=item;self.counts[item['item']]+=item['quantity'];changed=True
                    if kind=='launching_game':self.launches+=1;changed=True
                    if kind=='equipped_rod':self.joins+=1;changed=True
                    if path.name in ('recovery.jsonl','controls.jsonl') and kind not in ('screen','disconnect_observed'):
                        message=row.get('message') or row.get('reason') or kind.replace('_',' ')
                        self.activity.append({'at':row['at'],'kind':kind,'message':message});changed=True
                self.offsets[key]=f.tell()
        if changed:
            for reward_id,correction in self.corrections.items():
                item=self.by_id.get(reward_id)
                if not item or item.get('source')=='inventory' or item['quantity']!=correction.get('quantity'):continue
                if item['item']!='Unidentified item' and not item['item'].endswith('(partial)'):continue
                self.counts[item['item']]-=item['quantity']
                if not self.counts[item['item']]:del self.counts[item['item']]
                item['item']=correction['item'];item['source']='inventory';self.counts[item['item']]+=item['quantity']
            self.items.sort(key=lambda row:row['at']);self.activity.sort(key=lambda row:row['at']);self.version+=1
        return changed

    def export(self,directory=ROOT):
        directory=Path(directory)
        with (directory/'Item-log.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.writer(f);w.writerow(['Time (local)','Item','Quantity','Original screen text','Session','Source'])
            for row in self.items:w.writerow([time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(row['at'])),row['item'],row['quantity'],row['raw'],row['session'],row.get('source','reward banner')])
        with (directory/'Item-totals.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.writer(f);w.writerow(['Item','Quantity'])
            w.writerows(self.counts.most_common())
        if self.started:
            archive=directory/'Logs';archive.mkdir(exist_ok=True)
            stamp=time.strftime('%Y%m%d-%H%M%S',time.localtime(self.started))
            shutil.copyfile(directory/'Item-log.csv',archive/f'Items-{stamp}.csv')
        return directory/'Item-log.csv'
