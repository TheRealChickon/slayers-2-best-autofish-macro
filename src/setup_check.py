"""Read-only dependency checks; does not send game input."""
import importlib
import struct
import sys


def main():
    if sys.platform != 'win32' or struct.calcsize('P') != 8:
        raise RuntimeError('Fishing requires 64-bit Windows and 64-bit Python')
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11 or newer is required; Python 3.12 is tested')
    for name in ('tkinter', 'numpy', 'cv2', 'mss', 'psutil', 'win32gui', 'win32file',
                 'pynput', 'rapidocr_onnxruntime', 'PIL'):
        importlib.import_module(name)
    from app_config import ROOT, data_directory, load_config
    load_config()
    for name in ('exit.png', 'rod-icon.png', 'rod-unequipped.png', 'items/coral.png', 'items/sea-horse.png',
                 'items/silk-thread.png', 'items/metal-scraps.png', 'items/ore.png'):
        if not (ROOT/'assets'/name).exists(): raise RuntimeError('Missing asset: '+name)
    data_directory().mkdir(parents=True, exist_ok=True)
    print('Dependencies, settings and assets are ready.')


if __name__ == '__main__': main()
