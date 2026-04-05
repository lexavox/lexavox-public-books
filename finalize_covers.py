import json
from pathlib import Path

CATALOG = Path(r'C:\LexaVox\lexavox-public-books\catalog.json')
GH = 'https://raw.githubusercontent.com/lexavox/lexavox-public-books/main/covers'

catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
fixed = 0
for book in catalog['books']:
    if not book.get('coverUrl'):
        book['coverUrl'] = f"{GH}/{book['id']}.jpg"
        fixed += 1
        print(f"  Set coverUrl for {book['id']}: {book['title'][:45]}")
    elif 'raw.githubusercontent.com/lexavox' not in book['coverUrl']:
        print(f"  EXTERNAL STILL: {book['id']} -> {book['coverUrl']}")

CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Fixed {fixed} missing entries.')

remaining_external = [b for b in catalog['books'] if b.get('coverUrl') and 'raw.githubusercontent.com/lexavox' not in b['coverUrl']]
no_cover = [b for b in catalog['books'] if not b.get('coverUrl')]
print(f'External remaining: {len(remaining_external)}')
print(f'No cover remaining: {len(no_cover)}')
print(f'Total books: {len(catalog["books"])}')
