import os
import cv2
import yt_dlp
from typing import Any
from PIL import Image
from video_service.core.utils import logger

def get_stream_url(video_url: str) -> str:
    if os.path.exists(video_url): return video_url
    try:
        with yt_dlp.YoutubeDL({'format': 'best', 'quiet': True}) as ydl: return ydl.extract_info(video_url, download=False).get('url', video_url)
    except: return video_url

def _parse_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, str(default))
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("invalid_env_value name=%s value=%r fallback=%.4f", name, raw, default)
        return default


def _parse_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("invalid_env_value name=%s value=%r fallback=%d", name, raw, default)
        return default


def _compute_hs_histogram(frame_bgr: Any) -> Any:
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
    return cv2.normalize(hist, None).flatten()


def _maybe_extend_tail_frames(
    frames: list[dict[str, Any]],
    cap: Any,
    fps: float,
    tail_start_frame: int,
) -> list[dict[str, Any]]:
    # Require at least three tail samples before calling it static.
    # With only two frames, false-positive static detection is common.
    if len(frames) < 3:
        return frames

    threshold = _parse_float_env("TAIL_STATIC_THRESHOLD", 0.97)
    max_backward_seconds = max(0, _parse_int_env("TAIL_MAX_BACKWARD_SECONDS", 12))
    if max_backward_seconds == 0:
        logger.debug("tail_static_check disabled: TAIL_MAX_BACKWARD_SECONDS=0")
        return frames

    original_frames = list(frames)
    try:
        tail_histograms = [_compute_hs_histogram(frame["ocr_image"]) for frame in frames]
        consecutive_scores: list[float] = []
        for idx in range(len(tail_histograms) - 1):
            score = float(
                cv2.compareHist(
                    tail_histograms[idx],
                    tail_histograms[idx + 1],
                    cv2.HISTCMP_CORREL,
                )
            )
            consecutive_scores.append(score)
            logger.debug(
                "tail_hist_corr pair=%d->%d score=%.4f threshold=%.4f",
                idx,
                idx + 1,
                score,
                threshold,
            )

        if any(score <= threshold for score in consecutive_scores):
            logger.debug("tail_static_check: dynamic tail detected; no backward extension")
            return frames

        logger.info(
            "tail_static_check: static endcard detected; backward walk start_frame=%d threshold=%.4f max_seconds=%d",
            tail_start_frame,
            threshold,
            max_backward_seconds,
        )

        static_reference_hist = tail_histograms[-1]
        hop_frames = max(1, int(fps * 2))
        max_backward_frames = max(1, int(max_backward_seconds * fps))

        cursor = max(0, tail_start_frame - hop_frames)
        walked_frames = 0
        candidate_frames: list[dict[str, Any]] = []
        found_different_scene = False

        while cursor >= 0 and walked_frames < max_backward_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, cursor)
            ret, fr = cap.read()
            if not ret:
                logger.debug("backward_walk frame_read_failed frame=%d", cursor)
                break

            hist = _compute_hs_histogram(fr)
            corr = float(cv2.compareHist(hist, static_reference_hist, cv2.HISTCMP_CORREL))
            walked_frames = tail_start_frame - cursor
            logger.debug(
                "backward_walk_hist_corr frame=%d time=%.2fs score=%.4f threshold=%.4f",
                cursor,
                cursor / fps,
                corr,
                threshold,
            )

            candidate_frames.append(
                {
                    "image": Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)),
                    "ocr_image": fr,
                    "time": cursor / fps,
                    "type": "backward_ext",
                }
            )

            if corr <= threshold:
                found_different_scene = True
                break
            cursor -= hop_frames

        if found_different_scene and candidate_frames:
            frames[:0] = list(reversed(candidate_frames))
            logger.info(
                "backward_walk: extended %.1fs, added %d frames",
                walked_frames / fps,
                len(candidate_frames),
            )
        else:
            logger.info(
                "backward_walk: extended %.1fs, added 0 frames",
                min(max_backward_seconds, walked_frames / fps if fps > 0 else 0.0),
            )
        return frames
    except Exception as exc:
        logger.warning("tail_static_check_failed: %s", exc)
        return original_frames


def extract_frames_for_pipeline(url: str, scan_mode: str = "Tail Only") -> tuple[list[dict[str, Any]], Any]:
    cap = cv2.VideoCapture(get_stream_url(url))
    frames: list[dict[str, Any]] = []
    if not cap.isOpened():
        return frames, cap
    
    fps, total = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    if total <= 0 or fps <= 0:
        return frames, cap

    mode = (scan_mode or "").strip().lower()
    full_video_modes = {"full video", "full scan"}
    if mode in full_video_modes:
        start = 0
        step = max(1, int(fps * 2))
        frame_type = "scene"
    else:
        tail_window_seconds = 3
        target_tail_frames = _parse_int_env("TAIL_TARGET_FRAMES", 5)
        start = int(max(0, (total / fps) - tail_window_seconds) * fps)
        tail_window_frames = total - start
        step = max(1, int(tail_window_frames / max(1, target_tail_frames)))
        logger.debug(
            "tail_sampling: start_frame=%d step=%d expected_frames=%d tail_window=%.1fs",
            start,
            step,
            len(range(start, total, step)),
            tail_window_seconds,
        )
        frame_type = "tail"

    for t in range(start, total, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, t)
        ret, fr = cap.read()
        if ret: 
            frames.append({"image": Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)), "ocr_image": fr, "time": t/fps, "type": frame_type})

    if frame_type == "tail":
        frames = _maybe_extend_tail_frames(frames, cap, fps, start)

    return frames, cap

def extract_frames_for_agent(url: str) -> tuple[list[dict[str, Any]], Any]:
    cap = cv2.VideoCapture(get_stream_url(url))
    frames: list[dict[str, Any]] = []
    if not cap.isOpened():
        return frames, cap
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0 or total <= 0:
        return frames, cap

    for t in range(0, total, int(fps*2)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, t)
        ret, fr = cap.read()
        if ret: 
            frames.append({"image": Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)), "ocr_image": fr, "time": t/fps, "type": "scene"})
    
    return frames, cap

def resolve_urls(src: str, urls: str, fldr: str) -> list[str]:
    if src == "Web URLs":
        return [u.strip() for u in urls.split("\n") if u.strip()]
    elif os.path.isdir(fldr):
        return [os.path.join(fldr, f) for f in os.listdir(fldr) if f.lower().endswith(('.mp4', '.mov'))]
    return []
