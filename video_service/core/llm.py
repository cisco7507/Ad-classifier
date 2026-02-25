import queue
import threading
import concurrent.futures
import random
import time
import io
import base64
import json
import re
import subprocess
import os
import requests
from PIL import Image
from ddgs import DDGS
from video_service.core.utils import logger

class SearchManager:
    def __init__(self):
        self.queue = queue.Queue()
        self.client = DDGS() 
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        while True:
            query, future = self.queue.get()
            max_retries = 3
            base_delay = 2.0
            success = False
            attempt = 0
            
            while attempt < max_retries and not success:
                try:
                    results = self.client.text(query, max_results=3)
                    snippets = " | ".join([r.get('body', '') for r in results if isinstance(r, dict)])
                    future.set_result(snippets if snippets else None)
                    success = True
                except Exception as e:
                    attempt += 1
                    if attempt < max_retries:
                        backoff_sleep = (base_delay ** attempt) + random.uniform(0.8, 2.5)
                        time.sleep(backoff_sleep)
                        self.client = DDGS()
                    else:
                        future.set_exception(e)
            
            self.queue.task_done()
            if success:
                time.sleep(random.uniform(0.8, 2.5))

    def search(self, query, timeout=45):
        future = concurrent.futures.Future()
        self.queue.put((query, future))
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            return None

search_manager = SearchManager()

class HybridLLM:
    def _pil_to_base64(self, pil_image, max_dimension=768):
        if not pil_image:
            return None

        w, h = pil_image.size
        if max(w, h) > max_dimension:
            scale = max_dimension / float(max(w, h))
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            lanczos = getattr(Image, "Resampling", Image).LANCZOS
            pil_image = pil_image.resize((new_w, new_h), lanczos)

        buffered = io.BytesIO()
        pil_image.save(buffered, format="JPEG", quality=85)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def _clean_and_parse_json(self, raw_text):
        try:
            text = re.sub(r'\x1b\[[0-9;]*m', '', raw_text)
            text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).replace("```json", "").replace("```", "").strip()
            start, end = text.find("{"), text.rfind("}") + 1
            if start != -1 and end != -1: return json.loads(text[start:end])
            return {"error": "No JSON found", "raw_output": text}
        except Exception as e: return {"error": f"JSON Parse Failed: {str(e)}"}

    def query_pipeline(self, provider, backend_model, text, categories, tail_image=None, override=False, enable_search=False, force_multimodal=False, context_size=8192):
        validation_threshold_raw = os.environ.get("LLM_VALIDATION_THRESHOLD", "0.7")
        try:
            validation_threshold = float(validation_threshold_raw)
        except (TypeError, ValueError):
            logger.warning(
                "invalid_llm_validation_threshold value=%r fallback=0.7",
                validation_threshold_raw,
            )
            validation_threshold = 0.7

        sys_msg = (
            "You are a Senior Marketing Analyst and Global Brand Expert. "
            "Your goal is to categorize video advertisements by combining extracted text (OCR) with your vast internal knowledge of companies, slogans, and industries. "
            "Rely on Internal Brand Knowledge: You know every major brand, their parent companies, and their marketing styles. Use this internal database as your absolute primary source of truth. "
            "Treat OCR as Noisy Hints: The extracted OCR text is machine-generated and highly prone to typos, missing letters, and random artifacts. DO NOT blindly trust or copy the OCR text. Use your knowledge to autocorrect it. "
            "(e.g., if OCR says 'Strbcks' or 'Star bucks co', you know the true brand is 'Starbucks'). "
            "Determine Category: Pick from 'Suggested Categories' or generate a professional tag if Override Allowed is True. "
            "Output STRICT JSON: {\"brand\": \"...\", \"category\": \"...\", \"confidence\": 0.0, \"reasoning\": \"...\"}"
        )
        usr_msg = f"Categories: {categories}\nOverride: {override}\nOCR Text: \"{text}\""
        b64_img = self._pil_to_base64(tail_image) if tail_image else None

        def call_model(sys, usr, img=None):
            try:
                if provider == "Gemini CLI": return self._clean_and_parse_json(subprocess.run(["gemini", f"{sys}\n\n{usr}"], capture_output=True, text=True).stdout)
                elif provider == "Ollama":
                    payload = {"model": backend_model, "prompt": f"{sys}\n\n{usr}", "stream": False, "format": "json", "options": {"temperature": 0.1, "num_ctx": int(context_size)}}
                    if img: payload["images"] = [img]
                    return self._clean_and_parse_json(requests.post("http://localhost:11434/api/generate", json=payload).json().get("response", ""))
                elif provider == "LM Studio":
                    msgs = [{"role": "system", "content": sys}, {"role": "user", "content": usr}]
                    if img: msgs[1]["content"] = [{"type": "text", "text": usr}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}}]
                    return self._clean_and_parse_json(requests.post("http://localhost:1234/v1/chat/completions", json={"model": backend_model, "messages": msgs, "temperature": 0.1}).json().get("choices", [{}])[0].get("message", {}).get("content", ""))
            except Exception as e: return {"error": str(e)}

        res = call_model(sys_msg, usr_msg, b64_img if force_multimodal else None)
        logger.debug("llm_pipeline_initial_result: %s", res)
        
        brand = res.get("brand", "Unknown") if isinstance(res, dict) else "Unknown"
        if brand.lower() in ["unknown", "none", "n/a", ""] and enable_search:
            words = [w for w in re.sub(r'[^a-zA-Z0-9\s]', '', text).split() if len(w) > 3]
            if words and (sr := search_manager.search(" ".join(words[:8]) + " brand company product")):
                res = call_model(sys_msg + "\nAGENTIC RECOVERY", f"OCR: {text}\nWEB: {sr}")
                res["reasoning"] = "(Recovered) " + res.get("reasoning", "")
                brand = res.get("brand", "Unknown")

        confidence_raw = res.get("confidence", 0.0) if isinstance(res, dict) else 0.0
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        needs_validation = (
            validation_threshold <= 0.0
            or confidence <= 0.0
            or confidence < validation_threshold
        )

        if "category" in res and enable_search and brand.lower() not in ["unknown", "none", "n/a", ""]:
            if needs_validation:
                if validation_threshold <= 0.0:
                    logger.debug(
                        "llm_validation_triggered: confidence=%.2f threshold=%.2f (threshold<=0 forces validation)",
                        confidence,
                        validation_threshold,
                    )
                else:
                    logger.debug(
                        "llm_validation_triggered: confidence=%.2f < threshold=%.2f",
                        confidence,
                        validation_threshold,
                    )
                if val_snippets := search_manager.search(f"{brand} official brand company"):
                    val_res = call_model(sys_msg + "\nVALIDATION MODE", f"Brand: {brand}\nWeb: {val_snippets}\nCorrect brand name. Keep category {res.get('category')}.")
                    if "category" in val_res: return val_res
            else:
                logger.debug(
                    "llm_validation_skipped: confidence=%.2f >= threshold=%.2f",
                    confidence,
                    validation_threshold,
                )
        return res

    def query_agent(self, provider, backend_model, prompt, images=None, force_multimodal=False, context_size=8192):
        img_to_send = images[-1] if images else None
        b64_imgs = [self._pil_to_base64(img_to_send)] if (force_multimodal and img_to_send) else []
        
        try:
            if provider == "Gemini CLI":
                res = subprocess.run(["gemini", prompt], capture_output=True, text=True)
                if res.returncode != 0 or not res.stdout.strip():
                    err = res.stderr.strip() if res.stderr else "No stderr output."
                    return f'[TOOL: ERROR | reason="Gemini CLI failed (Code {res.returncode}): {err}"]'
                return res.stdout.strip()
                
            elif provider == "Ollama":
                payload = {"model": backend_model, "prompt": prompt, "stream": False, "options": {"temperature": 0.1, "num_ctx": int(context_size)}}
                if b64_imgs: payload["images"] = b64_imgs
                res = requests.post("http://localhost:11434/api/generate", json=payload, timeout=120)
                if res.status_code != 200:
                    return f'[TOOL: ERROR | reason="Ollama HTTP {res.status_code}: {res.text}"]'
                return res.json().get("response", "").strip()
                
            elif provider == "LM Studio":
                msgs = [{"role": "system", "content": "You are a ReACT Agent. Strictly follow the prompt formatting."}, {"role": "user", "content": prompt}]
                if b64_imgs: msgs[1]["content"] = [{"type": "text", "text": prompt}] + [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_imgs[0]}"}}]
                res = requests.post("http://localhost:1234/v1/chat/completions", json={"model": backend_model, "messages": msgs, "temperature": 0.1}, timeout=120)
                if res.status_code != 200:
                    return f'[TOOL: ERROR | reason="LM Studio HTTP {res.status_code}: {res.text}"]'
                return res.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                
        except Exception as e: 
            return f'[TOOL: ERROR | reason="Fatal Exception: {str(e)}"]'

llm_engine = HybridLLM()
