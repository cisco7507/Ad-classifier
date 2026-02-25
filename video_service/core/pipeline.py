import time
import os
import re
import torch
import cv2
import pandas as pd
import concurrent.futures
from contextvars import copy_context
from video_service.core.utils import logger, device, TORCH_DTYPE
from video_service.core.video_io import extract_frames_for_pipeline, resolve_urls
from video_service.core import categories as categories_runtime
from video_service.core.categories import category_mapper, normalize_feature_tensor
from video_service.core.ocr import ocr_manager
from video_service.core.llm import llm_engine

RESULT_COLUMNS = [
    "URL / Path",
    "Brand",
    "Category ID",
    "Category",
    "Confidence",
    "Reasoning",
    "category_match_method",
    "category_match_score",
]


def _normalize_ocr(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", (text or "").lower()).strip()


def _ocr_texts_similar(a: str, b: str, threshold: float = 0.85) -> bool:
    if not a and not b:
        return True
    if not a or not b:
        return False
    words_a, words_b = set(a.split()), set(b.split())
    if not words_a and not words_b:
        return True
    union = words_a | words_b
    if not union:
        return True
    return (len(words_a & words_b) / len(union)) >= threshold


def _resolve_ocr_dedup_threshold() -> float:
    raw = os.environ.get("OCR_DEDUP_THRESHOLD", "0.85")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("invalid_ocr_dedup_threshold value=%r fallback=0.85", raw)
        return 0.85
    return max(0.0, min(1.0, value))


def process_single_video(
    url,
    categories,
    p,
    m,
    oe,
    om,
    override,
    sm,
    enable_search,
    enable_vision,
    ctx,
    job_id=None,
    stage_callback=None,
):
    try:
        if stage_callback:
            stage_callback("ingest", "validating and preparing input")
        logger.info(f"[{url}] === STARTING PIPELINE WORKER ===")
        frames, cap = extract_frames_for_pipeline(url, scan_mode=sm)
        if cap and cap.isOpened():
            cap.release()
        
        if not frames: 
            logger.warning(f"[{url}] Extraction yielded no frames.")
            return {}, "Err", "No frames", [], [url, "Err", "", "Err", 0, "Empty", "none", None]

        if stage_callback:
            extracted_mode = "full video" if frames[0].get("type") == "scene" else "tail only"
            stage_callback("frame_extract", f"extracted {len(frames)} frames ({extracted_mode})")
        
        sorted_vision = {}
        if enable_vision:
            ready, reason = category_mapper.ensure_vision_text_features()
            siglip_model = categories_runtime.siglip_model
            siglip_processor = categories_runtime.siglip_processor
            if ready and siglip_model is not None and siglip_processor is not None:
                if stage_callback:
                    stage_callback("vision", "vision enabled; computing visual category scores")
                start_time = time.time()
                with torch.no_grad():
                    pil_images = [f["image"] for f in frames]
                    image_inputs = siglip_processor(images=pil_images, return_tensors="pt").to(device)
                    if TORCH_DTYPE != torch.float32:
                        image_inputs = {k: v.to(dtype=TORCH_DTYPE) if torch.is_floating_point(v) else v for k, v in image_inputs.items()}
                    image_features = siglip_model.get_image_features(**image_inputs)
                    image_features = normalize_feature_tensor(
                        image_features,
                        source="SigLIP.get_image_features",
                    )
                    
                    logit_scale = siglip_model.logit_scale.exp()
                    logit_bias = siglip_model.logit_bias
                    logits_per_image = (image_features @ category_mapper.vision_text_features.t()) * logit_scale + logit_bias
                    probs = torch.sigmoid(logits_per_image)
                    
                scores = probs.mean(dim=0).cpu().numpy()
                sorted_vision = dict(sorted({category_mapper.categories[i]: float(scores[i]) for i in range(len(category_mapper.categories))}.items(), key=lambda item: item[1], reverse=True)[:5])
                logger.debug("[%s] vision_scoring_done in %.2fs", url, time.time() - start_time)
            else:
                if stage_callback:
                    stage_callback("vision", f"vision skipped; {reason}")
                logger.info("[%s] vision skipped: %s", url, reason)
        
        if stage_callback:
            stage_callback("ocr", f"ocr engine={oe.lower()}")
        dedup_threshold = _resolve_ocr_dedup_threshold()
        ocr_lines: list[str] = []
        prev_normalized: str | None = None
        skipped_count = 0
        last_index = len(frames) - 1
        for idx, frame in enumerate(frames):
            raw_text = ocr_manager.extract_text(oe, frame["ocr_image"], om)
            normalized = _normalize_ocr(raw_text)
            is_last_frame = idx == last_index
            if (
                prev_normalized is not None
                and not is_last_frame
                and _ocr_texts_similar(normalized, prev_normalized, dedup_threshold)
            ):
                skipped_count += 1
                logger.debug(
                    "ocr_dedup_skip: frame at %.1fs similar to previous threshold=%.2f",
                    frame["time"],
                    dedup_threshold,
                )
                continue
            ocr_lines.append(f"[{frame['time']:.1f}s] {raw_text}")
            prev_normalized = normalized
        ocr_text = "\n".join(ocr_lines)
        logger.info(
            "ocr_dedup: processed=%d skipped=%d total_frames=%d threshold=%.2f",
            len(ocr_lines),
            skipped_count,
            len(frames),
            dedup_threshold,
        )
        if stage_callback:
            stage_callback("llm", f"calling provider={p.lower()} model={m}")
        res = llm_engine.query_pipeline(p, m, ocr_text, categories, frames[-1]["image"], override, enable_search, enable_vision, ctx)
        
        category_match = category_mapper.map_category(
            raw_category=res.get("category", "Unknown"),
            job_id=job_id,
            suggested_categories_text="",
            predicted_brand=res.get("brand", "Unknown"),
            ocr_summary=ocr_text,
        )
        cat_out = category_match["canonical_category"]
        cat_id_out = category_match["category_id"]
        row = [
            url,
            res.get("brand", "Unknown"),
            cat_id_out,
            cat_out,
            res.get("confidence", 0.0),
            res.get("reasoning", ""),
            category_match["category_match_method"],
            category_match["category_match_score"],
        ]
        
        return sorted_vision, ocr_text, f"Category: {cat_out}", [(f["ocr_image"], f"{f['time']}s") for f in frames], row
        
    except Exception as e: 
        logger.error(f"[{url}] Pipeline Worker Crash: {str(e)}", exc_info=True)
        return {}, "Err", str(e), [], [url, "Err", "", "Err", 0, str(e), "none", None]

def run_pipeline_job(
    src,
    urls,
    fldr,
    cats,
    p,
    m,
    oe,
    om,
    override,
    sm,
    enable_search,
    enable_vision,
    ctx,
    workers,
    job_id=None,
    stage_callback=None,
):
    if stage_callback:
        stage_callback("ingest", "resolving input sources")
    urls_list = resolve_urls(src, urls, fldr)
    if stage_callback:
        stage_callback("ingest", f"resolved {len(urls_list)} input item(s)")
    cat_list = [c.strip() for c in cats.split(",") if c.strip()]
    master = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(
                copy_context().run,
                process_single_video,
                u,
                cat_list,
                p,
                m,
                oe,
                om,
                override,
                sm,
                enable_search,
                enable_vision,
                ctx,
                job_id,
                stage_callback,
            ): u
            for u in urls_list
        }
        for fut in concurrent.futures.as_completed(futures):
            v, t, d, g, row = fut.result()
            master.append(row)
            yield v, t, d, g, pd.DataFrame(master, columns=RESULT_COLUMNS)
