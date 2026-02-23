import torch
import easyocr
import threading
from PIL import Image
from transformers import AutoProcessor, AutoModelForCausalLM
from transformers.dynamic_module_utils import get_imports
from unittest.mock import patch
from video_service.core.utils import logger, device, TORCH_DTYPE

class OCRManager:
    def __init__(self):
        self.engines = {}
        self.current_engine = None
        self.current_name = ""
        self.lock = threading.Lock()

    def get_engine(self, name):
        with self.lock:
            if name == self.current_name: return self.current_engine
            self.current_engine = None
            if torch.cuda.is_available(): torch.cuda.empty_cache()
            
            if name == "EasyOCR":
                use_gpu = (device == "cuda")
                logger.info(f"Initializing EasyOCR. GPU mode: {use_gpu}")
                self.current_engine = easyocr.Reader(['en', 'fr'], gpu=use_gpu, verbose=False)
            elif name == "Florence-2 (Microsoft)":
                def fixed_get_imports(filename):
                    imports = get_imports(filename)
                    if "flash_attn" in imports: imports.remove("flash_attn")
                    return imports
                with patch("transformers.dynamic_module_utils.get_imports", fixed_get_imports):
                    model_id = "microsoft/Florence-2-base"
                    logger.info(f"Initializing Florence-2 on {device} with dtype {TORCH_DTYPE}")
                    self.current_engine = {
                        "model": AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True, torch_dtype=TORCH_DTYPE).to(device).eval(),
                        "processor": AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
                    }
            self.current_name = name
            return self.current_engine

    def extract_text(self, engine_name, image_rgb, mode="Detailed"):
        engine = self.get_engine(engine_name)
        try:
            if engine_name == "EasyOCR":
                results = engine.readtext(image_rgb, detail=1)
                annotated = [f"{'[HUGE] ' if (max(p[1] for p in b) - min(p[1] for p in b))/image_rgb.shape[0] > 0.15 else ''}{t}" for b, t, c in results]
                return " ".join(annotated)
            elif engine_name == "Florence-2 (Microsoft)":
                pil_img = Image.fromarray(image_rgb)
                inputs = engine["processor"](text="<OCR_WITH_REGION>", images=pil_img, return_tensors="pt")
                inputs = {k: v.to(device, dtype=TORCH_DTYPE) if torch.is_floating_point(v) and TORCH_DTYPE != torch.float32 else v.to(device) for k, v in inputs.items()}
                with torch.inference_mode():
                    generated_ids = engine["model"].generate(**inputs, max_new_tokens=1024, num_beams=1 if "Fast" in mode else 3)
                parsed = engine["processor"].post_process_generation(engine["processor"].batch_decode(generated_ids, skip_special_tokens=False)[0], task="<OCR_WITH_REGION>", image_size=(pil_img.width, pil_img.height))
                ocr_data = parsed.get("<OCR_WITH_REGION>", {})
                annotated = [f"{'[HUGE] ' if (b[5]-b[1])/pil_img.height > 0.15 else ''}{l}" for l, b in zip(ocr_data.get("labels", []), ocr_data.get("quad_boxes", []))]
                return " ".join(annotated)
        except Exception as e:
            logger.error(f"OCR Error: {e}")
            return ""

ocr_manager = OCRManager()
