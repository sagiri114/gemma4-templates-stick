#!/usr/bin/env python3
"""check: one-call verification after an edit.

Compiles the changed Python files (in memory, no .pyc written), runs the existing tests related to
them, lists untracked files in the repository and shows the diff summary. Standard library only.

    check.py                          automatic test selection
    check.py tests/test_x.py::test_y  run these tests instead (several allowed)
"""
import os
import re
import subprocess
import sys
import time

T0 = time.time()
MAX_REPORT = 3500
TEST_TIMEOUT = 75
MAX_TEST_FILES = 3
PROTECTED = {'pytest.ini', 'conftest.py', 'setup.cfg', 'tox.ini', 'pyproject.toml'}
SKIP_IDENT = {'self', 'cls', 'None', 'True', 'False', 'return', 'import', 'from', 'class', 'def',
              'test', 'tests', 'main', 'init', 'setup', 'value', 'values', 'name', 'data', 'args',
              'kwargs', 'result', 'object', 'string', 'print', 'append', 'format'}


def find_workspace():
    cands = []
    pwd = os.environ.get('PWD')
    if pwd:
        cands.append(pwd)
    cands.append('/workspace')
    for c in cands:
        d = os.path.abspath(c)
        while True:
            if os.path.isdir(os.path.join(d, '.git')):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return None


def git(ws, *args):
    try:
        r = subprocess.run(['git'] + list(args), cwd=ws, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=30)
        return r.stdout
    except Exception:
        return ''


def base_ref(ws):
    """The harness tags its baseline commit; fall back to HEAD when the tag is missing."""
    return '_swegemma_baseline' if git(ws, 'rev-parse', '-q', '--verify', '_swegemma_baseline').strip() else 'HEAD'


def is_test_path(path):
    parts = path.split('/')
    base = parts[-1]
    return (base.startswith('test_') or base.endswith('_test.py') or base == 'conftest.py'
            or any(p in ('tests', 'test', 'testing') for p in parts[:-1]))


def parse_args(argv):
    targets = []
    i = 0
    while i < len(argv):
        a = str(argv[i]).strip()
        if a in ('--tests', '--test', '--targets', '--target', '--file', '--files'):
            if i + 1 < len(argv):
                targets.extend(str(argv[i + 1]).replace(',', ' ').split())
            i += 2
            continue
        if a and not a.startswith('-'):
            targets.extend(a.replace(',', ' ').split())
        i += 1
    return targets


def syntax_errors(ws, files):
    errs = []
    for f in files:
        try:
            with open(os.path.join(ws, f), 'rb') as fh:
                src = fh.read()
            compile(src, f, 'exec', dont_inherit=True)
        except SyntaxError as e:
            line = (e.text or '').rstrip()
            errs.append('%s line %s: %s%s' % (f, e.lineno, e.msg, (' -> ' + line.strip()) if line else ''))
        except Exception as e:  # unreadable file etc.
            errs.append('%s: %s' % (f, e))
    return errs


def changed_identifiers(ws, base):
    diff = git(ws, 'diff', '-U0', base, '--', '*.py')
    names = []
    for line in diff.splitlines():
        m = None
        if line.startswith('@@'):
            m = re.search(r'@@.*@@\s*(?:async\s+)?(?:def|class)\s+(\w+)', line)
        elif line.startswith(('+', '-')) and not line.startswith(('+++', '---')):
            m = re.search(r'^[+-]\s*(?:async\s+)?(?:def|class)\s+(\w+)', line)
        if m:
            n = m.group(1)
            if len(n) >= 4 and n not in SKIP_IDENT and not n.startswith('__') and n not in names:
                names.append(n)
    return names[:6]


def related_tests(ws, sources, all_tests, base='HEAD'):
    picked, how = [], []
    for src in sources:
        parts = src.split('/')
        stem = parts[-1][:-3]
        if stem == '__init__' and len(parts) > 1:
            stem = parts[-2]
        cands = []
        if 'docs_src' in parts:  # fastapi: docs_src/<topic>/tutorial001_py310.py
            topic = parts[parts.index('docs_src') + 1] if parts.index('docs_src') + 1 < len(parts) - 1 else ''
            core = re.sub(r'_(py3\d+|an)(_.*)?$', '', stem)
            for t in all_tests:
                tp = t.split('/')
                if ('test_' + topic) in tp and tp[-1].startswith('test_' + core):
                    cands.append(t)
        if not cands:
            for t in all_tests:
                b = t.split('/')[-1]
                if b == 'test_%s.py' % stem or b.startswith('test_%s_' % stem) or b == '%s_test.py' % stem:
                    cands.append(t)
        for c in sorted(cands, key=len)[:2]:
            if c not in picked:
                picked.append(c)
                how.append('name match')
    if not picked and all_tests:
        idents = changed_identifiers(ws, base)
        score = {}
        for n in idents:
            out = git(ws, 'grep', '-l', '-w', '-F', n, '--', *[t for t in all_tests][:2000])
            for f in out.splitlines():
                score[f] = score.get(f, 0) + 1
        for f, _ in sorted(score.items(), key=lambda kv: (-kv[1], len(kv[0])))[:2]:
            picked.append(f)
            how.append('mentions changed names')
    return picked[:MAX_TEST_FILES], how[:MAX_TEST_FILES]


def run_tests(ws, targets):
    env = dict(os.environ)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    cmd = [sys.executable, '-m', 'pytest', '-x', '-q', '--no-header', '-p', 'no:cacheprovider',
           '--tb=short'] + targets
    budget = max(10, TEST_TIMEOUT - int(time.time() - T0))
    try:
        r = subprocess.run(cmd, cwd=ws, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True, timeout=budget, env=env)
    except subprocess.TimeoutExpired:
        return 'TESTS TIMED OUT after %ds (try a single test: args=["path::test_name"])' % budget, ''
    lines = [l for l in r.stdout.splitlines() if l.strip() and 'stopping after' not in l]
    summary = lines[-1] if lines else '(no output)'
    if 'No module named pytest' in r.stdout:
        return 'TESTS COULD NOT RUN: pytest is not available here; check with one python3 -c command.', ''
    if r.returncode == 0:
        return 'TESTS PASSED: %s' % summary, ''
    if r.returncode == 5:
        return 'NO TESTS COLLECTED for %s' % ' '.join(targets), ''
    if r.returncode == 1:
        return 'TESTS FAILED: %s' % summary, '\n'.join(lines[-25:])
    return 'TESTS COULD NOT RUN (exit %d): %s' % (r.returncode, summary), '\n'.join(lines[-12:])


def main(argv):
    ws = find_workspace()
    if not ws:
        print('check: repository not found (no .git above $PWD or /workspace).')
        return
    explicit = parse_args(argv)
    base = base_ref(ws)
    # without the baseline tag, the root pytest.ini / conftest.py written by the harness look changed
    harness = {'pytest.ini', 'conftest.py'} if base == 'HEAD' else set()
    changed = [l.strip() for l in git(ws, 'diff', '--name-only', base).splitlines()
               if l.strip() and l.strip() not in harness]
    untracked = [l.strip() for l in git(ws, 'ls-files', '--others', '--exclude-standard').splitlines()
                 if l.strip() and l.strip() not in harness
                 and not os.path.basename(l.strip()).startswith('.adk_exec_')]
    out = ['check report']
    if not changed and not untracked:
        out.append('NO CHANGES: nothing differs from the original repository yet. Edit the source first.')
        print('\n'.join(out))
        return

    numstat = {}
    for line in git(ws, 'diff', '--numstat', base).splitlines():
        p = line.split('\t')
        if len(p) == 3:
            numstat[p[2]] = '+%s -%s' % (p[0], p[1])
    out.append('CHANGED: ' + (', '.join('%s (%s)' % (f, numstat.get(f, '?')) for f in changed) or 'none'))

    py_files = [f for f in changed + untracked
                if f.endswith('.py') and os.path.isfile(os.path.join(ws, f))]
    errs = syntax_errors(ws, py_files)
    if errs:
        out.append('SYNTAX ERROR: ' + ' | '.join(errs[:3]))
    else:
        out.append('SYNTAX: ok (%d Python file%s)' % (len(py_files), '' if len(py_files) == 1 else 's'))

    touched_tests = [f for f in changed if is_test_path(f) or os.path.basename(f) in PROTECTED]
    if touched_tests:
        out.append('WARNING: you changed test/config files, revert them unless the task requires it: '
                   + ', '.join(touched_tests))

    if errs:
        out.append('TESTS: skipped because of the syntax error.')
    else:
        all_tests = [f for f in git(ws, 'ls-files', '--', '*.py').splitlines()
                     if is_test_path(f) and os.path.basename(f) != 'conftest.py']
        if explicit:
            missing = [t for t in explicit if not os.path.exists(os.path.join(ws, t.split('::')[0]))]
            targets = [t for t in explicit if t not in missing]
            how = ['requested'] * len(targets)
            if missing:
                out.append('NOT FOUND: ' + ', '.join(missing))
        else:
            sources = [f for f in changed if f.endswith('.py') and not is_test_path(f)
                       and os.path.basename(f) not in PROTECTED]
            targets, how = related_tests(ws, sources, all_tests, base)
        if not targets:
            out.append('TESTS: no related existing test file found. Check the behaviour with one '
                       'python3 -c command, or pass args=["tests/test_file.py::test_name"].')
        else:
            status, detail = run_tests(ws, targets)
            out.append('TESTS RUN: ' + ', '.join('%s (%s)' % (t, h) for t, h in zip(targets, how)))
            out.append(status)
            if detail:
                out.append(detail)

    if untracked:
        out.append('UNTRACKED FILES (delete before submit_patch unless intended new source): '
                   + ', '.join(untracked[:15]))
    out.append('NEXT: fix any syntax error or failure caused by your change and run check again; '
               'otherwise delete scratch files and call submit_patch.')
    report = '\n'.join(out)
    if len(report) > MAX_REPORT:
        report = report[:MAX_REPORT - 200] + '\n...[report truncated]...\n' + out[-1]
    print(report)


if __name__ == '__main__':
    main(sys.argv[1:])
