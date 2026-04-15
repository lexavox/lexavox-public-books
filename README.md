# lexavox-public-books

## JSON conversion for order/integrity checks

Run from repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\convert_epubs_to_json.ps1
```

Outputs:

- `json/<category>/<book>.json` for each EPUB in `books/`
- `json/manifest.json` with SHA-256 hash + counts for verification

The converter now follows `catalog.json` as the published source of truth.
EPUBs that remain on disk but are intentionally omitted from the catalog will
not be exported into the published JSON manifest.

## Catalog and TTS maintenance

Run from repo root:

```powershell
python .\enrich_books.py
python .\regenerate_catalog.py
python .\regenerate_manifest.py
python .\validate_library.py
```

What these do:

- `enrich_books.py`
  - refreshes `role`, `skip`, and `ttsText` fields in every public-book JSON
  - repairs common Gutenberg small-caps and punctuation artifacts for smoother TTS
- `regenerate_catalog.py`
  - rebuilds `catalog.json` from the enriched JSON source metadata
  - skips entries whose EPUB metadata clearly does not match the catalog title/author
- `regenerate_manifest.py`
  - rebuilds `json/manifest.json` from the current enriched JSON payloads
  - refreshes the integrity summary after TTS or metadata updates
  - only includes books currently published in `catalog.json`
- `validate_library.py`
  - audits `catalog.json`, JSON source metadata, EPUB metadata, and generated `ttsText`
  - exits nonzero when hard catalog/source mismatches are found

## Current published state

The published catalog and manifest are currently aligned at `89` books, and
`validate_library.py` should return `0` errors and `0` warnings after a clean
rebuild.
