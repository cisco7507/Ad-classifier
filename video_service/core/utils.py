import logging
import torch
import warnings
import os

os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
warnings.filterwarnings("ignore", category=UserWarning)

logging.basicConfig(
    filename='ad_classifier_debug.log',
    filemode='a',
    level=logging.DEBUG,
    format='%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("video_service.core")

from .device import DEVICE as device, TORCH_DTYPE
