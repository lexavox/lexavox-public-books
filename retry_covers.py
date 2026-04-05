"""
Retry failed cover downloads using Open Library as the source.
Targets only books whose coverUrl still points to an external host.
"""
import json, time, urllib.request, urllib.parse
from pathlib import Path

CATALOG_PATH = Path(__file__).parent / "catalog.json"
COVERS_DIR   = Path(__file__).parent / "covers"
GH_RAW       = "https://raw.githubusercontent.com/lexavox/lexavox-public-books/main/covers"
HEADERS      = {"User-Agent": "LexaVox/1.0 (cover-retry; contact@lexavox.com)"}
OL_SEARCH    = "https://openlibrary.org/search.json?title={t}&author={a}&limit=1&fields=cover_i,cover_edition_key"
OL_COVER     = "https://covers.openlibrary.org/b/id/{cid}-M.jpg"

def download(url, dest):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            dest.write_bytes(r.read())
        return True
    except Exception as e:
        print(f"    FAIL: {e}")
        return False

def ol_url(title, author):
    url = OL_SEARCH.format(t=urllib.parse.quote(title), a=urllib.parse.quote(author or ""))
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            docs = json.loads(r.read()).get("docs", [])
            if docs and "cover_i" in docs[0]:
                return OL_COVER.format(cid=docs[0]["cover_i"])
    except Exception:
        pass
    return None

def main():
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    COVERS_DIR.mkdir(exist_ok=True)
    fixed = 0
    for book in catalog["books"]:
        url = book.get("coverUrl","")
        if not url or "raw.githubusercontent.com/lexavox/lexavox-public-books" in url:
            continue  # already self-hosted or none
        bid = book["id"]
        dest = COVERS_DIR / f"{bid}.jpg"
        title = book.get("title","")
        author = book.get("author","")
        print(f"  {title[:45]} ({bid})")
        src = ol_url(title, author)
        if src:
            print(f"    → Open Library: {src}")
            if download(src, dest):
                book["coverUrl"] = f"{GH_RAW}/{bid}.jpg"
                fixed += 1
                time.sleep(0.3)
                continue
        # Nothing worked — remove the broken external URL so the app shows a placeholder
        print(f"    → no cover available, removing URL")
        del book["coverUrl"]
        time.sleep(0.3)

    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFixed {fixed} covers.")

if __name__ == "__main__":
    main()
