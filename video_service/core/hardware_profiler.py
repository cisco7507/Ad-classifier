import json
import os
from pathlib import Path
from datetime import datetime, timezone

import psutil
import torch


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_capability_matrix() -> list[dict]:
    matrix_path = _repo_root() / "video_service" / "data" / "capability_matrix.json"
    if not matrix_path.exists():
        return []
    try:
        payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    return []


def _detect_accelerator() -> dict:
    cuda_available = bool(torch.cuda.is_available())
    mps_available = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    accelerator = "cpu"
    device_name = "cpu"
    total_vram_mb = None
    free_vram_mb = None

    if cuda_available:
        accelerator = "cuda"
        idx = int(os.environ.get("CUDA_DEVICE_INDEX", "0") or 0)
        props = torch.cuda.get_device_properties(idx)
        device_name = torch.cuda.get_device_name(idx)
        total_vram_mb = round(float(props.total_memory) / (1024 * 1024), 1)
        try:
            free_bytes, total_bytes = torch.cuda.mem_get_info(idx)
            free_vram_mb = round(float(free_bytes) / (1024 * 1024), 1)
            total_vram_mb = round(float(total_bytes) / (1024 * 1024), 1)
        except Exception:
            # Fallback to static property only.
            pass
    elif mps_available:
        accelerator = "mps"
        device_name = "apple-mps"

    return {
        "accelerator": accelerator,
        "device_name": device_name,
        "cuda_available": cuda_available,
        "mps_available": mps_available,
        "total_vram_mb": total_vram_mb,
        "free_vram_mb": free_vram_mb,
    }


def get_system_profile() -> dict:
    vm = psutil.virtual_memory()
    accelerator = _detect_accelerator()
    matrix = _load_capability_matrix()

    total_ram_mb = round(float(vm.total) / (1024 * 1024), 1)
    used_ram_mb = round(float(vm.used) / (1024 * 1024), 1)
    free_ram_mb = round(float(vm.available) / (1024 * 1024), 1)

    warnings = []
    for entry in matrix:
        model = str(entry.get("model", "")).strip()
        min_ram_mb = float(entry.get("min_ram_mb", 0) or 0)
        min_vram_mb = float(entry.get("min_vram_mb", 0) or 0)
        accelerator_required = str(entry.get("accelerator", "any")).strip().lower()

        insufficient_ram = min_ram_mb > 0 and total_ram_mb < min_ram_mb
        has_vram = accelerator["total_vram_mb"] is not None
        insufficient_vram = min_vram_mb > 0 and (
            (has_vram and float(accelerator["total_vram_mb"]) < min_vram_mb)
            or (not has_vram and total_ram_mb < min_vram_mb)
        )
        accelerator_mismatch = (
            accelerator_required not in {"", "any"}
            and accelerator_required != accelerator["accelerator"]
        )

        if insufficient_ram or insufficient_vram or accelerator_mismatch:
            warnings.append(
                {
                    "model": model,
                    "severity": "warning",
                    "message": (
                        f"Hardware below recommended capability for {model or 'model'}: "
                        f"requires >= {min_ram_mb:.0f}MB RAM, >= {min_vram_mb:.0f}MB VRAM, accelerator={accelerator_required or 'any'}."
                    ),
                    "requirements": {
                        "min_ram_mb": min_ram_mb,
                        "min_vram_mb": min_vram_mb,
                        "accelerator": accelerator_required or "any",
                    },
                }
            )

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hardware": {
            "cpu_count_logical": int(psutil.cpu_count(logical=True) or 0),
            "cpu_count_physical": int(psutil.cpu_count(logical=False) or 0),
            "total_ram_mb": total_ram_mb,
            "used_ram_mb": used_ram_mb,
            "free_ram_mb": free_ram_mb,
            "memory_percent": float(vm.percent),
            **accelerator,
        },
        "capability_matrix": matrix,
        "warnings": warnings,
    }
