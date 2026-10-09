"""A smaller detector pass may authorize only an explicit strong Collect cue."""
from pickup_policy import clear_collect


def read_cached_prompt(image,normal,fast,after_minigame=False,guard=lambda:None):
    result,_=fast(image,use_cls=False);guard()
    rows=[]
    for box,text,score in result or []:
        rows.append({'text':text,'score':float(score),
                     'center':(sum(point[0] for point in box)/len(box),
                               sum(point[1] for point in box)/len(box))})
    if clear_collect(rows,after_minigame=after_minigame):
        return result,True
    # Empty, weak, ambiguous, reward and non-fishing reads retain the original
    # detector. An inexpensive miss never becomes cached permission to press T.
    result,_=normal(image,use_cls=False);guard()
    return result,False
