"""Read-only run projections from unique catch and worker activity events."""
import collections
import math
import re
import time
from reward_evidence import reward_quantity

# NPC (Ginzo) sell prices in gold (Wen), fish only. Confirmed in game by the
# user on 2026-10-15: Common 33 (OuwFish, OuwFwesh, Coral), Uncommon 66 (Clown
# Fish, Golden Fish, Zebra Fish), Legendary 165 (Crustadon, Krathulon). Sea
# Horse is not confirmed and uses the Common price. Materials and ores are not fish.
TIER_PRICES={'common':33,'uncommon':66,'legendary':165}
PRICES={'ouwfish':33,'ouwfwesh':33,'coral':33,'seahorse':TIER_PRICES['common'],'clownfish':66,'goldenfish':66,'zebrafish':66,
        'krathulon':165,'crustadon':165}
TIER_INFERRED={'seahorse'}
NAMES={'ouwfish':'OuwFish','ouwfwesh':'OuwFwesh','coral':'Coral','seahorse':'Sea Horse','clownfish':'Clown Fish',
       'goldenfish':'Golden Fish','zebrafish':'Zebra Fish','krathulon':'Krathulon','crustadon':'Crustadon'}
MIN_CATCHES=20
MIN_ACTIVE_SECONDS=600


def normalize(name):return re.sub(r'[^a-z0-9]','',name.casefold())


def identity(row):
    source=row.get('source','')
    reward_id=str(row.get('reward_id') or '')
    match=re.match(r'^(\d{8}-\d{6}):(\d+)(?::|$)',reward_id)
    if match:return ('cycle',match[1],int(match[2]))
    if row.get('cycle') is not None:
        session=re.fullmatch(r'events-(\d{8}-\d{6})\.jsonl',source)
        return ('cycle',session[1] if session else source,row['cycle'])
    return ('id',reward_id) if reward_id else ('legacy',source,row.get('at'))


def activity_seconds(rows,start,end,live_source=None):
    states={};intervals=[];last_seen={};uncertain=[]
    for row in rows:
        source=row.get('source','')
        if source=='recovery.jsonl' and row.get('event') in ('worker_exit','supervisor_stopped'):
            at=max(start,min(end,float(row.get('at',start))))
            intervals.extend((a,at) for a in states.values());states.clear();continue
        if not re.fullmatch(r'events-\d{8}-\d{6}\.jsonl',source):continue
        event=row.get('event');at=max(start,min(end,float(row.get('at',start))))
        last_seen[source]=at
        if event in ('started','input_resumed'):states.setdefault(source,at)
        elif event in ('input_paused','stopped','session_limit') and source in states:
            intervals.append((states.pop(source),at))
    for source,at in states.items():
        if source==live_source:intervals.append((at,end))
        else:
            intervals.append((at,last_seen[source]));uncertain.append(source)
    # Merge overlapping workers, so a duplicate process cannot inflate active time.
    total=0.;last=None
    for a,b in sorted(intervals):
        if last is None:last=[a,b]
        elif a<=last[1]:last[1]=max(last[1],b)
        else:total+=max(0,last[1]-last[0]);last=[a,b]
    if last:total+=max(0,last[1]-last[0])
    return total,uncertain


def calculate(rows,run,hours=8,now=None,live_source=None):
    from item_names import item_name
    hours=float(hours)
    if not math.isfinite(hours) or not .25<=hours<=168:raise ValueError('Prediction hours must be 0.25–168')
    now=time.time() if now is None else now
    start=run.get('started',now);end=run.get('ended') or now
    rows=sorted((r for r in rows if start<=r.get('at',0)<=end),key=lambda r:r['at'])
    prompts={};catches={};links={};corrections=[];sold={};legacy=0
    for row in rows:
        event=row.get('event');key=identity(row)
        if event=='pickup_hold':prompts[key]=row.get('text','')
        elif event in ('reward_observed','inventory_recovered'):
            if key in catches:continue
            if event=='reward_observed':
                raw=row.get('text','')
                quantity=reward_quantity(raw)
                if quantity is None:continue
                name=item_name(raw,prompts.get(key,''))
            else:name=row.get('item','Unidentified item');quantity=row.get('quantity',1)
            if not isinstance(quantity,int) or not 1<=quantity<=999:continue
            catches[key]={'name':name,'quantity':quantity}
            if row.get('reward_id'):links[row['reward_id']]=key
            legacy+=key[0]=='legacy'
        elif event=='inventory_resolved':corrections.append(row)
        elif event=='sale_confirmed' and row.get('confirmed') is True:
            value=row.get('proceeds_wen')
            if isinstance(value,(int,float)) and math.isfinite(value) and value>=0:
                sold.setdefault(row.get('sale_id') or (row.get('source'),row.get('at')),value)
    for row in corrections:
        key=links.get(row.get('reward_id'),identity(row))
        if key in catches and row.get('item'):catches[key]['name']=row['item']
    items={}
    for catch in catches.values():
        name=catch['name'];key=normalize(name)
        item=items.setdefault(key,{'name':NAMES.get(key,name),'catches':0,'quantity':0,'unit_price_wen':PRICES.get(key),'price_inferred':key in TIER_INFERRED})
        item['catches']+=1;item['quantity']+=catch['quantity']
    active,uncertain=activity_seconds(rows,start,end,live_source)
    enough=len(catches)>=MIN_CATCHES and active>=MIN_ACTIVE_SECONDS and not uncertain
    known=0;unknown=0
    for item in items.values():
        item['items_per_hour']=item['quantity']*3600/active if active else None
        item['projected_quantity']=item['items_per_hour']*hours if enough else None
        price=item['unit_price_wen']
        item['estimated_npc_value_wen']=None if price is None else item['quantity']*price
        item['projected_npc_value_wen']=None if price is None or not enough else item['projected_quantity']*price
        if price is None:unknown+=item['quantity']
        else:known+=item['estimated_npc_value_wen']
    warnings=[]
    if not enough:warnings.append(f'Insufficient sample: need {MIN_CATCHES} unique catches and {MIN_ACTIVE_SECONDS//60} active minutes before projecting.')
    if any(item['catches']<5 for item in items.values()):warnings.append('Items with fewer than 5 catches have a small sample.')
    if legacy:warnings.append(f'{legacy} legacy observations lack a stable catch identity; repeats may remain.')
    if uncertain:warnings.append('Incomplete worker activity records: time is bounded by the last event; projections withheld.')
    projected_known=sum(i['projected_npc_value_wen'] for i in items.values() if i['projected_npc_value_wen'] is not None)
    return {'run_id':run.get('id'),'hours':hours,'elapsed_seconds':max(0,end-start),'active_seconds':active,
            'unique_catches':len(catches),'quantity':sum(c['quantity'] for c in catches.values()),
            'items_per_hour':sum(c['quantity'] for c in catches.values())*3600/active if active else None,
            'projection_available':enough,'items':sorted(items.values(),key=lambda item:(-item['quantity'],item['name'])),
            'known_price_subtotal_wen':known if any(i['unit_price_wen'] is not None for i in items.values()) else None,
            'projected_known_price_subtotal_wen':projected_known if enough and any(i['unit_price_wen'] is not None for i in items.values()) else None,
            'unknown_price_quantity':unknown,'known_price_per_hour_wen':known*3600/active if active>=120 and any(i['unit_price_wen'] is not None for i in items.values()) else None,'actual_sold_proceeds_wen':sum(sold.values()) if sold else None,'warnings':warnings}


def load(root,run,hours=8,now=None):
    from run_log import rows
    from discord_hourly import read_json
    import psutil
    now=time.time() if now is None else now
    worker=read_json(root/'status.json');lock=read_json(root/'pid.json');live=None
    if worker.get('running') and now-worker.get('updated',0)<10 and worker.get('pid')==lock.get('pid'):
        try:
            if abs(psutil.Process(lock['pid']).create_time()-lock['created'])<1:
                live='events-'+worker['session']+'.jsonl'
        except (psutil.Error,KeyError,TypeError):pass
    return calculate(rows(root,run),run,hours,now,live)
