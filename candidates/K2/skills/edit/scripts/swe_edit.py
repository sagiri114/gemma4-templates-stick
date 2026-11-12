#!/usr/bin/env python3
"""Fixed narrow editor. Only stdlib; check reports risks, never repairs files."""
import argparse
import ast
from collections import Counter
from contextlib import contextmanager
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

VERSION = 'r7-k-2'
CONFIGS = {'pyproject.toml', 'tox.ini', 'setup.cfg', 'pytest.ini', '.pytest.ini'}


class Refusal(Exception):
    def __init__(self, kind, detail):
        self.kind, self.detail = kind, detail


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git(root, *args):
    p = subprocess.run(['git', '-C', str(root), *args], capture_output=True)
    if p.returncode:
        raise Refusal('git_error', p.stderr.decode('utf-8', errors='replace')[:400])
    return p.stdout


def find_repo():
    # ADK changes cwd to its unpack directory without changing PWD.
    for start in [Path.cwd(), Path(os.environ.get('PWD') or Path.cwd())]:
        p = subprocess.run(['git', '-C', str(start), 'rev-parse', '--show-toplevel'],
                           capture_output=True)
        if p.returncode == 0:
            return Path(os.fsdecode(p.stdout).strip()).resolve()
    raise Refusal('repository_missing', 'Cannot locate repository from cwd or PWD')


def state_path(root):
    d = Path(os.fsdecode(git(root, 'rev-parse', '--absolute-git-dir')).strip())
    return d / 'swe_edit_state.json'


def read_state(root, verify_helper=True):
    try:
        state = json.loads(state_path(root).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise Refusal('incomplete', 'Missing or unreadable install state: ' + str(e))
    if state.get('root') != str(root) or state.get('version') != VERSION:
        raise Refusal('incomplete', 'Install root/version mismatch')
    if verify_helper and state.get('helper_sha256') != digest(Path(__file__).read_bytes()):
        raise Refusal('incomplete', 'Installed helper hash mismatch')
    git(root, 'cat-file', '-e', state['baseline'] + '^{commit}')
    return state


def install(source):
    root = find_repo()
    raw = source.read_bytes()
    location = state_path(root)
    if location.exists():
        state = read_state(root, verify_helper=False)
    else:
        try:
            baseline = git(root, 'rev-parse', '--verify', '_swegemma_baseline^{commit}')
            origin = '_swegemma_baseline'
        except Refusal:
            baseline = git(root, 'rev-parse', 'HEAD^{commit}')
            origin = 'fixed_install_HEAD'
        state = dict(root=str(root), baseline=baseline.decode().strip(), baseline_origin=origin)
    state.update(version=VERSION, helper_sha256=digest(raw))
    tmp = Path(os.environ.get('TMPDIR') or '/tmp').resolve()
    if not tmp.is_dir():
        raise Refusal('install_refused', 'TMPDIR must already be a directory')
    target = tmp / 'swe_edit.py'
    if target.is_symlink() or location.is_symlink():
        raise Refusal('install_refused', 'Refusing symlink install target or state')
    for dest, content, mode in [(target, raw, 0o700),
                                (location, (json.dumps(state, sort_keys=True)+'\n').encode(), 0o600)]:
        fd, name = tempfile.mkstemp(prefix='.swe_edit-', dir=dest.parent)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(content); f.flush(); os.fsync(f.fileno())
            os.chmod(name, mode)
            os.replace(name, dest)
        finally:
            if os.path.exists(name): os.unlink(name)
    return dict(status='ok', installed=str(target), **state)


def is_test(name):
    p = Path(name)
    return (p.name.startswith('test_') or p.name.endswith('_test.py') or p.name == 'conftest.py'
            or bool(set(p.parts[:-1]) & {'tests', 'test', 'testing'}))


def safe_path(root, name):
    p = Path(name)
    if p.is_absolute() or '..' in p.parts or '.git' in p.parts or not p.name or str(p) == '.':
        raise Refusal('path_refused', 'Expected a workspace relative source path')
    if is_test(name): raise Refusal('path_refused', 'Test path is protected')
    q = root
    for part in p.parts:
        q = q / part
        if q.is_symlink(): raise Refusal('path_refused', 'Symlink component')
    if not q.resolve().is_relative_to(root): raise Refusal('path_refused', 'Outside repository')
    return q


def encoding(raw):
    try:
        raw.decode('utf-8-sig')
    except UnicodeError:
        raise Refusal('encoding_refused', 'Only UTF-8 with optional BOM is supported')
    if b'\0' in raw: raise Refusal('encoding_refused', 'NUL/binary input')
    rest = raw.replace(b'\r\n', b'')
    if b'\r' in rest or (b'\r\n' in raw and b'\n' in rest):
        raise Refusal('encoding_refused', 'Mixed or bare CR newlines')
    return b'\r\n' if b'\r\n' in raw else b'\n'


def parse_blocks(payload, tag):
    try: payload.decode('utf-8')
    except UnicodeError: raise Refusal('protocol_error', 'Payload must be UTF-8')
    if tag is not None and not re.fullmatch(r'E\d{1,4}', tag):
        raise Refusal('protocol_error', 'Tag must be E0..E9999')
    payload = payload.replace(b'\r\n', b'\n')
    if b'\r' in payload or b'\0' in payload:
        raise Refusal('protocol_error', 'Bare CR or NUL in payload')
    suffix = (' ' + tag).encode() if tag else b''
    start, sep, end = [m + suffix for m in (b'<<<<<<< SEARCH', b'=======', b'>>>>>>> REPLACE')]
    outer = ('SWE_EDIT_EOF_' + tag if tag else 'SWE_EDIT_EOF').encode()
    lines = payload.split(b'\n'); i = 0; result = []
    while i < len(lines):
        if not lines[i]: i += 1; continue
        if lines[i] != start:
            raise Refusal('protocol_error', 'Expected SEARCH marker; use --tag on marker collision')
        i += 1; a = i
        while i < len(lines) and lines[i] != sep:
            if lines[i] in (start, end, outer):
                raise Refusal('protocol_error', 'Marker collision; choose --tag E0 (or another tag)')
            i += 1
        if i == len(lines): raise Refusal('protocol_error', 'Missing separator')
        old = b'\n'.join(lines[a:i]); i += 1; a = i
        while i < len(lines) and lines[i] != end:
            if lines[i] in (start, sep, outer):
                raise Refusal('protocol_error', 'Marker collision; choose --tag E0 (or another tag)')
            i += 1
        if i == len(lines): raise Refusal('protocol_error', 'Missing REPLACE end marker')
        new = b'\n'.join(lines[a:i]); i += 1
        if not old: raise Refusal('protocol_error', 'Empty SEARCH is forbidden')
        result.append((old, new))
    if not result: raise Refusal('protocol_error', 'No replacement blocks')
    return result


def line_no(body, pos):
    return body[:pos].count(b'\n') + 1


def line_anchored(body, start, end, needle, nl):
    """A match must cover whole lines; only the first line's leading indentation may be left out."""
    line_start = body.rfind(b'\n', 0, start) + 1
    if body[line_start:start].strip(b' \t'):
        return False
    return end == len(body) or needle.endswith(b'\n') or body.startswith(nl, end)


def similar_lines(body, needle):
    first = next((l.strip() for l in needle.split(b'\n') if l.strip()), b'')
    if not first:
        return []
    return [i + 1 for i, l in enumerate(body.split(b'\n')) if l.strip() == first][:5]


def short_scope(scope):
    names = [part.split(':', 1)[1].split('#', 1)[0] for part in scope.split('/')[1:] if ':' in part]
    return '.'.join(names) or '<module>'


def scope_warnings(before, after):
    """Risk flags for one edit: a function/class lost a return/raise/yield, self, decorator or itself."""
    try:
        a, b = scopes(before), scopes(after)
    except (SyntaxError, ValueError, UnicodeError):
        return [dict(kind='lexical_unverified')]
    out = []
    for scope, counts in a.items():
        current = b.get(scope, Counter())
        for key in ('definition', 'return', 'raise', 'yield', 'self', 'decorators'):
            if counts[key] > current[key]:
                out.append(dict(kind=key + '_removed', where=short_scope(scope), risk_only=True))
    return out


def positions(raw, needle):
    starts = []; i = 0
    while True:
        n = raw.find(needle, i)
        if n < 0: return starts
        starts.append(n); i = n + 1  # Include overlapping occurrences.


@contextmanager
def locked(root, path):
    key = digest(str(path.relative_to(root)).encode())[:24]
    lock = state_path(root).parent / ('swe_edit_' + key + '.lock')
    try: fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError: raise Refusal('conflict_refused', 'Another helper transaction owns this file')
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()


def syntax_ok(raw, name):
    try: compile(raw, str(name), 'exec'); return True
    except (SyntaxError, ValueError): return False


def receipt(path, before, after, count, original_compiled=None):
    return dict(status='ok', version=VERSION, helper_sha256=digest(Path(__file__).read_bytes()),
                path=str(path), blocks=count, changed=before != after,
                before_sha256=digest(before), after_sha256=digest(after),
                original_compiled=original_compiled,
                warnings=['protected_config'] if path.name in CONFIGS else [])


def edit(root, name, payload, tag):
    path = safe_path(root, name)
    pairs = parse_blocks(payload, tag)
    with locked(root, path):
        raw = path.read_bytes(); mode = stat.S_IMODE(path.stat().st_mode)
        nl = encoding(raw); bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
        body = raw[len(bom):]; spans = []
        for old, new in pairs:
            old = old.replace(b'\n', nl); new = new.replace(b'\n', nl)
            raw_hits = positions(body, old)
            hits = [p for p in raw_hits if line_anchored(body, p, p + len(old), old, nl)]
            if len(hits) != 1:
                if not hits and raw_hits:
                    lines = [line_no(body, p) for p in raw_hits[:10]]
                    raise Refusal('match_refused', f'SEARCH matched only part of a line at lines={lines}; '
                                  'SEARCH must cover whole lines (first-line indentation may be omitted)')
                if not hits:
                    raise Refusal('match_refused', 'Expected one match, got 0; lines with the same first '
                                  f'SEARCH line (ignoring spaces)={similar_lines(body, old)}')
                lines = [line_no(body, p) for p in hits[:10]]
                raise Refusal('match_refused', f'Expected one match, got {len(hits)}; lines={lines}')
            p = hits[0]
            if p > body.rfind(b'\n', 0, p) + 1 and new[:1] in (b' ', b'\t'):
                raise Refusal('match_refused', 'SEARCH left out the first-line indentation but REPLACE '
                              'starts with indentation; include the indentation in both or in neither')
            spans.append((p, p + len(old), new))
        spans.sort()
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
            raise Refusal('match_refused', 'Overlapping replacement blocks')
        after = body
        for start, end, new in reversed(spans): after = after[:start] + new + after[end:]
        after = bom + after
        if raw.endswith(b'\n') != after.endswith(b'\n'):
            raise Refusal('format_refused', 'Final newline state would change')
        encoding(after)
        original_compiled = syntax_ok(raw, path) if path.suffix == '.py' else None
        if path.suffix == '.py' and not syntax_ok(after, path):
            raise Refusal('syntax_refused', 'Candidate Python does not compile; original_compiled=' + str(original_compiled))
        if after != raw:
            fd, tmp = tempfile.mkstemp(prefix='.swe_edit-', dir=path.parent)
            try:
                with os.fdopen(fd, 'wb') as f:
                    f.write(after); f.flush(); os.fsync(f.fileno())
                os.chmod(tmp, mode)
                if path.is_symlink() or path.read_bytes() != raw or stat.S_IMODE(path.stat().st_mode) != mode:
                    raise Refusal('conflict_refused', 'File changed before commit')
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
        result = receipt(path, raw, after, len(spans), original_compiled)
        if path.suffix == '.py':
            result['warnings'] = result['warnings'] + scope_warnings(raw, after)
        result['context'] = list(difflib.unified_diff(
            raw.decode('utf-8-sig').splitlines(), after.decode('utf-8-sig').splitlines(),
            fromfile=name, tofile=name, n=2, lineterm=''))[:60]
        return result


def create(root, name, raw):
    path = safe_path(root, name)
    encoding(raw)
    if path.suffix == '.py' and not syntax_ok(raw, path):
        raise Refusal('syntax_refused', 'New Python does not compile')
    with locked(root, path):
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            with os.fdopen(fd, 'wb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
        except BaseException:
            path.unlink()
            raise
    result = receipt(path, b'', raw, 0)
    result.update(changed=True, before_exists=False)
    return result


def scopes(raw):
    tree = ast.parse(raw)
    result = {}; counters = Counter()
    def scan(node, scope):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            key = (scope, type(node).__name__, node.name)
            ordinal = counters[key]; counters[key] += 1
            scope = scope + '/' + type(node).__name__ + ':' + node.name + '#' + str(ordinal)
            result[scope] = Counter(definition=1)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [*node.args.posonlyargs, *node.args.args]
                result[scope]['self'] = int(bool(args) and args[0].arg == 'self')
            result[scope]['decorators'] = len(node.decorator_list)
        record = result.setdefault(scope, Counter())
        for cls, label in [(ast.Return,'return'),(ast.Raise,'raise'),(ast.Yield,'yield'),(ast.YieldFrom,'yield')]:
            if isinstance(node, cls): record[label] += 1
        for child in ast.iter_child_nodes(node): scan(child, scope)
    scan(tree, 'module')
    return result


def check(root, state):
    base = state['baseline']
    changed = git(root, 'diff', '--no-renames', '--name-only', '-z', base, '--').split(b'\0')
    untracked = git(root, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0')
    names = sorted({os.fsdecode(p) for p in changed + untracked if p})
    warnings = []; files = []; complete = True
    for name in names:
        path = root / name
        if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
            warnings.append(dict(path=name, kind='symlink_unverified')); complete = False; continue
        before_cmd = subprocess.run(['git','-C',str(root),'show',base+':'+name], capture_output=True)
        old = before_cmd.stdout if before_cmd.returncode == 0 else b''
        new = path.read_bytes() if path.is_file() else b''
        files.append(dict(path=name, before_sha256=digest(old), after_sha256=digest(new),
                          old_lines=len(old.splitlines()), new_lines=len(new.splitlines())))
        def warn(kind, **kw): warnings.append(dict(path=name, kind=kind, **kw))
        if is_test(name): warn('test_file')
        if path.name in CONFIGS: warn('protected_config')
        if old and old.endswith(b'\n') != new.endswith(b'\n'): warn('eof_changed')
        if path.suffix == '.py':
            if path.exists() and not syntax_ok(new, name): warn('syntax_error')
            try: a, b = scopes(old), scopes(new)
            except (SyntaxError, ValueError, UnicodeError):
                warn('lexical_unverified'); continue
            for scope, counts in a.items():
                current = b.get(scope, Counter())
                for key in ('definition','return','raise','yield','self','decorators'):
                    if counts[key] > current[key]: warn(key + '_removed', scope=scope, risk_only=True)
    return dict(status='ok' if complete else 'incomplete', version=VERSION, complete=complete,
                baseline=base, baseline_origin=state['baseline_origin'], files=files,
                untracked=[os.fsdecode(p) for p in untracked if p], warnings=warnings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='op', required=True)
    p = sub.add_parser('edit'); p.add_argument('--tag'); p.add_argument('path')
    p = sub.add_parser('create'); p.add_argument('path')
    sub.add_parser('check')
    args = parser.parse_args()
    try:
        root = find_repo(); state = read_state(root)
        if args.op == 'check': result = check(root, state)
        else:
            raw = sys.stdin.buffer.read()
            result = edit(root, args.path, raw, args.tag) if args.op == 'edit' else create(root, args.path, raw)
        print(json.dumps(result, ensure_ascii=True))
        return 0 if result.get('complete', True) else 2
    except (Refusal, OSError, ValueError) as e:
        print(json.dumps(dict(status='refused', kind=getattr(e,'kind','io_refused'),
                              detail=getattr(e,'detail',str(e)), complete=False), ensure_ascii=True))
        return 2


if __name__ == '__main__':
    sys.exit(main())
