"""RapidOCR on the NVIDIA GPU when the local CUDA runtime is present.

`.runtime/boss-tensorrt` holds an onnxruntime build with CUDA/TensorRT
providers and the matching NVIDIA libraries. It is local, untracked data. When
it is present and loads, the same PaddleOCR models run on CUDA (about four
times faster per scan on an RTX 5070 Ti); otherwise the installed CPU
onnxruntime is used unchanged. Import this module before anything else imports
onnxruntime, so one build serves the whole process.
"""
import glob
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CUDA_RUNTIME = ROOT/'.runtime'/'boss-tensorrt'
DISABLED = os.environ.get('AUTOFISH_OCR_DEVICE', '').lower() == 'cpu'
device = 'cpu'


def _prepare_cuda():
    if DISABLED or 'onnxruntime' in sys.modules or not (CUDA_RUNTIME/'onnxruntime'/'capi'/'onnxruntime_providers_cuda.dll').is_file():
        return False
    folders = glob.glob(str(CUDA_RUNTIME/'nvidia'/'*'/'bin'))+[str(CUDA_RUNTIME/'onnxruntime'/'capi')]
    for folder in folders:
        if os.path.isdir(folder):
            os.add_dll_directory(folder)
            os.environ['PATH'] = folder+os.pathsep+os.environ.get('PATH', '')
    sys.path.insert(0, str(CUDA_RUNTIME))
    try:
        import onnxruntime
        if 'CUDAExecutionProvider' in onnxruntime.get_available_providers():
            return True
    except Exception:
        pass
    # Fall back to the installed CPU build.
    sys.path.remove(str(CUDA_RUNTIME))
    for name in [name for name in sys.modules if name == 'onnxruntime' or name.startswith('onnxruntime.')]:
        del sys.modules[name]
    return False


_cuda = _prepare_cuda()
from rapidocr_onnxruntime import RapidOCR as _RapidOCR  # noqa: E402


def RapidOCR(**options):
    """Build RapidOCR on CUDA when available; a failed GPU session falls back to CPU."""
    global device
    if _cuda:
        try:
            engine = _RapidOCR(det_use_cuda=True, cls_use_cuda=True, rec_use_cuda=True, **options)
            providers = engine.text_det.infer.session.get_providers()
            if providers and providers[0] == 'CUDAExecutionProvider':
                device = 'cuda'
                return engine
        except Exception:
            pass
    device = 'cpu'
    return _RapidOCR(**options)
