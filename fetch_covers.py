"""
Resolve cover image URLs for all Project Gutenberg books in catalog.json.

Strategy (in order of preference):
  1. Project Gutenberg cache — covers hosted by Gutenberg itself:
       https://www.gutenberg.org/cache/epub/{id}/pg{id}.cover.medium.jpg
     These are the official cover images shown on gutenberg.org book pages.
     We do a HEAD request to confirm the file actually exists.

  2. Open Library title search fallback — if Gutenberg has no cover:
       https://openlibrary.org/search.json?title=...&author=...&limit=1&fields=cover_i
     Cover image served from:
       https://covers.openlibrary.org/b/id/{cover_id}-M.jpg

Run: python fetch_covers.py
"""

import json
import time
import urllib.request
import urllib.error
from pathlib import Path

CATALOG_PATH = Path(__file__).parent / "catalog.json"
GUTENBERG_COVER = "https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.cover.medium.jpg"
OL_SEARCH = "https://openlibrary.org/search.json?title={title}&author={author}&limit=1&fields=cover_i"
OL_COVER = "https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
HEADERS = {"User-Agent": "LexaVox/1.0 (cover-fetch; contact@lexavox.com)"}
DELAY = 0.5

def url_exists(url: str) -> bool:
    req = urllib.request.Request(url, method="HEAD", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except Exception:
        return False

def ol_cover_url(title: str, author: str) -> str | None:
    import urllib.parse
    url = OL_SEARCH.format(
        title=urllib.parse.quote(title),
        author=urllib.parse.quote(author),
    )
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            docs = data.get("docs", [])
            if docs and "cover_i" in docs[0]:
                return OL_COVER.format(cover_id=docs[0]["cover_i"])
    except Exception:
        pass
    return None

def main():
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    books = catalog["books"]

    found = 0
    for i, book in enumerate(books):
        book_id: str = book.get("id", "")
        title = book.get("title", "")
        author = book.get("author", "")

        if book.get("coverUrl"):
            print(f"  [{i+1}/{len(books)}] {title[:40]} — already set, skipping")
            found += 1
            continue

        cover_url = None

        # Strategy 1: Gutenberg cache
        if book_id.startswith("pg"):
            gid = book_id[2:]
            candidate = GUTENBERG_COVER.format(gid=gid)
            if url_exists(candidate):
                cover_url = candidate
                print(f"  [{i+1}/{len(books)}] {title[:40]} — Gutenberg cover ✓")

        # Strategy 2: Open Library fallback
        if not cover_url and author:
            cover_url = ol_cover_url(title, author)
            if cover_url:
                print(f"  [{i+1}/{len(books)}] {title[:40]} — Open Library cover ✓")

        if cover_url:
            book["coverUrl"] = cover_url
            found += 1
        else:
            print(f"  [{i+1}/{len(books)}] {title[:40]} — no cover found")

        time.sleep(DELAY)

    import datetime
    catalog["coversFetchedAt"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    CATALOG_PATH.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\nDone. {found}/{len(books)} books have cover URLs.")
    print(f"Catalog written to {CATALOG_PATH}")

if __name__ == "__main__":
    main()
