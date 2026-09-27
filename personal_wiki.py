"""Build a local, searchable item wiki and plain-text AI context from UI captures.

Captures and output remain in the account's ignored data directory.
"""
import argparse
import difflib
import html
import json
import re
import shutil
import time
import webbrowser
from collections import defaultdict
from pathlib import Path

import cv2
from rapidocr_onnxruntime import RapidOCR

from metrics import RUN
from damage_build import load_profile as load_damage_profile


def snapshot_root():
    return RUN if (RUN/'inventory-captures').exists() else RUN/'wiki-snapshot'


def ocr_badges(icon_path, engine):
    image=cv2.imread(str(icon_path))
    if image is None:return None,0
    h,w=image.shape[:2]
    if h<80 or w<80:return None,0
    def words(crop):
        found,_=engine(cv2.resize(crop,None,fx=4,fy=4))
        return [str(row[1]).replace(' ','') for row in (found or [])]
    qty=None
    for value in words(image[:min(50,h),max(0,w-55):]):
        match=re.search(r'[xX×](\d{1,6})',value)
        if match:qty=int(match[1]);break
    level=0
    for value in words(image[:min(48,h),:min(62,w)]):
        match=re.search(r'\+(\d{1,2})',value)
        if match:level=max(level,int(match[1]))
    return qty,level


def sections(record):
    rows=record.get('lines') or []
    text=[r['text'].strip() for r in rows if r.get('text') and r.get('confidence',1)>=.5]
    name=record.get('name') or ''
    rarity=record.get('rarity') or ''
    idx=next((i for i,x in enumerate(text) if x.lower()==rarity.lower()),0)
    rest=text[idx+1:]
    out={'description':[],'stats':[],'source_info':[]}
    bucket='description'
    for line in rest:
        low=line.lower().strip(': ')
        if low=='stats':bucket='stats';continue
        if low=='source':bucket='source_info';continue
        if low in ('equip','unequip','use','delete'):continue
        out[bucket].append(line)
    joined=[]
    for line in out['stats']:
        if joined and joined[-1].count('(')>joined[-1].count(')'):
            joined[-1]+=' '+line
        else:
            joined.append(line)
    out['stats']=joined
    return out


def load_records(root,folder):
    result=[]
    for file in sorted((root/folder).glob('*.json')):
        try:record=json.loads(file.read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        record['_file']=file.name
        result.append(record)
    return result


def selected_inventory(records):
    # The source grid has 123 entries. A fixed top slice and the scrolled
    # lower slices overlap intentionally, so take each grid position once.
    return [r for r in records if
            (r.get('page')=='top-accurate' and 0<=r.get('slot',-1)<40) or
            (r.get('page')=='bottom-verified' and 0<=r.get('slot',-1)<83)]


def clean_name(value):
    name=re.sub(r'\s+',' ',str(value or '').strip())
    # All three captured detail images show the Roman numeral II. OCR reads
    # its second stroke as either lowercase l or drops it entirely.
    if name in ('Demonic Horns I','Demonic Horns Il'):
        return 'Demonic Horns II'
    return name


def build_records(root):
    engine=RapidOCR()
    inventory=selected_inventory(load_records(root,'inventory-captures'))
    archive=load_records(root,'archive-captures')
    equipped=load_records(root,'equipped-captures')
    archive_names={clean_name(r.get('name')) for r in archive}
    for r in inventory+archive+equipped:
        r['name']=clean_name(r.get('name'))
        if r['name'].startswith('★ '):r['name']=r['name'][2:]
        for prefix in ('G ','θ '):
            if r['name'].startswith(prefix) and r['name'][2:] in archive_names:
                r['name']=r['name'][2:]
                break
        if r in inventory and r['name'] not in archive_names:
            nearest=difflib.get_close_matches(r['name'],archive_names,n=2,cutoff=.94)
            if len(nearest)==1 or (nearest and difflib.SequenceMatcher(None,r['name'],nearest[0]).ratio()-difflib.SequenceMatcher(None,r['name'],nearest[1]).ratio()>.04):
                r['name']=nearest[0]
        r.update(sections(r))
        if r['source']=='inventory':
            qty,level=ocr_badges(root/r['icon'],engine)
            if r.get('variant') is None:r['quantity']=qty or r.get('quantity') or 1
            else:r['quantity']=1
            r['refinement']=max(level,r.get('refinement') or 0)
        else:
            r['quantity']=None
            r['refinement']=0
    # Combine copies from one grouped slot; keep unlike refined variants apart.
    grouped=defaultdict(list)
    for r in inventory:
        key=(r['name'].casefold(),r.get('rarity'),r.get('refinement'),tuple(r.get('stats') or []))
        grouped[key].append(r)
    owned=[]
    for group in grouped.values():
        first=group[0].copy()
        first['quantity']=sum(int(r.get('quantity') or 1) for r in group)
        first['captures']=[r['_file'] for r in group]
        owned.append(first)
    owned.sort(key=lambda r:r['name'].casefold())
    # Archive passes intentionally overlap. Prefer the clearest title and
    # preserve its base stats separately from live refined inventory stats.
    archive_by_name={}
    for r in archive:
        name=r['name'].casefold()
        if not name:continue
        score=len(r.get('stats') or [])*3+len(r.get('description') or [])+len(r.get('source_info') or [])
        if name not in archive_by_name or score>archive_by_name[name][0]:archive_by_name[name]=(score,r)
    archive_unique=[v[1] for v in archive_by_name.values()]
    archive_unique.sort(key=lambda r:r['name'].casefold())
    owned_names={r['name'].casefold() for r in owned}
    for r in owned:
        base=archive_by_name.get(r['name'].casefold())
        if base:
            b=base[1]
            r['archive_stats']=b.get('stats') or []
            r['archive_detail_image']=b.get('detail_image')
            r['archive_icon']=b.get('icon')
    archive_only=[r for r in archive_unique if r['name'].casefold() not in owned_names]
    equipped_names={r['name'].casefold() for r in equipped}
    for r in owned:r['equipped']=r['name'].casefold() in equipped_names
    return owned,archive_only,archive_unique,equipped


def public_record(record):
    keys=('name','rarity','source','quantity','refinement','description','stats','source_info',
          'icon','detail_image','archive_stats','archive_detail_image','archive_icon','equipped')
    return {key:record.get(key) for key in keys if key in record}


def markdown(data):
    lines=['# Personal fishing-game inventory context','',
           f"Captured {data['captured_at']}. This is a UI/OCR snapshot; verify unclear text against linked detail images.",'',
           f"Inventory: {data['counts']['inventory']} distinct variants across {data['counts']['inventory_grid']} grid entries. Archive-only: {data['counts']['archive_only']}. Equipped: {len(data['equipped'])}.",'',
           'Inventory stats below are the current displayed values, including refinement. Archive stats are unrefined reference values and are never substituted for owned stats.','']
    if data.get('baseline'):
        lines+=['## Stats with stat gear unequipped','',
                'The equipped fishing titles and vanity stayed on. Values below are the bottom-left HUD capture; the screenshot preserves icon labels and OCR ambiguities.',
                '']
        if data.get('profile'):
            lines.append(json.dumps(data['profile'].get('naked_hud_summary'),ensure_ascii=False,indent=2))
        lines+=['',f"HUD image: assets/{data['baseline']['image']}",'']
    if data.get('profile'):
        profile=data['profile']
        lines+=['## Character','',f"{profile['player']} · Lv {profile['level']} {profile['race']} · {profile['clan']}",
                f"Equipped titles: {', '.join(profile['equipped_titles'])}",
                f"Equipped HUD image: assets/{profile['equipped_hud_image']}",'']
    if data.get('damage_build'):
        build=data['damage_build']; anchor=build.get('calibration',{})
        lines+=['## Later measured M1 build','',
                'This later in-game M1 calibration supersedes older heuristic build suggestions below. The weapon uses a separate slot from five Stats items.',
                '',f"Saved Gauntlet mastery: {build.get('mastery','unknown')}",
                f"Measured M1: {anchor.get('m1','unknown')} at mastery {anchor.get('mastery','unknown')}",
                f"Damage factor at measurement: {anchor.get('damage_factor','unknown')}x",'']
        lines += [f"- {name}" for name in build.get('stat_items',[])]
        lines += ['',f"Separate weapon: {build.get('weapon','unknown')}",'']
        lines += [f"- {test}" for test in build.get('tests',[])]
        lines += ['', 'The 0.025 base M1 per Gauntlet mastery level is inferred from measured levels 183–186; changing gear requires another measurement.', '']
        lines += [f"- {limit}" for limit in build.get('limits',[])]
        lines += ['']
    if data.get('profile'):
        profile=data['profile']
        lines+=['## Earlier capture damage notes','']
        lines += [f"- {note}" for note in profile['damage_assessment']]
        lines+=['',profile['assessment_limit'],'']
    lines+=['## Currently equipped','']
    for r in data['equipped']:
        lines.append(f"- {r['name']} — {', '.join(r.get('stats') or []) or 'no displayed stats'}")
    lines+=['','## Inventory','']
    for r in data['inventory']:
        suffix=f" +{r['refinement']}" if r.get('refinement') else ''
        lines.append(f"### {r['name']}{suffix} ×{r['quantity']} ({r.get('rarity') or 'rarity unread'})" )
        lines.append(f"Live stats: {'; '.join(r.get('stats') or []) or 'none shown'}")
        if r.get('archive_stats'):lines.append(f"Archive base stats: {'; '.join(r['archive_stats'])}")
        if r.get('description'):lines.append(f"Description: {' '.join(r['description'])}")
        lines.append(f"Icon: assets/{r['icon']} | Detail image: assets/{r['detail_image']}")
        lines.append('')
    lines+=['## Archive only','']
    for r in data['archive_only']:
        lines.append(f"### {r['name']} ({r.get('rarity') or 'rarity unread'})")
        lines.append(f"Archive stats: {'; '.join(r.get('stats') or []) or 'none shown'}")
        if r.get('description'):lines.append(f"Description: {' '.join(r['description'])}")
        if r.get('source_info'):lines.append(f"Source: {'; '.join(r['source_info'])}")
        lines.append(f"Icon: assets/{r['icon']} | Detail image: assets/{r['detail_image']}")
        lines.append('')
    return '\n'.join(lines)


HTML='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Field Notes — Item Archive</title>
<style>
:root{color-scheme:dark;--ink:#101714;--panel:#19231e;--panel2:#223027;--line:#344039;--text:#e5e8dc;--muted:#a6b1a4;--gold:#d9b970;--mint:#91c4a9}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 80% -20%,#2b382b 0,transparent 45%),#101714;color:var(--text);font:15px/1.45 system-ui,Segoe UI,sans-serif}button,input{font:inherit}button{cursor:pointer}header{padding:34px clamp(20px,4vw,64px) 20px;border-bottom:1px solid var(--line)}header .eyebrow{color:var(--gold);font-size:11px;letter-spacing:.25em;text-transform:uppercase}h1{font:500 clamp(30px,4vw,52px)/1.05 Georgia,serif;margin:8px 0 11px}header p{margin:0;color:var(--muted);max-width:750px}.shell{display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,390px);gap:20px;padding:24px clamp(20px,4vw,64px)}.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:20px}.toolbar input{min-width:200px;flex:1;background:#19231e;color:var(--text);border:1px solid var(--line);border-radius:7px;padding:11px 14px;outline:none}.toolbar input:focus{border-color:var(--mint)}.tab{border:0;background:transparent;color:var(--muted);padding:10px 12px;border-bottom:2px solid transparent}.tab.active{color:var(--gold);border-color:var(--gold)}.count{color:var(--muted);font-size:13px;margin-left:auto}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}.card{border:1px solid var(--line);background:linear-gradient(145deg,#222e26,#18221d);border-radius:9px;padding:13px;text-align:left;color:var(--text);transition:transform .16s,border-color .16s,background .16s}.card:hover,.card.active{transform:translateY(-2px);border-color:var(--gold);background:#283629}.card img{display:block;width:72px;height:72px;object-fit:cover;border-radius:5px;margin-bottom:13px}.card strong{display:block;font-weight:600;min-height:42px}.card small{display:block;color:var(--muted);margin-top:5px}.badge{color:var(--mint)}aside{position:sticky;top:18px;height:calc(100vh - 36px);overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:24px}aside .hero{width:88px;height:88px;object-fit:cover;border-radius:8px}aside h2{font:500 29px/1.1 Georgia,serif;margin:15px 0 8px}.rarity{color:var(--gold);font-size:12px;letter-spacing:.1em;text-transform:uppercase}h3{font-size:11px;color:var(--muted);letter-spacing:.18em;text-transform:uppercase;margin:26px 0 9px}aside p{margin:8px 0;color:var(--text)}.stat{padding:8px 0;border-bottom:1px solid var(--line)}.source{color:var(--muted)}.links{display:flex;gap:14px;flex-wrap:wrap;margin-top:22px}.links a{color:var(--mint);text-decoration:none}.links a:hover{text-decoration:underline}footer{padding:20px clamp(20px,4vw,64px);color:var(--muted);border-top:1px solid var(--line)}footer a{color:var(--gold)}@media(max-width:850px){.shell{display:block}aside{position:static;height:auto;margin-top:24px}.grid{grid-template-columns:repeat(auto-fill,minmax(140px,1fr))}}
</style><header><div class="eyebrow">Private field notes · local snapshot</div><h1>Item archive</h1><p>Owned items use the stats shown in your inventory. Archive entries provide the base reference for everything else, with refined values kept separate.</p></header><main class="shell"><section><div class="toolbar"><input id="search" type="search" placeholder="Find an item or stat…" aria-label="Search items"><button class="tab active" data-tab="inventory">Inventory</button><button class="tab" data-tab="archive">Archive only</button><button class="tab" data-tab="equipped">Equipped</button><span class="count" id="count"></span></div><div class="grid" id="grid"></div></section><aside id="detail"><div class="eyebrow">Select an item</div></aside></main><footer><span id="stamp"></span> · <a href="context.md">AI context</a> · <a href="items.json">Structured JSON</a> · Values transcribed from game UI; open each detail image to check OCR.</footer><script src="data.js"></script><script>
const data=window.WIKI_DATA;let tab='inventory',chosen=null;const $=id=>document.getElementById(id);const safe=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));const path=s=>s?'assets/'+encodeURI(s):'';const list=()=>tab==='inventory'?data.inventory:tab==='archive'?data.archive_only:data.inventory.filter(x=>x.equipped);function render(){let q=$('search').value.trim().toLowerCase(),items=list().filter(x=>(x.name+' '+(x.stats||[]).join(' ')).toLowerCase().includes(q));$('count').textContent=items.length+' shown';$('grid').innerHTML=items.map((x,i)=>`<button class="card ${chosen===x?'active':''}" data-index="${i}"><img src="${path(x.icon)}" alt=""><strong>${safe(x.name)}${x.refinement?' <span class="badge">+'+x.refinement+'</span>':''}</strong><small>${safe(x.rarity||'Unknown')} · ${x.source==='inventory'?'×'+x.quantity:'archive'}</small></button>`).join('');for(const b of $('grid').children)b.onclick=()=>{chosen=items[+b.dataset.index];detail(chosen);render()};if(chosen&&!items.includes(chosen)){chosen=null;$('detail').innerHTML='<div class="eyebrow">Select an item</div>'}}function detail(x){let stats=x.stats||[],base=x.archive_stats||[],desc=x.description||[],source=x.source_info||[];$('detail').innerHTML=`<img class="hero" src="${path(x.icon)}" alt=""><div class="rarity">${safe(x.rarity||'Unknown')} · ${x.source==='inventory'?'Owned ×'+x.quantity:'Archive'}</div><h2>${safe(x.name)}${x.refinement?' +'+x.refinement:''}</h2>${x.equipped?'<div class="badge">Equipped now</div>':''}<p>${safe(desc.join(' '))}</p><h3>${x.source==='inventory'?'Current inventory stats':'Archive stats'}</h3>${stats.length?stats.map(s=>`<div class="stat">${safe(s)}</div>`).join(''):'<p class="source">No stats shown</p>'}${base.length?'<h3>Archive base stats</h3>'+base.map(s=>`<div class="stat source">${safe(s)}</div>`).join(''):''}${source.length?'<h3>Source</h3>'+source.map(s=>`<p class="source">${safe(s)}</p>`).join(''):''}<div class="links"><a href="${path(x.detail_image)}" target="_blank">View captured detail ↗</a>${x.archive_detail_image?`<a href="${path(x.archive_detail_image)}" target="_blank">View base detail ↗</a>`:''}</div>`}document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;chosen=null;document.querySelectorAll('.tab').forEach(c=>c.classList.toggle('active',c===b));render()});$('search').oninput=render;$('stamp').textContent='Captured '+data.captured_at;render();
</script></html>'''


PROFILE_STYLE='''
[hidden]{display:none!important}.shell.character-open{display:block}.shell.character-open aside{display:none}
.profile{max-width:1180px}.profile-heading{display:flex;justify-content:space-between;gap:20px;align-items:end;flex-wrap:wrap;margin:4px 0 25px}.profile h2{font:500 34px/1.1 Georgia,serif;margin:3px 0}.profile small{color:var(--muted)}
.profile-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.profile-stat{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px}.profile-stat b{display:block;font-size:22px;color:var(--gold);font-weight:500}.profile-stat span{color:var(--muted);font-size:12px}
.profile h3{font-size:11px;color:var(--gold);letter-spacing:.19em;text-transform:uppercase;margin:31px 0 13px}.title-list{display:flex;gap:9px;flex-wrap:wrap}.title-list span{background:#233228;color:var(--text);padding:6px 10px;border-radius:5px}.snapshots{display:grid;grid-template-columns:1fr 1fr;gap:15px}.snapshot{display:block;color:var(--muted);text-decoration:none}.snapshot img{display:block;width:100%;max-height:275px;object-fit:cover;object-position:bottom left;border:1px solid var(--line);border-radius:8px;margin-bottom:6px}.snapshot:hover{color:var(--mint)}.assessment{margin:0;padding-left:22px;max-width:880px}.assessment li{padding:0 0 12px 5px}.assessment-limit{color:var(--muted);font-size:13px}@media(max-width:700px){.snapshots{display:block}.snapshot{margin-bottom:14px}}
'''

PROFILE_SCRIPT='''
const originalRender=render;
render=function(){
  const active=tab==='character',p=$('profile'),g=$('grid'),a=$('detail');
  p.hidden=!active;g.hidden=active;a.hidden=active;
  document.querySelector('.shell').classList.toggle('character-open',active);
  $('search').hidden=active;
  if(!active){originalRender();return}
  const c=data.profile||{},b=data.baseline||{},s=c.naked_hud_summary||{};
  $('count').textContent='snapshot';
  const stat=(value,label)=>`<div class="profile-stat"><b>${safe(value||'—')}</b><span>${safe(label)}</span></div>`;
  const title=(c.equipped_titles||[]).map(x=>`<span>${safe(x)}</span>`).join('');
  const shots=[['Stat gear unequipped',b.image],['Current loadout',c.equipped_hud_image]].filter(x=>x[1]).map(([label,file])=>`<a class="snapshot" href="${path(file)}" target="_blank"><img src="${path(file)}" alt="${safe(label)} HUD capture">${safe(label)} ↗</a>`).join('');
  p.innerHTML=`<div class="profile-heading"><div><small>${safe(c.player||'Character')} · ${safe(c.clan||'')}</small><h2>Lv ${safe(c.level||'?')} ${safe(c.race||'')}</h2></div><small>Captured loadout · ${safe(data.captured_at)}</small></div>
    <div class="profile-stats">${stat(s.health,'Health without stat gear')}${stat(s.additional_damage,'Additional Damage without stat gear')}${stat(s.additional_damage_factor,'Damage factor without stat gear')}${stat((data.equipped||[]).length,'Items currently equipped')}</div>
    <h3>Equipped titles</h3><div class="title-list">${title}</div>
    <h3>Bottom-left HUD</h3><div class="snapshots">${shots}</div><p class="assessment-limit">${safe(b.label||'')} · Remaining unlabeled HUD values, in display order: ${safe((s.other_displayed_values_in_hud_order||[]).join(' · '))}</p>
    <h3>Damage notes</h3><ol class="assessment">${(c.damage_assessment||[]).map(x=>`<li>${safe(x)}</li>`).join('')}</ol><p class="assessment-limit">${safe(c.assessment_limit||'')}</p>`;
  const m=data.damage_build;
  if(m){const a=m.calibration||{};
    p.innerHTML+=`<h3>Later measured M1 build</h3><p>Five Stats slots: ${safe((m.stat_items||[]).join(' · '))}. Weapon: ${safe(m.weapon||'unknown')} in a separate slot.</p><p>${safe(a.m1||'—')} M1 at Gauntlet mastery ${safe(a.mastery||'—')} with ${safe(a.damage_factor||'—')}x damage factor. This later live test takes priority over earlier estimates above.</p><ol class="assessment">${(m.tests||[]).map(x=>`<li>${safe(x)}</li>`).join('')}</ol><p class="assessment-limit">Mastery adds about 0.025 base M1 per level in the observed 183–186 range. Changed equipment needs another live calibration.</p>`;
  }
};
'''

HTML=HTML.replace('</style>','</style><style>'+PROFILE_STYLE+'</style>')
HTML=HTML.replace('<button class="tab" data-tab="equipped">Equipped</button>',
                  '<button class="tab" data-tab="equipped">Equipped</button><button class="tab" data-tab="character">Character</button>')
HTML=HTML.replace('<div class="grid" id="grid"></div>',
                  '<div class="profile" id="profile" hidden></div><div class="grid" id="grid"></div>')
HTML=HTML.replace('</script></html>',PROFILE_SCRIPT+'</script></html>')


def build(root=None,open_site=False):
    root=Path(root or snapshot_root())
    root.mkdir(parents=True,exist_ok=True)
    owned,archive_only,archive_all,equipped=build_records(root)
    grid={('top',r['slot']) for r in load_records(root,'inventory-captures') if r.get('page')=='top-accurate' and r.get('slot',99)<40}
    grid.update({('bottom',r['slot']) for r in load_records(root,'inventory-captures') if r.get('page')=='bottom-verified' and r.get('slot',99)<83})
    baseline_file=root/'baseline.json'
    baseline=json.loads(baseline_file.read_text(encoding='utf-8')) if baseline_file.exists() else None
    profile_file=root/'profile.json'
    profile=json.loads(profile_file.read_text(encoding='utf-8')) if profile_file.exists() else None
    damage_root=root.parent if root.name=='wiki-snapshot' else root
    damage_profile=load_damage_profile(damage_root)
    data={'captured_at':time.strftime('%Y-%m-%d %H:%M %Z'),'counts':{'inventory':len(owned),'inventory_grid':len(grid),'archive_only':len(archive_only),'archive_total':len(archive_all)},
          'inventory':[public_record(r) for r in owned],
          'archive_only':[public_record(r) for r in archive_only],
          'equipped':[public_record(r) for r in equipped],
          'baseline':baseline,
          'profile':profile,
          'damage_build':damage_profile or None}
    site=root/'site';site.mkdir(exist_ok=True)
    assets=site/'assets'
    for record in data['inventory']+data['archive_only']+data['equipped']:
        for field in ('icon','detail_image','archive_icon','archive_detail_image'):
            relative=record.get(field)
            if not relative:continue
            source=root/relative
            destination=assets/relative
            if source.exists():
                destination.parent.mkdir(parents=True,exist_ok=True)
                if not destination.exists() or source.stat().st_mtime>destination.stat().st_mtime:
                    shutil.copy2(source,destination)
    for relative in (baseline.get('image') if baseline else None,
                     profile.get('equipped_hud_image') if profile else None):
        if relative and (root/relative).exists():
            shutil.copy2(root/relative,assets/relative)
    (site/'index.html').write_text(HTML,encoding='utf-8')
    (site/'data.js').write_text('window.WIKI_DATA='+json.dumps(data,ensure_ascii=False).replace('</','<\\/')+';',encoding='utf-8')
    (site/'items.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    (site/'context.md').write_text(markdown(data),encoding='utf-8')
    if open_site:webbrowser.open((site/'index.html').as_uri())
    return site/'index.html',data['counts']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path)
    parser.add_argument('--open',action='store_true')
    args=parser.parse_args()
    file,counts=build(args.root,args.open)
    print(json.dumps({'site':str(file),'counts':counts},ensure_ascii=True))


if __name__=='__main__':main()
