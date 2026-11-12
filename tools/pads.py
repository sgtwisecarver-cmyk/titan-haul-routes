"""The pad cards (v30.6): data/pads/<customer>.json + data/pads/index.json, instead of `const DATA` in index.html.

  data/pads/index.json   {"files": [...], "order": [card id, ...]}  - the list order the site shows
  data/pads/<src>.json   one customer's cards (src lowercased: eog, ascent, gulfport, infinity, expand, tiburon,
                         frac, disposal), one card per line so a git diff shows just the card that changed

Splitting by customer means a one-pad edit makes phones download that customer's file, not every pad.
A card id is d.id or slug(src + "-" + pad), the same as the site.

Use from Python:
    sys.path.insert(0, "<site repo>/tools"); import pads
    cards = pads.load_cards(site_root)      # every card, in list order (hidden / expired cards included)
    pads.save_cards(site_root, cards)       # writes the files back; list order = the order of `cards`
Command line:
    python tools/pads.py check     # every card listed once in the manifest, every manifest id has a card (fixes it)
    python tools/pads.py dump      # all cards as one JSON array on stdout (what `const DATA` used to be)
A card added to a customer file without touching the manifest still shows on the site (after the listed cards)
and `check` (also run by the publish job) files it in A-Z order.
"""
import json
import os
import re
import sys

FILES = ['ascent', 'eog', 'gulfport', 'infinity', 'expand', 'tiburon', 'frac', 'disposal']


def _dir(root):
    return os.path.join(root, 'data', 'pads')


def norm(s):
    s = re.sub(r'[^a-z0-9 ]+', ' ', (s or '').lower())
    return re.sub(r'\s+', ' ', s).strip()


def card_id(d):
    return d.get('id') or norm(f"{d.get('src')}-{d.get('pad')}").replace(' ', '-')


def file_of(d):
    return (d.get('src') or 'other').lower()


def _read(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def load_manifest(root):
    return _read(os.path.join(_dir(root), 'index.json'))


def load_cards(root):
    m = load_manifest(root)
    parts = [_read(os.path.join(_dir(root), f + '.json')) for f in m['files']]
    by = {}
    for part in parts:
        for d in part:
            by[card_id(d)] = d
    out, seen = [], set()
    for i in m['order']:
        if i in by and i not in seen:
            seen.add(i); out.append(by[i])
    for part in parts:                       # cards the manifest doesn't list yet: after the listed ones
        for d in part:
            if card_id(d) not in seen:
                seen.add(card_id(d)); out.append(d)
    return out


def _dump_list(cards):
    if not cards:
        return '[]\n'
    return '[\n' + ',\n'.join(json.dumps(d, ensure_ascii=False, separators=(',', ':')) for d in cards) + '\n]\n'


def save_cards(root, cards):
    ids = [card_id(d) for d in cards]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ValueError(f'duplicate card ids: {dup}')
    groups = {}
    for d in cards:
        groups.setdefault(file_of(d), []).append(d)
    files = [f for f in FILES if f in groups] + sorted(f for f in groups if f not in FILES)
    os.makedirs(_dir(root), exist_ok=True)
    for f in files:
        with open(os.path.join(_dir(root), f + '.json'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(_dump_list(groups[f]))
    for old in os.listdir(_dir(root)):           # a customer with no cards left
        if old.endswith('.json') and old != 'index.json' and old[:-5] not in files:
            os.remove(os.path.join(_dir(root), old))
    manifest = '{"files":' + json.dumps(files) + ',\n"order":[\n' + ',\n'.join(json.dumps(i) for i in ids) + '\n]}\n'
    with open(os.path.join(_dir(root), 'index.json'), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(manifest)
    return files


def check(root, fix=True):
    """manifest vs files: unknown ids dropped, unlisted cards filed in A-Z position. Returns a list of notes."""
    m = load_manifest(root)
    present = [f[:-5] for f in sorted(os.listdir(_dir(root))) if f.endswith('.json') and f != 'index.json']
    notes = []
    if sorted(present) != sorted(m['files']):
        notes.append(f"files on disk {present} vs manifest {m['files']}")
    m['files'] = [f for f in FILES if f in present] + [f for f in present if f not in FILES]
    cards = []
    for f in m['files']:
        cards += _read(os.path.join(_dir(root), f + '.json'))
    by = {card_id(d): d for d in cards}
    order = [i for i in m['order'] if i in by]
    if len(order) != len(m['order']):
        notes.append(f"dropped {len(m['order']) - len(order)} manifest id(s) with no card")
    listed = set(order)
    for d in cards:                              # file a new card where an A-Z list would put it
        i = card_id(d)
        if i in listed:
            continue
        k = d.get('pad', '').lower()
        pos = next((n for n, j in enumerate(order) if by[j].get('pad', '').lower() > k), len(order))
        order.insert(pos, i); listed.add(i)
        notes.append(f'filed new card {i} at position {pos}')
    for f in m['files']:                         # a card in the wrong customer's file
        for d in _read(os.path.join(_dir(root), f + '.json')):
            if file_of(d) != f:
                notes.append(f"{card_id(d)} is in {f}.json but its src is {d.get('src')}")
    if fix and notes:
        save_cards(root, [by[i] for i in order])
    return notes


if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'check'
    if cmd == 'check':
        notes = check(root)
        print('\n'.join(notes) if notes else 'pads ok: manifest and customer files agree')
    elif cmd == 'dump':
        sys.stdout.reconfigure(encoding='utf-8')
        print(json.dumps(load_cards(root), ensure_ascii=False, separators=(',', ':')))
    else:
        sys.exit(__doc__)
