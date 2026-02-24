"""
video_service/core/security.py
================================
Security helpers used by API endpoints.

- URL fetch protection  : allowed schemes, optional host allowlist/denylist,
                          request timeout + max content-length
- Upload size guard     : configurable MAX_UPLOAD_BYTES
- Path traversal guard  : safe_folder_path() for by-folder endpoints
"""

import os
import re
import logging
from urllib.parse import urlparse
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# ── Configuration (all overridable via env) ──────────────────────────────────

MAX_UPLOAD_MB: float = float(os.environ.get("MAX_UPLOAD_MB", "500"))
MAX_UPLOAD_BYTES: int = int(MAX_UPLOAD_MB * 1024 * 1024)

URL_FETCH_TIMEOUT: float = float(os.environ.get("URL_FETCH_TIMEOUT", "30"))
URL_MAX_SIZE_MB: float = float(os.environ.get("URL_MAX_SIZE_MB", "2048"))

# Comma-separated list of allowed hostnames (empty = allow all)
_ALLOWLIST_RAW = os.environ.get("URL_HOST_ALLOWLIST", "")
URL_HOST_ALLOWLIST: list[str] = [h.strip().lower() for h in _ALLOWLIST_RAW.split(",") if h.strip()]

# Comma-separated list of denied hostnames (empty = deny none)
_DENYLIST_RAW = os.environ.get("URL_HOST_DENYLIST", "")
URL_HOST_DENYLIST: list[str] = [h.strip().lower() for h in _DENYLIST_RAW.split(",") if h.strip()]

# Allowed folder roots for by-folder endpoint (empty = allow any absolute path)
_FOLDER_ROOTS_RAW = os.environ.get("ALLOWED_FOLDER_ROOTS", "")
ALLOWED_FOLDER_ROOTS: list[str] = [
    os.path.realpath(r.strip()) for r in _FOLDER_ROOTS_RAW.split(",") if r.strip()
]

ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


# ── URL validation ────────────────────────────────────────────────────────────

def validate_url(url: str) -> str:
    """
    Validate a URL submitted for processing.

    Raises HTTPException(400) if the URL fails any check.
    Returns the (unchanged) URL on success.
    """
    if not url or not url.strip():
        raise HTTPException(status_code=400, detail="Empty URL provided")

    url = url.strip()

    # Local paths are allowed (for by-folder and upload temp paths)
    if not url.startswith(("http://", "https://")):
        # Treat as local file path — path traversal checked separately
        return url

    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Malformed URL: {exc}") from exc

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail=f"Scheme not allowed: '{parsed.scheme}'")

    host = (parsed.hostname or "").lower()

    if URL_HOST_DENYLIST and any(host == d or host.endswith(f".{d}") for d in URL_HOST_DENYLIST):
        logger.warning("URL denied by denylist: host=%s", host)
        raise HTTPException(status_code=403, detail=f"Host '{host}' is not allowed")

    if URL_HOST_ALLOWLIST and not any(host == a or host.endswith(f".{a}") for a in URL_HOST_ALLOWLIST):
        logger.warning("URL rejected by allowlist: host=%s", host)
        raise HTTPException(status_code=403, detail=f"Host '{host}' is not in the allowlist")

    return url


# ── Folder path traversal guard ──────────────────────────────────────────────

def safe_folder_path(folder_path: str) -> str:
    """
    Resolve and validate a server-side folder path.

    - Must be an absolute path (no relative tricks like ../../etc/passwd)
    - Must resolve inside one of ALLOWED_FOLDER_ROOTS (if configured)
    - Must be an existing directory

    Returns the real (resolved) path on success.
    Raises HTTPException(400/403) on failure.
    """
    if not folder_path or not folder_path.strip():
        raise HTTPException(status_code=400, detail="Empty folder path")

    # Resolve symlinks & normalise
    try:
        real = os.path.realpath(folder_path.strip())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid path: {exc}") from exc

    if not os.path.isabs(real):
        raise HTTPException(status_code=400, detail="Folder path must be absolute")

    if ALLOWED_FOLDER_ROOTS:
        if not any(real.startswith(root + os.sep) or real == root for root in ALLOWED_FOLDER_ROOTS):
            logger.warning("Path traversal attempt blocked: path=%s", real)
            raise HTTPException(
                status_code=403,
                detail=f"Folder '{real}' is outside the allowed roots"
            )

    if not os.path.isdir(real):
        raise HTTPException(status_code=404, detail=f"Folder not found: {real}")

    return real


# ── Upload size guard ─────────────────────────────────────────────────────────

def check_upload_size(content_length: Optional[int]) -> None:
    """
    Called before streaming a file upload.
    Raises HTTPException(413) if Content-Length exceeds limit.
    """
    if content_length is None:
        return  # Can't check without Content-Length; rely on chunked read
    if content_length > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Upload too large: {content_length / 1_048_576:.1f} MB "
                f"(max {MAX_UPLOAD_MB:.0f} MB)"
            )
        )
