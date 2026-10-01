"""Vibe City analysis — links raw scan facts into a city graph.

Resolves imports across files, connects front-end fetches to API routes,
spots external services, detects "disasters" and computes the blast radius
of uncommitted changes.
"""
import json
import os
import re
import subprocess
from collections import defaultdict, deque

from vc_scan import JS_EXTS, SFC_EXTS, pascal

RESOLVE_EXTS = ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.vue', '.svelte']

# package name (or prefix ending in '/') -> (id, label, kind)
SERVICES = {
    'stripe': ('stripe', 'Stripe', 'payments'), '@stripe/': ('stripe', 'Stripe', 'payments'),
    '@supabase/': ('supabase', 'Supabase', 'database'), 'supabase': ('supabase', 'Supabase', 'database'),
    'firebase': ('firebase', 'Firebase', 'database'), 'firebase/': ('firebase', 'Firebase', 'database'),
    'firebase-admin': ('firebase', 'Firebase', 'database'), 'firebase_admin': ('firebase', 'Firebase', 'database'),
    '@prisma/client': ('prisma', 'Database (Prisma)', 'database'),
    'mongoose': ('mongodb', 'MongoDB', 'database'), 'mongodb': ('mongodb', 'MongoDB', 'database'),
    'pymongo': ('mongodb', 'MongoDB', 'database'),
    'pg': ('postgres', 'Postgres', 'database'), 'postgres': ('postgres', 'Postgres', 'database'),
    '@neondatabase/': ('postgres', 'Postgres (Neon)', 'database'), '@vercel/postgres': ('postgres', 'Postgres', 'database'),
    'drizzle-orm': ('sql', 'SQL database (Drizzle)', 'database'), 'drizzle-orm/': ('sql', 'SQL database (Drizzle)', 'database'),
    'psycopg2': ('postgres', 'Postgres', 'database'), 'psycopg': ('postgres', 'Postgres', 'database'),
    'sqlalchemy': ('sql', 'SQL database', 'database'), 'sqlite3': ('sqlite', 'SQLite', 'database'),
    'better-sqlite3': ('sqlite', 'SQLite', 'database'), 'mysql2': ('mysql', 'MySQL', 'database'),
    'redis': ('redis', 'Redis', 'database'), 'ioredis': ('redis', 'Redis', 'database'),
    '@upstash/': ('redis', 'Upstash', 'database'), 'convex': ('convex', 'Convex', 'database'), 'convex/': ('convex', 'Convex', 'database'),
    'openai': ('openai', 'OpenAI', 'ai'), '@anthropic-ai/sdk': ('anthropic', 'Claude API', 'ai'),
    'anthropic': ('anthropic', 'Claude API', 'ai'), '@google/generative-ai': ('gemini', 'Gemini', 'ai'),
    '@google/genai': ('gemini', 'Gemini', 'ai'), '@ai-sdk/': ('ai-sdk', 'AI SDK', 'ai'), 'replicate': ('replicate', 'Replicate', 'ai'),
    'resend': ('resend', 'Resend email', 'email'), 'nodemailer': ('smtp', 'Email (SMTP)', 'email'),
    '@sendgrid/mail': ('sendgrid', 'SendGrid', 'email'), 'sendgrid': ('sendgrid', 'SendGrid', 'email'),
    'twilio': ('twilio', 'Twilio', 'messaging'),
    '@clerk/': ('clerk', 'Clerk auth', 'auth'), 'next-auth': ('authjs', 'Auth.js', 'auth'), 'next-auth/': ('authjs', 'Auth.js', 'auth'),
    '@auth/': ('authjs', 'Auth.js', 'auth'), '@auth0/': ('auth0', 'Auth0', 'auth'), '@kinde-oss/': ('kinde', 'Kinde auth', 'auth'),
    '@aws-sdk/': ('aws', 'AWS', 'cloud'), 'aws-sdk': ('aws', 'AWS', 'cloud'), 'boto3': ('aws', 'AWS', 'cloud'),
    'cloudinary': ('cloudinary', 'Cloudinary', 'storage'), 'uploadthing': ('uploadthing', 'UploadThing', 'storage'),
    'uploadthing/': ('uploadthing', 'UploadThing', 'storage'), '@vercel/blob': ('blob', 'Vercel Blob', 'storage'),
    'posthog-js': ('posthog', 'PostHog', 'analytics'), 'posthog-node': ('posthog', 'PostHog', 'analytics'),
    '@sentry/': ('sentry', 'Sentry', 'monitoring'), 'socket.io': ('realtime', 'Realtime (Socket.IO)', 'realtime'),
    'socket.io-client': ('realtime', 'Realtime (Socket.IO)', 'realtime'), 'pusher': ('pusher', 'Pusher', 'realtime'),
    'pusher-js': ('pusher', 'Pusher', 'realtime'), '@liveblocks/': ('liveblocks', 'Liveblocks', 'realtime'),
    'lemonsqueezy': ('lemonsqueezy', 'Lemon Squeezy', 'payments'), '@lemonsqueezy/': ('lemonsqueezy', 'Lemon Squeezy', 'payments'),
}

NEXT_ENTRY = re.compile(r'(^|/)(page|layout|template|loading|error|not-found|global-error|route|middleware|default|head|instrumentation|opengraph-image|sitemap|robots|manifest)\.(tsx?|jsx?|mjs)$')
MAIN_BASENAMES = {'main', 'index', 'app', 'server', '__main__', 'manage', 'wsgi', 'asgi', 'cli', 'root', 'entry', 'worker', '_app', '_document'}
HTTP_METHODS = ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS')


def service_for(spec, py=False):
    top = spec.split('.')[0] if py else spec
    if top in SERVICES:
        return SERVICES[top]
    for key, val in SERVICES.items():
        if key.endswith('/') and spec.startswith(key):
            return val
        if not py and spec.startswith(key + '/'):
            return val
    return None


# ---------------------------------------------------------------- resolution

def load_aliases(root):
    """Read compilerOptions.paths/baseUrl from tsconfig/jsconfig (JSONC tolerant)."""
    for name in ('tsconfig.json', 'jsconfig.json'):
        p = os.path.join(root, name)
        if not os.path.isfile(p):
            continue
        try:
            txt = open(p, encoding='utf-8').read()
            txt = re.sub(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*[\s\S]*?\*/', lambda m: m.group(1) or '', txt)
            txt = re.sub(r',(\s*[}\]])', r'\1', txt)
            co = json.loads(txt).get('compilerOptions', {})
        except Exception:
            continue
        base = co.get('baseUrl', '.')
        aliases = []
        for pat, targets in (co.get('paths') or {}).items():
            if targets:
                aliases.append((pat, os.path.normpath(os.path.join(base, targets[0])).replace(os.sep, '/')))
        return aliases, (base if 'baseUrl' in co else None)
    return [('@/*', 'src/*'), ('~/*', 'src/*')], None


class Resolver:
    def __init__(self, root, paths):
        self.root = root
        self.files = set(paths)
        self.aliases, self.base_url = load_aliases(root)
        self.py_modules = {}
        for p in paths:
            if p.endswith('.py'):
                mod = p[:-3].replace('/', '.')
                if mod.endswith('.__init__'):
                    mod = mod[:-9]
                self.py_modules.setdefault(mod, p)
                if mod.startswith('src.'):
                    self.py_modules.setdefault(mod[4:], p)
                if mod.startswith('app.'):
                    self.py_modules.setdefault(mod[4:], p)

    def _try(self, base):
        base = os.path.normpath(base).replace(os.sep, '/')
        if base.startswith('./'):
            base = base[2:]
        if base in self.files:
            return base
        stem, ext = os.path.splitext(base)
        if ext in ('.js', '.jsx', '.mjs', '.cjs'):  # TS ESM style: import './x.js' -> x.ts
            for e in ('.ts', '.tsx', '.mts'):
                if stem + e in self.files:
                    return stem + e
        for e in RESOLVE_EXTS:
            if base + e in self.files:
                return base + e
        for e in RESOLVE_EXTS:
            if base + '/index' + e in self.files:
                return base + '/index' + e
        return None

    def js(self, from_file, spec):
        """-> (resolved_path | None, is_local_spec)"""
        if spec.startswith('.'):
            return self._try(os.path.join(os.path.dirname(from_file), spec)), True
        for pat, target in self.aliases:
            if pat.endswith('*'):
                prefix = pat[:-1]
                if spec.startswith(prefix):
                    return self._try(target[:-1] + spec[len(prefix):] if target.endswith('*') else target), True
            elif spec == pat:
                return self._try(target), True
        if self.base_url is not None:
            hit = self._try(os.path.join(self.base_url, spec))
            if hit:
                return hit, True
        if spec.startswith('/'):
            return self._try(spec[1:]), True
        return None, False

    def py(self, from_file, spec, level, name=None):
        if level:
            parts = from_file.split('/')[:-1]
            if level > 1:
                parts = parts[:-(level - 1)] if level - 1 <= len(parts) else []
            mod = '.'.join(parts + ([spec] if spec else []))
        else:
            mod = spec
        if name and (mod + '.' + name) in self.py_modules:
            return self.py_modules[mod + '.' + name], True, True
        if mod in self.py_modules:
            return self.py_modules[mod], True, False
        return None, bool(level) or mod.split('.')[0] in {m.split('.')[0] for m in self.py_modules}, False


# ---------------------------------------------------------------- routes

def next_route_path(path):
    """src/app/api/cart/[id]/route.ts -> /api/cart/:id ; pages/api/x.ts -> /api/x"""
    parts = path.split('/')
    if 'app' in parts and re.match(r'route\.(tsx?|jsx?|mjs)$', parts[-1]):
        segs = parts[parts.index('app') + 1:-1]
    elif 'pages' in parts and 'api' in parts[parts.index('pages') + 1:parts.index('pages') + 2]:
        segs = parts[parts.index('pages') + 1:]
        segs[-1] = os.path.splitext(segs[-1])[0]
        if segs[-1] == 'index':
            segs = segs[:-1]
    else:
        return None
    out = []
    for s in segs:
        if s.startswith('(') and s.endswith(')') or s.startswith('@'):
            continue
        if s.startswith('[...') or s.startswith('[[...'):
            out.append('*')
        elif s.startswith('['):
            out.append(':' + s.strip('[]'))
        else:
            out.append(s)
    return '/' + '/'.join(out)


def norm_url(url):
    url = url.split('?')[0].split('#')[0]
    url = re.sub(r'^https?://(localhost|127\.0\.0\.1)(:\d+)?', '', url)
    url = re.sub(r'^\$\{\}(?=/)', '', url)  # `${API_BASE}/api/x`
    return url.replace('${}', ':p')


def route_matches(route_path, url):
    rs = [s for s in route_path.split('/') if s]
    us = [s for s in url.split('/') if s]
    for i, r in enumerate(rs):
        if r == '*':
            return True
        if i >= len(us):
            return False
        u = us[i]
        if r.startswith(':') or u.startswith(':') or ':p' in u or r == u:
            continue
        return False
    return len(rs) == len(us)


# ---------------------------------------------------------------- roles

def role_of(f):
    p = f['path'].lower()
    base = os.path.basename(p)
    if re.search(r'(^|/)(__tests__|tests?|spec|e2e|cypress|playwright)/', p) or re.search(r'\.(test|spec|stories)\.', base) \
            or base.startswith('test_') or base == 'conftest.py':
        return 'test'
    if re.search(r'\.config\.[cm]?[jt]s$', base) or base in ('settings.py', 'config.py', 'conf.py', 'env.ts', 'env.js', 'env.mjs'):
        return 'config'
    if any(s.get('route') for s in f['symbols']) or re.search(r'(^|/)(api|server|routes|controllers|handlers|functions|backend|endpoints)/', p) \
            or re.match(r'middleware\.[jt]s$', base) or f.get('serverFramework'):
        return 'api'
    if f.get('hasJsx') or os.path.splitext(p)[1] in SFC_EXTS:
        return 'ui'
    if f.get('_services_kinds', set()) & {'database', 'storage'} or any(s.get('tables') for s in f['symbols']) or \
            re.search(r'(^|/)(db|database|models?|schemas?|prisma|supabase|store|stores|repositories|repository|data|dal)(/|\.|$)', p):
        return 'data'
    return 'logic'


def is_entry(f):
    p = f['path']
    base = os.path.splitext(os.path.basename(p))[0]
    return bool(
        NEXT_ENTRY.search(p) or re.search(r'(^|/)(pages|routes)/', p) or base.startswith('+')
        or base in MAIN_BASENAMES or base.lower() in MAIN_BASENAMES or f['role'] in ('test', 'config')
        or f.get('isMain') or any(s.get('route') for s in f['symbols'])
        or re.match(r'(scripts|bin|tools|migrations|seeds?)/', p) or p.count('/') == 0
    )


# ---------------------------------------------------------------- main

def build_graph(root, files, notes=None, checks=None):
    notes = notes or {}
    checks = checks or []
    R = Resolver(root, [f['path'] for f in files])
    by_path = {f['path']: f for f in files}
    sym_index = {}  # id -> (file, sym)
    for f in files:
        for s in f['symbols']:
            s['id'] = f['path'] + '#' + s['name']
            sym_index[s['id']] = (f, s)

    incidents = []

    def incident(kind, f, msg, line=None, sym=None, source='scan'):
        incidents.append({'type': kind, 'file': f['path'] if isinstance(f, dict) else f,
                          'symbol': sym, 'line': line, 'message': msg, 'source': source})

    # -- imports
    file_edges = []           # (from_path, to_path, kind)
    externals = {}            # id -> {id,label,kind,tables:set,users:set}
    for f in files:
        f['_imap'] = {}       # local -> ('file', path, name) | ('ext', ext_id)
        f['_services_kinds'] = set()
        f['_reexp'] = []
        py = f['lang'] == 'py'
        for imp in f['imports']:
            if py:
                names = imp['names']
                if imp.get('asname') is not None or (not imp.get('level') and len(names) == 1 and list(names.values())[0] == '*'):
                    target, local_spec, _ = R.py(f['path'], imp['spec'], 0)
                    svc = service_for(imp['spec'], py=True)
                    for local in names:
                        if target:
                            f['_imap'][local] = ('file', target, '*')
                        elif svc:
                            f['_imap'][local] = ('ext', svc[0])
                    if target:
                        file_edges.append((f['path'], target, 'static'))
                    elif svc:
                        externals.setdefault(svc[0], {'id': svc[0], 'label': svc[1], 'kind': svc[2], 'tables': set(), 'users': set()})
                        f['_services_kinds'].add(svc[2])
                    continue
                svc = service_for(imp['spec'], py=True) if not imp.get('level') else None
                any_hit = False
                for local, name in names.items():
                    target, local_spec, is_submodule = R.py(f['path'], imp['spec'], imp.get('level', 0), name)
                    if target:
                        any_hit = True
                        f['_imap'][local] = ('file', target, '*' if is_submodule else name)
                        file_edges.append((f['path'], target, 'static'))
                    elif svc:
                        f['_imap'][local] = ('ext', svc[0])
                if not any_hit and svc:
                    externals.setdefault(svc[0], {'id': svc[0], 'label': svc[1], 'kind': svc[2], 'tables': set(), 'users': set()})
                    f['_services_kinds'].add(svc[2])
                elif not any_hit and imp.get('level'):
                    incident('broken', f, "Import from '%s%s' points at a module that doesn't exist" % ('.' * imp['level'], imp['spec']), imp['line'])
                continue
            target, is_local = R.js(f['path'], imp['spec'])
            if target:
                file_edges.append((f['path'], target, imp['kind']))
                for local, name in imp['names'].items():
                    f['_imap'][local] = ('file', target, name)
            elif is_local:
                incident('broken', f, "Import '%s' points at a file that doesn't exist" % imp['spec'], imp['line'])
            else:
                svc = service_for(imp['spec'])
                if svc and imp['kind'] != 'type':
                    ext = externals.setdefault(svc[0], {'id': svc[0], 'label': svc[1], 'kind': svc[2], 'tables': set(), 'users': set()})
                    f['_services_kinds'].add(svc[2])
                    for local in imp['names']:
                        f['_imap'][local] = ('ext', svc[0])
        for rx in f.get('reexports', []):
            target, _ = R.js(f['path'], rx['spec'])
            if target:
                f['_reexp'].append((target, rx['names']))

    def resolve_export(path, name, depth=0):
        f = by_path.get(path)
        if not f or depth > 4:
            return None
        if name == '*':
            return None
        for s in f['symbols']:
            if name in s['exportNames'] or (f['lang'] == 'py' and s['name'] == name):
                return s['id']
        if name == 'default':
            for s in f['symbols']:
                if s['kind'] == 'component' and s['exported']:
                    return s['id']
        for target, names in f['_reexp']:
            if names == '*':
                hit = resolve_export(target, name, depth + 1)
                if hit:
                    return hit
            elif name in names:
                hit = resolve_export(target, names[name], depth + 1)
                if hit:
                    return hit
        local = f['_imap'].get(name)  # `import x from ...; export { x }`
        if local and local[0] == 'file':
            return resolve_export(local[1], local[2], depth + 1)
        return None

    # -- route mounts (express app.use('/api', router))
    for f in files:
        for mnt in f['mounts']:
            local = f['_imap'].get(mnt['ident'])
            if local and local[0] == 'file':
                tf = by_path.get(local[1])
                for s in (tf['symbols'] if tf else []):
                    if s.get('route') and not s['route'].get('_mounted'):
                        s['route']['path'] = ('/' + mnt['prefix'].strip('/') + '/' + s['route']['path'].strip('/')).rstrip('/') or '/'
                        s['route']['_mounted'] = True
                        s['name'] = '%s %s' % (s['route']['method'], s['route']['path'])

    # -- Next.js route handlers
    for f in files:
        rp = next_route_path(f['path'])
        if not rp:
            continue
        for s in f['symbols']:
            if s['name'] in HTTP_METHODS and s['exported']:
                s['kind'] = 'route'
                s['route'] = {'method': s['name'], 'path': rp}
            elif '/pages/' in '/' + f['path'] and 'default' in s['exportNames']:
                s['kind'] = 'route'
                s['route'] = {'method': 'ANY', 'path': rp}

    routes = [(s['route'], s['id'], f) for f in files for s in f['symbols'] if s.get('route')]

    # -- roles (need service kinds first)
    for f in files:
        f['role'] = role_of(f)

    # -- symbol edges
    edges = {}

    def edge(a, b, kind, label=None):
        if a == b:
            return
        key = (a, b)
        prio = ['import', 'use', 'call', 'render', 'service', 'fetch']
        if key in edges and prio.index(edges[key]['type']) >= prio.index(kind):
            return
        edges[key] = {'from': a, 'to': b, 'type': kind}
        if label:
            edges[key]['label'] = label

    for f in files:
        local_syms = {s['name']: s for s in f['symbols']}
        for s in f['symbols']:
            calls, jsx = set(s['calls']), set(s['jsx'])
            members = defaultdict(set)
            for base, attr in s['members']:
                members[base].add(attr)
            for r in s['refs']:
                if r == s['name']:
                    continue
                kind = 'render' if r in jsx else ('call' if r in calls else 'use')
                if r in local_syms and local_syms[r] is not s:
                    edge(s['id'], local_syms[r]['id'], kind)
                elif r in f['_imap']:
                    ent = f['_imap'][r]
                    if ent[0] == 'ext':
                        edge(s['id'], 'ext:' + ent[1], 'service', None)
                        externals[ent[1]]['users'].add(s['id'])
                    elif ent[2] == '*':
                        for attr in members.get(r, ()):
                            hit = resolve_export(ent[1], attr)
                            if hit:
                                edge(s['id'], hit, 'call')
                    else:
                        hit = resolve_export(ent[1], ent[2])
                        if hit:
                            edge(s['id'], hit, kind)
            # front-end → API route
            for ft in s['fetches']:
                url = norm_url(ft['url'])
                if url.startswith('http'):
                    host = re.sub(r'^https?://', '', url).split('/')[0]
                    if host and '${}' not in host and ':p' not in host:
                        eid = 'host:' + host
                        externals.setdefault(eid, {'id': eid, 'label': host, 'kind': 'web', 'tables': set(), 'users': set()})
                        externals[eid]['users'].add(s['id'])
                        edge(s['id'], 'ext:' + eid, 'service', '%s %s' % (ft['method'], host))
                    continue
                best = None
                for rt, rid, rf in routes:
                    if route_matches(rt['path'], url):
                        score = 2 if rt['method'] == ft['method'] else (1 if rt['method'] == 'ANY' else 0)
                        if best is None or score > best[0]:
                            best = (score, rid, rt)
                if best and best[0] > 0:
                    ft['target'] = best[1]
                    edge(s['id'], best[1], 'fetch', '%s %s' % (ft['method'], url.replace(':p', '…')))
                elif best:
                    ft['target'] = best[1]
                    edge(s['id'], best[1], 'fetch', '%s %s (method mismatch?)' % (ft['method'], url))

    # attach tables to the database service the symbol talks to (directly or one hop away)
    sym_out = defaultdict(set)
    for (a, b) in edges:
        sym_out[a].add(b)
    for f in files:
        for s in f['symbols']:
            if not s['tables']:
                continue
            targets = set(sym_out[s['id']])
            for t in list(targets):
                targets |= sym_out.get(t, set())
            for t in targets:
                if t.startswith('ext:') and externals.get(t[4:], {}).get('kind') == 'database':
                    externals[t[4:]]['tables'].update(s['tables'])

    # -- file graph: incoming refs (for ghosts) & cycles (gridlock)
    incoming = defaultdict(set)
    for a, b, kind in file_edges:
        if a != b:
            incoming[b].add(a)
    for (a, b) in edges:
        fa, fb = a.split('#')[0], b.split('#')[0]
        if not b.startswith('ext:') and fa != fb:
            incoming[fb].add(fa)

    graph = defaultdict(set)
    for a, b, kind in file_edges:
        if kind == 'static' and a != b:
            graph[a].add(b)
    for comp in _sccs(graph):
        if len(comp) > 1:
            names = sorted(comp)
            for p in names:
                others = [os.path.basename(x) for x in names if x != p]
                incident('gridlock', p, 'Circular import with %s — these files depend on each other in a loop' % ', '.join(others[:3]))

    for f in files:
        f['entry'] = is_entry(f)
        if f['syntax']:
            incident('fire', f, f['syntax'], f.get('syntaxLine'))
        if f.get('scanError'):
            incident('fire', f, 'Could not read this file: ' + f['scanError'])
        for t in f['todos']:
            incident('construction', f, '%s: %s' % (t['tag'], t['text'] or '(no details)'), t['line'])
        for sc in f['secrets']:
            incident('toxic', f, '%s hard-coded in source (%s) — move it to an env variable' % (sc['label'], sc['preview']), sc['line'])
        if f['useClient']:
            for v in f['env']:
                if not v.startswith('NEXT_PUBLIC_'):
                    incident('toxic', f, "Browser code reads secret env var %s — it will be undefined in the browser (or leak if you rename it NEXT_PUBLIC_)" % v)
        if not f['entry'] and not incoming.get(f['path']) and f['symbols']:
            incident('ghost', f, 'Nothing imports this file — it may be dead code')

    for c in checks:
        incident('fire', c['file'], c['message'], c.get('line'), source=c.get('source', 'check'))

    for inc in (notes.get('incidents') or []):
        if inc.get('file') in by_path and inc.get('type'):
            incidents.append({'type': inc['type'], 'file': inc['file'], 'symbol': inc.get('symbol'),
                              'line': inc.get('line'), 'message': inc.get('message', ''), 'source': 'claude'})

    # attach incident → symbol by line
    for inc in incidents:
        f = by_path.get(inc['file'])
        if f and inc['line'] and not inc['symbol']:
            for s in f['symbols']:
                if s['line'] <= inc['line'] <= s['endLine']:
                    inc['symbol'] = s['name']
                    break

    return {
        'files': files, 'edges': list(edges.values()), 'fileEdges': file_edges,
        'externals': externals, 'incidents': incidents,
    }


def _sccs(graph):
    index, low, on, stack, out = {}, {}, set(), [], []
    counter = [0]
    nodes = set(graph) | {b for v in graph.values() for b in v}

    def strong(v):
        work = [(v, iter(graph.get(v, ())))]
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        while work:
            node, it = work[-1]
            pushed = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter[0]
                    counter[0] += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(graph.get(w, ()))))
                    pushed = True
                    break
                elif w in on:
                    low[node] = min(low[node], index[w])
            if pushed:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                out.append(comp)

    for v in sorted(nodes):
        if v not in index:
            strong(v)
    return out


# ---------------------------------------------------------------- checks

ERR_LINE = re.compile(r'((?:[A-Za-z]:)?[\w./\\@\-\[\]()+]+\.(?:tsx?|jsx?|mjs|cjs|py|vue|svelte))(?:[:(](\d+))?')
PY_TB = re.compile(r'File "([^"]+)", line (\d+)')


def parse_errors(root, text, paths, source='check'):
    """Map any `path:line` / `path(line,col)` / Python traceback mention onto known files."""
    known = set(paths)
    root_abs = os.path.abspath(root).replace(os.sep, '/') + '/'
    out, seen = [], set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or not re.search(r'error|Error|ERR|failed|FAIL|Traceback|✕|×|exception|Exception', line + ' ' + raw):
            if not PY_TB.search(line):
                continue
        hits = [(m.group(1), m.group(2)) for m in PY_TB.finditer(line)] or \
               [(m.group(1), m.group(2)) for m in ERR_LINE.finditer(line)]
        for p, ln in hits:
            p = p.replace('\\', '/')
            if p.startswith(root_abs):
                p = p[len(root_abs):]
            p = re.sub(r'^\./', '', p)
            if p not in known:
                cands = [k for k in known if k.endswith('/' + p) or p.endswith('/' + k)]
                if len(cands) != 1:
                    continue
                p = cands[0]
            key = (p, ln, line[:80])
            if key in seen:
                continue
            seen.add(key)
            msg = re.sub(r'\s+', ' ', line)[:220]
            out.append({'file': p, 'line': int(ln) if ln else None, 'message': msg, 'source': source})
    return out[:300]


def run_checks(root, paths, check_cmd=None):
    """Run the project's own type checker / tests and turn failures into fires."""
    results = []
    cmds = []
    if check_cmd:
        cmds.append(check_cmd)
    else:
        tsc = os.path.join(root, 'node_modules', '.bin', 'tsc')
        if os.path.exists(tsc) and os.path.exists(os.path.join(root, 'tsconfig.json')):
            cmds.append('"%s" --noEmit --pretty false -p .' % tsc)
    for cmd in cmds:
        try:
            p = subprocess.run(cmd, shell=True, cwd=root, capture_output=True, text=True, timeout=300)
            results += parse_errors(root, p.stdout + '\n' + p.stderr, paths, source=cmd.split()[0].strip('"').split('/')[-1])
        except Exception as e:
            print('[vibe-city] check command failed: %s' % e)
    return results


# ---------------------------------------------------------------- impact

def git(root, *args):
    try:
        p = subprocess.run(['git', '-C', root] + list(args), capture_output=True, text=True, timeout=30)
        return p.stdout if p.returncode == 0 else None
    except Exception:
        return None


def compute_impact(root, city, base=None):
    if git(root, 'rev-parse', '--is-inside-work-tree') is None:
        return None
    has_head = git(root, 'rev-parse', '--verify', 'HEAD') is not None
    ref = base or ('HEAD' if has_head else None)
    by_path = {f['path']: f for f in city['files']}
    changed_lines = defaultdict(list)  # path -> [(a,b)] ; [] means whole file
    whole = set()
    if ref:
        diff = git(root, 'diff', '-U0', '--relative', '--no-color', ref, '--', '.') or ''
        cur = None
        for line in diff.splitlines():
            if line.startswith('+++ '):
                p = line[4:]
                cur = p[2:] if p.startswith('b/') else None
            elif line.startswith('@@') and cur:
                m = re.search(r'\+(\d+)(?:,(\d+))?', line)
                if m:
                    a = int(m.group(1))
                    cnt = int(m.group(2)) if m.group(2) is not None else 1
                    changed_lines[cur].append((a, a + max(cnt, 1) - 1))
    else:
        for f in city['files']:
            whole.add(f['path'])
    untracked = git(root, 'ls-files', '--others', '--exclude-standard') or ''
    for p in untracked.splitlines():
        whole.add(p.strip())

    changed_files = sorted((set(changed_lines) | whole) & set(by_path))
    if not changed_files:
        return {'base': ref or '(no commits)', 'changedFiles': [], 'changedFloors': [], 'blast': {}}
    changed_floors = set()
    for p in changed_files:
        f = by_path[p]
        if p in whole:
            changed_floors.update(s['id'] for s in f['symbols'])
            continue
        hit = False
        for s in f['symbols']:
            for a, b in changed_lines[p]:
                if a <= s['endLine'] and b >= s['line']:
                    changed_floors.add(s['id'])
                    hit = True
        if not hit:  # imports/top-level tweak: treat exported API as touched
            changed_floors.update(s['id'] for s in f['symbols'] if s['exported'])

    rev = defaultdict(set)
    for e in city['edges']:
        rev[e['to']].add(e['from'])
    rev_files = defaultdict(set)
    for a, b, kind in city['fileEdges']:
        rev_files[b].add(a)

    blast = {}
    q = deque((x, 0) for x in changed_floors)
    seen = set(changed_floors)
    while q:
        node, d = q.popleft()
        if d >= 6:
            continue
        for src in rev.get(node, ()):
            if src not in seen:
                seen.add(src)
                blast[src] = d + 1
                q.append((src, d + 1))
    # files whose changes map to no floors still shake their importers
    for p in changed_files:
        if not by_path[p]['symbols']:
            for imp in rev_files.get(p, ()):
                for s in by_path.get(imp, {}).get('symbols', []):
                    blast.setdefault(s['id'], 1)
    for x in changed_floors:
        blast.pop(x, None)
    return {'base': ref or '(no commits)', 'changedFiles': changed_files,
            'changedFloors': sorted(changed_floors), 'blast': blast}


# ---------------------------------------------------------------- health

WEIGHTS = {'fire': 15, 'toxic': 12, 'broken': 10, 'gridlock': 5, 'ghost': 2, 'construction': 1}


def health(incidents):
    counts = defaultdict(int)
    for i in incidents:
        counts[i['type']] += 1
    penalty = 0
    for k, w in WEIGHTS.items():
        n = counts.get(k, 0)
        penalty += min(n * w, 12 if k == 'construction' else (16 if k == 'ghost' else 60))
    score = max(0, 100 - penalty)
    if counts.get('fire'):
        weather = ('🔥', 'City on fire')
    elif score >= 90:
        weather = ('☀️', 'Sunny skies')
    elif score >= 75:
        weather = ('⛅', 'A few clouds')
    elif score >= 50:
        weather = ('🌧️', 'Stormy')
    else:
        weather = ('🌪️', 'Disaster zone')
    return {'score': score, 'icon': weather[0], 'weather': weather[1], 'counts': dict(counts)}
