import time
import re
import torch
import pandas as pd
from video_service.core.utils import logger, device
from video_service.core.categories import category_mapper, siglip_model, siglip_processor
from video_service.core.video_io import extract_frames_for_agent, resolve_urls
from video_service.core.ocr import ocr_manager
from video_service.core.llm import llm_engine, search_manager

class AdClassifierAgent:
    def __init__(self, max_iterations=4):
        self.max_iterations = max_iterations

    def run(self, frames_data, categories, provider, model, ocr_engine, ocr_mode, allow_override, enable_search, enable_vision, context_size):
        memory_log = "Initial State: I am investigating a chronological storyboard of scenes extracted from an ad.\n"
        pil_images = [f["image"] for f in frames_data]
        
        for step in range(self.max_iterations):
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
                    if not enable_search:
                        observation = "Observation: Formatting ERROR. Web Search is disabled by user settings. Proceed without searching."
                    else:
                        observation = f"Observation from Web: {search_manager.search(kwargs.get('query', ''))}"
            else:
                observation = "Observation: Formatting ERROR. Missing [TOOL: ] syntax. Remember to ONLY output the tool command."

            memory_log += f"\n--- Step {step + 1} ---\nAction: {response}\nResult: {observation}\n"

        yield memory_log, "Unknown", "Unknown", "", "N/A", "Agent Timeout: Max iterations reached."

def run_agent_job(src, urls, fldr, cats, p, m, oe, om, override, sm, enable_search, enable_vision, ctx):
    urls_list = resolve_urls(src, urls, fldr)
    cat_list = [c.strip() for c in cats.split(",") if c.strip()]
    master = []
    agent = AdClassifierAgent()
    
    for url in urls_list:
        yield f"Processing {url}...", [], pd.DataFrame(master, columns=["URL / Path", "Brand", "Category ID", "Category", "Confidence", "Reasoning"]), category_mapper.get_nebula_plot()
        try:
            frames, cap = extract_frames_for_agent(url)
            if cap and cap.isOpened():
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
