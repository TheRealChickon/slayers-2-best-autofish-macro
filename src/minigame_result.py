"""Read result percentages without turning clipped 100% text into a failure."""
import re
import cv2


def percent_value(rows):
    values=[]
    for row in rows or []:
        if row[2]<.85:continue
        match=re.fullmatch(r'(100|[1-9]\d?|0)\s*%',row[1].strip())
        if match:values.append(int(match[1]))
    return values[0] if len(values)==1 else None


def read_percent(frame,ocr,guard=lambda:None):
    readings=[]
    for scale in (3,4):
        # The small old crop let OCR report "00%" for a visible 100%.
        image=cv2.resize(frame[1250:1370,1100:1460],None,fx=scale,fy=scale)
        rows,_=ocr(image,use_cls=False);guard()
        readings.append({'scale':scale,'rows':[{'text':row[1],'score':float(row[2])} for row in rows or []]})
        value=percent_value(rows)
        if len(readings)==1:
            if value is None or value==100:return value,readings
            first=value
        else:
            # A sub-100 reading can trigger an unattended failure response.
            # Confirm it at another scale; contradictory/clipped text is unknown.
            return first if value==first else None,readings
