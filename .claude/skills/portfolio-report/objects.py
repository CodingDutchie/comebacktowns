#!/usr/bin/env python3
"""Update Emory's Objects knowledge base from a project session (stdlib only).

Objects pages are rows in a Cloudflare D1 database, reached over the REST API.
This is the small slice of that a session needs: read a project's open tasks and
history, append a history line, tick or annotate a task, add a task, and tick the
matching item on the shared triage page.

  objects.py show
  objects.py history "<line>"
  objects.py tick "<task substring>" ["<note>"]
  objects.py note "<task substring>" "<note>"
  objects.py add "<task text>"
  objects.py triage-tick "<substring>" ["<note>"]

The page comes from --page, else the one-line file .claude/objects-page in the repo.

Never fails a session: with no credentials, or if the API refuses, it prints one
line saying Objects was skipped and exits 0. A tick/note that matches zero or
several tasks is refused (exit 1) with the candidates listed. The token is read
from the environment and is never printed.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

OWNER = 'edekoop@gmail.com'
DB = 'af344d7c-7f52-4359-81f0-3ce40045d084'
TRIAGE = 'triage-2026-10'
RETRIES = 3  # re-reads after a lost race, on top of the first attempt


class Skip(Exception):
    """Objects cannot be reached; the session carries on without it."""


class Refuse(Exception):
    """The request was understood and declined (no match, several matches...)."""


# ---- D1 ---------------------------------------------------------------------

def api(sql, params):
    """Run one statement. Returns (rows, rows_changed). Raises Skip on any failure."""
    token = os.environ.get('CLOUDFLARE_API_TOKEN')
    acc = os.environ.get('CLOUDFLARE_ACCOUNT_ID')
    if not token or not acc:
        raise Skip('CLOUDFLARE_API_TOKEN or CLOUDFLARE_ACCOUNT_ID is not set')
    url = f'https://api.cloudflare.com/client/v4/accounts/{acc}/d1/database/{DB}/query'
    req = urllib.request.Request(
        url, data=json.dumps({'sql': sql, 'params': params}).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        body = json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        raise Skip(f'the API answered HTTP {e.code}')
    except Exception as e:  # network down, bad JSON, timeout
        raise Skip(f'the API could not be reached ({type(e).__name__})')
    if not body.get('success'):
        raise Skip('the API refused the query')
    res = body['result'][0]
    return res.get('results', []), (res.get('meta') or {}).get('changes', 0)


def read_row(page):
    rows, _ = api("SELECT data, updated_at FROM records WHERE owner=? AND kind='object' "
                  "AND id=? AND deleted=0", [OWNER, page])
    if not rows:
        raise Skip(f'page {page} was not found')
    return json.loads(rows[0]['data']), int(rows[0]['updated_at'])


def write_row(data, read_at):
    """Compare-and-swap on updated_at. True if written, False if someone got there first."""
    now = max(int(datetime.datetime.now().timestamp() * 1000), read_at + 1)
    data['updatedAt'] = now  # the app keeps data.updatedAt equal to the column
    _, changed = api(
        "UPDATE records SET data=?, updated_at=?, seq=(SELECT COALESCE(MAX(seq),0)+1 FROM records) "
        "WHERE owner=? AND kind='object' AND id=? AND updated_at=?",
        [json.dumps(data, ensure_ascii=False), now, OWNER, data['id'], read_at])
    return changed > 0


def mutate(page, fn):
    """Read, apply fn(data), write; on a lost race re-read and apply again."""
    for _ in range(RETRIES + 1):
        data, read_at = read_row(page)
        msg = fn(data)
        finish(data)
        if write_row(data, read_at):
            return msg
    raise Skip(f'page {page} kept changing underneath the write; nothing was saved')


# ---- ProseMirror helpers ----------------------------------------------------

def inline(p):
    return ''.join(x.get('text') or x.get('attrs', {}).get('label', '')
                   for x in p.get('content', []) or [])


def text(n):
    if n['type'] in ('paragraph', 'heading', 'codeBlock'):
        return inline(n)
    return '\n'.join(t for t in (text(c) for c in n.get('content', []) or []) if t)


def mentions(n, acc=None):
    acc = [] if acc is None else acc
    if n.get('type') == 'mention':
        acc.append(n['attrs']['id'])
    for c in n.get('content', []) or []:
        mentions(c, acc)
    return acc


def finish(d):
    """Recompute the plain-text rendering and mention links, as the app does."""
    d['text'] = text(d['content'])
    ls = mentions(d['content'])
    d['links'] = [x for x in dict.fromkeys((d.get('links') or []) + ls) if x != d['id']]


def task_items(n):
    if n.get('type') == 'taskItem':
        yield n
    for c in n.get('content', []) or []:
        yield from task_items(c)


def task_lists(n):
    if n.get('type') == 'taskList':
        yield n
    for c in n.get('content', []) or []:
        yield from task_lists(c)


def para(s):
    return {'type': 'paragraph', 'content': [{'type': 'text', 'text': s}]}


def is_open(it):
    return not it.get('attrs', {}).get('checked')


def history_list(d, create=False):
    C = d['content']['content']
    for i, n in enumerate(C):
        if n['type'] == 'heading' and inline(n).strip().lower() == 'history':
            if i + 1 < len(C) and C[i + 1]['type'] == 'bulletList':
                return C[i + 1]
            if not create:
                return None
            bl = {'type': 'bulletList', 'content': []}
            C.insert(i + 1, bl)
            return bl
    if not create:
        return None
    bl = {'type': 'bulletList', 'content': []}
    C.append({'type': 'heading', 'attrs': {'level': 2}, 'content': [{'type': 'text', 'text': 'History'}]})
    C.append(bl)
    return bl


def clean(s):
    return re.sub(r'\s+', ' ', s).strip()


def find_open(d, needle):
    """The one open task containing needle; Refuse on zero or several."""
    n = clean(needle).lower()
    if not n:
        raise Refuse('give a non-empty task substring')
    hits = [it for it in task_items(d['content']) if is_open(it) and n in text(it).lower()]
    if len(hits) == 1:
        return hits[0]
    opened = [text(it) for it in task_items(d['content']) if is_open(it)]
    if not hits:
        raise Refuse(f'no open task matches "{needle}". Open tasks:\n'
                     + '\n'.join('  - ' + t for t in opened))
    raise Refuse(f'{len(hits)} open tasks match "{needle}"; use a longer substring. Candidates:\n'
                 + '\n'.join('  - ' + text(it) for it in hits))


def append_note(item, note):
    note = clean(note)
    if not note:
        return
    last = next((c for c in reversed(item.get('content', [])) if c['type'] == 'paragraph'), None)
    if last is None:
        last = para('')
        last['content'] = []
        item.setdefault('content', []).append(last)
    last.setdefault('content', []).append({'type': 'text', 'text': ' → ' + note})


# ---- commands ---------------------------------------------------------------

def cmd_show(page, a):
    d, _ = read_row(page)
    opened = [text(it) for it in task_items(d['content']) if is_open(it)]
    print(f"{d.get('title', page)} ({page})")
    print(f'Open tasks ({len(opened)}):')
    for t in opened:
        print('  - ' + t)
    if not opened:
        print('  (none)')
    hl = history_list(d)
    lines = [text(li) for li in (hl['content'] if hl else [])]
    print('History, last 5:')
    for t in lines[-5:]:
        print('  - ' + t)
    if not lines:
        print('  (none)')


def cmd_history(page, a):
    line = clean(a.line)
    if not line:
        raise Refuse('history line is empty')
    if not re.match(r'\d{4}-\d{2}-\d{2}', line):
        line = f'{datetime.date.today().isoformat()} — {line}'

    def fn(d):
        history_list(d, create=True)['content'].append({'type': 'listItem', 'content': [para(line)]})
        return f'history line added: {line}'
    print(mutate(page, fn))


def cmd_tick(page, a, check=True):
    def fn(d):
        it = find_open(d, a.task)
        if check:
            it.setdefault('attrs', {})['checked'] = True
        append_note(it, a.note or '')
        return ('ticked: ' if check else 'noted: ') + text(it)
    print(mutate(page, fn))


def cmd_add(page, a):
    t = clean(a.task)
    if not t:
        raise Refuse('task text is empty')

    def fn(d):
        lists = list(task_lists(d['content']))
        target = next((l for l in lists if any(is_open(i) for i in task_items(l))),
                      lists[0] if lists else None)
        item = {'type': 'taskItem', 'attrs': {'checked': False}, 'content': [para(t)]}
        if target is None:
            C = d['content']['content']
            i = next((k for k, n in enumerate(C) if n['type'] == 'heading'
                      and inline(n).strip().lower() == 'history'), len(C))
            C.insert(i, {'type': 'taskList', 'content': [item]})
        else:
            target['content'].append(item)
        return f'task added: {t}'
    print(mutate(page, fn))


# ---- entry ------------------------------------------------------------------

def page_from_repo():
    try:
        top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True,
                             text=True).stdout.strip() or os.getcwd()
    except Exception:
        top = os.getcwd()
    for base in (os.getcwd(), top):
        try:
            p = open(os.path.join(base, '.claude', 'objects-page')).read().strip()
        except OSError:
            continue
        if p:
            return p
    return None


def parser():
    ap = argparse.ArgumentParser(prog='objects.py', description=__doc__.split('\n')[0])
    ap.add_argument('--page', help='page id (default: .claude/objects-page)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('show')
    sub.add_parser('history').add_argument('line')
    for name in ('tick', 'note', 'triage-tick'):
        p = sub.add_parser(name)
        p.add_argument('task')
        p.add_argument('note', nargs='?', default='')
    sub.add_parser('add').add_argument('task')
    return ap


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        if a.cmd == 'triage-tick':
            page = TRIAGE
        else:
            page = a.page or page_from_repo()
            if not page:
                raise Skip('no page given: pass --page or write .claude/objects-page')
        if a.cmd == 'note' and not clean(a.note):
            raise Refuse('note needs a non-empty note')
        if a.cmd == 'show':
            cmd_show(page, a)
        elif a.cmd == 'history':
            cmd_history(page, a)
        elif a.cmd in ('tick', 'triage-tick'):
            cmd_tick(page, a, True)
        elif a.cmd == 'note':
            cmd_tick(page, a, False)
        elif a.cmd == 'add':
            cmd_add(page, a)
    except Skip as e:
        print(f'Objects skipped: {e}.')
        return 0
    except Refuse as e:
        print(f'Objects refused: {e}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
