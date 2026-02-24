import logging
import torch
import warnings
import os

os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
warnings.filterwarnings("ignore", category=UserWarning)

logger = logging.getLogger("video_service.core")

from .device import DEVICE as device, TORCH_DTYPE
