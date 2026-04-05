"""
Download all cover images referenced in catalog.json into covers/{id}.jpg
and rewrite each coverUrl to the GitHub raw URL.

Run: python download_covers.py
"""

import json
import time
import urllib.request
import urllib.error
from pathlib import Path

CATALOG_PATH = Path(__file__).parent / "catalog.json"
COVERS_DIR = Path(__file__).parent / "covers"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/lexavox/lexavox-public-books/main/covers"
HEADERS = {"User-Agent": "LexaVox/1.0 (cover-download; contact@lexavox.com)"}
DELAY = 0.3

def download(url: str, dest: Path) -> bool:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            dest.write_bytes(resp.read())
        return True
    except Exception as e:
        print(f"    ERROR: {e}")
        return False

def main():
    COVERS_DIR.mkdir(exist_ok=True)

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    books = catalog["books"]

    downloaded = 0
    skipped = 0
    failed = 0

    for i, book in enumerate(books):
        book_id = book.get("id", "")
        cover_url = book.get("coverUrl", "")

        if not cover_url:
            print(f"  [{i+1}/{len(books)}] {book['title'][:40]} — no coverUrl, skipping")
            continue

        # Already points to our repo — nothing to do
        if "raw.githubusercontent.com/lexavox/lexavox-public-books" in cover_url and "/covers/" in cover_url:
            print(f"  [{i+1}/{len(books)}] {book['title'][:40]} — already self-hosted, skipping")
            skipped += 1
            continue

        dest = COVERS_DIR / f"{book_id}.jpg"

        if dest.exists():
            # File already downloaded; just rewrite URL
            book["coverUrl"] = f"{GITHUB_RAW_BASE}/{book_id}.jpg"
            print(f"  [{i+1}/{len(books)}] {book['title'][:40]} — already on disk, URL updated")
            skipped += 1
            continue

        print(f"  [{i+1}/{len(books)}] {book['title'][:40]} — downloading...")
        if download(cover_url, dest):
            book["coverUrl"] = f"{GITHUB_RAW_BASE}/{book_id}.jpg"
            downloaded += 1
        else:
            failed += 1

        time.sleep(DELAY)

    CATALOG_PATH.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\nDone. downloaded={downloaded}  skipped(already done)={skipped}  failed={failed}")
    print(f"Covers in: {COVERS_DIR}")
    print(f"Catalog updated: {CATALOG_PATH}")

if __name__ == "__main__":
    main()
