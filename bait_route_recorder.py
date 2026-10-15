"""Foreground-only, physical-input route recorder for the player's own demonstration."""
import argparse
import ctypes
import json
import os
import queue
import shutil
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import psutil
import tkinter as tk
from tkinter import messagebox
import win32api
import win32con
import win32gui
import win32process
from pynput import keyboard, mouse

from app_config import ROOT, data_directory
from capture_session import CaptureSession
from discord_hourly import atomic_json
from dpi import dpi_aware
from route_recording import RouteSession

LEASE = 'route-recorder-pid.json'
STOP = 'route-recorder-stop'
HOTKEYS = {117: 'checkpoint', 118: 'toggle', 119: 'pause', 121: 'finish',
           120: 'abort', 123: 'abort'}  # F6, F7, F8, F10, F9, F12
SYSTEM_KEYS = {18, 91, 92, 164, 165}
USER = ctypes.WinDLL('user32', use_last_error=True)
dpi_aware(USER)


def client_rect(hwnd):
    _, _, width, height = win32gui.GetClientRect(hwnd)
    left, top = win32gui.ClientToScreen(hwnd, (0, 0))
    return left, top, left + width, top + height


def player_target(hwnd):
    if not hwnd or not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd):
        return None
    try:
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        process = psutil.Process(pid)
        if process.name().lower() != 'robloxplayerbeta.exe':
            return None
        return {'hwnd': hwnd, 'pid': pid, 'process_created': process.create_time(),
                'window_title': win32gui.GetWindowText(hwnd)}
    except (psutil.Error, OSError):
        return None


def selected_foreground(target):
    return bool(target and win32gui.IsWindow(target['hwnd']) and
        not win32gui.IsIconic(target['hwnd']) and win32gui.GetForegroundWindow() == target['hwnd'] and
        win32process.GetWindowThreadProcessId(target['hwnd'])[1] == target['pid'])


def marker_state(root):
    result = []
    for name in ('STOP', 'PAUSE', 'F8_PAUSE', STOP):
        path = root / name
        try:
            stat = path.stat()
            result.append((name, stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            result.append((name, None, None))
    return result


def launch():
    import control_actions as actions
    root = data_directory()
    with actions.guard():
        actions.refuse_peer_controller()
        if actions.alive(LEASE):
            return 'Bait route recorder is already open. F7 starts/resumes in your selected Roblox window.'
        if actions.alive() or actions.alive('pid.json') or actions.starting() or actions.alive('calibration-pid.json'):
            raise RuntimeError('Use Pause in Fishing and wait for the controller to stop, then open Record bait route')
        (root / STOP).unlink(missing_ok=True)
        executable = Path(sys.executable).with_name('pythonw.exe')
        if not executable.exists():
            executable = Path(sys.executable)
        with (root / 'route-recorder-stdout.log').open('a') as out, (root / 'route-recorder-stderr.log').open('a') as err:
            process = subprocess.Popen([str(executable), str(ROOT / 'bait_route_recorder.py')],
                stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        atomic_json(root / LEASE, {'pid': process.pid, 'created': psutil.Process(process.pid).create_time()})
    return 'Bait route recorder opened. Bring the intended Roblox window forward and press F7 to begin.'


def parse_raw_mouse(payload):
    """RAWINPUTHEADER is 16/24 bytes on Windows x86/x64; RAWMOUSE is 24 bytes."""
    header_size = 8 + 2 * ctypes.sizeof(ctypes.c_void_p)
    if len(payload) < header_size + 24:
        return None
    kind, size = struct.unpack_from('<II', payload)
    device = int.from_bytes(payload[8:8 + ctypes.sizeof(ctypes.c_void_p)], 'little')
    if kind != 0 or size != len(payload) or not device:
        return None
    flags, buttons, _, dx, dy, _ = struct.unpack_from('<H2xIIiiI', payload, header_size)
    if not dx and not dy:
        return None
    return {'dx': dx, 'dy': dy, 'absolute': bool(flags & 1),
            'virtual_desktop': bool(flags & 2), 'raw_flags': flags, 'raw_buttons': buttons}


class InputCapture:
    """Observers only. Hooks pass every input through unchanged."""
    def __init__(self, foreground=win32gui.GetForegroundWindow):
        self.foreground = foreground
        self.target = None
        self.recording = False
        self.events = queue.Queue(maxsize=16000)
        self.failed = threading.Event()
        self.control_down = set()
        self.listeners = []
        self.raw_thread = None
        self.raw_hwnd = None
        self.ready = threading.Event()
        self.raw_error = None
        self.last_move = 0.0

    def put(self, kind, **details):
        try:
            self.events.put_nowait((time.monotonic(), kind, details))
        except queue.Full:
            self.failed.set()  # Stop as incomplete rather than lose route inputs silently.

    def owns_focus(self):
        return bool(self.recording and self.target and self.foreground() == self.target['hwnd'])

    def keyboard_event(self, message, data):
        if data.flags & 0x10:  # LLKHF_INJECTED
            return False
        down = message in (0x100, 0x104)
        up = message in (0x101, 0x105)
        if not (down or up):
            return False
        vk = int(data.vkCode)
        if vk in HOTKEYS:
            if up:
                self.control_down.discard(vk)
            elif vk not in self.control_down:
                self.control_down.add(vk)
                hwnd = self.foreground()
                if (self.target and hwnd == self.target['hwnd']) or (not self.target and player_target(hwnd)):
                    self.put('control', action=HOTKEYS[vk], hwnd=hwnd)
            return False
        if self.owns_focus():
            if vk in SYSTEM_KEYS:
                if down:
                    self.put('control', action='pause', reason='System navigation')
                    self.recording = False
            else:
                self.put('key', vk=vk, scan_code=int(data.scanCode),
                         extended=bool(data.flags & 1), down=down)
        return False

    def mouse_event(self, message, data):
        if data.flags & 1 or not self.owns_focus():  # LLMHF_INJECTED
            return False
        x, y = int(data.pt.x), int(data.pt.y)
        rect = client_rect(self.target['hwnd'])
        if not (rect[0] <= x < rect[2] and rect[1] <= y < rect[3]):
            if message != 0x200:
                self.put('control', action='pause', reason='Pointer left the game')
                self.recording = False
            return False
        point = {'desktop_x': x, 'desktop_y': y}
        if message == 0x200:
            now = time.monotonic()
            if now - self.last_move >= 1 / 60:
                self.last_move = now
                self.put('mouse_move', **point)
        elif message in (0x201, 0x202, 0x204, 0x205, 0x207, 0x208, 0x20B, 0x20C):
            names = {0x201: 'left', 0x202: 'left', 0x204: 'right', 0x205: 'right',
                     0x207: 'middle', 0x208: 'middle'}
            button = names.get(message, 'x' + str((int(data.mouseData) >> 16) & 0xffff))
            self.put('mouse_button', button=button, down=message in (0x201, 0x204, 0x207, 0x20B), **point)
        elif message in (0x20A, 0x20E):
            delta = ctypes.c_short(int(data.mouseData) >> 16).value
            self.put('mouse_wheel', delta=delta, horizontal=message == 0x20E, **point)
        return False

    def raw_messages(self):
        class RawDevice(ctypes.Structure):
            _fields_ = [('usage_page', ctypes.c_ushort), ('usage', ctypes.c_ushort),
                        ('flags', ctypes.c_uint32), ('hwnd', ctypes.c_void_p)]
        USER.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RawDevice), ctypes.c_uint32, ctypes.c_uint32]
        USER.RegisterRawInputDevices.restype = ctypes.c_bool
        USER.GetRawInputData.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32]
        USER.GetRawInputData.restype = ctypes.c_uint32
        header_size = 8 + 2 * ctypes.sizeof(ctypes.c_void_p)
        class_name = f'FishingRouteMouse-{os.getpid()}'
        registered = False
        def window_proc(hwnd, message, wparam, lparam):
            if message == 0xFF and self.owns_focus():  # WM_INPUT
                size = ctypes.c_uint32()
                result = USER.GetRawInputData(lparam, 0x10000003, None, ctypes.byref(size), header_size)
                if result == 0 and 0 < size.value < 4096:
                    buffer = ctypes.create_string_buffer(size.value)
                    count = USER.GetRawInputData(lparam, 0x10000003, buffer, ctypes.byref(size), header_size)
                    if count == size.value:
                        row = parse_raw_mouse(buffer.raw[:count])
                        if row:
                            self.put('raw_mouse', **row)
            elif message == win32con.WM_CLOSE:
                win32gui.DestroyWindow(hwnd)
                return 0
            elif message == win32con.WM_DESTROY:
                win32gui.PostQuitMessage(0)
                return 0
            return win32gui.DefWindowProc(hwnd, message, wparam, lparam)
        try:
            window_class = win32gui.WNDCLASS()
            window_class.hInstance = win32api.GetModuleHandle(None)
            window_class.lpszClassName = class_name
            window_class.lpfnWndProc = window_proc
            atom = win32gui.RegisterClass(window_class)
            self.raw_hwnd = win32gui.CreateWindowEx(0, atom, '', 0, 0, 0, 0, 0, 0, 0,
                                                   window_class.hInstance, None)
            device = RawDevice(1, 2, 0x100, self.raw_hwnd)  # RIDEV_INPUTSINK, mouse only
            if not USER.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(device)):
                raise ctypes.WinError(ctypes.get_last_error())
            registered = True
            self.ready.set()
            win32gui.PumpMessages()
        except Exception as error:
            self.raw_error = str(error)
            self.failed.set()
            self.ready.set()
        finally:
            if registered:
                remove = RawDevice(1, 2, 1, None)  # RIDEV_REMOVE
                USER.RegisterRawInputDevices(ctypes.byref(remove), 1, ctypes.sizeof(remove))
            if self.raw_hwnd and win32gui.IsWindow(self.raw_hwnd):
                win32gui.DestroyWindow(self.raw_hwnd)
            if 'atom' in locals():
                win32gui.UnregisterClass(atom, window_class.hInstance)

    def start(self):
        self.listeners = [keyboard.Listener(win32_event_filter=self.keyboard_event),
                          mouse.Listener(win32_event_filter=self.mouse_event)]
        for listener in self.listeners:
            listener.start()
            listener.wait()
        self.raw_thread = threading.Thread(target=self.raw_messages, daemon=True, name='BaitRouteRawMouse')
        self.raw_thread.start()
        if not self.ready.wait(3) or self.raw_error:
            raise RuntimeError('Raw mouse recorder could not start: ' + (self.raw_error or 'startup timeout'))

    def stop(self):
        self.recording = False
        for listener in self.listeners:
            listener.stop()
        for listener in self.listeners:
            listener.join(1)
        if self.raw_hwnd and win32gui.IsWindow(self.raw_hwnd):
            win32gui.PostMessage(self.raw_hwnd, win32con.WM_CLOSE, 0, 0)
        if self.raw_thread:
            self.raw_thread.join(2)


class RecorderWindow:
    def __init__(self, root, storage):
        self.root, self.storage = root, storage
        self.session = None
        self.capture = CaptureSession()
        self.hooks = InputCapture()
        self.initial_markers = marker_state(storage)
        self.next_frame = self.next_save = 0.0
        self.closed = False
        root.title('Fishing · Record bait route')
        root.geometry('640x480')
        root.configure(bg='#11161c')
        root.resizable(False, False)
        self.status = tk.StringVar(value='Ready · nothing is recording yet')
        self.detail = tk.StringVar(value='Bring your intended Roblox window forward, then press F7.')
        tk.Label(root, text='RECORD BAIT ROUTE', bg='#11161c', fg='#dcc393',
                 font=('Segoe UI', 18, 'bold')).pack(anchor='w', padx=24, pady=(22, 12))
        tk.Label(root, textvariable=self.status, bg='#11161c', fg='#e2e7ea',
                 font=('Segoe UI', 13)).pack(anchor='w', padx=24)
        tk.Label(root, textvariable=self.detail, bg='#11161c', fg='#a7b3bf', justify='left',
                 wraplength=550, font=('Segoe UI', 10)).pack(anchor='w', padx=24, pady=(8, 16))
        instructions = ('F7  Start / pause / resume     F6  Save visual checkpoint\n'
                        'F10  Finish and save     F8  Pause     F9 / F12  End as partial\n\n'
                        'Start at your fishing spot. Mark these views with F6:\n'
                        'shrine menu → shrine arrival → path turns → seller → shop\n'
                        '→ bait count after buying → fishing spot after your reset.\n\n'
                        'Stand still briefly at each checkpoint. Switching apps pauses\n'
                        'recording; return to the same Roblox window and press F7.\n'
                        'Only your game is recorded. Limit: 20 minutes of recording.')
        tk.Label(root, text=instructions, bg='#11161c', fg='#a7b3bf', justify='left',
                 font=('Segoe UI', 10)).pack(anchor='w', padx=24)
        row = tk.Frame(root, bg='#11161c')
        row.pack(fill='x', padx=24, pady=(18, 10))
        tk.Button(row, text='Finish and save', command=lambda: self.finish(True),
                  bg='#26332e', fg='#e2e7ea', relief='flat', padx=15, pady=8).pack(side='left')
        tk.Button(row, text='Open recordings', command=self.open_recordings,
                  bg='#202832', fg='#e2e7ea', relief='flat', padx=15, pady=8).pack(side='left', padx=12)
        root.protocol('WM_DELETE_WINDOW', self.close)
        try:
            self.hooks.start()
        except Exception:
            self.hooks.stop()
            self.capture.close()
            raise
        root.after(25, self.tick)

    def frame(self):
        target = self.hooks.target
        if not selected_foreground(target):
            raise RuntimeError('Selected Roblox window lost focus')
        rect = client_rect(target['hwnd'])
        width, height = rect[2] - rect[0], rect[3] - rect[1]
        if width < 320 or height < 240:
            raise RuntimeError('Roblox client is too small to record')
        result = np.asarray(self.capture.grab({'left': rect[0], 'top': rect[1],
                                               'width': width, 'height': height}))[:, :, :3].copy()
        if not selected_foreground(target):
            raise RuntimeError('Focus changed during capture; frame discarded')
        return rect, result

    def toggle(self, hwnd):
        if self.session and self.session.state == 'finished':
            self.detail.set('Recording saved. Close and reopen the recorder for another take.')
            return
        if self.session and self.session.state == 'recording':
            self.pause('Paused by F7')
            return
        if any(USER.GetAsyncKeyState(vk) & 0x8000 for vk in range(1, 255) if vk not in HOTKEYS):
            self.detail.set('Release other keys and mouse buttons, then press F7 again.')
            return
        if self.hooks.target is None:
            target = player_target(hwnd)
            if not target:
                return
            self.hooks.target = target
        rect, frame = self.frame()
        if self.session is None:
            if shutil.disk_usage(self.storage).free < 500 * 1024 * 1024:
                raise RuntimeError('At least 500 MB free disk space is needed to start recording')
            self.session = RouteSession(self.storage, self.hooks.target, rect, frame)
        else:
            self.session.resume(rect)
            self.session.checkpoint(frame, 'resume_' + str(len(self.session.metadata['checkpoints'])))
        self.hooks.recording = True
        self.status.set('Recording · F6 checkpoint · F10 finish')
        self.detail.set('Record the shrine trip, purchase, and reset. F6 saves each important view.')
        self.next_frame = time.monotonic() + 1 / self.session.fps

    def pause(self, reason):
        self.hooks.recording = False
        if self.session and self.session.state == 'recording':
            self.session.pause(reason)
            self.status.set('Paused · press F7 in the same Roblox window to resume')
            self.detail.set(reason)

    def finish(self, complete):
        self.hooks.recording = False
        if self.session and self.session.state != 'finished':
            if complete and selected_foreground(self.hooks.target) and self.session.state == 'recording':
                try:
                    _, frame = self.frame()
                    self.session.checkpoint(frame, 'route_end')
                except Exception as error:
                    complete = False
                    self.detail.set(str(error))
            self.session.finish(complete, 'Finished by user' if complete else 'Recording ended as partial')
            atomic_json(self.storage / 'bait-route-latest.json', {'path': str(self.session.path),
                'complete': complete, 'at': time.time(), 'automation_ready': False})
            self.status.set('Saved · ' + ('complete demonstration' if complete else 'partial demonstration'))
            self.detail.set(str(self.session.path))
        elif not self.session:
            self.status.set('No recording started · press F7 in Roblox to begin')

    def tick(self):
        if self.closed:
            return
        try:
            if marker_state(self.storage) != self.initial_markers:
                self.pause('Fishing Pause/Stop changed; recording ended')
                self.finish(False)
                self.close()
                return
            if self.hooks.failed.is_set() or any(not listener.is_alive() for listener in self.hooks.listeners):
                raise RuntimeError(self.hooks.raw_error or 'Input recorder interrupted; saved as partial')
            for _ in range(6000):
                try:
                    at, kind, details = self.hooks.events.get_nowait()
                except queue.Empty:
                    break
                if kind == 'control':
                    action = details['action']
                    if action == 'toggle':
                        self.toggle(details['hwnd'])
                    elif action == 'pause':
                        self.pause(details.get('reason', 'Paused by F8'))
                    elif action in ('finish', 'abort'):
                        self.finish(action == 'finish')
                    elif action == 'checkpoint' and self.session and self.session.state == 'recording':
                        rect, frame = self.frame()
                        self.session.rect = rect
                        mark = self.session.checkpoint(frame)
                        self.detail.set('Saved ' + mark['name'] + ' · ' + str(len(self.session.metadata['checkpoints']) - 1) + ' manual checkpoints')
                elif self.session and selected_foreground(self.hooks.target):
                    self.session.add_input(kind, at, **details)
            if self.session and self.session.state == 'recording':
                if not selected_foreground(self.hooks.target):
                    self.pause('Roblox lost focus. No other app was recorded.')
                else:
                    now = time.monotonic()
                    if self.session.elapsed() >= 1200:
                        self.pause('20 minute recording limit reached')
                        self.finish(False)
                    elif now >= self.next_frame:
                        rect, frame = self.frame()
                        if tuple(rect) != self.session.rect:
                            self.pause('Roblox moved or resized. Press F7 after the window settles.')
                        else:
                            self.session.capture(frame)
                            self.next_frame = now + 1 / self.session.fps
                    if now >= self.next_save:
                        if shutil.disk_usage(self.storage).free < 100 * 1024 * 1024:
                            self.pause('Low disk space; recording ended')
                            self.finish(False)
                        else:
                            self.session.save()
                        self.next_save = now + 1
        except Exception as error:
            self.pause(str(error))
            if self.hooks.failed.is_set():
                self.finish(False)
            self.detail.set(str(error))
        self.root.after(25, self.tick)

    def open_recordings(self):
        path = self.storage / 'bait-routes'
        path.mkdir(exist_ok=True)
        os.startfile(str(path))

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.session and self.session.state != 'finished':
                self.finish(False)
        finally:
            self.hooks.stop()
            self.capture.close()
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launch', action='store_true', help='Open the recorder without a console')
    args = parser.parse_args()
    if args.launch:
        print(launch())
        return
    import control_actions as actions
    storage = data_directory()
    record = {'pid': os.getpid(), 'created': psutil.Process().create_time()}
    with actions.guard():
        actions.refuse_peer_controller()
        if actions.alive(LEASE):
            saved = json.loads((storage / LEASE).read_text())
            if saved['pid'] not in (os.getpid(), psutil.Process().ppid()):
                raise RuntimeError('A bait route recorder is already open')
        if actions.alive() or actions.alive('pid.json') or actions.starting() or actions.alive('calibration-pid.json'):
            raise RuntimeError('Pause Fishing and wait for the controller to stop before recording a route')
        if (storage / STOP).exists():
            raise RuntimeError('Route recording was cancelled by Pause/Stop; reopen it through Fishing')
        atomic_json(storage / LEASE, record)
    root = None
    window = None
    try:
        root = tk.Tk()
        window = RecorderWindow(root, storage)
        root.mainloop()
    except Exception as error:
        if root:
            messagebox.showerror('Bait route recorder', str(error), parent=root)
        raise
    finally:
        if window:
            window.close()
        elif root:
            root.destroy()
        with actions.guard():
            try:
                saved = json.loads((storage / LEASE).read_text())
                if saved == record:
                    (storage / LEASE).unlink(missing_ok=True)
            except (OSError, ValueError):
                pass


if __name__ == '__main__':
    main()
