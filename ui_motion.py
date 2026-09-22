"""Small Tk animations; no window effects or external rendering runtime."""
import time
import tkinter as tk


def mix(a,b,t):
    first=[int(a[i:i+2],16) for i in (1,3,5)]
    second=[int(b[i:i+2],16) for i in (1,3,5)]
    return '#'+''.join(f'{round(x+(y-x)*t):02x}' for x,y in zip(first,second))


def tween(widget, apply, seconds=.22, enabled=True):
    started=time.monotonic()
    def step():
        if not widget.winfo_exists():return
        t=min(1,(time.monotonic()-started)/seconds) if enabled else 1
        apply(1-(1-t)**3)
        if t<1:widget.after(16,step)
    step()


class SoftButton(tk.Button):
    def __init__(self,*args,motion=lambda:True,**kwargs):
        kwargs.update(highlightthickness=0,borderwidth=0,relief='flat',overrelief='flat')
        self.motion=motion;self.base=kwargs.get('bg','#242727');self.generation=0
        super().__init__(*args,**kwargs)
        self.bind('<Enter>',lambda event:self.fade(mix(self.base,'#ffffff',.1)))
        self.bind('<Leave>',lambda event:self.fade(self.base))
    def configure(self,cnf=None,**kwargs):
        if 'bg' in kwargs:
            self.base=kwargs['bg'];self.generation+=1
            kwargs['activebackground']=mix(self.base,'#ffffff',.1)
        return super().configure(cnf,**kwargs)
    config=configure
    def fade(self,target):
        if self.cget('state')=='disabled':return
        self.generation+=1;generation=self.generation;start=self.cget('bg')
        def apply(t):
            if generation==self.generation:
                value=mix(start,target,t)
                tk.Button.configure(self,bg=value,activebackground=value)
        tween(self,apply,.16,self.motion())
