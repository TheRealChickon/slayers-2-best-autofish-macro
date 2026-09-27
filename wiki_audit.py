"""Audit overlapping archive screenshots for gaps before publishing a wiki."""
import json
import re
from collections import defaultdict
from pathlib import Path

from personal_wiki import snapshot_root


def normalize(name):
    return re.sub(r'\s+',' ',re.sub(r'^[Gθ★α] ','',name or '')).strip().casefold()


def audit(root=None):
    folder=Path(root or snapshot_root())/'archive-captures'
    pages=defaultdict(lambda:[None]*49)
    for file in folder.glob('p??-??.json'):
        record=json.loads(file.read_text(encoding='utf-8'))
        pages[record['page']][record['slot']]=normalize(record['name'])
    sequence=[];positions={}
    for page in sorted(pages):
        names=pages[page]
        if not sequence:start=0
        else:
            lower=max(0,len(sequence)-60)
            candidates=[]
            for start in range(lower,len(sequence)+20):
                matched=conflict=0
                for slot,name in enumerate(names):
                    index=start+slot
                    if not name or index>=len(sequence) or not sequence[index]:continue
                    if name==sequence[index]:matched+=1
                    else:conflict+=1
                candidates.append((matched*3-conflict*4,matched,-conflict,start))
            *_,start=max(candidates)
        positions[page]=start
        while len(sequence)<start+49:sequence.append(None)
        for slot,name in enumerate(names):
            if name and not sequence[start+slot]:sequence[start+slot]=name
    print('page starts:',positions)
    print('stitched slots:',len(sequence),'named slots:',sum(x is not None for x in sequence))
    print('gaps:',[(i,sequence[max(0,i-2):i+3]) for i,x in enumerate(sequence) if x is None])
    print('distinct names:',len(set(x for x in sequence if x)))
    return sequence


if __name__=='__main__':audit()
