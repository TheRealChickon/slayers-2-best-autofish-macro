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
           f"Wiki generated {data['captured_at']} from saved UI/OCR captures; verify unclear text against linked detail images.",'',
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
        lines += ['', 'Owned but untested against Stone Haori in a same-mastery M1 swap: Serpent Haori and Flame Haori Style 1 each display a 1.07x Additional Damage Factor. Their higher displayed factor is not proof of higher actual damage.', '']
        lines += ['', 'The 0.025 base M1 per Gauntlet mastery level is inferred from measured levels 183–186; changing gear requires another measurement.', '']
        lines += [f"- {limit}" for limit in build.get('limits',[])]
        lines += ['']
    if data.get('boss_analysis'):
        boss=data['boss_analysis']; summary=boss.get('summary',{})
        lines+=['## Boss fights measured from recording','',
                f"{summary.get('solo_fights',0)} solo-credit fights; median {summary.get('overall_median_seconds','unknown')} seconds, mean {summary.get('overall_mean_seconds','unknown')} seconds of engaged combat. All shown boss bars are 3,000 HP.",
                'Times are approximate because the video was sampled every three seconds. Travel, respawn waits and menus are excluded. Shared-damage and incomplete fights were excluded.','']
        for row in boss.get('bosses',[]):
            lines.append(f"- {row['name']}: median {row['median_seconds']}s, observed {row['min_seconds']}–{row['max_seconds']}s across {row['count']} clean fights")
        economy=boss.get('economy') or {}
        if economy:
            lines+=['','## Boss farming income without 2x Wen','',
                    f"Normal reward {economy['base_wen_per_boss']} Wen + {economy['coin_pouches_per_boss_min']}–{economy['coin_pouches_per_boss_max']} coin pouches worth {economy['coin_pouch_wen_each']} Wen each = {economy['wen_per_boss_without_2x_min']:,}–{economy['wen_per_boss_without_2x_max']:,} Wen per boss.",
                    f"{economy['clean_kills']} clean kills in {round(economy['recording_seconds']/60,1)} minutes = {economy['clean_kills_per_hour']} kills/hour and about {economy['estimated_wen_per_hour_min']:,}–{economy['estimated_wen_per_hour_max']:,} Wen/hour gross, including redeemed pouches.",
                    economy['assumption'],'']
        lines+=['','Video damage anchors: 64.78 Gauntlet M1 at mastery 202 with displayed +35.888 Additional Damage and 1.461x factor; Shockwave ticks of 37.57 and 38.23 at Shockwave mastery 206. Other visible hits range roughly 60–78 but cannot be assigned confidently to named skills from the sampled recording. Earlier same-gear M1 tests at mastery 183–186 imply about +0.0365 displayed M1 per Gauntlet mastery level.','']
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


HTML=(Path(__file__).with_name('wiki_template.html')).read_text(encoding='utf-8')


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
    boss_file=root/'boss-analysis.json'
    boss_analysis=json.loads(boss_file.read_text(encoding='utf-8')) if boss_file.exists() else None
    data={'captured_at':time.strftime('%Y-%m-%d %H:%M %Z'),'counts':{'inventory':len(owned),'inventory_grid':len(grid),'archive_only':len(archive_only),'archive_total':len(archive_all)},
          'inventory':[public_record(r) for r in owned],
          'archive_only':[public_record(r) for r in archive_only],
          'equipped':[public_record(r) for r in equipped],
          'baseline':baseline,
          'profile':profile,
          'damage_build':damage_profile or None,
          'boss_analysis':boss_analysis}
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
    for relative in (['field-banner.jpg','world-probe.jpg'] + [x.get('file') for x in (boss_analysis or {}).get('evidence',[])]):
        if relative and (root/relative).exists():
            (assets/relative).parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(root/relative,assets/relative)
    (site/'index.html').write_text(HTML,encoding='utf-8')
    shutil.copy2(Path(__file__).with_name('wiki_site.css'),site/'site.css')
    shutil.copy2(Path(__file__).with_name('wiki_site.js'),site/'site.js')
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
