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
from library_validation import repair_mojibake

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
    result = re.sub(
        r"\b([AI])\s+([A-Z]{2,})\b",
        lambda m: f"{m.group(1)} {m.group(2).lower().capitalize()}",
        text,
    )
    result = re.sub(
        r"\b([A-Z][A-Z'’.-]*['’]S)\s+([A-Z]{2,})\b",
        lambda m: f"{m.group(1).lower().capitalize()} {m.group(2).lower().capitalize()}",
        result,
    )
    result = re.sub(
        r"(?<![A-Za-z'’])([B-HJ-Z])\s+([A-Z]{2,})\b",
        lambda m: (m.group(1) + m.group(2)).lower().capitalize(),
        result,
    )
    return result


WORD_OR_SEPARATOR_RE = re.compile(
    r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+(?:['’][A-Za-zÀ-ÖØ-öø-ÿ0-9]+)?|[^\w\s]+|\s+",
    re.UNICODE,
)
ROMAN_NUMERAL_RE = re.compile(r"^[IVXLCDM]+$", re.IGNORECASE)
FORCE_LOWER_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
PRESERVE_ACRONYMS = {
    "AI",
    "AM",
    "BC",
    "DNA",
    "OCR",
    "PDF",
    "UK",
    "US",
    "USA",
}
ELLIPSIS_RE = re.compile(r"\.(?:\s*\.){2,}")
DOUBLE_HYPHEN_RE = re.compile(r"(?<=\S)\s*--+\s*(?=\S)")
SPACED_INITIALISM_RE = re.compile(r"\b(?:[A-Za-z]\s*\.\s*){2,}")
SENTENCE_TERMINATOR_RE = re.compile(r"[.!?\u2026]")
SENTENCE_ABBREVIATIONS = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "sr",
    "jr",
    "st",
    "vs",
    "etc",
    "no",
    "fig",
    "vol",
    "ch",
    "rev",
    "hon",
    "gen",
    "sen",
    "rep",
    "col",
    "lt",
    "sgt",
    "capt",
    "mt",
    "inc",
    "co",
}


def is_all_caps_word(token: str) -> bool:
    letters = [ch for ch in token if ch.isalpha()]
    return bool(letters) and all(ch.isupper() for ch in letters)


def smart_capitalize(token: str, force_lower: bool = False) -> str:
    lowered = token.lower()
    if not lowered:
        return token
    if force_lower:
        return lowered
    return lowered[0].upper() + lowered[1:]


def humanize_caps_tokens(text: str) -> str:
    tokens = WORD_OR_SEPARATOR_RE.findall(text)
    result: list[str] = []

    def previous_word(position: int) -> str | None:
        for index in range(position - 1, -1, -1):
            token = tokens[index]
            if token.isspace():
                continue
            if re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", token):
                return token
            if token in {".", "!", "?", ":", ";", ",", "—", "–", "-", "(", "\"", "“"}:
                return None
        return None

    def next_word_position(position: int) -> int | None:
        for index in range(position + 1, len(tokens)):
            token = tokens[index]
            if token.isspace():
                continue
            if re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", token):
                return index
            if token in {".", "!", "?", ":", ";", ",", "—", "–", "-", ")", "\"", "”"}:
                return None
        return None

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.isspace() or not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", token):
            result.append(token)
            i += 1
            continue

        if len(token) == 1 and token.isupper():
            run_letters = [token]
            j = i
            while (
                j + 2 < len(tokens)
                and tokens[j + 1].isspace()
                and len(tokens[j + 2]) == 1
                and tokens[j + 2].isupper()
            ):
                run_letters.append(tokens[j + 2])
                j += 2
            if len(run_letters) >= 2:
                result.append("".join(run_letters).lower().capitalize())
                i = j + 1
                continue

            next_position = next_word_position(i)
            next_token = tokens[next_position] if next_position is not None else None
            prev_token = previous_word(i)
            if next_token and is_all_caps_word(next_token):
                if token in {"A", "I"}:
                    after_next = next_word_position(next_position)
                    if prev_token and after_next is None and len(next_token) <= 4:
                        result.append((token + next_token).lower().capitalize())
                        i = next_position + 1
                    else:
                        result.append(token)
                        i += 1
                    continue

                result.append((token + next_token).lower().capitalize())
                i = next_position + 1
                continue

        if is_all_caps_word(token):
            bare = re.sub(r"[^A-Za-z]", "", token)
            if ROMAN_NUMERAL_RE.fullmatch(bare):
                result.append(token.upper())
            elif bare.upper() in PRESERVE_ACRONYMS:
                result.append(bare.upper())
            else:
                force_lower = bare.lower() in FORCE_LOWER_WORDS and bool(previous_word(i))
                result.append(smart_capitalize(token, force_lower=force_lower))
        else:
            result.append(token)
        i += 1

    return "".join(result)


def fix_fragmented_honorifics(text: str) -> str:
    replacements = [
        (r"\bM\s+r\s*\.", "Mr."),
        (r"\bM\s+rs\s*\.", "Mrs."),
        (r"\bM\s+s\s*\.", "Ms."),
        (r"\bD\s+r\s*\.", "Dr."),
        (r"\bP\s+rof\s*\.", "Prof."),
        (r"\bS\s+t\s*\.", "St."),
    ]
    fixed = text
    for pattern, replacement in replacements:
        fixed = re.sub(pattern, replacement, fixed, flags=re.IGNORECASE)
    fixed = re.sub(r"\b([A-Z])\s+\.", r"\1.", fixed)
    fixed = re.sub(r"(?<=\.)\s+([A-Z])\.", r" \1.", fixed)
    return fixed


def compact_spaced_initialisms(text: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        letters = re.findall(r"[A-Za-z]", match.group(0))
        if len(letters) < 2:
            return match.group(0)
        compact = ".".join(letter.upper() for letter in letters) + "."
        lowered = compact.lower()
        if lowered in {"a.m.", "p.m."}:
            return lowered
        return compact

    return SPACED_INITIALISM_RE.sub(replacer, text)


def normalize_punctuation_for_tts(text: str) -> str:
    fixed = repair_mojibake(text)
    fixed = ELLIPSIS_RE.sub("…", fixed)
    fixed = DOUBLE_HYPHEN_RE.sub(" — ", fixed)
    fixed = re.sub(r"_(.*?)_", lambda m: m.group(1), fixed)
    fixed = fixed.replace("&", " and ")
    fixed = re.sub(r"\s*[\u2014\u2013]+\s*", ", ", fixed)
    fixed = re.sub(r"\s*…\s*", " … ", fixed)
    fixed = re.sub(r"\s+([,.;:!?])", lambda m: m.group(1), fixed)
    fixed = re.sub(r"\s+", " ", fixed)
    return fixed.strip()


def _trim_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if end <= start:
        return None
    return start, end


def build_tts_sentence_ends(text: str) -> list[int]:
    """
    Build sentence end offsets (exclusive) for a TTS-ready string.
    Offsets are relative to the exact string consumed by TTS.
    """
    if not text:
        return []

    ends: list[int] = []
    start = 0
    i = 0
    text_len = len(text)

    while i < text_len:
        ch = text[i]
        if not SENTENCE_TERMINATOR_RE.match(ch):
            i += 1
            continue

        end = i + 1
        while end < text_len and text[end] in {'"', "'", "\u2019", "\u201d", ")", "]", "}"}:
            end += 1

        is_abbreviation = False
        if ch == ".":
            prefix = text[start:end].strip()
            tail_word = re.search(r"([A-Za-z]+)\.$", prefix)
            if tail_word and tail_word.group(1).lower() in SENTENCE_ABBREVIATIONS:
                is_abbreviation = True
            if re.search(r"(?:\b[A-Za-z]\.){2,}$", prefix):
                is_abbreviation = True

        next_non_space = end
        while next_non_space < text_len and text[next_non_space].isspace():
            next_non_space += 1

        is_boundary = False
        if next_non_space >= text_len:
            is_boundary = True
        elif not is_abbreviation:
            next_char = text[next_non_space]
            if next_char.isupper() or next_char.isdigit() or next_char in {'"', "'", "\u2018", "\u201c", "(", "["}:
                is_boundary = True

        if is_boundary:
            span = _trim_span(text, start, end)
            if span is not None:
                _, span_end = span
                ends.append(span_end)
            start = next_non_space
            i = next_non_space
            continue

        i += 1

    tail = _trim_span(text, start, text_len)
    if tail is not None:
        _, tail_end = tail
        if not ends or ends[-1] != tail_end:
            ends.append(tail_end)

    return ends

def needs_tts_fix(text: str) -> bool:
    """Check if text has Gutenberg small-caps artifacts that need a ttsText."""
    repaired = repair_mojibake(text)
    if repaired != text:
        return True
    if is_spaced_caps(repaired.strip()):
        return True
    if re.search(r'\b[A-Z]\s[A-Z]{2,}\b', repaired):
        return True
    if re.search(r"\b(?:M\s+r|M\s+rs|M\s+s|D\s+r|P\s+rof|S\s+t)\s*\.", repaired, re.IGNORECASE):
        return True
    if SPACED_INITIALISM_RE.search(repaired):
        return True
    if re.search(r"\b[A-Z]{2,}(?:['\u2019][A-Z]+)?\b", repaired):
        return True
    if ELLIPSIS_RE.search(repaired):
        return True
    if "--" in repaired:
        return True
    if "&" in repaired or "_" in repaired:
        return True
    return False

def build_tts_text(text: str) -> str | None:
    """Build a clean ttsText override. Returns None if no fix needed."""
    t = repair_mojibake(text.strip())
    fixed = re.sub(r"(?<=[A-Za-z])\?(?=[A-Za-z])", "'", t)
    if is_spaced_caps(fixed):
        fixed = collapse_spaced_caps(fixed)
    if re.search(r"\b[A-Z]\s[A-Z]{2,}\b", fixed) or re.search(r"\b[A-Z]{2,}(?:['\u2019][A-Z]+)?\b", fixed):
        fixed = humanize_caps_tokens(fixed)
    fixed = fix_fragmented_honorifics(fixed)
    fixed = compact_spaced_initialisms(fixed)
    fixed = normalize_punctuation_for_tts(fixed)
    return fixed if fixed != t else None

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
    re.compile(r'^\[\s*Copyright\b', re.IGNORECASE),
    re.compile(r'^\[\s*Illustration\b', re.IGNORECASE),
    re.compile(r'^\[\s*Transcriber', re.IGNORECASE),
    re.compile(r'^\[\s*Redactor', re.IGNORECASE),
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

    source = data.get('source')
    if isinstance(source, dict):
        for key in ('title', 'author', 'language', 'category', 'filename', 'relativePath'):
            if key in source and isinstance(source.get(key), str):
                source[key] = repair_mojibake(source.get(key))

    items = data.get('paragraphs', [])
    stats = {
        'total': len(items),
        'skipped': 0,
        'titled': 0,
        'headings': 0,
        'paragraphs': 0,
        'tts_overrides': 0,
        'tts_sentence_structured': 0,
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
        if 'ttsSentenceEnds' not in p:
            p['ttsSentenceEnds'] = None

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
            p['ttsText'] = None
            p['ttsSentenceEnds'] = None
            continue
        t = p.get('text', '').strip()
        existing_role = p.get('role', '')

        # Recompute ttsText deterministically so stale overrides can be cleaned up.
        override = build_tts_text(t)
        p['ttsText'] = override

        tts_source = override if override is not None else t
        sentence_ends = build_tts_sentence_ends(tts_source)
        p['ttsSentenceEnds'] = sentence_ends if len(sentence_ends) > 1 else None

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
        if p.get('ttsSentenceEnds') is None:
            del p['ttsSentenceEnds']

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
            if p.get('ttsSentenceEnds'):
                stats['tts_sentence_structured'] += 1

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
    print(f"{'Book':<55} {'Total':>6} {'Skip':>6} {'Title':>6} {'Head':>6} {'Para':>6} {'TTS':>5} {'TTS-S':>6}")
    print("-" * 95)

    grand = {
        'total': 0,
        'skipped': 0,
        'titled': 0,
        'headings': 0,
        'paragraphs': 0,
        'tts_overrides': 0,
        'tts_sentence_structured': 0,
    }

    for path in book_files:
        rel = path.relative_to(script_dir)
        try:
            stats = enrich_book(path)
            label = str(rel)[:54]
            print(
                f"{label:<55} {stats['total']:>6} {stats['skipped']:>6} "
                f"{stats['titled']:>6} {stats['headings']:>6} {stats['paragraphs']:>6} "
                f"{stats['tts_overrides']:>5} {stats['tts_sentence_structured']:>6}"
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
        f"{grand['tts_overrides']:>5} {grand['tts_sentence_structured']:>6}"
    )
    print(f"\n{'[DRY RUN — no files written]' if DRY_RUN else 'Done. All files written.'}")


if __name__ == '__main__':
    main()
