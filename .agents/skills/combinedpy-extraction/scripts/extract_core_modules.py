"""Helper script (optional) to scaffold a module layout for combined.py refactor.
Intended to be run manually; it does not guarantee correctness.
"""
from pathlib import Path

TARGETS = [
    "video_service/core/video_io.py",
    "video_service/core/ocr.py",
    "video_service/core/llm.py",
    "video_service/core/categories.py",
    "video_service/core/pipeline.py",
    "video_service/core/agent.py",
]

def main():
    for t in TARGETS:
        p = Path(t)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("# scaffolded\n")
    print("Scaffolded core modules.")

if __name__ == "__main__":
    main()
