"""Growing code generator: solve a problem from the library, reuse a known algorithm under a
new name, or learn a new template — and keep it only if it passes every test.

  python grow.py solve problems.json [--ids A B] [--learner claude|none] [--model sonnet]
  python grow.py check            # regression over every learned algorithm

Problem format (JSON list): {"id", "statement", "signature": "solve(a, b)", "tests": [{"args", "expected"}]}

Per problem, in order:
  1. known   : Datalog resolves task(id) through supported/alias facts and all tests pass.
  2. reused  : some library algorithm with a compatible signature passes all tests;
               a rule alias(task, algorithm) is added — no model call.
  3. learned : the learner writes a new module from the statement and the *visible* tests
               (about half; hidden tests are never shown). It is admitted only if every test
               passes, then the whole library is regression-tested; any failure rolls back.
  4. failed  : nothing passed within --max-rounds; the library is unchanged.
"""
import argparse, ast, json, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

from generate import generate

ROOT = Path(__file__).resolve().parent
PACK = ROOT / 'packs' / 'growing'
RUNNER = ROOT / 'grow_runner.py'
PER_TEST_SECONDS = 10


# ---------------------------------------------------------------- library access
def slug(text):
    s = re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')
    return s if s and s[0].isalpha() else 'p_' + s


def library(pack):
    return json.loads((pack / 'library.json').read_text())


def add_fact(pack, fact):
    line = f'{fact} :- target(python).'
    path = pack / 'learned.dl'
    if line not in path.read_text().splitlines():
        with path.open('a') as fh:
            fh.write(line + '\n')


def template_path(pack, alg):
    return pack / 'templates' / 'algorithms' / f'{alg}.py.j2'


def render_task(pack, task):
    """Datalog decides which template implements the task; returns the module path or None."""
    out = Path(tempfile.mkdtemp(prefix='grow_'))
    key = 't'
    try:
        generate({'facts': {'task': [[key, task]], 'destination': [[key, 'sol.py']]}, 'data': {key: {}}}, out, pack)
    except ValueError as exc:
        if 'No emit' in str(exc):
            shutil.rmtree(out, ignore_errors=True)
            return None
        raise
    return out / 'sol.py'


def arity_ok(source, signature):
    want = len([a for a in signature[signature.index('(') + 1:signature.rindex(')')].split(',') if a.strip()])
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'solve':
            a = node.args
            if a.vararg:
                return True
            total = len(a.posonlyargs) + len(a.args)
            return total - len(a.defaults) <= want <= total
    return False


# ---------------------------------------------------------------- testing
def run_tests(module, tests):
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fh:
        json.dump(tests, fh)
    try:
        p = subprocess.run([sys.executable, '-I', str(RUNNER), str(module), fh.name, str(PER_TEST_SECONDS)],
                           capture_output=True, text=True, timeout=PER_TEST_SECONDS * len(tests) + 30,
                           cwd=module.parent, env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'})
        line = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ''
        data = json.loads(line) if line else {'load_error': (p.stderr.strip().splitlines() or ['crash'])[-1][:300]}
    except subprocess.TimeoutExpired:
        data = {'load_error': 'suite timeout'}
    finally:
        Path(fh.name).unlink(missing_ok=True)
    if 'load_error' in data:
        return [{'ok': False, 'error': data['load_error'], 'got': None} for _ in tests]
    return data['results']


def split(tests):
    """Visible half for the learner: small cases first; everything else stays hidden."""
    small = [i for i, t in enumerate(tests) if len(json.dumps(t)) < 1500]
    visible = set(small[:max(3, len(small) // 2)])
    return [t for i, t in enumerate(tests) if i in visible], [t for i, t in enumerate(tests) if i not in visible]


# ---------------------------------------------------------------- learner
PROMPT = """Write a Python 3 module (standard library only) that defines a top-level function with this exact signature:

    {signature}

Problem:
{statement}

Example tests (args are passed positionally; the result is compared with == after a JSON round trip):
{examples}

Other hidden tests exist, including edge cases and large inputs; aim for a solution with the usual optimal complexity.
{feedback}
Reply with only the module source inside one ```python code block. No prints, no input(), no file or network access."""


def show(tests, limit=8):
    lines = []
    for t in tests[:limit]:
        a, e = json.dumps(t['args'], ensure_ascii=False), json.dumps(t['expected'], ensure_ascii=False)
        lines.append(f"- solve(*{a[:300]}{'…' if len(a) > 300 else ''}) == {e[:150]}")
    return '\n'.join(lines)


def ask_claude(prompt, model):
    p = subprocess.run(['claude', '-p', '--model', model, '--tools', '', '--no-session-persistence', '--strict-mcp-config'],
                       input=prompt, capture_output=True, text=True, timeout=600, cwd=tempfile.gettempdir())
    if p.returncode != 0:
        raise RuntimeError(f'learner failed: {p.stderr.strip()[-300:]}')
    m = re.search(r'```(?:python)?\n(.*?)```', p.stdout, re.S)
    return (m.group(1) if m else p.stdout).strip() + '\n'


def describe_failures(visible, vres, hidden, hres):
    lines = []
    for t, r in zip(visible, vres):
        if not r['ok']:
            lines.append(f"- solve(*{json.dumps(t['args'])[:200]}) expected {json.dumps(t['expected'])[:100]}, "
                         f"got {r['got'] or r['error']}")
    bad = [r for r in hres if not r['ok']]
    if bad:
        kinds = sorted({(r['error'] or 'wrong answer').split(':')[0] for r in bad})
        lines.append(f'- {len(bad)} of {len(hres)} hidden tests failed ({", ".join(kinds)}); details are not shown.')
    return '\n'.join(lines[:10])


# ---------------------------------------------------------------- admission with rollback
def regression(pack):
    """Every learned algorithm must still pass its stored tests through the full rule pipeline."""
    broken = []
    for alg, entry in library(pack).items():
        if not entry.get('tests'):
            continue
        module = render_task(pack, alg)
        tests = json.loads((pack / entry['tests']).read_text())
        if module is None or not all(r['ok'] for r in run_tests(module, tests)):
            broken.append(alg)
        if module:
            shutil.rmtree(module.parent, ignore_errors=True)
    return broken


def admit(pack, alg, code, problem, origin):
    if '{%' in code and 'endraw' in code:
        raise ValueError('code contains a Jinja raw terminator')
    backup = Path(tempfile.mkdtemp(prefix='grow_backup_')) / 'pack'
    shutil.copytree(pack, backup)
    try:
        template_path(pack, alg).write_text('{% raw %}\n' + code + '{% endraw %}\n')
        (pack / 'tests' / f'{alg}.json').write_text(json.dumps(problem['tests'], ensure_ascii=False))
        add_fact(pack, f'supported({alg})')
        lib = library(pack)
        lib[alg] = {'origin': origin, 'signature': problem['signature'],
                    'statement': problem['statement'][:500], 'tests': f'tests/{alg}.json'}
        (pack / 'library.json').write_text(json.dumps(lib, indent=1, ensure_ascii=False) + '\n')
        broken = regression(pack)
        if broken:
            raise RuntimeError(f'regression broke {broken}')
    except Exception:
        shutil.rmtree(pack); shutil.copytree(backup, pack)
        raise
    finally:
        shutil.rmtree(backup.parent, ignore_errors=True)


# ---------------------------------------------------------------- main loop
def solve_one(pack, problem, learner, model, max_rounds):
    task = slug(problem['id'])
    tests = problem['tests']
    rec = {'id': problem['id'], 'task': task, 'model_calls': 0, 'model_seconds': 0.0}
    # 1. known through rules
    module = render_task(pack, task)
    if module is not None:
        res = run_tests(module, tests)
        shutil.rmtree(module.parent, ignore_errors=True)
        if all(r['ok'] for r in res):
            return {**rec, 'status': 'known', 'passed': len(res), 'total': len(tests)}
        rec['known_but_failing'] = sum(r['ok'] for r in res)
    # 2. reuse: any compatible library algorithm that passes everything becomes an alias
    visible, hidden = split(tests)
    for alg in sorted(library(pack)):
        source = template_path(pack, alg).read_text()
        if not arity_ok(source.replace('{% raw %}', '').replace('{% endraw %}', ''), problem['signature']):
            continue
        module = render_task(pack, alg)
        quick = run_tests(module, visible)
        if all(r['ok'] for r in quick) and all(r['ok'] for r in run_tests(module, tests)):
            shutil.rmtree(module.parent, ignore_errors=True)
            add_fact(pack, f'alias({task},{alg})')
            assert render_task(pack, task) is not None
            return {**rec, 'status': 'reused', 'via': alg, 'passed': len(tests), 'total': len(tests)}
        shutil.rmtree(module.parent, ignore_errors=True)
    if learner == 'none':
        return {**rec, 'status': 'failed', 'reason': 'not in library and learning disabled'}
    # 3. learn
    feedback, code = '', None
    for round_ in range(1, max_rounds + 1):
        prompt = PROMPT.format(signature=problem['signature'], statement=problem['statement'],
                               examples=show(visible), feedback=feedback)
        t0 = time.time()
        try:
            code = ask_claude(prompt, model)
        except Exception as exc:  # noqa: BLE001
            rec.update(status='failed', reason=str(exc)[:200]); return rec
        rec['model_calls'] += 1; rec['model_seconds'] += round(time.time() - t0, 1)
        d = Path(tempfile.mkdtemp(prefix='grow_try_'))
        (d / 'sol.py').write_text(code)
        vres, hres = run_tests(d / 'sol.py', visible), run_tests(d / 'sol.py', hidden)
        shutil.rmtree(d, ignore_errors=True)
        passed = sum(r['ok'] for r in vres + hres)
        rec.setdefault('rounds', []).append({'visible': sum(r['ok'] for r in vres), 'hidden': sum(r['ok'] for r in hres),
                                             'of': (len(vres), len(hres))})
        if passed == len(tests):
            try:
                admit(pack, task, code, problem, origin=f'learned:{model}:round{round_}')
            except Exception as exc:  # noqa: BLE001
                rec.update(status='failed', reason=f'admission rolled back: {exc}'[:200]); return rec
            return {**rec, 'status': 'learned', 'passed': passed, 'total': len(tests)}
        feedback = ('\nYour previous attempt:\n```python\n' + code[:4000] + '```\nIt failed:\n'
                    + describe_failures(visible, vres, hidden, hres) + '\nFix it.\n')
    rec.update(status='failed', reason=f'{max_rounds} rounds without passing every test')
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('solve')
    s.add_argument('problems', type=Path)
    s.add_argument('--ids', nargs='*')
    s.add_argument('--learner', choices=['claude', 'none'], default='claude')
    s.add_argument('--model', default='sonnet')
    s.add_argument('--max-rounds', type=int, default=3)
    s.add_argument('--pack', type=Path, default=PACK)
    s.add_argument('--log', type=Path)
    c = sub.add_parser('check')
    c.add_argument('--pack', type=Path, default=PACK)
    args = ap.parse_args()
    if args.cmd == 'check':
        broken = regression(args.pack.resolve())
        print('regression ok' if not broken else f'broken: {broken}')
        sys.exit(1 if broken else 0)
    problems = json.loads(args.problems.read_text())
    if args.ids:
        problems = [p for p in problems if p['id'] in args.ids]
    log = []
    for p in problems:
        rec = solve_one(args.pack.resolve(), p, args.learner, args.model, args.max_rounds)
        log.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
        if args.log:
            args.log.write_text(json.dumps(log, ensure_ascii=False, indent=1))
    counts = {}
    for r in log:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    print('SUMMARY', json.dumps(counts), 'model_calls', sum(r['model_calls'] for r in log))


if __name__ == '__main__':
    main()
