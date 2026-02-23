import os
import gradio as gr
import cv2
import torch
from PIL import Image
from transformers import AutoProcessor, AutoModel, AutoModelForCausalLM
from transformers.dynamic_module_utils import get_imports
from unittest.mock import patch
import yt_dlp
import easyocr
import json
import subprocess
import re
import requests
import warnings
import base64
import io
import concurrent.futures
import logging
import pandas as pd
from ddgs import DDGS
import time
import queue
import threading
from sentence_transformers import SentenceTransformer, util
import random
from scenedetect import detect, ContentDetector
import numpy as np
import plotly.graph_objects as go
from sklearn.decomposition import PCA

# --- LOGGING SETUP ---
logging.basicConfig(
    filename='ad_classifier_debug.log',
    filemode='a',
    level=logging.DEBUG,
    format='%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)
logger.info("=== Unified Ad Classifier Started ===")

os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
warnings.filterwarnings("ignore", category=UserWarning)

# --- DEVICE SETUP ---
def get_device():
    if torch.cuda.is_available(): return "cuda"
    elif torch.backends.mps.is_available(): return "mps"
    return "cpu"

device = get_device()
print(f"🚀 Device: {device.upper()}")

# --- LOAD VISION MODEL (SigLIP) ---
print("Loading SigLIP Vision Model...")
SIGLIP_ID = "google/siglip-so400m-patch14-384"
try:
    siglip_model = AutoModel.from_pretrained(SIGLIP_ID).to(device)
    siglip_processor = AutoProcessor.from_pretrained(SIGLIP_ID)
except Exception as e:
    print(f"⚠️ Failed to load SigLIP: {e}")
    siglip_model, siglip_processor = None, None

# --- CENTRAL SEARCH MANAGER ---
# --- CENTRAL SEARCH MANAGER (WITH JITTER & BACKOFF) ---
class SearchManager:
    def __init__(self):
        self.queue = queue.Queue()
        self.client = DDGS() 
        
        # Start the background consumer thread immediately
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        while True:
            query, future = self.queue.get()
            
            # Backoff configurations
            max_retries = 3
            base_delay = 2.0
            success = False
            attempt = 0
            
            while attempt < max_retries and not success:
                try:
                    logger.info(f"[SearchManager] Executing Metasearch (Attempt {attempt + 1}): '{query}'")
                    print(f"🌐 Search Manager executing: '{query}'")
                    
                    results = self.client.text(query, max_results=3)
                    snippets = " | ".join([r.get('body', '') for r in results if isinstance(r, dict)])
                    
                    future.set_result(snippets if snippets else None)
                    success = True
                    
                except Exception as e:
                    attempt += 1
                    if attempt < max_retries:
                        # EXPONENTIAL BACKOFF: e.g., 2s, 4s, plus random jitter
                        backoff_sleep = (base_delay ** attempt) + random.uniform(0.8, 2.5)
                        logger.warning(f"[SearchManager] Rate limited/Failed ({e}). Backing off for {backoff_sleep:.2f}s...")
                        print(f"⚠️ Search blocked. Backing off for {backoff_sleep:.2f} seconds...")
                        
                        time.sleep(backoff_sleep)
                        self.client = DDGS()  # Re-initialize session to clear bad sockets
                    else:
                        logger.error(f"[SearchManager] Metasearch completely failed after {max_retries} attempts: {e}")
                        future.set_exception(e)
            
            self.queue.task_done()
            
            # STANDARD JITTER: Random organic delay between 0.8s and 2.5s after every successful request
            if success:
                jitter = random.uniform(0.8, 2.5)
                logger.debug(f"[SearchManager] Jitter sleep for {jitter:.2f}s.")
                time.sleep(jitter)

    def search(self, query, timeout=45):
        """Video threads call this to drop a query in the inbox and wait for the result."""
        future = concurrent.futures.Future()
        self.queue.put((query, future))
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            logger.error(f"Search request timed out or failed: {e}")
            return None

search_manager = SearchManager()


# --- MODULAR OCR ENGINE ---
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
                self.current_engine = easyocr.Reader(['en', 'fr'], gpu=torch.cuda.is_available() or torch.backends.mps.is_available(), verbose=False)
            elif name == "Florence-2 (Microsoft)":
                def fixed_get_imports(filename):
                    imports = get_imports(filename)
                    if "flash_attn" in imports: imports.remove("flash_attn")
                    return imports
                with patch("transformers.dynamic_module_utils.get_imports", fixed_get_imports):
                    model_id = "microsoft/Florence-2-base"
                    self.current_engine = {
                        "model": AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True).to(device).eval(),
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
                inputs = {k: v.to(device) for k, v in engine["processor"](text="<OCR_WITH_REGION>", images=pil_img, return_tensors="pt").items()}
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

# --- SEMANTIC CATEGORY MAPPER & NEBULA GENERATOR ---
class CategoryMapper:
    def __init__(self, csv_path="categories.csv"):
        try:
            self.df = pd.read_csv(csv_path)
            col_name = 'Freewheel Industry Category' if 'Freewheel Industry Category' in self.df.columns else self.df.columns[1]
            id_name = 'ID' if 'ID' in self.df.columns else self.df.columns[0]
            self.cat_to_id = dict(zip(self.df[col_name].astype(str), self.df[id_name].astype(str)))
            self.categories = list(self.cat_to_id.keys())
            
            self.embedder = SentenceTransformer('all-MiniLM-L6-v2', device=device)
            self.category_embeddings = self.embedder.encode(self.categories, convert_to_tensor=True)
            self.active = True
            
            if len(self.categories) >= 3:
                self.pca = PCA(n_components=3)
                self.coords_3d = self.pca.fit_transform(self.category_embeddings.cpu().numpy()) * 1000
                self.df_3d = pd.DataFrame({
                    'x': self.coords_3d[:, 0], 'y': self.coords_3d[:, 1], 'z': self.coords_3d[:, 2],
                    'Category': self.categories, 'ColorID': range(len(self.categories))
                })
                self.has_nebula = True
                self.max_range = max(self.df_3d['x'].max() - self.df_3d['x'].min(), self.df_3d['y'].max() - self.df_3d['y'].min(), self.df_3d['z'].max() - self.df_3d['z'].min())
            else: 
                self.has_nebula = False
                
            # 🚀 NEW: Pre-compute SigLIP text embeddings for lightning-fast Vision calls
            if siglip_model is not None and len(self.categories) > 0:
                logger.info("Pre-computing SigLIP text embeddings for all categories...")
                vision_prompts = [f"A video ad for {cat}" for cat in self.categories]
                text_inputs = siglip_processor(text=vision_prompts, padding="max_length", return_tensors="pt").to(device)
                with torch.no_grad():
                    text_features = siglip_model.get_text_features(**text_inputs)
                    self.vision_text_features = text_features / text_features.norm(p=2, dim=-1, keepdim=True)
                logger.info("SigLIP text embeddings successfully cached.")
            else:
                self.vision_text_features = None

        except Exception as e: 
            logger.error(f"Mapper init failed: {e}")
            self.active, self.has_nebula, self.vision_text_features = False, False, None

    def get_closest_official_category(self, raw_category):
        if not self.active or not raw_category or raw_category.lower() in ["unknown", "none", "n/a", ""]: return raw_category, ""
        best_match_idx = torch.argmax(util.cos_sim(self.embedder.encode(raw_category, convert_to_tensor=True), self.category_embeddings)[0]).item()
        return self.categories[best_match_idx], self.cat_to_id.get(self.categories[best_match_idx], "")

    def get_nebula_plot(self, highlight_category=None):
        if not self.has_nebula: return go.Figure().update_layout(title="Nebula Offline")
        fig = go.Figure()
        fig.add_trace(go.Scatter3d(x=self.df_3d['x'], y=self.df_3d['y'], z=self.df_3d['z'], mode='markers', marker=dict(size=6, color=self.df_3d['ColorID'], colorscale='Turbo', opacity=0.85, line=dict(width=0.5, color='rgba(255,255,255,0.5)')), text=self.df_3d['Category'], hoverinfo='text', name='Categories'))
        scene_dict = dict(aspectmode='cube', xaxis=dict(visible=False), yaxis=dict(visible=False), zaxis=dict(visible=False))
        
        if highlight_category and highlight_category in self.categories:
            idx = self.categories.index(highlight_category)
            px, py, pz = self.df_3d.iloc[idx][['x', 'y', 'z']]
            fig.add_trace(go.Scatter3d(x=[px], y=[py], z=[pz], mode='markers', marker=dict(size=22, color='#FF0000', symbol='diamond', line=dict(color='white', width=3)), text=[f"🎯 TARGET:<br>{highlight_category}"], hoverinfo='text', name='Selected'))
            norm_x, norm_y, norm_z = px/self.max_range, py/self.max_range, pz/self.max_range
            scene_dict['camera'] = dict(center=dict(x=norm_x, y=norm_y, z=norm_z), eye=dict(x=norm_x + 0.15, y=norm_y + 0.15, z=norm_z + 0.15))
            ui_state = f"zoomed_in_{highlight_category}"
        else:
            frames = [go.Frame(layout=dict(scene=dict(camera=dict(eye=dict(x=1.8*np.cos(np.radians(t)), y=1.8*np.sin(np.radians(t)), z=0.5))))) for t in range(0, 360, 5)]
            fig.frames = frames
            fig.update_layout(updatemenus=[dict(type="buttons", showactive=False, y=0.1, x=0.5, xanchor="center", yanchor="bottom", buttons=[dict(label="🌌 Auto-Spin Nebula", method="animate", args=[None, dict(frame=dict(duration=50, redraw=True), transition=dict(duration=0), fromcurrent=True, mode="immediate")])])])
            scene_dict['camera'] = dict(center=dict(x=0, y=0, z=0), eye=dict(x=1.8, y=1.8, z=0.5))
            ui_state = "zoomed_out_global"

        return fig.update_layout(margin=dict(l=0, r=0, b=0, t=0), scene=scene_dict, showlegend=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', uirevision=ui_state)

category_mapper = CategoryMapper()

# --- HYBRID LLM (Unified Pipeline + Agent) ---
class HybridLLM:
    def _pil_to_base64(self, pil_image):
        if not pil_image: return None
        buffered = io.BytesIO()
        pil_image.save(buffered, format="JPEG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def _clean_and_parse_json(self, raw_text):
        try:
            text = re.sub(r'\x1b\[[0-9;]*m', '', raw_text)
            text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).replace("```json", "").replace("```", "").strip()
            start, end = text.find("{"), text.rfind("}") + 1
            if start != -1 and end != -1: return json.loads(text[start:end])
            return {"error": "No JSON found", "raw_output": text}
        except Exception as e: return {"error": f"JSON Parse Failed: {str(e)}"}

    # --- PIPELINE MODE LOGIC ---
    def query_pipeline(self, provider, backend_model, text, categories, tail_image=None, override=False, enable_search=False, force_multimodal=False, context_size=8192):
        sys_msg = "You are a Senior Marketing Analyst. Output STRICT JSON: {\"brand\": \"...\", \"category\": \"...\", \"confidence\": 0.0, \"reasoning\": \"...\"}"
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
        
        brand = res.get("brand", "Unknown") if isinstance(res, dict) else "Unknown"
        if brand.lower() in ["unknown", "none", "n/a", ""] and enable_search:
            words = [w for w in re.sub(r'[^a-zA-Z0-9\s]', '', text).split() if len(w) > 3]
            if words and (sr := search_manager.search(" ".join(words[:8]) + " brand company product")):
                res = call_model(sys_msg + "\nAGENTIC RECOVERY", f"OCR: {text}\nWEB: {sr}")
                res["reasoning"] = "(Recovered) " + res.get("reasoning", "")
                brand = res.get("brand", "Unknown")
                
        if "category" in res and enable_search and brand.lower() not in ["unknown", "none", "n/a", ""]:
            if val_snippets := search_manager.search(f"{brand} official brand company"):
                val_res = call_model(sys_msg + "\nVALIDATION MODE", f"Brand: {brand}\nWeb: {val_snippets}\nCorrect brand name. Keep category {res.get('category')}.")
                if "category" in val_res: return val_res
        return res

    # --- AGENT MODE LOGIC ---
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

# --- THE ReACT AGENT CORE ---

class AdClassifierAgent:
    def __init__(self, max_iterations=4):
        self.max_iterations = max_iterations

    def run(self, frames_data, categories, provider, model, ocr_engine, ocr_mode, allow_override, enable_search, enable_vision, context_size):
        memory_log = "Initial State: I am investigating a chronological storyboard of scenes extracted from an ad.\n"
        pil_images = [f["image"] for f in frames_data]
        
        for step in range(self.max_iterations):
            
            # 🚀 DYNAMIC MENU BUILDER: Only add tools and protocol steps if they are enabled in the UI!
            tools_list = ["- [TOOL: OCR] (Use first to extract all visible text from the video frames)"]
            examples_list = ["[TOOL: OCR]"]
            protocol_steps = ["1. You MUST always start by using [TOOL: OCR]."]
            step_num = 2
            
            if enable_search:
                tools_list.append('- [TOOL: SEARCH | query="search term"] (Use to web search company names, slogans, or partial URLs found in OCR)')
                examples_list.append('[TOOL: SEARCH | query="Nike slogan"]')
                protocol_steps.append(f"{step_num}. You MUST use [TOOL: SEARCH] at least once to fact-check the brand name or slogan found in the OCR before you are allowed to finish.")
                step_num += 1
                
            if enable_vision and category_mapper.categories and siglip_model is not None:
                tools_list.append('- [TOOL: VISION] (Use to check the visual probability against our official industry categories)')
                examples_list.append('[TOOL: VISION]')
                protocol_steps.append(f"{step_num}. (Optional) Use [TOOL: VISION] if you are still unsure about the product context.")
                step_num += 1
            
            tools_list.append('- [TOOL: FINAL | brand="Brand", category="Category", reason="Logic"] (Use only when you have confidently identified the brand and category)')
            examples_list.append('[TOOL: FINAL | brand="Apple", category="Tech", reason="Apple logo and website found in OCR"]')
            
            tools_str = "\n".join(tools_list)
            examples_str = "\n".join(examples_list)
            protocol_str = "\n".join(protocol_steps)

            system_prompt = f"""You are a Senior Marketing Analyst and Global Brand Expert.
Your goal is to categorize video advertisements by combining extracted text (OCR) with your vast internal knowledge of companies, slogans, and industries.
Rely on Internal Brand Knowledge: You know every major brand, their parent companies, and their marketing styles. Use this internal database as your absolute primary source of truth.
Treat OCR as Noisy Hints: The extracted OCR text is machine-generated and highly prone to typos, missing letters, and random artifacts. DO NOT blindly trust or copy the OCR text. Use your knowledge to autocorrect it.
(e.g., if OCR says 'Strbcks' or 'Star bucks co', you know the true brand is 'Starbucks').
Determine Category: Pick from 'Suggested Categories' or generate a professional tag if Override Allowed is True.

CRITICAL PROTOCOL - YOU MUST FOLLOW THESE STEPS IN ORDER:
{protocol_str}

CRITICAL INSTRUCTION: You MUST output exactly ONE tool command per turn. 
You must use the EXACT bracket syntax below. DO NOT output any conversational text. DO NOT output markdown blocks.

Tools available:
{tools_str}

Valid Examples:
{examples_str}

Current Memory:
{memory_log}"""
            
            yield memory_log, "Unknown", "Unknown", "", "N/A", "Agent is thinking..."
            
            response = llm_engine.query_agent(provider, model, system_prompt, images=pil_images, force_multimodal=enable_vision, context_size=context_size)
            
            if not response:
                response = "[TOOL: ERROR | reason=\"LLM returned absolute empty string. Check backend.\"]"

            thought = response.split('[TOOL:')[0].strip() if '[TOOL:' in response else response
            yield memory_log + f"\n🤔 Thought: {thought}\n", "Unknown", "Unknown", "", "N/A", "Executing Tool..."
            
            tool_match = re.search(r"\[TOOL:\s*(.*?)(?:\|\s*(.*?))?\]", response)
            observation = ""
            
            if tool_match:
                tool_name = tool_match.group(1).strip()
                kwargs = dict(re.findall(r'(\w+)="(.*?)"', tool_match.group(2) or ""))

                if tool_name == "FINAL":
                    brand = kwargs.get("brand", "Unknown")
                    raw_cat = kwargs.get("category", "Unknown")
                    official_cat, cat_id = category_mapper.get_closest_official_category(raw_cat)
                    reason = kwargs.get("reason", "No reason provided")
                    if raw_cat != official_cat: reason += f" [Mapped from '{raw_cat}']"
                    
                    memory_log += f"\n✅ FINAL CONCLUSION REACHED."
                    yield memory_log, brand, official_cat, cat_id, "N/A", reason
                    return
                    
                elif tool_name == "OCR":
                    all_findings = []
                    for i, f in enumerate(frames_data):
                        text = ocr_manager.extract_text(ocr_engine, f["ocr_image"], mode=ocr_mode)
                        if text: all_findings.append(f"[Scene {i+1}]: {text}")
                    observation = "Observation: " + (" | ".join(all_findings) if all_findings else "No text found.")
                    
                elif tool_name == "VISION":
                    # Hard-stop if hallucinated while disabled
                    if not enable_vision:
                        observation = "Observation: Formatting ERROR. The VISION tool is disabled by user settings. Proceed without it."
                    elif category_mapper.categories and siglip_model is not None and getattr(category_mapper, 'vision_text_features', None) is not None:
                        with torch.no_grad():
                            image_inputs = siglip_processor(images=pil_images, return_tensors="pt").to(device)
                            image_features = siglip_model.get_image_features(**image_inputs)
                            image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)
                            
                            logit_scale = siglip_model.logit_scale.exp()
                            logit_bias = siglip_model.logit_bias
                            logits_per_image = (image_features @ category_mapper.vision_text_features.t()) * logit_scale + logit_bias
                            probs = torch.sigmoid(logits_per_image)
                            
                        scores = probs.mean(dim=0).cpu().numpy()
                        top_cats = dict(sorted({category_mapper.categories[i]: float(scores[i]) for i in range(len(category_mapper.categories))}.items(), key=lambda item: item[1], reverse=True)[:5])
                        observation = f"Observation: Vision Model's Top 5 matches from the official CSV taxonomy: {top_cats}"
                    else:
                        observation = "Observation: Vision Model unavailable or text embeddings failed to cache."
                
                elif tool_name == "SEARCH":
                    # Hard-stop if hallucinated while disabled
                    if not enable_search:
                        observation = "Observation: Formatting ERROR. Web Search is disabled by user settings. Proceed without searching."
                    else:
                        observation = f"Observation from Web: {search_manager.search(kwargs.get('query', ''))}"
            else:
                observation = "Observation: Formatting ERROR. Missing [TOOL: ] syntax. Remember to ONLY output the tool command."

            memory_log += f"\n--- Step {step + 1} ---\nAction: {response}\nResult: {observation}\n"

        yield memory_log, "Unknown", "Unknown", "", "N/A", "Agent Timeout: Max iterations reached."


# --- HELPERS ---
def fetch_ollama_models():
    try: return [m["name"] for m in requests.get("http://localhost:11434/api/tags", timeout=1).json().get("models", [])]
    except: return []
def fetch_lmstudio_models():
    try: return [m["id"] for m in requests.get("http://localhost:1234/v1/models", timeout=1).json().get("data", [])]
    except: return []
def update_model_dropdown(provider):
    if provider == "Ollama": return gr.update(choices=fetch_ollama_models() or ["Ensure Ollama running"], value=fetch_ollama_models()[0] if fetch_ollama_models() else "")
    elif provider == "LM Studio": return gr.update(choices=fetch_lmstudio_models() or ["Ensure LM Studio running"], value=fetch_lmstudio_models()[0] if fetch_lmstudio_models() else "")
    return gr.update(choices=["Gemini CLI Default"], value="Gemini CLI Default")
def get_stream_url(video_url):
    if os.path.exists(video_url): return video_url
    try:
        with yt_dlp.YoutubeDL({'format': 'best', 'quiet': True}) as ydl: return ydl.extract_info(video_url, download=False).get('url', video_url)
    except: return video_url

# --- PIPELINE WORKER ---
def process_single_video(url, categories, p, m, oe, om, override, sm, enable_search, enable_vision, ctx):
    try:
        logger.info(f"[{url}] === STARTING PIPELINE WORKER ===")
        cap = cv2.VideoCapture(get_stream_url(url))
        if not cap.isOpened(): 
            logger.error(f"[{url}] Video Load Failed.")
            return {}, "Error", "Failed", [], [url, "Error", "", "Error", 0, "Load Failed"]
            
        fps, total = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frames = []
        for t in range(int(max(0, (total/fps)-3)*fps), total, max(1, int(total/6))):
            cap.set(cv2.CAP_PROP_POS_FRAMES, t)
            ret, fr = cap.read()
            if ret: frames.append({"image": Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)), "ocr_image": fr, "time": t/fps, "type": "tail"})
        cap.release()
        
        if not frames: 
            logger.warning(f"[{url}] Extraction yielded no frames.")
            return {}, "Err", "No frames", [], [url, "Err", "", "Err", 0, "Empty"]
        
        # 🚀 ENRICHED SIGLIP LOGGING
        sorted_vision = {}
        if enable_vision and category_mapper.categories and siglip_model is not None and getattr(category_mapper, 'vision_text_features', None) is not None:
            logger.info(f"[{url}] 👁️ SigLIP Vision Triggered: Evaluating {len(frames)} frames against {len(category_mapper.categories)} categories...")
            start_time = time.time()
            
            with torch.no_grad():
                pil_images = [f["image"] for f in frames]
                image_inputs = siglip_processor(images=pil_images, return_tensors="pt").to(device)
                image_features = siglip_model.get_image_features(**image_inputs)
                image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)
                
                logit_scale = siglip_model.logit_scale.exp()
                logit_bias = siglip_model.logit_bias
                logits_per_image = (image_features @ category_mapper.vision_text_features.t()) * logit_scale + logit_bias
                probs = torch.sigmoid(logits_per_image)
                
            scores = probs.mean(dim=0).cpu().numpy()
            sorted_vision = dict(sorted({category_mapper.categories[i]: float(scores[i]) for i in range(len(category_mapper.categories))}.items(), key=lambda item: item[1], reverse=True)[:5])
            
            # Write the exact scores and execution time to the debug log!
            logger.debug(f"[{url}] SigLIP Matrix Math completed in {time.time() - start_time:.2f} seconds.")
            logger.info(f"[{url}] SigLIP Top 5 Matches: {sorted_vision}")
        else:
            logger.debug(f"[{url}] SigLIP Vision skipped (Disabled in UI or missing dependencies).")
        
        # Base OCR and LLM routing
        logger.info(f"[{url}] 📝 Extracting OCR text...")
        ocr_text = "\n".join([f"[{f['time']:.1f}s] {ocr_manager.extract_text(oe, f['ocr_image'], om)}" for f in frames])
        
        logger.info(f"[{url}] 🧠 Querying LLM Pipeline...")
        res = llm_engine.query_pipeline(p, m, ocr_text, categories, frames[-1]["image"], override, enable_search, enable_vision, ctx)
        
        cat_out, cat_id_out = category_mapper.get_closest_official_category(res.get("category", "Unknown"))
        row = [url, res.get("brand", "Unknown"), cat_id_out, cat_out, res.get("confidence", 0.0), res.get("reasoning", "")]
        
        logger.info(f"[{url}] === FINISHED | Brand: {row[1]} | Category: {cat_out} ===")
        return sorted_vision, ocr_text, f"Category: {cat_out}", [(f["ocr_image"], f"{f['time']}s") for f in frames], row
        
    except Exception as e: 
        logger.error(f"[{url}] Pipeline Worker Crash: {str(e)}", exc_info=True)
        return {}, "Err", str(e), [], [url, "Err", "", "Err", 0, str(e)]


# --- EXECUTION MANAGERS ---
def run_pipeline(src, urls, fldr, cats, p, m, oe, om, override, sm, enable_search, enable_vision, ctx, workers):
    urls_list = [u.strip() for u in urls.split("\n") if u.strip()] if src == "Web URLs" else [os.path.join(fldr, f) for f in os.listdir(fldr) if f.lower().endswith(('.mp4', '.mov'))] if os.path.isdir(fldr) else []
    cat_list = [c.strip() for c in cats.split(",") if c.strip()]
    master = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(process_single_video, u, cat_list, p, m, oe, om, override, sm, enable_search, enable_vision, ctx): u for u in urls_list}
        for fut in concurrent.futures.as_completed(futures):
            v, t, d, g, row = fut.result()
            master.append(row)
            yield v, t, d, g, pd.DataFrame(master, columns=["URL / Path", "Brand", "Category ID", "Category", "Confidence", "Reasoning"])

def run_agent(src, urls, fldr, cats, p, m, oe, om, override, sm, enable_search, enable_vision, ctx):
    urls_list = [u.strip() for u in urls.split("\n") if u.strip()] if src == "Web URLs" else [os.path.join(fldr, f) for f in os.listdir(fldr) if f.lower().endswith(('.mp4', '.mov'))] if os.path.isdir(fldr) else []
    cat_list = [c.strip() for c in cats.split(",") if c.strip()]
    master = []
    agent = AdClassifierAgent()
    
    for url in urls_list:
        yield f"Processing {url}...", [], pd.DataFrame(master, columns=["URL / Path", "Brand", "Category ID", "Category", "Confidence", "Reasoning"]), category_mapper.get_nebula_plot()
        try:
            cap = cv2.VideoCapture(get_stream_url(url))
            frames = []
            for t in range(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), int(cap.get(cv2.CAP_PROP_FPS)*2)):
                cap.set(cv2.CAP_PROP_POS_FRAMES, t)
                ret, fr = cap.read()
                if ret: frames.append({"image": Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)), "ocr_image": fr, "time": t/cap.get(cv2.CAP_PROP_FPS), "type": "scene"})
            cap.release()
            gallery = [(f["ocr_image"], f"{f['time']}s") for f in frames]
            
            for log, b, c, cid, conf, r in agent.run(frames, cat_list, p, m, oe, om, override, enable_search, enable_vision, ctx):
                brand, cat, cat_id, reason = b, c, cid, r
                yield log, gallery, pd.DataFrame(master, columns=["URL / Path", "Brand", "Category ID", "Category", "Confidence", "Reasoning"]), category_mapper.get_nebula_plot(cat)
            
            master.append([url, brand, cat_id, cat, "N/A", reason])
            yield log, gallery, pd.DataFrame(master, columns=["URL / Path", "Brand", "Category ID", "Category", "Confidence", "Reasoning"]), category_mapper.get_nebula_plot(cat)
            time.sleep(4)
        except Exception as e:
            master.append([url, "Error", "", "Error", "N/A", str(e)])


# --- UNIFIED UI ---
with gr.Blocks(title="Unified Ad Classifier") as demo:
    gr.Markdown("# 🎬 Ad Classifier: Unified Engine (Pipeline & Agent)")
    
    exec_mode = gr.Radio(["Standard Pipeline (Concurrent)", "ReACT Agent (Sequential Live)"], label="Execution Mode", value="Standard Pipeline (Concurrent)")
    
    with gr.Row():
        with gr.Column(scale=1):
            input_source = gr.Radio(["Web URLs", "Local Folder"], label="Input Source", value="Web URLs")
            url_input = gr.Textbox(label="Video URLs (One per line)", lines=3)
            folder_input = gr.Textbox(label="Local Directory Path", lines=1, visible=False)
            input_source.change(fn=lambda c: (gr.update(visible=c=="Web URLs"), gr.update(visible=c=="Local Folder")), inputs=[input_source], outputs=[url_input, folder_input])
            cats_input = gr.Textbox(label="Categories (Optional)")
            
            with gr.Row():
                provider_selector = gr.Radio(["Gemini CLI", "Ollama", "LM Studio"], label="LLM Provider", value="Gemini CLI")
                llm_selector = gr.Dropdown(["Gemini CLI Default"], label="LLM Model", value="Gemini CLI Default")
            provider_selector.change(fn=update_model_dropdown, inputs=[provider_selector], outputs=[llm_selector])
            ocr_selector = gr.Dropdown(["EasyOCR", "Florence-2 (Microsoft)"], label="OCR Engine", value="EasyOCR")
            
            with gr.Accordion("⚙️ Engine Settings", open=True):
                workers_slider = gr.Slider(minimum=1, maximum=10, value=2, step=1, label="Concurrent Workers (Pipeline Only)")
                context_size_slider = gr.Slider(minimum=2048, maximum=32768, value=8192, step=1024, label="Context Limit")
                scan_mode = gr.Radio(["Full Video", "Tail Only"], label="Scan Strategy", value="Tail Only")
                ocr_mode = gr.Radio(["🚀 Fast", "🧠 Detailed"], label="OCR Mode", value="🚀 Fast")
                override_chk = gr.Checkbox(label="Allow LLM to invent new categories", value=False)
                
                # 🚀 The renamed checkboxes
                search_chk = gr.Checkbox(label="🌐 Web Features: Enable Agentic Search", value=True)
                enable_vision_chk = gr.Checkbox(label="👁️ Vision Tool: Enable Image Analysis", value=True)

            btn_pipe = gr.Button("🚀 Start Concurrent Pipeline", variant="primary", visible=True)
            btn_agent = gr.Button("🧠 Start ReACT Agent", variant="primary", visible=False)
            
        with gr.Column(scale=1):
            with gr.Column(visible=True) as pipe_group:
                with gr.Tabs():
                    with gr.TabItem("🖼️ Latest Frames"): ocr_gallery_pipe = gr.Gallery()
                    with gr.TabItem("📊 Vision Data"): vision_label = gr.Label()
                    with gr.TabItem("📝 OCR Output"): ocr_output = gr.Textbox(lines=10)
                final_output = gr.Markdown("### 🏁 Latest Status")
            
            with gr.Column(visible=False) as agent_group:
                with gr.Tabs():
                    with gr.TabItem("🧠 Inner Monologue"): log_out = gr.Textbox(lines=15, max_lines=30, autoscroll=True, label="Agent Scratchpad")
                    with gr.TabItem("🖼️ Storyboard"): ocr_gallery_agent = gr.Gallery()
                    with gr.TabItem("🌌 Semantic Nebula"): nebula_plot = gr.Plot()

    gr.Markdown("## 📋 Unified Batch Results")
    batch_table = gr.Dataframe(headers=["URL / Path", "Brand", "Category ID", "Category", "Confidence", "Reasoning"], interactive=False, wrap=True)
    gr.Button("💾 Export").click(fn=lambda df: df.to_csv("results.csv", index=False) or "results.csv", inputs=batch_table, outputs=gr.File(label="Download"))

    def toggle_mode(mode):
        is_pipe = mode == "Standard Pipeline (Concurrent)"
        return gr.update(visible=is_pipe), gr.update(visible=not is_pipe), gr.update(visible=is_pipe), gr.update(visible=not is_pipe), gr.update(visible=is_pipe)
    
    exec_mode.change(fn=toggle_mode, inputs=[exec_mode], outputs=[pipe_group, agent_group, btn_pipe, btn_agent, workers_slider])

    # 🚀 FIXED: The inputs lists below now use 'enable_vision_chk' instead of 'force_multimodal_chk'
    btn_pipe.click(fn=run_pipeline, inputs=[input_source, url_input, folder_input, cats_input, provider_selector, llm_selector, ocr_selector, ocr_mode, override_chk, scan_mode, search_chk, enable_vision_chk, context_size_slider, workers_slider], outputs=[vision_label, ocr_output, final_output, ocr_gallery_pipe, batch_table])
    btn_agent.click(fn=run_agent, inputs=[input_source, url_input, folder_input, cats_input, provider_selector, llm_selector, ocr_selector, ocr_mode, override_chk, scan_mode, search_chk, enable_vision_chk, context_size_slider], outputs=[log_out, ocr_gallery_agent, batch_table, nebula_plot])

if __name__ == "__main__":
    demo.launch()