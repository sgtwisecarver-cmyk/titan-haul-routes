"""The pad cards (v30.6): data/pads/<customer>.json + data/pads/index.json, instead of `const DATA` in index.html.

  data/pads/index.json   {"files": [...], "order": [card id, ...]}  - the list order the site shows
  data/pads/<src>.json   one customer's cards (src lowercased: eog, ascent, gulfport, infinity, expand, tiburon,
                         frac, disposal), one card per line so a git diff shows just the card that changed

Splitting by customer means a one-pad edit makes phones download that customer's file, not every pad.
A card id is d.id or slug(src + "-" + pad), the same as the site.

Road alerts on a card: `alert` is one string, or a list of {"t": text, "added": "YYYY-MM-DD", "temp": bool,
"from": where it came from} (v31.7). Both show as ROAD ALERT boxes at the top of the card. To clear temporary
traffic control later, look for "temp": true and its "added" date.

Use from Python:
    sys.path.insert(0, "<site repo>/tools"); import pads
    cards = pads.load_cards(site_root)      # every card, in list order (hidden / expired cards included)
    pads.save_cards(site_root, cards)       # writes the files back; list order = the order of `cards`
Command line:
    python tools/pads.py check     # every card listed once in the manifest, every manifest id has a card (fixes it)
    python tools/pads.py dump      # all cards as one JSON array on stdout (what `const DATA` used to be)
A card added to a customer file without touching the manifest still shows on the site (after the listed cards)
and `check` (also run by the publish job) files it in A-Z order.

Shared rule sets (v31.9): data/rules.json holds named sets of road rules, {"<set>": {"name": ..., "rules": [alert, ...]}},
each rule shaped like a card alert. A card lists the sets it follows in "rules": ["<set>", ...]; the page shows the
set's rules first, then the card's own "alert" lines. Any alert or rule may carry "until": "YYYY-MM-DD" - shown
through that day, then dropped. `check` fails (exit 1) when a card names a set that doesn't exist, a "temp": true
alert or rule has no "until", a pad has a visible regular card and a visible frac card at the same time, or cards
sharing a set give different speeds for the same thing in their own alerts.
"""
import datetime
import json
import os
import re
import sys

FILES = ['ascent', 'eog', 'gulfport', 'infinity', 'expand', 'tiburon', 'frac', 'disposal']
RULES = os.path.join('data', 'rules.json')     # shared rule sets (v31.9) - not a customer file, so not in FILES


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


def load_rules(root):
    path = os.path.join(root, RULES)
    return _read(path) if os.path.exists(path) else {}


def save_rules(root, sets):
    """one rule per line, like the card files, so a diff shows just the rule that changed"""
    out = []
    for k, s in sets.items():
        head = {x: y for x, y in s.items() if x != 'rules'}
        rules = ',\n'.join('   ' + json.dumps(r, ensure_ascii=False, separators=(',', ':')) for r in s.get('rules', []))
        out.append(json.dumps(k) + ':' + json.dumps(head, ensure_ascii=False, separators=(',', ':'))[:-1]
                   + ',"rules":[\n' + rules + '\n  ]}')
    with open(os.path.join(root, RULES), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('{\n' + ',\n'.join(out) + '\n}\n')


def alert_list(x):
    """a card's "alert" (one string or a list) or a set's "rules" as a list of dicts"""
    return [{'t': a} if isinstance(a, str) else a for a in (x if isinstance(x, list) else [x] if x else []) if a]


def today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo('America/New_York')).date().isoformat()
    except Exception:
        return (datetime.datetime.utcnow() - datetime.timedelta(hours=5)).date().isoformat()


def visible(d, day=None):
    day = day or today()
    return not d.get('hidden') and not (d.get('until') and day > d['until'])


def live(a, day=None):
    """an alert or rule still showing today (no "until", or "until" not passed yet)"""
    return not (a.get('until') and (day or today()) > a['until'])


def card_alerts(d, sets, day=None):
    """what the page shows on a card, in order: its rule sets' rules, then its own alerts (expired ones dropped)"""
    out = []
    for k in d.get('rules') or []:
        out += [a for a in alert_list(sets.get(k, {}).get('rules')) if live(a, day)]
    return out + [a for a in alert_list(d.get('alert')) if live(a, day)]


# what a speed line is about: the subject named first in its label (the text before the first ":"), else first in
# the whole line - "10 MPH ZONE: ... to the pad" is the zone, "CUTLER RD past the Lambeau lease road: ..." is Cutler Rd,
# "OAK DALE RD INTERSECTION (Cutler Rd & ...)" is the intersection
SPEED_SUBJECTS = [('zone', r'\bzone\b'), ('lease road', r'lease road'), ('on pad', r'\bon (the )?pad\b'),
                  ('intersection', r'\bintersection\b'), ('cutler rd', r'\bcutler\b')]


def _first_subject(text):
    hits = [(m.start(), name) for name, rx in SPEED_SUBJECTS for m in [re.search(rx, text, re.I)] if m]
    return min(hits)[1] if hits else None


def speeds(a):
    t = a.get('t') or ''
    mph = sorted({int(m) for m in re.findall(r'(\d+)\s*mph', t, re.I)})
    subj = (_first_subject(t.split(':', 1)[0]) if ':' in t else None) or _first_subject(t)
    return subj, mph


FRAC_RX = re.compile(r'^(.*?)\s+frac\b', re.I)


def consistency(cards, sets, day=None):
    """the publish-blocking problems (v31.9). Returns a list of messages; empty = fine."""
    errs = []
    for k, s in sets.items():
        for a in alert_list(s.get('rules')):
            if a.get('temp') and not a.get('until'):
                errs.append(f'rule set {k}: temporary rule has no "until" date: {a.get("t", "")[:70]}')
            if a.get('until') and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', a['until']):
                errs.append(f'rule set {k}: "until" must be YYYY-MM-DD: {a["until"]}')
    for d in cards:
        i = card_id(d)
        for k in d.get('rules') or []:
            if k not in sets:
                errs.append(f'{i}: rule set "{k}" is not in data/rules.json')
        for a in alert_list(d.get('alert')):
            if a.get('temp') and not a.get('until'):
                errs.append(f'{i}: temporary alert has no "until" date: {a.get("t", "")[:70]}')
            if a.get('until') and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', a['until']):
                errs.append(f'{i}: "until" must be YYYY-MM-DD: {a["until"]}')
    # a pad shows one way at a time: while its frac card is up, the regular card is hidden (with "goto")
    regular = {(d['src'], d.get('pad', '').strip().lower()): d for d in cards if d.get('src') not in ('Frac', 'Disposal')}
    for f in cards:
        if f.get('src') != 'Frac' or not visible(f, day):
            continue
        m = FRAC_RX.match(f.get('pad', ''))
        n = regular.get((f.get('operator'), (m.group(1) if m else '').strip().lower()))
        if n and visible(n, day):
            errs.append(f'{card_id(n)} is still on the list while its frac card {card_id(f)} is up: '
                        f'set "hidden": true and "goto": "{card_id(f)}" on it, or take the frac card down')
    # cards following the same set must not give different speeds for the same thing in their own alerts
    for k in sets:
        said = {}                                        # subject -> {mph: [card ids]}
        for a in alert_list(sets[k].get('rules')):
            subj, mph = speeds(a)
            if subj:
                for v in mph:
                    said.setdefault(subj, {}).setdefault(v, []).append(f'set {k}')
        for d in cards:
            if k not in (d.get('rules') or []):
                continue
            for a in alert_list(d.get('alert')):
                subj, mph = speeds(a)
                if subj:
                    for v in mph:
                        said.setdefault(subj, {}).setdefault(v, []).append(card_id(d))
        for subj, by in said.items():
            if len(by) > 1:
                errs.append(f'rule set {k}: different speeds for {subj}: ' +
                            '; '.join(f'{v} MPH ({", ".join(sorted(set(w)))})' for v, w in sorted(by.items())))
    return errs


if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'check'
    if cmd == 'check':
        notes = check(root)
        print('\n'.join(notes) if notes else 'pads ok: manifest and customer files agree')
        errs = consistency(load_cards(root), load_rules(root))
        if errs:
            print('\nCHECK FAILED - fix these before publishing:\n  ' + '\n  '.join(errs))
            sys.exit(1)
        print('rules ok: rule sets, "until" dates, frac/regular cards and speeds agree')
    elif cmd == 'dump':
        sys.stdout.reconfigure(encoding='utf-8')
        print(json.dumps(load_cards(root), ensure_ascii=False, separators=(',', ':')))
    else:
        sys.exit(__doc__)
