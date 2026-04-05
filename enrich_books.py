#!/usr/bin/env python3
"""
enrich_books.py — Enriches LexaVox public book JSON files with:
  - Proper 'role' values (title / heading / paragraph)
  - 'skip: true' on Gutenberg boilerplate, blank blocks, and ToC entries
  - 'ttsText' override for blocks with Gutenberg small-caps artifacts

Run from the lexavox-public-books directory:
  python enrich_books.py [--dry-run]
"""

import json
import os
import re
import sys
import glob
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def is_spaced_caps(text: str) -> bool:
    """Detect small-caps artifacts like 'D R A C U L A' or 'A N N E'."""
    t = text.strip()
    # Must be only uppercase letters separated by single spaces
    return bool(re.match(r'^[A-Z]( [A-Z])+$', t))


def collapse_spaced_caps(text: str) -> str:
    """Convert 'D R A C U L A' → 'Dracula'."""
    letters = text.strip().split()
    return ''.join(letters).title()


def fix_smallcaps_words(text: str) -> str:
    """
    Fix mixed small-caps artifacts within a sentence, e.g.:
      'M RS. RACHEL LYNDE'  → 'Mrs. Rachel Lynde'
      'J OHN'               → 'John'
    Pattern: uppercase letter, space, then all-caps continuation (2+ chars).
    Also handles 'L. M. M ONTGOMERY' → 'L. M. Montgomery'
    """
    # Pattern: single uppercase letter followed by space then 2+ uppercase letters
    # (represents a word broken by small-caps rendering)
    result = re.sub(
        r'\b([A-Z])\s([A-Z]{2,})\b',
        lambda m: (m.group(1) + m.group(2)).title(),
        text
    )
    return result


def needs_tts_fix(text: str) -> bool:
    """Check if text has Gutenberg small-caps artifacts that need a ttsText."""
    if is_spaced_caps(text.strip()):
        return True
    # Single uppercase letter + space + 2+ uppercase letters (broken word)
    if re.search(r'\b[A-Z]\s[A-Z]{2,}\b', text):
        return True
    return False


def build_tts_text(text: str) -> str | None:
    """Build a clean ttsText override. Returns None if no fix needed."""
    t = text.strip()
    if is_spaced_caps(t):
        return collapse_spaced_caps(t)
    if re.search(r'\b[A-Z]\s[A-Z]{2,}\b', t):
        fixed = fix_smallcaps_words(t)
        if fixed != t:
            return fixed
    return None


def is_chapter_heading(text: str) -> bool:
    """Detect chapter/section headings."""
    t = text.strip()
    # Common heading keywords
    if re.match(
        r'^(CHAPTER|STAVE|LETTER|PART|BOOK|VOLUME|ACT|SCENE|SECTION|'
        r'PROLOGUE|EPILOGUE|PREFACE|INTRODUCTION|APPENDIX|POSTSCRIPT|'
        r'NOTE|CANTO|BOOK|TALE)\b',
        t, re.IGNORECASE
    ):
        return True
    # Standalone roman numerals (I, II, III, IV ... XLVIII)
    if re.match(r'^[IVXLCDM]+\.?\s*$', t):
        return True
    # "I." or "1." at start followed by em-dash or long title
    if re.match(r'^([IVXLCDM]+|[0-9]+)[.—\-]\s*.{3,}', t):
        return True
    return False


def is_toc_entry(text: str) -> bool:
    """More lenient — used inside a known ToC block."""
    t = text.strip()
    if not t:
        return True  # blank line inside ToC → skip
    # Starts with chapter keyword
    if re.match(
        r'^(CHAPTER|STAVE|LETTER|PART|BOOK|VOLUME|ACT|SCENE|SECTION|'
        r'BOOK|TALE|CANTO|APPENDIX|INTRODUCTION|PREFACE|EPILOGUE|PROLOGUE)\b',
        t, re.IGNORECASE
    ):
        return True
    # Short ALL-CAPS title (e.g. "ANNE OF GREEN GABLES" repeated in ToC)
    if len(t) <= 80 and re.match(r'^[A-Z][A-Z\s\-\'\.,:]+$', t):
        return True
    # Roman numeral entry
    if re.match(r'^[IVXLCDM]+[\.\s]', t):
        return True
    # Author credit line "By ..." in ToC
    if re.match(r'^By\s', t):
        return True
    return False


def is_title_line(text: str) -> bool:
    """Short ALL-CAPS line that looks like a book/chapter title."""
    t = text.strip()
    if len(t) < 2 or len(t) > 80:
        return False
    # Must be all uppercase (allowing spaces, punctuation, numbers)
    words = t.split()
    if not words:
        return False
    # At least one alphabetic char
    if not re.search(r'[A-Z]', t):
        return False
    # All alphabetic words must be uppercase
    alpha_words = [w for w in words if re.search(r'[a-zA-Z]', w)]
    if not alpha_words:
        return False
    return all(w == w.upper() for w in alpha_words)


# Patterns that identify Gutenberg website artifacts (should be skipped)
SKIP_ARTIFACTS = [
    re.compile(r'Click on any of the filenumber', re.IGNORECASE),
    re.compile(r'\(Original First Edition Cover', re.IGNORECASE),
    re.compile(r'\(Published in \d{4}', re.IGNORECASE),
    re.compile(r'^Cover of \d{4}', re.IGNORECASE),
    re.compile(r'^Title Page of \d{4}', re.IGNORECASE),
    re.compile(r'^\d+\s+\(', re.IGNORECASE),  # "46 (Original First Edition...)"
    re.compile(r'^There are several editions of this ebook', re.IGNORECASE),
    re.compile(r'THERE IS AN ILLUSTRATED EDITION', re.IGNORECASE),
    re.compile(r'EBOOK\s*\[\s*#', re.IGNORECASE),  # "EBOOK [ #48320"
    re.compile(r'\|\s*Project Gutenberg\s*$'),        # "Title | Project Gutenberg"
    re.compile(r'^The Project Gutenberg eBook of\b', re.IGNORECASE),  # near-END credit line
    re.compile(r'^\d{3,5}[a-z]$'),                   # image refs: "0009m", "0011m"
]


def is_web_artifact(text: str) -> bool:
    t = text.strip()
    return any(p.search(t) for p in SKIP_ARTIFACTS)


# ---------------------------------------------------------------------------
# Main enrichment function
# ---------------------------------------------------------------------------

def enrich_book(path: Path) -> dict:
    """Enrich a single book JSON file. Returns stats dict."""
    with open(path, encoding='utf-8-sig') as f:
        data = json.load(f)

    items = data.get('paragraphs', [])
    stats = {
        'total': len(items),
        'skipped': 0,
        'titled': 0,
        'headings': 0,
        'paragraphs': 0,
        'tts_overrides': 0,
    }

    # -----------------------------------------------------------------------
    # Step 1: Locate *** START *** and *** END *** markers
    # -----------------------------------------------------------------------
    start_idx = end_idx = None
    for i, p in enumerate(items):
        t = p.get('text', '')
        if start_idx is None and '*** START OF THE PROJECT GUTENBERG' in t:
            start_idx = i
        elif start_idx is not None and '*** END OF THE PROJECT GUTENBERG' in t:
            end_idx = i
            break

    end_range = end_idx if end_idx is not None else len(items)

    # -----------------------------------------------------------------------
    # Step 2: Initialize fields (don't overwrite existing enrichment)
    # -----------------------------------------------------------------------
    for p in items:
        if 'skip' not in p:
            p['skip'] = False
        if 'ttsText' not in p:
            p['ttsText'] = None

    # -----------------------------------------------------------------------
    # Step 3: Mark pre-START boilerplate as skip
    # -----------------------------------------------------------------------
    if start_idx is not None:
        for i in range(0, start_idx + 1):
            items[i]['skip'] = True

    # -----------------------------------------------------------------------
    # Step 4: Mark post-END boilerplate as skip
    # -----------------------------------------------------------------------
    if end_idx is not None:
        for i in range(end_idx, len(items)):
            items[i]['skip'] = True

    # -----------------------------------------------------------------------
    # Step 5: Mark blank items as skip
    # -----------------------------------------------------------------------
    for p in items:
        if not p.get('text', '').strip():
            p['skip'] = True

    # -----------------------------------------------------------------------
    # Step 6: Mark web artifacts between START and content as skip
    # -----------------------------------------------------------------------
    if start_idx is not None:
        for i in range(start_idx + 1, end_range):
            if items[i]['skip']:
                continue
            if is_web_artifact(items[i].get('text', '')):
                items[i]['skip'] = True

    # -----------------------------------------------------------------------
    # Step 7: Find and mark ToC section (CONTENTS header + entries)
    # -----------------------------------------------------------------------
    if start_idx is not None:
        for i in range(start_idx + 1, end_range):
            if items[i]['skip']:
                continue
            t = items[i]['text'].strip()
            if re.match(r'^CONTENTS?\.?\s*$', t, re.IGNORECASE):
                items[i]['skip'] = True
                # Mark following lines as skip while they look like ToC entries
                j = i + 1
                while j < end_range:
                    jt = items[j]['text'].strip()
                    if items[j]['skip'] or is_toc_entry(jt):
                        items[j]['skip'] = True
                        j += 1
                    else:
                        break
                break  # Only process first CONTENTS section

    # -----------------------------------------------------------------------
    # Step 8: Assign roles and ttsText to non-skipped items
    # -----------------------------------------------------------------------
    for p in items:
        if p['skip']:
            continue
        t = p.get('text', '').strip()
        existing_role = p.get('role', '')

        # Build ttsText if needed (regardless of role)
        if not p['ttsText']:
            override = build_tts_text(t)
            if override:
                p['ttsText'] = override

        # Assign role (don't overwrite if already set to something meaningful)
        if not existing_role:
            if is_spaced_caps(t):
                p['role'] = 'title'
            elif is_title_line(t) and len(t) <= 60:
                # Distinguish: standalone short ALL-CAPS → could be title or heading
                if is_chapter_heading(t):
                    p['role'] = 'heading'
                else:
                    p['role'] = 'title'
            elif is_chapter_heading(t):
                p['role'] = 'heading'
            else:
                p['role'] = 'paragraph'

    # -----------------------------------------------------------------------
    # Step 9: Clean up — remove null ttsText and false skip to keep JSON lean
    # -----------------------------------------------------------------------
    for p in items:
        if p.get('skip') is False:
            del p['skip']
        if p.get('ttsText') is None:
            del p['ttsText']

    # -----------------------------------------------------------------------
    # Gather stats
    # -----------------------------------------------------------------------
    for p in items:
        if p.get('skip', False):
            stats['skipped'] += 1
        else:
            role = p.get('role', '')
            if role == 'title':
                stats['titled'] += 1
            elif role == 'heading':
                stats['headings'] += 1
            else:
                stats['paragraphs'] += 1
            if p.get('ttsText'):
                stats['tts_overrides'] += 1

    # -----------------------------------------------------------------------
    # Write back
    # -----------------------------------------------------------------------
    if not DRY_RUN:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return stats


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    script_dir = Path(__file__).parent
    json_dir = script_dir / 'json'

    if not json_dir.exists():
        print(f"ERROR: json/ directory not found at {json_dir}")
        sys.exit(1)

    book_files = sorted(json_dir.glob('**/*.json'))
    # Exclude manifest
    book_files = [f for f in book_files if f.name != 'manifest.json']

    if not book_files:
        print("No book JSON files found.")
        sys.exit(1)

    total_books = len(book_files)
    print(f"{'[DRY RUN] ' if DRY_RUN else ''}Enriching {total_books} books...\n")
    print(f"{'Book':<55} {'Total':>6} {'Skip':>6} {'Title':>6} {'Head':>6} {'Para':>6} {'TTS':>5}")
    print("-" * 95)

    grand = {'total': 0, 'skipped': 0, 'titled': 0, 'headings': 0, 'paragraphs': 0, 'tts_overrides': 0}

    for path in book_files:
        rel = path.relative_to(script_dir)
        try:
            stats = enrich_book(path)
            label = str(rel)[:54]
            print(
                f"{label:<55} {stats['total']:>6} {stats['skipped']:>6} "
                f"{stats['titled']:>6} {stats['headings']:>6} {stats['paragraphs']:>6} "
                f"{stats['tts_overrides']:>5}"
            )
            for k in grand:
                grand[k] += stats[k]
        except Exception as e:
            print(f"  ERROR processing {rel}: {e}")
            import traceback; traceback.print_exc()

    print("-" * 95)
    print(
        f"{'TOTAL':<55} {grand['total']:>6} {grand['skipped']:>6} "
        f"{grand['titled']:>6} {grand['headings']:>6} {grand['paragraphs']:>6} "
        f"{grand['tts_overrides']:>5}"
    )
    print(f"\n{'[DRY RUN — no files written]' if DRY_RUN else 'Done. All files written.'}")


if __name__ == '__main__':
    main()
