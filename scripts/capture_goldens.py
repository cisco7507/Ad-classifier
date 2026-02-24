#!/usr/bin/env python3
"""
scripts/capture_goldens.py
==========================
Captures golden reference outputs by running poc/combined.py core logic
directly (no Gradio, no API). Outputs are saved to tests/golden/<fixture_id>.json.

Usage:
    source venv/bin/activate
    python scripts/capture_goldens.py                  # all fixtures
    python scripts/capture_goldens.py --fixture short_url  # specific fixture

This script imports the EXTRACTED service modules (video_service.core.*), NOT
combined.py directly, because:
1. combined.py starts a Gradio server on import.
2. The service modules ARE the ported core of combined.py.
3. Any behavioral difference is itself a bug to fix — not a tolerance to add.

To refresh goldens after an intentional behavioral change:
    python scripts/capture_goldens.py --force
    git add tests/golden/ && git commit -m "chore: refresh parity goldens (reason: <why>)"
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FIXTURES_FILE = PROJECT_ROOT / "tests" / "fixtures" / "parity_fixtures.json"
GOLDEN_DIR    = PROJECT_ROOT / "tests" / "golden"
GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

# ---- Lazy imports so the script fails fast if env is wrong ----------------
def load_service_modules():
    """Import video_service modules — triggers model loading."""
    from video_service.core.video_io import extract_frames_for_pipeline, get_stream_url
    from video_service.core.ocr import ocr_manager
    from video_service.core.categories import category_mapper
    from video_service.core.llm import llm_engine
    return extract_frames_for_pipeline, get_stream_url, ocr_manager, category_mapper, llm_engine


def capture_fixture(fixture: dict, force: bool = False) -> dict:
    """
    Run the pipeline on one fixture using the service core modules and
    return a golden dict.
    """
    fid = fixture["id"]
    golden_path = GOLDEN_DIR / f"{fid}.json"

    if golden_path.exists() and not force:
        print(f"  [SKIP] {fid} — golden already exists (use --force to overwrite)")
        return json.loads(golden_path.read_text())

    print(f"  [CAPTURE] {fid} ...")
    extract_frames_for_pipeline, get_stream_url, ocr_manager, category_mapper, llm_engine = load_service_modules()

    s = fixture["settings"]
    target_url = fixture.get("url") or fixture.get("local_path")
    if not target_url:
        raise ValueError(f"Fixture {fid} has neither 'url' nor 'local_path'")

    # Resolve local path relative to project root
    if fixture.get("local_path") and not os.path.isabs(fixture["local_path"]):
        target_url = str(PROJECT_ROOT / fixture["local_path"])

    if not os.path.exists(target_url) and not target_url.startswith("http"):
        raise FileNotFoundError(f"Local fixture file not found: {target_url}")

    t0 = time.time()

    # --- Frame extraction (mirrors process_single_video in combined.py) ---
    frames, cap = extract_frames_for_pipeline(target_url)
    if cap and cap.isOpened():
        cap.release()

    if not frames:
        raise RuntimeError(f"No frames extracted from {target_url}")

    frame_meta = [
        {"time_seconds": round(f["time"], 3), "type": f.get("type", "tail")}
        for f in frames
    ]

    # --- OCR ---
    ocr_lines = []
    for f in frames:
        text = ocr_manager.extract_text(s["ocr_engine"], f["ocr_image"], s["ocr_mode"])
        ocr_lines.append({"time_seconds": round(f["time"], 3), "text": text})

    full_ocr_text = "\n".join([f"[{l['time_seconds']:.1f}s] {l['text']}" for l in ocr_lines])

    # --- LLM pipeline ---
    cat_list = [c.strip() for c in s["categories"].split(",") if c.strip()]
    res = llm_engine.query_pipeline(
        s["provider"], s["model_name"],
        full_ocr_text, cat_list,
        frames[-1]["image"],
        s["override"], s["enable_search"], s["enable_vision"], s["context_size"]
    )

    # --- Category mapping ---
    cat_out, cat_id_out = category_mapper.get_closest_official_category(res.get("category", "Unknown"))

    ocr_has_text = any(l["text"].strip() for l in ocr_lines)

    golden = {
        "_fixture_id": fid,
        "_captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "_elapsed_seconds": round(time.time() - t0, 1),
        "_source": target_url,
        "_settings": s,

        # === Parity fields ===
        "frame_count": len(frames),
        "frame_meta": frame_meta,                   # timestamps + type
        "ocr_has_text": ocr_has_text,               # at least some OCR output
        "ocr_lines": ocr_lines,                     # per-frame OCR (used for presence checks)

        # Core classification result
        "result": {
            "brand":      res.get("brand",      "Unknown"),
            "category":   cat_out,
            "category_id": cat_id_out,
            "confidence": round(float(res.get("confidence", 0.0)), 4),
            "reasoning":  res.get("reasoning",  ""),
        }
    }

    golden_path.write_text(json.dumps(golden, indent=2))
    print(f"    ✅  Saved {golden_path.name}  ({len(frames)} frames, brand={golden['result']['brand']}, cat={golden['result']['category']})")
    return golden


def main():
    parser = argparse.ArgumentParser(description="Capture golden parity outputs from service core modules.")
    parser.add_argument("--fixture", help="Fixture ID to capture (omit for all)")
    parser.add_argument("--force",   action="store_true", help="Overwrite existing goldens")
    args = parser.parse_args()

    fixtures = json.loads(FIXTURES_FILE.read_text())["fixtures"]
    if args.fixture:
        fixtures = [f for f in fixtures if f["id"] == args.fixture]
        if not fixtures:
            print(f"ERROR: fixture '{args.fixture}' not found in parity_fixtures.json")
            sys.exit(1)

    print(f"\n📸  Capturing {len(fixtures)} golden(s)...\n")
    for fixture in fixtures:
        try:
            capture_fixture(fixture, force=args.force)
        except Exception as e:
            print(f"  ❌  FAILED {fixture['id']}: {e}")
            raise

    print("\n✅  All goldens captured.\n")


if __name__ == "__main__":
    main()
