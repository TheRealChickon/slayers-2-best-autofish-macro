"""Canonical names shared by inventory reconciliation and reward journals."""
import re

KNOWN={'coral':'Coral','silkthread':'Silk Thread','metalscraps':'Metal Scraps','seahorse':'Sea Horse','ouwfwesh':'OuwFwesh','ouwfish':'OuwFish','goldenfish':'Golden Fish','zebrafish':'Zebra Fish','clownfish':'Clown Fish','ore':'Ore'}


def inventory_name(raw):
    """Correct one spurious OCR letter only when one known item matches uniquely."""
    value=re.sub(r'[^a-z]','',raw.lower())
    if value in KNOWN:return KNOWN[value]
    candidates=[label for key,label in KNOWN.items() if len(value)==len(key)+1 and
                any(value[:i]+value[i+1:]==key for i in range(len(value)))]
    return candidates[0] if len(candidates)==1 else raw

def item_name(raw,prompt=''):
    def clean(value):
        value=re.sub(r'\bx\s*\d+\b|\bnew\b|\bT\b|collect|ollect|llect|\blect\b','',value,flags=re.I)
        return re.sub(r'[^a-z0-9]','',value.lower())
    known=KNOWN
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
