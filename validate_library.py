#!/usr/bin/env python3
"""
Audit the public-books catalog, JSON payloads, and EPUB source metadata.

Usage:
  python validate_library.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from enrich_books import build_tts_sentence_ends, build_tts_text
from library_validation import (
    AUTHOR_STOPWORDS,
    TITLE_STOPWORDS,
    is_allowed_author_variant,
    is_allowed_title_variant,
    is_severe_source_mismatch,
    overlap_score,
    read_epub_metadata,
    repair_mojibake,
)


def main() -> int:
    repo_root = Path(__file__).parent
    catalog = json.loads((repo_root / "catalog.json").read_text(encoding="utf-8-sig"))

    errors: list[str] = []
    warnings: list[str] = []

    for book in catalog.get("books", []):
        category = book.get("category", "")
        json_filename = book.get("jsonFilename", "")
        epub_filename = book.get("epubFilename", "")
        json_path = repo_root / "json" / category / json_filename
        epub_path = repo_root / "books" / category / epub_filename

        if not json_path.exists():
            errors.append(f"{book['id']}: missing JSON {json_path}")
            continue
        if not epub_path.exists():
            errors.append(f"{book['id']}: missing EPUB {epub_path}")
            continue

        data = json.loads(json_path.read_text(encoding="utf-8-sig"))
        source = data.get("source", {})
        epub = read_epub_metadata(epub_path)

        catalog_title = repair_mojibake(book.get("title", ""))
        catalog_author = repair_mojibake(book.get("author", ""))
        json_title = repair_mojibake(source.get("title", ""))
        json_author = repair_mojibake(source.get("author", ""))
        epub_title = repair_mojibake(epub.title)
        epub_author = repair_mojibake(epub.creator)

        if source.get("id") != book.get("id"):
            errors.append(
                f"{book['id']}: JSON source.id mismatch ({source.get('id')!r})",
            )

        if repair_mojibake(book.get("title", "")) != book.get("title", ""):
            warnings.append(f"{book['id']}: catalog title contains mojibake")
        if repair_mojibake(book.get("author", "")) != book.get("author", ""):
            warnings.append(f"{book['id']}: catalog author contains mojibake")

        title_overlap = overlap_score(catalog_title, epub_title, TITLE_STOPWORDS)
        author_overlap = overlap_score(catalog_author, epub_author, AUTHOR_STOPWORDS)

        if is_severe_source_mismatch(catalog_title, epub_title, catalog_author, epub_author):
            errors.append(
                f"{book['id']}: severe source mismatch | "
                f"title={catalog_title!r} vs {epub_title!r} | "
                f"author={catalog_author!r} vs {epub_author!r}",
            )
            continue

        if title_overlap < 0.6 and not is_allowed_title_variant(book["id"], epub_title):
            warnings.append(
                f"{book['id']}: title variant | {catalog_title!r} vs {epub_title!r}",
            )
        if author_overlap < 0.6 and not is_allowed_author_variant(book["id"], epub_author):
            warnings.append(
                f"{book['id']}: author variant | {catalog_author!r} vs {epub_author!r}",
            )

        if json_title != catalog_title or json_author != catalog_author:
            warnings.append(
                f"{book['id']}: catalog/json metadata drift | "
                f"catalog=({catalog_title!r}, {catalog_author!r}) "
                f"json=({json_title!r}, {json_author!r})",
            )

        tts_drift_count = 0
        tts_sentence_drift_count = 0
        stale_tts_count = 0
        stale_tts_sentence_count = 0
        for paragraph in data.get("paragraphs", []):
            actual_tts = paragraph.get("ttsText")
            actual_sentence_ends = paragraph.get("ttsSentenceEnds")
            if paragraph.get("skip"):
                if actual_tts:
                    stale_tts_count += 1
                if actual_sentence_ends:
                    stale_tts_sentence_count += 1
                continue

            expected_tts = build_tts_text(paragraph.get("text", ""))
            if actual_tts != expected_tts:
                tts_drift_count += 1

            tts_source = expected_tts if expected_tts is not None else paragraph.get("text", "").strip()
            expected_sentence_ends = build_tts_sentence_ends(tts_source)
            expected_sentence_payload = expected_sentence_ends if len(expected_sentence_ends) > 1 else None
            if actual_sentence_ends != expected_sentence_payload:
                tts_sentence_drift_count += 1

        if tts_drift_count:
            warnings.append(f"{book['id']}: ttsText drift in {tts_drift_count} paragraphs")
        if stale_tts_count:
            warnings.append(f"{book['id']}: skipped paragraphs still carry {stale_tts_count} ttsText overrides")
        if tts_sentence_drift_count:
            warnings.append(f"{book['id']}: ttsSentenceEnds drift in {tts_sentence_drift_count} paragraphs")
        if stale_tts_sentence_count:
            warnings.append(
                f"{book['id']}: skipped paragraphs still carry {stale_tts_sentence_count} ttsSentenceEnds"
            )

    print(f"Catalog books: {len(catalog.get('books', []))}")
    print(f"Errors: {len(errors)}")
    print(f"Warnings: {len(warnings)}")

    if errors:
        print("\nErrors")
        for line in errors:
            print(f"- {line}")

    if warnings:
        print("\nWarnings")
        for line in warnings:
            print(f"- {line}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
