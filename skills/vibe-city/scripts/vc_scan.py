"""Vibe City scanner — turns source files into raw facts.

Stdlib only. JS/TS/JSX/TSX/Vue/Svelte are read with a lightweight masking
tokenizer (strings and comments blanked out, then structure found with
regexes + bracket matching). Python is read with the real `ast` module.
"""
import ast
import hashlib
import os
import re
import subprocess
from bisect import bisect_right

JS_EXTS = {'.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs'}
SFC_EXTS = {'.vue', '.svelte'}
PY_EXTS = {'.py'}
CODE_EXTS = JS_EXTS | SFC_EXTS | PY_EXTS

SKIP_DIRS = {
    'node_modules', '.git', '.next', '.nuxt', '.svelte-kit', 'dist', 'build', 'out',
    'coverage', '.vibecity', '.venv', 'venv', 'env', '__pycache__', '.turbo', '.vercel',
    '.cache', '.output', 'vendor', '.expo', '.idea', '.vscode', 'target', '.parcel-cache',
    'storybook-static', '.pytest_cache', '.mypy_cache', 'site-packages',
}
MAX_BYTES = 400_000
MAX_FILES = 3000

JS_KEYWORDS = {
    'if', 'for', 'while', 'switch', 'catch', 'function', 'return', 'typeof', 'new', 'await',
    'import', 'super', 'this', 'async', 'yield', 'void', 'delete', 'in', 'of', 'instanceof',
    'require', 'const', 'let', 'var', 'else', 'do', 'try', 'finally', 'throw', 'case',
    'default', 'break', 'continue', 'class', 'extends', 'export', 'from', 'as', 'true',
    'false', 'null', 'undefined', 'with', 'type', 'interface', 'enum', 'implements',
    'static', 'get', 'set', 'public', 'private', 'protected', 'readonly', 'declare',
    'keyof', 'satisfies', 'is', 'any', 'string', 'number', 'boolean', 'never', 'unknown',
}

SECRET_PATTERNS = [
    (re.compile(r'sk_live_[0-9A-Za-z]{10,}'), 'Stripe live secret key'),
    (re.compile(r'sk_test_[0-9A-Za-z]{10,}'), 'Stripe test secret key'),
    (re.compile(r'sk-ant-[0-9A-Za-z_\-]{20,}'), 'Anthropic API key'),
    (re.compile(r'sk-(?:proj-)?[0-9A-Za-z_\-]{20,}'), 'OpenAI-style API key'),
    (re.compile(r'AKIA[0-9A-Z]{16}'), 'AWS access key'),
    (re.compile(r'gh[pousr]_[0-9A-Za-z]{30,}'), 'GitHub token'),
    (re.compile(r'xox[abpr]-[0-9A-Za-z\-]{10,}'), 'Slack token'),
    (re.compile(r'AIza[0-9A-Za-z_\-]{35}'), 'Google API key'),
    (re.compile(r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----'), 'Private key'),
]

TODO_RE = re.compile(r'\b(TODO|FIXME|HACK|XXX|BUG)\b[:\s-]*(.{0,90})')


# ---------------------------------------------------------------- files

def list_files(root):
    files = None
    try:
        out = subprocess.run(['git', '-C', root, 'ls-files', '-co', '--exclude-standard'],
                             capture_output=True, text=True, timeout=20)
        if out.returncode == 0:
            files = [f for f in out.stdout.splitlines() if f]
    except Exception:
        files = None
    if files is None:
        files = []
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith('.')]
            for fn in fns:
                files.append(os.path.relpath(os.path.join(dp, fn), root))
    res = []
    for f in files:
        f = f.replace(os.sep, '/')
        parts = f.split('/')
        if any(p in SKIP_DIRS for p in parts[:-1]):
            continue
        ext = os.path.splitext(f)[1].lower()
        if ext not in CODE_EXTS or f.endswith('.d.ts') or '.min.' in f:
            continue
        full = os.path.join(root, f)
        try:
            if not os.path.isfile(full) or os.path.getsize(full) > MAX_BYTES:
                continue
        except OSError:
            continue
        res.append(f)
    res.sort()
    return res[:MAX_FILES]


class Lines:
    def __init__(self, src):
        self.starts = [0] + [m.end() for m in re.finditer('\n', src)]

    def at(self, pos):
        return bisect_right(self.starts, pos)


def file_hash(src):
    return hashlib.sha1(src.encode('utf-8', 'replace')).hexdigest()[:12]


def count_loc(src):
    return sum(1 for ln in src.splitlines() if ln.strip())


def pascal(name):
    parts = re.split(r'[^A-Za-z0-9]+', name)
    return ''.join(p[:1].upper() + p[1:] for p in parts if p) or 'Module'


# ---------------------------------------------------------------- JS masking

REGEX_PREV = set('(,=:[!&|?{};+-*%<>~^')
REGEX_PREV_WORDS = {'return', 'typeof', 'case', 'do', 'else', 'in', 'of', 'yield', 'await',
                    'instanceof', 'new', 'delete', 'void', 'throw'}


def mask_js(src):
    """Blank out string/comment/regex contents (keeping offsets and newlines).

    Returns (masked, strings, comments). strings maps the opening-quote offset
    to (content, quote, closing_offset); template `${...}` parts become `${}`.
    """
    n = len(src)
    out = list(src)
    strings = {}
    comments = []

    def blank(a, b):
        for k in range(a, min(b, n)):
            if out[k] != '\n':
                out[k] = ' '

    last, lastword = '', ''
    i = 0
    while i < n:
        c = src[i]
        nx = src[i + 1] if i + 1 < n else ''
        if c == '/' and nx == '/':
            j = src.find('\n', i)
            j = n if j < 0 else j
            comments.append((i, src[i:j]))
            blank(i, j)
            i = j
            continue
        if c == '/' and nx == '*':
            j = src.find('*/', i + 2)
            j = n if j < 0 else j + 2
            comments.append((i, src[i:j]))
            blank(i, j)
            i = j
            continue
        if c in '\'"':
            if i > 0 and src[i - 1].isalnum():  # apostrophe in prose (JSX text)
                i += 1
                continue
            j = i + 1
            while j < n and src[j] != c and src[j] != '\n':
                j += 2 if src[j] == '\\' else 1
            j = min(j, n)
            strings[i] = (src[i + 1:j], c, j)
            blank(i + 1, j)
            i = j + 1
            last, lastword = '"', ''
            continue
        if c == '`':
            j = i + 1
            seg = j
            parts = []
            while j < n and src[j] != '`':
                if src[j] == '\\':
                    j += 2
                    continue
                if src[j] == '$' and j + 1 < n and src[j + 1] == '{':
                    parts.append(src[seg:j])
                    blank(seg, j)
                    d, k = 0, j + 1
                    while k < n:
                        if src[k] == '{':
                            d += 1
                        elif src[k] == '}':
                            d -= 1
                            if d == 0:
                                break
                        k += 1
                    parts.append('${}')
                    j = k + 1
                    seg = j
                    continue
                j += 1
            j = min(j, n)
            parts.append(src[seg:j])
            blank(seg, j)
            strings[i] = (''.join(parts), '`', j)
            i = j + 1
            last, lastword = '"', ''
            continue
        if c == '/':
            prev_imm = src[i - 1] if i > 0 else ''
            if (last == '' or last in REGEX_PREV or lastword in REGEX_PREV_WORDS) \
                    and nx != '>' and prev_imm != '<':
                j, cls = i + 1, False
                while j < n and src[j] != '\n':
                    ch = src[j]
                    if ch == '\\':
                        j += 2
                        continue
                    if ch == '[':
                        cls = True
                    elif ch == ']':
                        cls = False
                    elif ch == '/' and not cls:
                        break
                    j += 1
                if j < n and src[j] == '/':
                    blank(i + 1, j)
                    i = j + 1
                    while i < n and src[i].isalpha():
                        i += 1
                    last, lastword = 'a', ''
                    continue
        if not c.isspace():
            if c.isalnum() or c in '_$':
                j = i
                while j < n and (src[j].isalnum() or src[j] in '_$'):
                    j += 1
                lastword = src[i:j]
                last = 'a'
                i = j
                continue
            last, lastword = c, ''
        i += 1
    return ''.join(out), strings, comments


def depth_array(masked):
    arr = [0] * (len(masked) + 1)
    d = 0
    for i, ch in enumerate(masked):
        arr[i] = d
        if ch in '([{':
            d += 1
        elif ch in ')]}':
            d = d - 1 if d > 0 else 0
    arr[len(masked)] = d
    return arr


PAIRS = {'(': ')', '[': ']', '{': '}'}


def match_close(masked, open_idx):
    o = masked[open_idx]
    c = PAIRS[o]
    d = 0
    for i in range(open_idx, len(masked)):
        ch = masked[i]
        if ch == o:
            d += 1
        elif ch == c:
            d -= 1
            if d == 0:
                return i
    return len(masked) - 1


CONT_END = set('=,(+-*/?:&|.[{<>!%^~')
CONT_START = set('.?:+-*/&|)]},=>')


def stmt_end(masked, strings, start):
    d, i, n = 0, start, len(masked)
    while i < n:
        if i in strings:
            i = strings[i][2] + 1
            continue
        ch = masked[i]
        if ch in '([{':
            d += 1
        elif ch in ')]}':
            d -= 1
            if d < 0:
                return i
        elif ch == ';' and d == 0:
            return i + 1
        elif ch == '\n' and d == 0:
            k = i - 1
            while k >= start and masked[k] in ' \t\r':
                k -= 1
            prevc = masked[k] if k >= start else '='
            m = i + 1
            while m < n and masked[m] in ' \t\r\n':
                m += 1
            nextc = masked[m] if m < n else ''
            if prevc not in CONT_END and nextc not in CONT_START:
                return i
        i += 1
    return n


def string_after(masked, strings, pos):
    """The string literal starting at the first non-space char at/after pos."""
    n = len(masked)
    while pos < n and masked[pos] in ' \t\r\n':
        pos += 1
    if pos in strings:
        return strings[pos][0]
    return None


# ---------------------------------------------------------------- JS scan

RE_FUNC = re.compile(r'\b(export\s+)?(default\s+)?(async\s+)?function\b\s*\*?\s*([A-Za-z_$][\w$]*)?\s*(?:<[^>{(]*>)?\s*\(')
RE_VAR = re.compile(r'\b(export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=;]+?)?=(?![=>])\s*')
RE_CLASS = re.compile(r'\b(export\s+)?(default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)')
RE_EXPORTS_ASSIGN = re.compile(r'\b(?:module\.)?exports\.([A-Za-z_$][\w$]*)\s*=(?!=)\s*')
RE_MODULE_EXPORTS = re.compile(r'\bmodule\.exports\s*=\s*')
RE_EXPORT_DEFAULT = re.compile(r'\bexport\s+default\s+')
RE_EXPORT_LIST = re.compile(r'\bexport\s*\{([^}]*)\}')
RE_ROUTE_CALL = re.compile(r'\b([A-Za-z_$][\w$]*)\.(get|post|put|patch|delete|all|use|options|head|route)\s*\(')
RE_IMPORT = re.compile(r'\bimport\s+(type\s+)?([\w$*{}\s,]+?)\s+from\s*(?=[\'"])')
RE_IMPORT_BARE = re.compile(r'\bimport\s*(?=[\'"])')
RE_IMPORT_DYN = re.compile(r'\bimport\s*\(\s*')
RE_REQUIRE = re.compile(r'(?:\b(?:const|let|var)\s+(\{[^}]*\}|[A-Za-z_$][\w$]*)\s*=\s*)?\brequire\s*\(\s*')
RE_EXPORT_FROM = re.compile(r'\bexport\s+(type\s+)?(\*(?:\s+as\s+[\w$]+)?|\{[^}]*\})\s*from\s*(?=[\'"])')

RE_CALL = re.compile(r'(?<![\w$.])(new\s+)?([A-Za-z_$][\w$]*)\s*(?:<[^<>()]*>)?\s*\(')
RE_MEMBER = re.compile(r'(?<![\w$.])([A-Za-z_$][\w$]*)\s*\??\.\s*([A-Za-z_$][\w$]*)')
RE_IDENT = re.compile(r'(?<![\w$.])([A-Za-z_$][\w$]*)')
RE_JSX = re.compile(r'(?<![\w$])<([A-Z][\w$]*(?:\.[A-Z][\w$]*)?)(?=[\s/>])')
RE_EVENT = re.compile(r'\b(on[A-Z]\w*)\s*=\s*\{')
RE_ENV = re.compile(r'\b(?:process\.env|import\.meta\.env)\.([A-Za-z_][A-Za-z0-9_]*)')
RE_FETCH = re.compile(r'(?<![\w$.])(fetch|\$fetch|axios|useSWR|useSWRImmutable|useSWRMutation)\s*(?:<[^<>()]*>)?\s*\(')
RE_HTTP_MEMBER = re.compile(r'(?<![\w$.])([A-Za-z_$][\w$]*)\.(get|post|put|patch|delete)\s*(?:<[^<>()]*>)?\s*\(')
RE_FROM_TABLE = re.compile(r'(?<![\w$])([A-Za-z_$][\w$]*)?\s*\.\s*from\s*\(')
RE_PRISMA = re.compile(r'\b(?:prisma|db)\.([a-z][A-Za-z0-9_]*)\.(?:find|create|update|delete|upsert|count|aggregate|groupBy)')
RE_METHOD = re.compile(r'\bmethod\s*:\s*')

SERVER_FRAMEWORKS = {'express', 'hono', 'fastify', 'koa', '@koa/router', 'koa-router', 'elysia', 'itty-router', 'polka'}
HTTP_CLIENTS = {'axios', 'ky', 'api', 'http', 'client', 'apiClient', 'request', 'instance', 'got', 'superagent'}
EVENT_NOISE = {'preventDefault', 'stopPropagation', 'persist'}


def _parse_named(clause):
    """'{ a, b as c, type D }' -> {local: imported}"""
    res = {}
    for part in clause.strip().strip('{}').split(','):
        part = part.strip()
        if not part:
            continue
        part = re.sub(r'^type\s+', '', part)
        m = re.match(r'([\w$]+)(?:\s+as\s+([\w$]+))?$', part)
        if m:
            res[m.group(2) or m.group(1)] = m.group(1)
    return res


def _js_imports(masked, strings, lines):
    imports = []
    for m in RE_IMPORT.finditer(masked):
        spec = string_after(masked, strings, m.end())
        if spec is None:
            continue
        clause = m.group(2).strip()
        names = {}
        mm = re.match(r'([\w$]+)?\s*,?\s*(\*\s+as\s+([\w$]+)|\{[^}]*\})?$', clause)
        if mm:
            if mm.group(1):
                names[mm.group(1)] = 'default'
            if mm.group(3):
                names[mm.group(3)] = '*'
            elif mm.group(2):
                names.update(_parse_named(mm.group(2)))
        imports.append({'spec': spec, 'names': names, 'line': lines.at(m.start()),
                        'kind': 'type' if m.group(1) else 'static'})
    for m in RE_IMPORT_BARE.finditer(masked):
        spec = string_after(masked, strings, m.end())
        if spec is not None:
            imports.append({'spec': spec, 'names': {}, 'line': lines.at(m.start()), 'kind': 'static'})
    for m in RE_IMPORT_DYN.finditer(masked):
        spec = string_after(masked, strings, m.end())
        if spec is not None:
            imports.append({'spec': spec, 'names': {}, 'line': lines.at(m.start()), 'kind': 'dynamic'})
    for m in RE_REQUIRE.finditer(masked):
        spec = string_after(masked, strings, m.end())
        if spec is None:
            continue
        names = {}
        lhs = m.group(1)
        if lhs:
            if lhs.startswith('{'):
                names = {k: v for k, v in (
                    (p.split(':')[-1].strip(), p.split(':')[0].strip()) for p in lhs.strip('{}').split(',') if p.strip())}
            else:
                names[lhs] = '*'
        imports.append({'spec': spec, 'names': names, 'line': lines.at(m.start()), 'kind': 'static'})
    reexports = []
    for m in RE_EXPORT_FROM.finditer(masked):
        spec = string_after(masked, strings, m.end())
        if spec is None:
            continue
        what = m.group(2)
        if what.startswith('*'):
            alias = re.match(r'\*\s+as\s+([\w$]+)', what)
            reexports.append({'spec': spec, 'names': {alias.group(1): '*'} if alias else '*'})
        else:
            reexports.append({'spec': spec, 'names': _parse_named(what)})
        imports.append({'spec': spec, 'names': {}, 'line': lines.at(m.start()),
                        'kind': 'type' if m.group(1) else 'static'})
    return imports, reexports


def _is_fn_init(masked, pos):
    t = masked[pos:pos + 400].lstrip()
    if re.match(r'(async\s+)?function\b', t):
        return True
    if re.match(r'(async\s*)?(<[^>]*>\s*)?\([^()]*(\([^()]*\)[^()]*)*\)\s*(:\s*[^=]{1,80}?)?=>', t, re.S):
        return True
    if re.match(r'(async\s+)?[A-Za-z_$][\w$]*\s*=>', t):
        return True
    if re.match(r'(React\.)?(memo|forwardRef|useCallback|lazy)\s*[(<]', t):
        return True
    return False


def _analyze_body(sym, masked, strings, lines, ctx):
    a, b = sym['start'], sym['end']
    body = masked[a:b]
    calls, refs, jsx, members = set(), set(), set(), set()
    for m in RE_CALL.finditer(body):
        name = m.group(2)
        if name not in JS_KEYWORDS:
            calls.add(name)
    for m in RE_IDENT.finditer(body):
        name = m.group(1)
        if name not in JS_KEYWORDS:
            refs.add(name)
    for m in RE_MEMBER.finditer(body):
        members.add((m.group(1), m.group(2)))
    if ctx['jsx_ok']:
        for m in RE_JSX.finditer(body):
            jsx.add(m.group(1).split('.')[0])

    triggers = []
    if ctx['jsx_ok']:
        for m in RE_EVENT.finditer(body):
            open_i = a + m.end() - 1
            close_i = match_close(masked, open_i)
            inner = masked[open_i + 1:close_i].strip()
            handlers = []
            if re.fullmatch(r'[A-Za-z_$][\w$.]*', inner):
                handlers.append(inner)
            else:
                for cm in RE_CALL.finditer(inner):
                    nm = cm.group(2)
                    if nm not in JS_KEYWORDS and nm not in EVENT_NOISE:
                        handlers.append(nm)
                for mm in re.finditer(r'([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\s*\(', inner):
                    if mm.group(2) not in EVENT_NOISE:
                        handlers.append(mm.group(1) + '.' + mm.group(2))
            seen = []
            for h in handlers:
                if h not in seen:
                    seen.append(h)
            triggers.append({'event': m.group(1), 'handlers': seen[:3], 'line': lines.at(open_i)})
    if re.search(r'\buseEffect\s*\(', body):
        triggers.append({'event': 'useEffect', 'handlers': [], 'line': lines.at(a + body.find('useEffect'))})

    fetches = []
    for m in RE_FETCH.finditer(body):
        open_i = a + m.end() - 1
        url = string_after(masked, strings, open_i + 1)
        if url is None:
            continue
        close_i = match_close(masked, open_i)
        method = 'GET'
        mm = RE_METHOD.search(masked, open_i, close_i)
        if mm:
            mv = string_after(masked, strings, mm.end())
            if mv:
                method = mv.upper()
        if m.group(1) == 'useSWRMutation':
            method = 'POST'
        fetches.append({'method': method, 'url': url, 'line': lines.at(open_i)})
    for m in RE_HTTP_MEMBER.finditer(body):
        base = m.group(1)
        if ctx['server_framework'] and base not in ('axios', 'ky', 'got'):
            continue
        open_i = a + m.end() - 1
        url = string_after(masked, strings, open_i + 1)
        if url is None or not (url.startswith('/') or url.startswith('http') or url.startswith('${}')):
            continue
        if base not in HTTP_CLIENTS and not url.startswith(('/api', 'http', '${}')):
            continue
        fetches.append({'method': m.group(2).upper(), 'url': url, 'line': lines.at(open_i)})

    tables = set()
    for m in RE_FROM_TABLE.finditer(body):
        if m.group(1) in ('Array', 'Buffer', 'Object', 'Uint8Array', 'Set', 'Map'):
            continue
        t = string_after(masked, strings, a + m.end())
        if t and re.fullmatch(r'[A-Za-z_][\w.]*', t):
            tables.add(t)
    for m in RE_PRISMA.finditer(body):
        tables.add(m.group(1))

    sym.update({
        'calls': sorted(calls), 'refs': sorted(refs), 'jsx': sorted(jsx),
        'members': sorted(members), 'triggers': triggers, 'fetches': fetches,
        'tables': sorted(tables),
        'env': sorted(set(RE_ENV.findall(ctx['src'][a:b]))),
    })


def scan_js(path, src, sfc=False):
    lines = Lines(src)
    template = ''
    if sfc:
        # keep only <script> bodies as code; remember the template for tags/events
        code = [' ' if ch != '\n' else '\n' for ch in src]
        for m in re.finditer(r'<script\b[^>]*>([\s\S]*?)</script>', src):
            code[m.start(1):m.end(1)] = list(m.group(1))
        tpl = re.sub(r'<script\b[^>]*>[\s\S]*?</script>|<style\b[^>]*>[\s\S]*?</style>', '', src)
        template = tpl
        src_code = ''.join(code)
    else:
        src_code = src
    masked, strings, comments = mask_js(src_code)
    depth = depth_array(masked)
    ext = os.path.splitext(path)[1].lower()
    imports, reexports = _js_imports(masked, strings, lines)
    import_specs = {i['spec'] for i in imports}
    server_framework = any(s in SERVER_FRAMEWORKS for s in import_specs)
    has_jsx = bool(re.search(r'(?<![\w$])<([A-Za-z][\w.]*)(\s[^<>]*)?/?>', masked)) and ext in ('.jsx', '.tsx', '.js')
    ctx = {'jsx_ok': ext in ('.jsx', '.tsx', '.js') or sfc, 'server_framework': server_framework, 'src': src_code}

    symbols = []
    taken = set()

    def add(name, kind, start, end, exported, export_names=None, extra=None):
        if name in taken:
            name = '%s@%d' % (name, lines.at(start))
        taken.add(name)
        s = {'name': name, 'kind': kind, 'start': start, 'end': end,
             'line': lines.at(start), 'endLine': lines.at(max(start, end - 1)),
             'exported': exported, 'exportNames': list(export_names or ([name] if exported else []))}
        if extra:
            s.update(extra)
        symbols.append(s)
        return s

    base_name = pascal(os.path.splitext(os.path.basename(path))[0])

    for m in RE_FUNC.finditer(masked):
        if depth[m.start()] != 0:
            continue
        name = m.group(4) or (base_name if m.group(2) else None)
        if not name:
            continue
        p_close = match_close(masked, m.end() - 1)
        brace = masked.find('{', p_close)
        end = match_close(masked, brace) + 1 if brace >= 0 else p_close + 1
        exported = bool(m.group(1))
        names = ['default'] if m.group(2) else ([name] if exported else [])
        add(name, 'function', m.start(), end, exported, names)

    for m in RE_VAR.finditer(masked):
        if depth[m.start()] != 0:
            continue
        end = stmt_end(masked, strings, m.end())
        kind = 'function' if _is_fn_init(masked, m.end()) else 'value'
        add(m.group(2), kind, m.start(), end, bool(m.group(1)))

    for m in RE_CLASS.finditer(masked):
        if depth[m.start()] != 0:
            continue
        brace = masked.find('{', m.end())
        end = match_close(masked, brace) + 1 if brace >= 0 else m.end()
        exported = bool(m.group(1))
        names = ['default'] if m.group(2) else ([m.group(3)] if exported else [])
        add(m.group(3), 'class', m.start(), end, exported, names)

    for m in RE_EXPORTS_ASSIGN.finditer(masked):
        if depth[m.start()] != 0:
            continue
        end = stmt_end(masked, strings, m.end())
        kind = 'function' if _is_fn_init(masked, m.end()) else 'value'
        add(m.group(1), kind, m.start(), end, True)

    by_name = {s['name']: s for s in symbols}

    # export { a, b as c }  /  export default ident  /  module.exports = ...
    for m in RE_EXPORT_LIST.finditer(masked):
        if depth[m.start()] != 0:
            continue
        tail = masked[m.end():m.end() + 12]
        if re.match(r'\s*from\b', tail):
            continue
        for local, exported_as in ((v, k) for k, v in _parse_named(m.group(1)).items()):
            s = by_name.get(local)
            if s:
                s['exported'] = True
                s['exportNames'].append(exported_as)
    for m in RE_EXPORT_DEFAULT.finditer(masked):
        if depth[m.start()] != 0:
            continue
        rest = masked[m.end():]
        if re.match(r'(async\s+)?(function|class)\b', rest):
            continue
        im = re.match(r'([A-Za-z_$][\w$]*)\s*(;|\n|$)', rest)
        if im and im.group(1) in by_name:
            by_name[im.group(1)]['exported'] = True
            by_name[im.group(1)]['exportNames'].append('default')
        else:
            end = stmt_end(masked, strings, m.end())
            name = base_name if base_name not in by_name else base_name + 'Default'
            s = add(name, 'component' if sfc else 'value', m.start(), end, True, ['default'])
            by_name[s['name']] = s
    for m in RE_MODULE_EXPORTS.finditer(masked):
        if depth[m.start()] != 0:
            continue
        rest = masked[m.end():]
        if rest.startswith('{'):
            close = match_close(masked, m.end())
            for part in masked[m.end() + 1:close].split(','):
                kv = [x.strip() for x in part.split(':')]
                if kv[0] in by_name:
                    by_name[kv[0]]['exported'] = True
                    by_name[kv[0]]['exportNames'].append(kv[0])
                elif len(kv) == 2 and kv[1] in by_name:
                    by_name[kv[1]]['exported'] = True
                    by_name[kv[1]]['exportNames'].append(kv[0])
        else:
            im = re.match(r'([A-Za-z_$][\w$]*)', rest)
            if im and im.group(1) in by_name:
                by_name[im.group(1)]['exported'] = True
                by_name[im.group(1)]['exportNames'] += ['default', '*']

    # Express / Hono / Fastify style routes declared at top level
    mounts = []
    if server_framework:
        for m in RE_ROUTE_CALL.finditer(masked):
            if depth[m.start()] != 0 or m.group(1) in ('axios', 'ky', 'got'):
                continue
            open_i = m.end() - 1
            route_path = string_after(masked, strings, open_i + 1)
            close_i = match_close(masked, open_i)
            method = m.group(2).upper()
            if method == 'USE':
                inner = masked[open_i + 1:close_i]
                idents = [x for x in re.findall(r'(?<![\w$.])([A-Za-z_$][\w$]*)', inner) if x not in JS_KEYWORDS]
                if route_path and idents:
                    mounts.append({'prefix': route_path, 'ident': idents[-1]})
                continue
            if not route_path or not route_path.startswith('/'):
                continue
            label = '%s %s' % ('ANY' if method == 'ALL' else method, route_path)
            add(label, 'route', m.start(), close_i + 1, False, [],
                {'route': {'method': 'ANY' if method == 'ALL' else method, 'path': route_path}})

    symbols.sort(key=lambda s: s['start'])
    for s in symbols:
        _analyze_body(s, masked, strings, lines, ctx)
        if s['kind'] == 'function':
            if re.match(r'use[A-Z0-9]', s['name']):
                s['kind'] = 'hook'
            elif s['name'][:1].isupper() and (s['jsx'] or has_jsx):
                s['kind'] = 'component'
        elif s['kind'] == 'value' and s['name'][:1].isupper() and s['jsx']:
            s['kind'] = 'component'

    if sfc:
        name = base_name
        tpl_tags = set(re.findall(r'<([A-Z][\w]*)', template))
        tpl_tags |= {pascal(t) for t in re.findall(r'<([a-z]+(?:-[a-z0-9]+)+)', template)}
        events = []
        for m in re.finditer(r'(?:@|v-on:|on:)([a-z]+)[^=]*=\s*["{]\s*([A-Za-z_$][\w$.]*)', template):
            events.append({'event': 'on' + m.group(1).capitalize(), 'handlers': [m.group(2)],
                           'line': lines.at(src.find(m.group(0)))})
        refs = set(re.findall(r'(?<![\w$.])([A-Za-z_$][\w$]*)', template)) - JS_KEYWORDS
        main = {'name': name if name not in taken else name + 'View', 'kind': 'component',
                'start': 0, 'end': len(src), 'line': 1, 'endLine': lines.at(len(src)),
                'exported': True, 'exportNames': ['default'], 'calls': [], 'refs': sorted(refs),
                'jsx': sorted(tpl_tags), 'members': [], 'triggers': events, 'fetches': [],
                'tables': [], 'env': []}
        symbols = [s for s in symbols if not ('default' in s['exportNames'] and s['kind'] == 'component')]
        symbols.insert(0, main)

    # health facts
    problems = []
    for o, c in (('{', '}'), ('(', ')'), ('[', ']')):
        diff = masked.count(o) - masked.count(c)
        if diff:
            problems.append("%d unclosed '%s'" % (diff, o) if diff > 0 else "%d extra '%s'" % (-diff, c))
    todos = []
    for pos, text in comments:
        for tm in TODO_RE.finditer(text):
            todos.append({'line': lines.at(pos + tm.start()), 'tag': tm.group(1),
                          'text': tm.group(2).strip(' */')})
    secrets = []
    for pos, (content, _q, _e) in strings.items():
        for rx, label in SECRET_PATTERNS:
            sm = rx.search(content)
            if sm:
                secrets.append({'line': lines.at(pos), 'label': label, 'preview': sm.group(0)[:8] + '…'})
                break

    head = masked[:300]
    use_client = bool(re.search(r'^\s*([\'"])use client\1', src_code[:200]))
    return {
        'path': path, 'lang': 'sfc' if sfc else ('ts' if ext in ('.ts', '.tsx') else 'js'),
        'imports': imports, 'reexports': reexports, 'symbols': symbols, 'mounts': mounts,
        'hasJsx': has_jsx or sfc, 'useClient': use_client, 'serverFramework': server_framework,
        'syntax': ('Brackets do not balance (%s) — this file probably has a syntax error' % ', '.join(problems)) if problems else None,
        'syntaxLine': None, 'todos': todos, 'secrets': secrets, 'isMain': False,
        'env': sorted(set(RE_ENV.findall(src_code))), '_head': head,
    }


# ---------------------------------------------------------------- Python scan

PY_HTTP = {'requests', 'httpx', 'aiohttp'}


def _py_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _py_name(node.value)
        return base + '.' + node.attr if base else None
    return None


def _py_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = ''
        for v in node.values:
            out += v.value if isinstance(v, ast.Constant) else '${}'
        return out
    return None


def scan_py(path, src):
    lines = src.splitlines()
    todos = []
    for i, ln in enumerate(lines, 1):
        if '#' in ln:
            tm = TODO_RE.search(ln[ln.index('#'):])
            if tm:
                todos.append({'line': i, 'tag': tm.group(1), 'text': tm.group(2).strip()})
    base = {'path': path, 'lang': 'py', 'imports': [], 'reexports': [], 'symbols': [], 'mounts': [],
            'hasJsx': False, 'useClient': False, 'serverFramework': False, 'syntax': None,
            'syntaxLine': None, 'todos': todos, 'secrets': [], 'isMain': '__main__' in src,
            'env': []}
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        base['syntax'] = 'Python syntax error: %s' % (e.msg,)
        base['syntaxLine'] = e.lineno
        return base

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                base['imports'].append({'spec': a.name, 'names': {(a.asname or a.name.split('.')[0]): '*'},
                                        'line': node.lineno, 'kind': 'static', 'py': True,
                                        'level': 0, 'asname': a.asname})
        elif isinstance(node, ast.ImportFrom):
            names = {(a.asname or a.name): a.name for a in node.names}
            base['imports'].append({'spec': node.module or '', 'names': names, 'line': node.lineno,
                                    'kind': 'static', 'py': True, 'level': node.level})
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for rx, label in SECRET_PATTERNS:
                sm = rx.search(node.value)
                if sm:
                    base['secrets'].append({'line': node.lineno, 'label': label, 'preview': sm.group(0)[:8] + '…'})
                    break

    env_all = set()

    def analyze(sym, nodes):
        calls, refs, members, fetches, env, tables = set(), set(), set(), [], set(), set()
        for root in nodes:
            for n in ast.walk(root):
                if isinstance(n, ast.Name):
                    refs.add(n.id)
                elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                    members.add((n.value.id, n.attr))
                if isinstance(n, ast.Call):
                    fn = _py_name(n.func)
                    if not fn:
                        continue
                    calls.add(fn.split('.')[0] if '.' not in fn else fn.split('.')[0])
                    if '.' not in fn:
                        calls.add(fn)
                    parts = fn.split('.')
                    if parts[0] in PY_HTTP and parts[-1] in ('get', 'post', 'put', 'patch', 'delete', 'request') and n.args:
                        url = _py_str(n.args[0])
                        if url:
                            fetches.append({'method': parts[-1].upper(), 'url': url, 'line': n.lineno})
                    if fn in ('os.getenv', 'os.environ.get', 'getenv') and n.args:
                        v = _py_str(n.args[0])
                        if v:
                            env.add(v)
                    if parts[-1] in ('table', 'from_') and n.args:
                        v = _py_str(n.args[0])
                        if v:
                            tables.add(v)
                if isinstance(n, ast.Subscript) and _py_name(n.value) == 'os.environ':
                    sl = n.slice
                    if sl.__class__.__name__ == 'Index':  # Python 3.8 wraps subscripts
                        sl = sl.value
                    v = _py_str(sl)
                    if v:
                        env.add(v)
        env_all.update(env)
        sym.update({'calls': sorted(calls), 'refs': sorted(refs), 'jsx': [], 'members': sorted(members),
                    'triggers': [], 'fetches': fetches, 'tables': sorted(tables), 'env': sorted(env)})

    for node in tree.body:
        sym = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = getattr(node, 'end_lineno', node.lineno)
            start_line = min([d.lineno for d in getattr(node, 'decorator_list', [])] + [node.lineno])
            kind = 'class' if isinstance(node, ast.ClassDef) else 'function'
            sym = {'name': node.name, 'kind': kind, 'line': start_line, 'endLine': end,
                   'exported': not node.name.startswith('_'), 'exportNames': [node.name]}
            route = None
            for d in getattr(node, 'decorator_list', []):
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.args:
                    attr = d.func.attr
                    p = _py_str(d.args[0])
                    if p and p.startswith('/') and attr in ('get', 'post', 'put', 'patch', 'delete', 'route', 'api_route', 'websocket'):
                        method = attr.upper() if attr not in ('route', 'api_route') else 'ANY'
                        for kw in d.keywords:
                            if kw.arg == 'methods' and isinstance(kw.value, (ast.List, ast.Tuple)) and kw.value.elts:
                                mv = _py_str(kw.value.elts[0])
                                method = mv.upper() if mv else method
                        route = {'method': method, 'path': p}
                        base['serverFramework'] = True
            if route:
                sym['kind'] = 'route'
                sym['route'] = route
            analyze(sym, [node])
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Call):
            nm = node.targets[0].id
            sym = {'name': nm, 'kind': 'value', 'line': node.lineno,
                   'endLine': getattr(node, 'end_lineno', node.lineno),
                   'exported': not nm.startswith('_'), 'exportNames': [nm]}
            analyze(sym, [node])
        if sym:
            base['symbols'].append(sym)
    base['env'] = sorted(env_all)
    return base


# ---------------------------------------------------------------- entry

def scan_file(root, rel):
    full = os.path.join(root, rel)
    with open(full, 'r', encoding='utf-8', errors='replace') as fh:
        src = fh.read()
    ext = os.path.splitext(rel)[1].lower()
    if ext in PY_EXTS:
        info = scan_py(rel, src)
    else:
        info = scan_js(rel, src, sfc=ext in SFC_EXTS)
    for s in info['symbols']:
        s.pop('start', None)
        s.pop('end', None)
        s['loc'] = max(1, s['endLine'] - s['line'] + 1)
    info.pop('_head', None)
    info['loc'] = count_loc(src)
    info['hash'] = file_hash(src)
    return info


def scan_project(root):
    out = []
    for rel in list_files(root):
        try:
            out.append(scan_file(root, rel))
        except Exception as e:  # never let one weird file kill the city
            out.append({'path': rel, 'lang': 'unknown', 'imports': [], 'reexports': [], 'symbols': [],
                        'mounts': [], 'hasJsx': False, 'useClient': False, 'serverFramework': False,
                        'syntax': None, 'syntaxLine': None, 'todos': [], 'secrets': [], 'isMain': False,
                        'env': [], 'loc': 0, 'hash': '', 'scanError': str(e)})
    return out
