#!/usr/bin/env python3
"""Vibe City — see your codebase as a living 3D city.

  python3 vibecity.py build  [DIR] [--base REF] [--check] [--check-cmd CMD] [--errors LOG] [--open]
  python3 vibecity.py serve  [DIR] [--port 4321]      live city that rebuilds as files change
  python3 vibecity.py pending [DIR] [--limit N]       files that still need a plain-English summary
  python3 vibecity.py notes  [DIR] --merge FILE       merge Claude-written summaries into notes.json
  python3 vibecity.py hook                            Claude Code Stop hook: refresh an existing city

Everything is written to DIR/.vibecity/ (city.html, graph.json, notes.json).
Stdlib only — needs Python 3.8+.
"""
import argparse
import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from vc_scan import scan_project, list_files, SKIP_DIRS  # noqa: E402
from vc_analyze import build_graph, compute_impact, health, run_checks, parse_errors  # noqa: E402

VERSION = '0.1.0'
TEMPLATE = os.path.join(HERE, '..', 'assets', 'viewer.html')
MAX_FLOORS = 30


def out_dir(root):
    d = os.path.join(root, '.vibecity')
    os.makedirs(d, exist_ok=True)
    gi = os.path.join(d, '.gitignore')
    if not os.path.exists(gi):
        with open(gi, 'w') as fh:
            fh.write('# generated — notes.json is worth committing\ncity.html\ngraph.json\n')
    return d


def load_notes(root):
    p = os.path.join(root, '.vibecity', 'notes.json')
    try:
        with open(p, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print('[vibe-city] notes.json is not valid JSON (%s) — ignoring it' % e, file=sys.stderr)
        return {}


GENERIC_NAMES = {'route', 'page', 'layout', 'index', 'loading', 'error', 'template', 'default',
                 'not-found', '+page', '+page.server', '+layout', '+server', '__init__', 'views', 'models', 'urls'}


def display_name(path):
    """route.ts is ambiguous in a Next app — show 'cart/route.ts' instead."""
    base = os.path.basename(path)
    parts = path.split('/')
    if os.path.splitext(base)[0] in GENERIC_NAMES and len(parts) > 1:
        parent = parts[-2]
        return '%s/%s' % (parent, base)
    return base


def assign_districts(buildings, max_size=36):
    """Group files into city districts: top-level folders (minus src/), API routes together."""
    def key(dir_, depth):
        parts = [p for p in dir_.split('/') if p and p != '.']
        if len(parts) > 1 and parts[0] == 'src':
            parts = parts[1:]
        if 'api' in parts:
            return '/'.join(parts[:parts.index('api') + 1])
        return '/'.join(parts[:depth]) or '.'
    for b in buildings:
        b['district'] = key(b['dir'], 1)
    sizes = {}
    for b in buildings:
        sizes[b['district']] = sizes.get(b['district'], 0) + 1
    for b in buildings:
        if sizes[b['district']] > max_size:
            b['district'] = key(b['dir'], 2)


def assemble(root, base=None, check=False, check_cmd=None, errors_file=None):
    t0 = time.time()
    files = scan_project(root)
    notes = load_notes(root)
    paths = [f['path'] for f in files]
    checks = []
    if check or check_cmd:
        checks += run_checks(root, paths, check_cmd)
    if errors_file:
        with open(errors_file, encoding='utf-8', errors='replace') as fh:
            checks += parse_errors(root, fh.read(), paths, source='log')
    city = build_graph(root, files, notes, checks)
    impact = compute_impact(root, city, base)

    fnotes = notes.get('files') or {}
    buildings = []
    for f in files:
        n = fnotes.get(f['path']) or {}
        sym_notes = n.get('symbols') or {}
        floors = []
        syms = sorted(f['symbols'], key=lambda s: s['line'])
        extra = syms[MAX_FLOORS - 1:] if len(syms) > MAX_FLOORS else []
        for s in (syms[:MAX_FLOORS - 1] if extra else syms):
            floors.append({
                'id': s['id'], 'name': s['name'], 'kind': s['kind'], 'line': s['line'],
                'endLine': s['endLine'], 'loc': s['loc'], 'exported': s['exported'],
                'route': ('%s %s' % (s['route']['method'], s['route']['path'])) if s.get('route') else None,
                'summary': sym_notes.get(s['name']), 'triggers': s['triggers'],
                'fetches': s['fetches'], 'tables': s['tables'], 'env': s['env'],
            })
        if extra:
            floors.append({'id': f['path'] + '#…', 'name': '+%d more' % len(extra), 'kind': 'more',
                           'line': extra[0]['line'], 'endLine': extra[-1]['endLine'],
                           'loc': sum(s['loc'] for s in extra), 'exported': False, 'route': None,
                           'summary': ', '.join(s['name'] for s in extra[:12]), 'triggers': [],
                           'fetches': [], 'tables': [], 'env': []})
        buildings.append({
            'id': f['path'], 'name': display_name(f['path']),
            'dir': os.path.dirname(f['path']) or '.', 'role': f['role'], 'loc': f['loc'],
            'lang': f['lang'], 'entry': f['entry'], 'client': f['useClient'],
            'summary': n.get('summary'), 'stale': bool(n) and n.get('hash') != f['hash'],
            'env': f['env'], 'hash': f['hash'], 'floors': floors,
        })

    assign_districts(buildings)

    externals = []
    for e in city['externals'].values():
        externals.append({'id': 'ext:' + e['id'], 'label': e['label'], 'kind': e['kind'],
                          'tables': sorted(e['tables']), 'users': len(e['users'])})
    used = {e['to'] for e in city['edges']}
    externals = [e for e in externals if e['id'] in used]

    file_imports = sorted({(a, b) for a, b, k in city['fileEdges'] if a != b})
    hp = health(city['incidents'])
    langs = sorted({f['lang'] for f in files})
    return {
        'version': VERSION,
        'meta': {
            'name': os.path.basename(os.path.abspath(root)), 'root': os.path.abspath(root),
            'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'langs': langs, 'scanMs': int((time.time() - t0) * 1000),
            'files': len(files), 'floors': sum(len(b['floors']) for b in buildings),
            'summarized': sum(1 for b in buildings if b['summary']),
        },
        'project': notes.get('project') or {},
        'buildings': buildings, 'externals': externals, 'edges': city['edges'],
        'imports': [{'from': a, 'to': b} for a, b in file_imports],
        'incidents': city['incidents'], 'impact': impact, 'health': hp,
    }


def render(root, data):
    d = out_dir(root)
    with open(os.path.join(d, 'graph.json'), 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=1)
    with open(TEMPLATE, encoding='utf-8') as fh:
        tpl = fh.read()
    payload = json.dumps(data, separators=(',', ':')).replace('</', '<\\/')
    html = tpl.replace('/*__VIBECITY_DATA__*/null', payload)
    path = os.path.join(d, 'city.html')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(html)
    return path


def summary_line(data):
    h = data['health']
    c = h['counts']
    parts = ['%s %d/100 %s' % (h['icon'], h['score'], h['weather']),
             '%d buildings, %d floors' % (data['meta']['files'], data['meta']['floors'])]
    icons = [('fire', '🔥'), ('toxic', '☣️'), ('broken', '🌉'), ('gridlock', '🚦'), ('ghost', '👻'), ('construction', '🚧')]
    dis = ' '.join('%s%d' % (ic, c[k]) for k, ic in icons if c.get(k))
    if dis:
        parts.append(dis)
    imp = data.get('impact')
    if imp and imp['changedFiles']:
        parts.append('⚡ %d changed floor(s), %d in the blast radius' % (len(imp['changedFloors']), len(imp['blast'])))
    return ' · '.join(parts)


def cmd_build(a):
    root = os.path.abspath(a.dir)
    data = assemble(root, a.base, a.check, a.check_cmd, a.errors)
    path = render(root, data)
    if not a.quiet:
        print('[vibe-city] ' + summary_line(data))
        print('[vibe-city] city: ' + path)
        if a.json:
            print(json.dumps({'health': data['health'], 'impact': data['impact'],
                              'incidents': data['incidents']}, indent=1))
    if a.open:
        webbrowser.open('file://' + path)


def cmd_pending(a):
    root = os.path.abspath(a.dir)
    files = scan_project(root)
    notes = (load_notes(root).get('files') or {})
    todo = []
    for f in files:
        n = notes.get(f['path'])
        if n and n.get('hash') == f['hash'] and n.get('summary'):
            continue
        todo.append({'path': f['path'], 'loc': f['loc'],
                     'symbols': ['%s (%s, L%d)' % (s['name'], s['kind'], s['line']) for s in f['symbols']][:MAX_FLOORS]})
    todo.sort(key=lambda t: (-t['loc']))
    print(json.dumps({'pending': len(todo), 'total': len(files),
                      'files': todo[:a.limit] if a.limit else todo}, indent=1))


def cmd_notes(a):
    root = os.path.abspath(a.dir)
    with open(a.merge, encoding='utf-8') as fh:
        part = json.load(fh)
    notes = load_notes(root)
    notes.setdefault('version', 1)
    hashes = {f['path']: f['hash'] for f in scan_project(root)}
    if part.get('project'):
        notes.setdefault('project', {}).update(part['project'])
    files = notes.setdefault('files', {})
    added = 0
    for path, n in (part.get('files') or {}).items():
        if path not in hashes:
            print('[vibe-city] skipping unknown file: %s' % path, file=sys.stderr)
            continue
        cur = files.get(path) or {}
        if n.get('summary'):
            cur['summary'] = n['summary']
        if n.get('symbols'):
            cur.setdefault('symbols', {}).update(n['symbols'])
        cur['hash'] = hashes[path]
        files[path] = cur
        added += 1
    if 'incidents' in part:
        notes['incidents'] = part['incidents']
    d = out_dir(root)
    with open(os.path.join(d, 'notes.json'), 'w', encoding='utf-8') as fh:
        json.dump(notes, fh, indent=1, ensure_ascii=False)
    print('[vibe-city] merged notes for %d file(s) → %s' % (added, os.path.join(d, 'notes.json')))


def cmd_hook(_a):
    try:
        sys.stdin.read()
    except Exception:
        pass
    root = os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()
    if not os.path.exists(os.path.join(root, '.vibecity', 'graph.json')):
        return  # opt-in: only refresh projects that already have a city
    try:
        render(root, assemble(root))
    except Exception as e:
        print('[vibe-city] hook refresh failed: %s' % e, file=sys.stderr)


# ---------------------------------------------------------------- live server

def cmd_serve(a):
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

    root = os.path.abspath(a.dir)
    state = {'version': 0, 'data': None, 'html': None}
    cond = threading.Condition()

    def rebuild(reason):
        try:
            data = assemble(root, a.base)
            path = render(root, data)
            with open(path, 'rb') as fh:
                html = fh.read()
        except Exception as e:
            print('[vibe-city] rebuild failed: %s' % e, file=sys.stderr)
            return
        with cond:
            state['data'] = json.dumps(data).encode()
            state['html'] = html
            state['version'] += 1
            cond.notify_all()
        print('[vibe-city] %s → %s' % (reason, summary_line(data)))

    def snapshot():
        snap = {}
        for rel in list_files(root):
            try:
                snap[rel] = os.stat(os.path.join(root, rel)).st_mtime
            except OSError:
                pass
        try:
            snap['.vibecity/notes.json'] = os.stat(os.path.join(root, '.vibecity', 'notes.json')).st_mtime
        except OSError:
            pass
        return snap

    def watch():
        prev = snapshot()
        while True:
            time.sleep(1.0)
            cur = snapshot()
            if cur != prev:
                time.sleep(0.5)  # let editors finish writing
                changed = [k for k in set(cur) | set(prev) if cur.get(k) != prev.get(k)]
                prev = snapshot()
                rebuild('change in %s%s' % (changed[0], ' +%d' % (len(changed) - 1) if len(changed) > 1 else ''))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            p = self.path.split('?')[0]
            if p in ('/', '/index.html', '/city.html'):
                return self._send(200, state['html'], 'text/html; charset=utf-8')
            if p == '/graph.json':
                return self._send(200, state['data'], 'application/json')
            if p == '/events':
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                seen = state['version']
                try:
                    self.wfile.write(b'event: hello\ndata: %d\n\n' % seen)
                    self.wfile.flush()
                    while True:
                        with cond:
                            cond.wait(timeout=15)
                            v = state['version']
                        if v != seen:
                            seen = v
                            self.wfile.write(b'event: rebuild\ndata: %d\n\n' % v)
                        else:
                            self.wfile.write(b': ping\n\n')
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
            return self._send(404, b'not found', 'text/plain')

    rebuild('initial build')
    srv = ThreadingHTTPServer(('127.0.0.1', a.port), H)
    srv.daemon_threads = True
    threading.Thread(target=watch, daemon=True).start()
    url = 'http://127.0.0.1:%d/' % a.port
    print('[vibe-city] live city at %s — rebuilding on every save (Ctrl+C to stop)' % url)
    if not a.no_open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(prog='vibecity', description='See your codebase as a living 3D city.')
    sub = ap.add_subparsers(dest='cmd', required=True)

    b = sub.add_parser('build', help='scan the project and write .vibecity/city.html')
    b.add_argument('dir', nargs='?', default='.')
    b.add_argument('--base', help='git ref to compare against for the blast radius (default: HEAD)')
    b.add_argument('--check', action='store_true', help="run the project's TypeScript checker; errors become fires")
    b.add_argument('--check-cmd', help='run this command (e.g. "npm test") and turn file:line errors into fires')
    b.add_argument('--errors', help='a saved error log / stack trace to map onto the city as fires')
    b.add_argument('--open', action='store_true', help='open the city in your browser')
    b.add_argument('--json', action='store_true', help='also print health, impact and incidents as JSON')
    b.add_argument('--quiet', action='store_true')
    b.set_defaults(fn=cmd_build)

    s = sub.add_parser('serve', help='live city that rebuilds whenever files change')
    s.add_argument('dir', nargs='?', default='.')
    s.add_argument('--port', type=int, default=4321)
    s.add_argument('--base')
    s.add_argument('--no-open', action='store_true')
    s.set_defaults(fn=cmd_serve)

    p = sub.add_parser('pending', help='list files that still need a plain-English summary')
    p.add_argument('dir', nargs='?', default='.')
    p.add_argument('--limit', type=int, default=0)
    p.set_defaults(fn=cmd_pending)

    n = sub.add_parser('notes', help='merge a partial notes JSON into .vibecity/notes.json')
    n.add_argument('dir', nargs='?', default='.')
    n.add_argument('--merge', required=True)
    n.set_defaults(fn=cmd_notes)

    h = sub.add_parser('hook', help='Claude Code Stop hook: refresh an existing city quietly')
    h.set_defaults(fn=cmd_hook)

    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)  # live logs when run in the background
    except Exception:
        pass
    a.fn(a)


if __name__ == '__main__':
    main()
