#!/usr/bin/env python3
"""
regenerate_catalog.py — Rebuilds catalog.json from the enriched book JSON files.
Reads source metadata from each book JSON and generates a clean catalog.

Run from the lexavox-public-books directory:
  python regenerate_catalog.py
"""
import json
import os
from pathlib import Path

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/lexavox/lexavox-public-books/main"

# Fixed categories list (order and labels from original catalog)
CATEGORIES = [
    {"id": "christian", "label": "Christian Classics",       "icon": "book-cross"},
    {"id": "fiction",   "label": "Classic Fiction",          "icon": "book-open-variant"},
    {"id": "adventure", "label": "Adventure",                "icon": "compass-rose"},
    {"id": "scifi",     "label": "Science Fiction",          "icon": "rocket-launch"},
    {"id": "children",  "label": "Children's Literature",    "icon": "teddy-bear"},
    {"id": "poetry",    "label": "Poetry & Drama",           "icon": "script-text"},
    {"id": "philosophy","label": "Philosophy",               "icon": "head-cog"},
    {"id": "history",   "label": "History & Biography",      "icon": "history"},
]

script_dir = Path(__file__).parent
json_dir = script_dir / "json"

book_files = sorted(json_dir.glob("**/*.json"))
book_files = [f for f in book_files if f.name != "manifest.json"]

books = []
seen_ids = set()

for path in book_files:
    try:
        data = json.load(open(path, encoding="utf-8-sig"))
    except Exception as e:
        print(f"  SKIP {path.name}: {e}")
        continue

    src = data.get("source", {})
    book_id = src.get("id", "")
    if not book_id:
        print(f"  SKIP {path.name}: no source.id")
        continue

    if book_id in seen_ids:
        print(f"  SKIP {path.name}: duplicate id {book_id!r}")
        continue
    seen_ids.add(book_id)

    # Determine relative JSON path from repo root
    rel_path = path.relative_to(script_dir).as_posix()   # e.g. json/fiction/a_christmas_carol...json
    json_url = f"{GITHUB_RAW_BASE}/{rel_path}"

    entry = {
        "id": book_id,
        "title": src.get("title", path.stem),
        "author": src.get("author", ""),
        "language": src.get("language", "en"),
        "category": src.get("category", path.parent.name),
        "jsonFilename": path.name,
        "jsonUrl": json_url,
    }
    # Optionally preserve epub filename for reference/fallback
    if src.get("filename"):
        entry["epubFilename"] = src["filename"]

    books.append(entry)

from datetime import datetime, timezone
catalog = {
    "version": 3,
    "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "categories": CATEGORIES,
    "books": books,
}

out_path = script_dir / "catalog.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(catalog, f, ensure_ascii=False, indent=2)

print(f"catalog.json regenerated: {len(books)} books")
