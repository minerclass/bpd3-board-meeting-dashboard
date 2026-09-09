#!/usr/bin/env python3
"""Refresh the board meeting schedule from bpd3.org.

Reads the district's two public board-meeting pages, extracts the regular
meeting schedule plus any posted agenda/minutes links, merges the result into
scripts/schedule.json, and rewrites the embedded JSON block in index.html.

Hand-written fields on a meeting (items, detail, cats, sourceNote) are preserved
across runs -- this script only owns the schedule facts: date, label, agenda
link, minutes link, and the "minutes pending" note. A hand-added special-hearing
label survives only while the district's own schedule list does not supply one.

Run with --check to report drift without writing anything.

Both pages are Nuxt apps that ship their content as a JSON payload in a
__NUXT_DATA__ script tag, so no JS execution or headless browser is needed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, 'scripts', 'schedule.json')
INDEX_PATH = os.path.join(ROOT, 'index.html')

SCHEDULE_PAGE = 'https://www.bpd3.org/page/board-of-education-school-board-meetings'
REGULAR_PAGE = 'https://www.bpd3.org/o/bpd3/page/regular-board-meeting'

UA = 'Mozilla/5.0 (compatible; bpd3-board-dashboard/1.0; +https://github.com/minerclass/bpd3-board-meeting-dashboard)'

MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
          'July', 'August', 'September', 'October', 'November', 'December']
MONTH_NUM = {m: i + 1 for i, m in enumerate(MONTHS)}
MONTH_RE = '(?:' + '|'.join(MONTHS) + ')'
DATE_RE = re.compile(r'\b(' + MONTH_RE + r')\s+(\d{1,2}),\s*(20\d\d)\b')

# A schedule this short means the page changed shape; refuse to publish it.
MIN_MEETINGS = 8

# The embedded data block in index.html that the dashboard renders from.
BLOCK_RE = re.compile(
    r'(<script type="application/json" id="mtg-data">)(.*?)(</script>)', re.S)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode('utf-8', 'replace')


def nuxt_strings(page: str) -> list:
    """Return the page's content strings, in document order."""
    m = re.search(r'id="__NUXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        raise RuntimeError('no __NUXT_DATA__ payload found')
    payload = json.loads(m.group(1))
    return [x for x in payload if isinstance(x, str)]


def strip_tags(fragment: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', fragment)
    return re.sub(r'\s+', ' ', html.unescape(text)).strip()


def iso(month: str, day: str, year: str) -> str:
    return '%s-%02d-%02d' % (year, MONTH_NUM[month], int(day))


def parse_schedule(page: str) -> dict:
    """Dates -> special-hearing label (or None) from the annual schedule list."""
    found = {}
    for s in nuxt_strings(page):
        if '<' not in s:
            continue
        for item in re.findall(r'<li>(.*?)</li>', s, re.S):
            text = strip_tags(item)
            m = DATE_RE.search(text)
            if not m:
                continue
            tail = text[m.end():]
            label = re.search(r'\(([^)]+)\)', tail)
            found[iso(*m.groups())] = label.group(1).strip() if label else None
    return found


def parse_documents(page: str) -> dict:
    """Dates -> {'agenda': url, 'minutes': url, 'minutesNote': str}.

    The payload lists content nodes in document order, so a date heading is
    followed by that meeting's location line and its agenda/minutes list.
    """
    docs = {}
    current = None
    for s in nuxt_strings(page):
        if '<' not in s:
            continue
        text = strip_tags(s)
        links = re.findall(
            r'href="(https://drive\.google\.com/[^"]+)"[^>]*>(.*?)</a>', s, re.S)

        # A short node that is just a date is a meeting heading.
        m = DATE_RE.search(text)
        if m and not links and len(text) < 60:
            current = iso(*m.groups())
            docs.setdefault(current, {})
            continue

        if not links or current is None:
            continue

        entry = docs.setdefault(current, {})
        for url, label_html in links:
            label = strip_tags(label_html).lower()
            url = url.split('?')[0]
            if 'agenda' in label:
                entry['agenda'] = url
            elif 'minute' in label:
                entry['minutes'] = url
        note = re.search(r'Minutes\s*\(([^)]+)\)', text)
        if note and 'minutes' not in entry:
            n = note.group(1).strip()
            entry['minutesNote'] = n[:1].upper() + n[1:]
    return docs


def school_year(dates: list) -> tuple:
    """('2026-27', '2026–27') for a schedule starting in Aug 2026."""
    start = min(dates)
    y = int(start[:4])
    if int(start[5:7]) < 7:      # a Jan-Jun start belongs to the prior fall
        y -= 1
    return '%d-%02d' % (y, (y + 1) % 100), '%d–%02d' % (y, (y + 1) % 100)


def build(schedule: dict, docs: dict, previous: dict) -> dict:
    old = {m['date']: m for m in previous.get('meetings', [])}
    meetings = []
    for date in sorted(schedule):
        d = dt.date(int(date[:4]), int(date[5:7]), int(date[8:10]))
        label = '%s %d, %d' % (MONTHS[d.month - 1], d.day, d.year)
        doc = docs.get(date, {})
        prev = old.get(date, {})

        meeting = {
            'date': date,
            'label': label,
            'month': '%s %d' % (MONTHS[d.month - 1], d.year),
            'short': '%s %d' % (MONTHS[d.month - 1][:3], d.day),
            'mon': MONTHS[d.month - 1][:3],
            'type': 'Regular',
            # The district's schedule list is authoritative for hearing labels,
            # but it does not tag every one (e.g. the August administrative
            # costs hearing appears only on the agenda), so a curated label
            # survives when the site offers none.
            'special': schedule[date] or prev.get('special'),
            'agenda': doc.get('agenda') or prev.get('agenda'),
            'minutes': doc.get('minutes') or prev.get('minutes'),
            # curated fields survive untouched
            'cats': prev.get('cats', []),
            'items': prev.get('items', []),
            'detail': prev.get('detail', {}),
        }
        note = doc.get('minutesNote') or prev.get('minutesNote')
        if note and not meeting['minutes']:
            meeting['minutesNote'] = note
        if prev.get('sourceNote'):
            meeting['sourceNote'] = prev['sourceNote']
        meetings.append(meeting)

    year, year_label = school_year(list(schedule))
    out = dict(previous)
    out.update({
        'year': year,
        'yearLabel': year_label,
        'source': REGULAR_PAGE,
        'schedulePage': SCHEDULE_PAGE,
        'updated': dt.date.today().isoformat(),
        'meetings': meetings,
    })
    out.setdefault('defaults', {
        'time': '6:30 PM',
        'location': 'Beach Park Middle School (Cafeteria)',
        'address': '40667 N. Green Bay Rd., Beach Park, IL 60099',
    })
    out.setdefault('notes', [])
    return out


def comparable(doc: dict) -> str:
    """Serialization used to decide whether anything really changed.

    Ignores the 'updated' stamp so an unchanged schedule produces no commit.
    """
    d = {k: v for k, v in doc.items() if k != 'updated'}
    return json.dumps(d, sort_keys=True, ensure_ascii=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true',
                    help='report drift without writing')
    args = ap.parse_args()

    try:
        schedule_page = fetch(SCHEDULE_PAGE)
        regular_page = fetch(REGULAR_PAGE)
    except (urllib.error.URLError, OSError) as exc:
        print('ERROR: could not reach bpd3.org: %s' % exc, file=sys.stderr)
        return 2

    schedule = parse_schedule(schedule_page)
    if len(schedule) < MIN_MEETINGS:
        # Fall back to the dates listed on the regular-meetings page.
        schedule.update({d: schedule.get(d)
                         for d in parse_schedule(regular_page)})
    if len(schedule) < MIN_MEETINGS:
        print('ERROR: only %d meetings parsed (expected >= %d); '
              'the district page layout probably changed. Nothing written.'
              % (len(schedule), MIN_MEETINGS), file=sys.stderr)
        return 3

    docs = parse_documents(regular_page)

    with open(DATA_PATH, encoding='utf-8') as fh:
        previous = json.load(fh)

    updated = build(schedule, docs, previous)
    changed = comparable(updated) != comparable(previous)

    old_dates = {m['date'] for m in previous.get('meetings', [])}
    new_dates = {m['date'] for m in updated['meetings']}
    for d in sorted(new_dates - old_dates):
        print('  + meeting added: %s' % d)
    for d in sorted(old_dates - new_dates):
        print('  - meeting removed: %s' % d)
    old_docs = {m['date']: (m.get('agenda'), m.get('minutes'))
                for m in previous.get('meetings', [])}
    for m in updated['meetings']:
        was = old_docs.get(m['date'])
        now = (m.get('agenda'), m.get('minutes'))
        if was and was != now:
            print('  ~ documents changed: %s %s -> %s' % (m['date'], was, now))

    print('%d meetings parsed; %s' % (len(updated['meetings']),
                                      'changes found' if changed else 'no changes'))
    if args.check:
        return 1 if changed else 0
    if not changed:
        return 0

    blob = json.dumps(updated, indent=2, ensure_ascii=False)
    with open(DATA_PATH, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(blob + '\n')

    with open(INDEX_PATH, encoding='utf-8') as fh:
        index = fh.read()
    if not BLOCK_RE.search(index):
        print('ERROR: could not find the #mtg-data block in index.html',
              file=sys.stderr)
        return 4
    index = BLOCK_RE.sub(
        lambda m: m.group(1) + blob + m.group(3), index, count=1)
    with open(INDEX_PATH, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(index)

    print('wrote scripts/schedule.json and index.html')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
