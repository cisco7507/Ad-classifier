import os
import torch
import logging

logger = logging.getLogger("video_service.core.device")

def get_device() -> str:
    pref = os.getenv("DEVICE_PREFERENCE", "auto").lower()
    
    if pref == "cuda" and torch.cuda.is_available(): return "cuda"
    if pref == "mps" and torch.backends.mps.is_available(): return "mps"
    if pref == "cpu": return "cpu"

    if pref == "auto":
        if torch.cuda.is_available(): return "cuda"
        if torch.backends.mps.is_available(): return "mps"
        return "cpu"
    
    # Fallback if preference is invalid or unavailable
    logger.warning(f"Preferred device '{pref}' is unavailable or invalid. Falling back to auto.")
    if torch.cuda.is_available(): return "cuda"
    if torch.backends.mps.is_available(): return "mps"
    return "cpu"

def get_torch_dtype():
    dtype_pref = os.getenv("TORCH_DTYPE", "auto").lower()
    device = get_device()
    
    if dtype_pref == "float16": return torch.float16
    if dtype_pref == "bfloat16": return torch.bfloat16
    if dtype_pref == "float32": return torch.float32

    # Auto dtype
    if device == "cuda":
        return torch.float16 # Alternatively bfloat16, but float16 is safe
    elif device == "mps":
        # MPS can be tricky with some ops in float16, returning float32 or float16 based on model 
        # but float16 may be requested. By default, let's use float32 or float16.
        # Let's use float32 to be safe for auto on MPS, or float16 if preferred
        return torch.float32 
    return torch.float32

def init_device():
    device = get_device()
    logger.info(f"Initialized device: {device}")
    
    if os.getenv("ENABLE_DEVICE_SELFTEST") == "1":
        try:
            a = torch.randn(10, 10).to(device)
            b = torch.randn(10, 10).to(device)
            c = torch.matmul(a, b)
            # Verify if it actually ran on cuda
            if device == "cuda" and c.device.type != "cuda":
                logger.error("Selftest failed: Expected CUDA but tensor is on CPU. Forcing fallback to CPU.")
                os.environ["DEVICE_PREFERENCE"] = "cpu"
        except Exception as e:
            logger.error(f"Device selftest failed: {e}. Forcing fallback to CPU.")
            os.environ["DEVICE_PREFERENCE"] = "cpu"
    
    return get_device()

DEVICE = init_device()
TORCH_DTYPE = get_torch_dtype()

def get_diagnostics():
    device = get_device()
    cuda_avail = torch.cuda.is_available()
    mps_avail = torch.backends.mps.is_available()
    
    diag = {
        "device": device,
        "cuda_available": cuda_avail,
        "mps_available": mps_avail,
        "torch_version": torch.__version__,
        "torch_dtype": str(get_torch_dtype())
    }
    
    if cuda_avail:
        diag["cuda_version"] = torch.version.cuda
        diag["device_name"] = torch.cuda.get_device_name(0)

    return diag
