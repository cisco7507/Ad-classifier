#!/usr/bin/env python3
"""
scripts/download_fixtures.py
============================
Downloads the local fixture video(s) needed for the parity test suite.

Usage:
    source venv/bin/activate
    python scripts/download_fixtures.py
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_FILE = PROJECT_ROOT / "tests" / "fixtures" / "parity_fixtures.json"

# Mapping: fixture_id -> (download_url, destination_relative_path)
# Add entries here when adding new local fixtures.
DOWNLOAD_MAP = {
    "local_mp4": (
        # Using the same Ads of the World video as a convenient local test fixture.
        # Replace with a more suitable video URL if needed.
        "https://video.adsoftheworld.com/bzoe961keml3r4b5uo66q1gftv9m.mp4",
        "tests/fixtures/sample_local.mp4",
    ),
}


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"  [SKIP] {dest.name} already exists.")
        return
    print(f"  ⬇️  Downloading {url}")
    print(f"       → {dest}")
    try:
        urllib.request.urlretrieve(url, str(dest))
        size_mb = dest.stat().st_size / 1_048_576
        print(f"       ✅  Done ({size_mb:.1f} MB)")
    except Exception as e:
        print(f"       ❌  Failed: {e}")
        sys.exit(1)


def main():
    fixtures = json.loads(FIXTURES_FILE.read_text())["fixtures"]
    local_fixtures = [f for f in fixtures if f["source_type"] == "local"]

    if not local_fixtures:
        print("No local fixtures defined — nothing to download.")
        return

    print(f"\n📦  Downloading {len(local_fixtures)} local fixture(s)...\n")
    for fixture in local_fixtures:
        fid = fixture["id"]
        if fid not in DOWNLOAD_MAP:
            print(f"  [WARN] No download URL configured for fixture '{fid}' — skipping.")
            continue
        url, rel_path = DOWNLOAD_MAP[fid]
        dest = PROJECT_ROOT / rel_path
        download_file(url, dest)

    print("\n✅  Fixture download complete.\n")


if __name__ == "__main__":
    main()
