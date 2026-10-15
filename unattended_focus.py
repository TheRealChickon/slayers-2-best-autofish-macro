"""Overnight-only focus recovery gated by physical input inactivity."""
import time
from pynput import keyboard,mouse


INPUT_TAG=0xA17F15


def allowed(now,paused_at,last_physical,expires_at,wall_now,manual=False,grace=120,last_other_input=None):
    return (not manual and expires_at>wall_now and paused_at is not None
            and now-paused_at>=grace and now-last_physical>=45
            and (last_other_input is None or now-last_other_input>=grace))


class TaggedInput:
    def __init__(self,user):self.user=user
    def __getattr__(self,name):return getattr(self.user,name)
    def mouse_event(self,*args):self.user.mouse_event(*args[:-1],INPUT_TAG)
    def keybd_event(self,*args):self.user.keybd_event(*args[:-1],INPUT_TAG)


class PhysicalActivity:
    """Keep an activity timestamp only; never record key or pointer contents."""
    def __init__(self):
        self.last=time.monotonic()
        self.last_other_input=None
        self.listeners=[]

    def keyboard_event(self,message,data):
        if not data.flags&0x10:self.last=time.monotonic()  # LLKHF_INJECTED
        elif getattr(data,'dwExtraInfo',INPUT_TAG)!=INPUT_TAG:self.last_other_input=time.monotonic()
        return False

    def mouse_event(self,message,data):
        if not data.flags&1:self.last=time.monotonic()  # LLMHF_INJECTED
        elif getattr(data,'dwExtraInfo',INPUT_TAG)!=INPUT_TAG:self.last_other_input=time.monotonic()
        return False

    def start(self):
        self.listeners=[keyboard.Listener(win32_event_filter=self.keyboard_event),
                        mouse.Listener(win32_event_filter=self.mouse_event)]
        for listener in self.listeners:listener.start()

    def stop(self):
        for listener in self.listeners:listener.stop()
