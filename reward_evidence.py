"""Bound reward amounts consistently in live vision and read-only reports."""
import re


def reward_quantity(text):
    if re.search(r'collect|climb|purchase',text,re.I):return None
    amounts=re.findall(r'\bx\s*(\d+)\b',text,re.I)
    if amounts:
        if len(amounts)!=1 or not re.fullmatch(r'[1-9]\d?',amounts[0]):return None
        return int(amounts[0])
    return 1 if re.search(r'\bnew\b',text,re.I) else None
