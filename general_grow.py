"""Grow packs/general: when a problem is not covered, a model proposes an extension of the
vocabulary, rules and schema templates; it is kept only if the problem passes all its tests
and every previously solved problem still passes (regression from stored facts, no model).

  python general_grow.py remember LOG.json PROBLEMS.json   # store solved problems + their facts
  python general_grow.py check                             # regression over the stored problems
  python general_grow.py lint                              # static rule checks (dead / redundant / contradicting rules)
  python general_grow.py grow PROBLEMS.json [--ids ...] [--model sonnet] [--max-rounds 3] [--log out.json]

The model may change vocab.json, learned.dl, algorithms.dl and templates/schemas/*.py.j2, and may add (never
change or delete) library functions in templates/lib; rules.dl and solution.py.j2 are fixed. Proposals are asked to be general (parameterised) rather than
specific to one problem; whether they are is measured afterwards on unseen problems.
"""
import argparse, difflib, hashlib, json, re, shutil, subprocess, tempfile, time
from pathlib import Path

import general
import lib_check
from grow import split

PACK = general.PACK
ROOT_DIR = Path(__file__).resolve().parent
EDITABLE = re.compile(r'^(vocab\.json|learned\.dl|algorithms\.dl|templates/schemas/[a-z0-9_]+\.py\.j2|templates/reference/[a-z0-9_]+\.py\.j2|templates/lib/[a-z0-9_]+\.(py|json))$')
LIBRARY = re.compile(r'^templates/lib/')
REFERENCE = re.compile(r'^templates/reference/')


def edit_violations(pack, files, delete=()):
    """Library functions are append-only (no changes, no deletions) and new ones come as .py + .json; references
    may be extended but not deleted (reference_compat checks the extension); a new schema comes with a reference."""
    bad = [f'may not edit {p}' for p in [*files, *delete] if not EDITABLE.match(p)]
    bad += [f'library function {p} already exists and may not be changed' for p in files
            if LIBRARY.match(p) and (pack / p).exists() and (pack / p).read_text().rstrip() != files[p].rstrip()]
    bad += [f'library function {p} may not be deleted' for p in delete if LIBRARY.match(p)]
    bad += [f'reference implementation {p} may not be deleted' for p in delete if REFERENCE.match(p)]
    for p in files:  # a new schema needs its slow reference implementation for differential testing
        if p.startswith('templates/schemas/') and not (pack / p).exists():
            ref = p.replace('templates/schemas/', 'templates/reference/')
            if ref not in files and not (pack / ref).exists():
                bad.append(f'new schema {p} needs a reference implementation {ref}')
    new = {Path(p).stem for p in files if p.startswith('templates/lib/') and not (pack / p).exists()}
    for stem in new:
        if not {f'templates/lib/{stem}.py', f'templates/lib/{stem}.json'} <= set(files):
            bad.append(f'new library function {stem} needs both templates/lib/{stem}.py and templates/lib/{stem}.json')
    return bad


def solved_dir(pack):
    d = pack / 'solved'
    d.mkdir(exist_ok=True)
    return d


def remember(pack, problem, facts):
    rec = {k: problem[k] for k in ('id', 'signature', 'statement', 'tests')}
    rec['facts'] = facts
    (solved_dir(pack) / f"{problem['id']}.json").write_text(json.dumps(rec, ensure_ascii=False))


def check_stored(pack_str, path_str):
    """All checks for one stored problem (runs in a worker process): tests with stored facts, glue whitelist,
    differential test against the reference, reference on the stored tests, cost growth."""
    pack, rec = Path(pack_str), json.loads(Path(path_str).read_text())
    r = general.evaluate(rec, rec['facts'], pack)
    if r['status'] != 'solved':
        return [(rec['id'], r['status'], str(r.get('reason') or r.get('first_failure'))[:150])]
    module = general.build(rec, rec['facts'], pack)
    try:
        source = module.read_text()
    finally:
        shutil.rmtree(module.parent, ignore_errors=True)
    bad = glue_violations(source, chosen_functions(source))
    if bad:
        return [(rec['id'], 'glue', '; '.join(bad[:3]) + ' (put algorithmic work in a library function)')]
    diff = differential(pack, rec)
    if diff:
        return [(rec['id'], 'differs_from_reference', diff)]
    ref = reference_on_tests(pack, rec)
    if ref:
        return [(rec['id'], 'reference_fails_tests', ref)]
    slow = problem_cost(pack, rec)
    if slow:
        return [(rec['id'], 'cost', slow)]
    return []


def rejected_dir(pack):
    return pack / 'rejected'


def error_constants(pack):
    """Every error constant that some rule of the pack can derive, error(<constant>,P) :- ..."""
    import general_lint
    return sorted({head[1][0] for _, head, _ in general_lint.load_rules(pack) if head[0] == 'error' and not head[1][0][:1].isupper()})


def uncovered_errors(pack):
    """Error constants with no rejection case."""
    covered = {json.loads(f.read_text())['error'] for f in rejected_dir(pack).glob('*.json')}
    return [e for e in error_constants(pack) if e.strip('"') not in covered]


def check_rejection(pack_str, path_str):
    """One corpus case: its facts must make the rules derive exactly the error constants {error} + also (the engine
    only; no tests, no code). Returns [] or [(case, 'rejection', why)]."""
    pack, path = Path(pack_str), Path(path_str)
    case = json.loads(path.read_text())
    problem = {'id': path.stem, 'signature': case['signature'], 'tests': []}
    try:
        d = general.engine_for(problem, case['facts'], pack, extra_rules=case.get('extra_rules', ''))
    except Exception as exc:  # noqa: BLE001 - a rule file that no longer loads is a failure of this case too
        return [(path.stem, 'rejection', f'engine failed: {type(exc).__name__}: {str(exc)[:120]}')]
    got = sorted({row[0] for row in d.db.get('error', ())})
    want = sorted({case['error'], *case.get('also', [])})
    if got == want:
        return []
    if not got:
        return [(path.stem, 'rejection', f"no longer rejected (expected error {case['error']}): the description now passes")]
    return [(path.stem, 'rejection', f'rejected with {got} instead of {want}')]


def rejections(pack, workers=4):
    """Run the rejection corpus (packs/general/rejected/*.json): every case must still be rejected with its error."""
    from concurrent.futures import ProcessPoolExecutor
    paths = [str(f) for f in sorted(rejected_dir(pack).glob('*.json'))]
    broken = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(check_rejection, [str(pack)] * len(paths), paths):
            broken += result
    return broken


def regression(pack, only=None, workers=4, corpus=True):
    """Every library function passes its unit tests and its declared complexity (lib_check), every stored
    problem passes every check (check_stored), and every rejection-corpus case is still rejected with its error
    (corpus=False skips that last part when the caller has just run it). No model calls. Stored problems are checked in parallel."""
    from concurrent.futures import ProcessPoolExecutor
    rejected = rejections(pack, workers) if corpus else []   # cheap (about 2 s); reported together with whatever else is broken
    broken = [('library', 'library', p) for p in lib_check.check_all(pack / 'templates' / 'lib')[0]]
    if broken:
        return rejected + broken
    paths = [str(f) for f in sorted(solved_dir(pack).glob('*.json')) if only is None or f.stem in only]
    if len(paths) <= 1 or workers <= 1:
        for path in paths:
            broken += check_stored(str(pack), path)
        return rejected + broken
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(check_stored, [str(pack)] * len(paths), paths):
            broken += result
    return rejected + broken


def render_deps(pack, rec):
    """Render a stored problem (rules + Jinja only, nothing is executed): schema, chosen functions and the sha256 of the
    solution and reference sources. Raises on render failure."""
    d = general.engine_for(rec, rec['facts'], pack)
    out = {'schema': sorted({s for _, s in d.db.get('schema', ())}), 'uses': sorted({f for _, f in d.db.get('uses', ())})}
    for key, reference in (('solution_sha256', False), ('reference_sha256', True)):
        module = general.build(rec, rec['facts'], pack, reference=reference)
        try:
            out[key] = hashlib.sha256(module.read_bytes()).hexdigest()
        finally:
            shutil.rmtree(module.parent, ignore_errors=True)
    return out


def update_deps(pack, ids=None):
    """Store `deps` in packs/.../solved/<id>.json for the given ids (default: all). Returns the ids written."""
    done = []
    for f in sorted(solved_dir(pack).glob('*.json')):
        if ids is not None and f.stem not in ids:
            continue
        rec = json.loads(f.read_text())
        rec['deps'] = render_deps(pack, rec)
        f.write_text(json.dumps(rec, ensure_ascii=False))
        done.append(f.stem)
    return done


def affected(pack):
    """Stored problems whose rendered solution or reference differs from the stored hash, that fail to render, or have no
    stored deps. Exact: identical generated code cannot behave differently. Returns {id: reason}."""
    out = {}
    for f in sorted(solved_dir(pack).glob('*.json')):
        rec = json.loads(f.read_text())
        old = rec.get('deps')
        if not old:
            out[rec['id']] = 'no stored deps'
            continue
        try:
            new = render_deps(pack, rec)
        except Exception as exc:  # noqa: BLE001
            out[rec['id']] = f'render failed: {type(exc).__name__}: {str(exc)[:100]}'
            continue
        changed = [k for k in ('solution_sha256', 'reference_sha256') if new[k] != old.get(k)]
        if changed:
            out[rec['id']] = 'changed ' + ', '.join(changed)
    return out


def who(pack, name):
    """Stored problems depending on a schema, a library function, or a rule (a substring of a rule line in the pack's
    .dl files: found exactly by deleting those lines in a copy and asking which problems' code changes)."""
    stored = [json.loads(f.read_text()) for f in sorted(solved_dir(pack).glob('*.json'))]
    hits = {r['id'] for r in stored if name in (r.get('deps') or {}).get('uses', []) or name in (r.get('deps') or {}).get('schema', [])}
    config = json.loads((pack / 'pack.json').read_text())
    lines = {n: [l for l in (pack / n).read_text().splitlines() if name in l and l.strip() and not l.lstrip().startswith('%')] for n in config['rules']}
    if any(lines.values()) and not hits:
        work = Path(tempfile.mkdtemp(prefix='gwho_')) / 'pack'
        shutil.copytree(pack, work)
        try:
            for n, ls in lines.items():
                kept = [l for l in (work / n).read_text().splitlines() if l not in ls]
                (work / n).write_text('\n'.join(kept) + '\n')
            hits = set(affected(work))
        finally:
            shutil.rmtree(work.parent, ignore_errors=True)
    return sorted(hits)


RANK = {'1': 0, 'n': 1, 'n+out': 1, 'cells': 1, 'n log n': 2, 'n*t': 3, 'n*t*k': 4, 'n^2': 5}


def plan_rank(pack, rec):
    """Worst declared complexity among the library functions the rules choose for a stored problem."""
    comp = {m.stem: json.loads(m.read_text())['complexity'] for m in (pack / 'templates' / 'lib').glob('*.json')}
    d = general.engine_for(rec, rec['facts'], pack)
    return max((RANK[comp[f]] for _, f in d.db.get('uses', set()) if f in comp), default=0)


def complexity_regressions(old_pack, new_pack):
    """Stored problems whose chosen functions got a worse declared complexity (selection rules must not regress)."""
    worse = []
    for f in sorted(solved_dir(new_pack).glob('*.json')):
        new_rec = json.loads(f.read_text())
        old_f = solved_dir(old_pack) / f.name
        old_rec = json.loads(old_f.read_text()) if old_f.exists() else None
        if old_rec is None:
            continue
        before, after = plan_rank(old_pack, old_rec), plan_rank(new_pack, new_rec)
        if after > before:
            worse.append((new_rec['id'], 'complexity', f'chosen functions went from rank {before} to {after}'))
    return worse


# Glue whitelist. Glue may only call the chosen library functions and builtins whose cost is known;
# anything linear (library calls, sum/sorted/join, `in` on a non-literal) may only run outside loops.
CONSTANT_CALLS = {'abs', 'int', 'bool', 'len', 'str', 'float', 'ValueError'}
LINEAR_CALLS = {'sum', 'max', 'min', 'any', 'all', 'sorted', 'list', 'set', 'tuple', 'dict', 'range', 'enumerate', 'zip', 'reversed'}
CONSTANT_METHODS = {'lower', 'upper', 'isalpha', 'isdigit', 'isupper', 'islower', 'isspace', 'isalnum', 'isascii'}
LINEAR_METHODS = {'join', 'fromkeys'}
LOOPS = ('For', 'ListComp', 'SetComp', 'DictComp', 'GeneratorExp')


def glue_violations(source, library):
    """Problems with the generated solve(): calls outside the whitelist, linear work inside a loop,
    loops nested more than once, while loops, nested function definitions or recursion."""
    import ast
    tree = ast.parse(source)
    solve = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'solve'), None)
    if solve is None:
        return ['no solve()']
    # the stages of a staged problem that are not seq_fold are rendered as functions _stageI(...) called once from solve(); they are
    # glue like solve() itself (checked with the same rules), not library functions
    stage_fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and STAGE_FN.match(n.name)]
    library = set(library) | {n.name for n in stage_fns}
    roots = [solve] + stage_fns
    out = []

    def is_sequence_expr(node):
        return (isinstance(node, (ast.List, ast.ListComp, ast.Tuple, ast.JoinedStr, ast.SetComp, ast.Set, ast.Dict, ast.DictComp))
                or (isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)))
                or (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('list', 'str', 'tuple', 'sorted', 'set', 'dict')))
    # names that hold sequences somewhere in solve(): growing them by `x = x + ...` inside a loop copies them
    seq_names = {t.id for root in roots for n in ast.walk(root) if isinstance(n, ast.Assign) and is_sequence_expr(n.value)
                 for t in n.targets if isinstance(t, ast.Name)}

    def fixed_size(node):
        return isinstance(node, (ast.Tuple, ast.List, ast.Set)) or (isinstance(node, ast.Constant))

    def literal(node):
        return isinstance(node, ast.Constant) or (isinstance(node, (ast.Tuple, ast.List, ast.Set)) and all(isinstance(e, ast.Constant) for e in node.elts))

    def visit(node, depth):
        if isinstance(node, (ast.While, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node is not solve:
            out.append(f'{type(node).__name__} not allowed in glue (line {node.lineno})')
            return
        if type(node).__name__ in LOOPS:
            # the outermost iterable is evaluated once, before the loop starts
            first_iter = node.iter if isinstance(node, ast.For) else node.generators[0].iter
            visit(first_iter, depth)
            depth += 1 if isinstance(node, ast.For) else len(node.generators)  # each `for` clause is one more level
            if depth > 1:
                out.append(f'loops nested {depth} deep (line {node.lineno})')
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.comprehension):
                    for part in [child.target, *child.ifs] + ([] if child.iter is first_iter else [child.iter]):
                        visit(part, depth)
                elif child is not first_iter:
                    visit(child, depth)
            return
        if isinstance(node, ast.Lambda):
            for child in ast.iter_child_nodes(node):
                visit(child, depth + 1)  # a lambda body runs once per element
            return
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                name = f.id
                if name in library or name in LINEAR_CALLS:
                    if depth and not (name in LINEAR_CALLS and node.args and all(fixed_size(a) for a in node.args)):
                        out.append(f'{name}() inside a loop (line {node.lineno})')
                elif name not in CONSTANT_CALLS:
                    out.append(f'call to {name}() not allowed in glue (line {node.lineno})')
            elif isinstance(f, ast.Attribute):
                if f.attr in LINEAR_METHODS:
                    if depth:
                        out.append(f'.{f.attr}() inside a loop (line {node.lineno})')
                elif f.attr not in CONSTANT_METHODS:
                    out.append(f'method .{f.attr}() not allowed in glue (line {node.lineno})')
            else:
                out.append(f'indirect call not allowed in glue (line {node.lineno})')
        if isinstance(node, ast.Assign) and depth and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            grows = isinstance(node.value, ast.BinOp) and any(isinstance(x, ast.Name) and x.id == name for x in ast.walk(node.value))
            if grows and (name in seq_names or any(is_sequence_expr(x) for x in ast.walk(node.value))):
                out.append(f'{name} = ... {name} ... inside a loop copies it each time (line {node.lineno}); use += or a library function')
        if isinstance(node, ast.BinOp) and depth and isinstance(node.op, ast.Mult):
            for seq, times in ((node.left, node.right), (node.right, node.left)):
                if is_sequence_expr(seq) and not isinstance(times, ast.Constant):
                    out.append(f'sequence repeated a non-constant number of times inside a loop (line {node.lineno})')
        if isinstance(node, ast.Compare) and depth:
            for op, right in zip(node.ops, node.comparators):
                if isinstance(op, (ast.In, ast.NotIn)) and not literal(right):
                    out.append(f"'in' on a non-literal inside a loop (line {node.lineno})")
        for child in ast.iter_child_nodes(node):
            visit(child, depth)

    for root in roots:
        for stmt in root.body:
            visit(stmt, 0)
    return out


def reference_compat(old_pack, new_pack):
    """An extended reference must give the same answers as before on every stored problem (random inputs),
    so that changing a reference cannot silently change what the stored problems mean."""
    import subprocess, sys
    changed = {p.name for p in (new_pack / 'templates' / 'reference').glob('*.py.j2')
               if not (old_pack / 'templates' / 'reference' / p.name).exists()
               or (old_pack / 'templates' / 'reference' / p.name).read_text() != p.read_text()}
    if not changed:
        return []
    broken = []
    for f in sorted(solved_dir(old_pack).glob('*.json')):
        rec = json.loads(f.read_text())
        old_ref = general.build(rec, rec['facts'], old_pack, reference=True)
        new_ref = general.build(rec, rec['facts'], new_pack, reference=True)
        inputs = random_inputs(rec)
        try:
            with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fa, tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as fr:
                json.dump(inputs, fa); fr.write(OUTPUTS)
            outs = []
            for module in (old_ref, new_ref):
                proc = subprocess.run([sys.executable, '-I', fr.name, str(module), fa.name], capture_output=True, text=True, timeout=120)
                outs.append(json.loads(proc.stdout) if proc.returncode == 0 else None)
        finally:
            shutil.rmtree(old_ref.parent, ignore_errors=True); shutil.rmtree(new_ref.parent, ignore_errors=True)
            Path(fa.name).unlink(missing_ok=True); Path(fr.name).unlink(missing_ok=True)
        if outs[1] is None:
            broken.append((rec['id'], 'reference_changed', 'the new reference crashes'))
            continue
        for args, a, b in zip(inputs, *outs):
            if a[0] == 'ok' and a != b:
                broken.append((rec['id'], 'reference_changed', f'solve(*{json.dumps(args)[:100]}): old reference {a[1]!r}, new {b[1]!r}'))
                break
    return broken


STAGE_FN = re.compile(r'^_stage\d+$')


def chosen_functions(source):
    import ast
    return {n.name for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name != 'solve' and not STAGE_FN.match(n.name)}


OUTPUTS = r"""
import importlib.util, json, sys
sys.setrecursionlimit(100000)
spec = importlib.util.spec_from_file_location("m", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
out = []
for args in json.load(open(sys.argv[2])):
    try:
        out.append(["ok", json.loads(json.dumps(m.solve(*args)))])
    except Exception as e:
        out.append(["error", type(e).__name__])
print(json.dumps(out))
"""


def _pools(rec):
    tests = [t['args'] for t in rec['tests'] if len(json.dumps(t['args'])) < 20000]
    kinds = {f[1]: f[2] for f in rec['facts'] if f[0] == 'arg'}
    pools = []
    for i, name in enumerate(general.params_of(rec['signature'])):
        pools.append((kinds.get(name), [t[i] for t in tests if i < len(t)]))
    return pools, any(f[0] == 'items' for f in rec['facts'])


def _make_input(pools, knap, length, rng, offset=0, scale=1, min_len=0, square_grid=False):
    """One argument list: lists/strings of `length` elements, grids `length` rows (at most 6 columns),
    interval coordinates shifted by `offset`, integer list values multiplied by `scale` (never for knapsack)."""
    args = []
    for kind, vals in pools:
        if kind == 'grid' or (vals and all(isinstance(v, list) and all(isinstance(r, str) for r in v) for v in vals if v)):
            chars = sorted({ch for g in vals for row in g for ch in row}) or ['.']
            if square_grid:  # timing: about sqrt(length) x sqrt(length) cells, so the grid really grows
                side = max(1, int(length ** 0.5))
                h, w = side, side
            else:  # differential: `length` rows (at most 40), narrow
                h, w = min(length, 40), rng.randint(1, 6)
            args.append([''.join(rng.choice(chars) for _ in range(w)) for _ in range(h)])
        elif kind == 'interval_list' or (vals and any(isinstance(v, list) and v and isinstance(v[0], list) for v in vals)):
            args.append([[offset + s, offset + s + rng.randint(min_len, 6)] for s in (rng.randint(0, 25) for _ in range(length))])
        elif kind == 'string' or (vals and all(isinstance(v, str) for v in vals)):
            chars = sorted({ch for v in vals for ch in v}) or ['a']
            args.append(''.join(rng.choice(chars) for _ in range(length)))
        elif kind == 'int_list' or (vals and all(isinstance(v, list) for v in vals)):
            pool = [x for v in vals for x in v if isinstance(x, int) and not isinstance(x, bool)] or [0]
            n = min(length, 6) if knap else length
            args.append([rng.choice(pool) * (1 if knap else scale) for _ in range(n)])
        else:
            pool = [v for v in vals if isinstance(v, int) and not isinstance(v, bool)] or [0]
            lo, hi = min(pool), max(pool)
            if knap:
                lo, hi = max(min(lo, 0), -1), min(max(hi, 0), 14)
            args.append(rng.choice(pool) if rng.random() < 0.3 and (not knap or hi >= max(pool)) else rng.randint(lo, max(lo, hi)))
    return args


def random_inputs(rec, cases=45, seed=0):
    """Random inputs shaped like the problem's tests. Every length 0..20 once (list length, string length, grid rows),
    then random lengths up to 60, 60..200 and 200..500; a third of the cases shift interval coordinates far away
    (10^6 or 10^9) and scale integer list values by 1000. Knapsack item lists stay at most 6 long and targets at most 14,
    because its reference enumerates. Values are drawn from the values seen in the tests."""
    import random
    rng = random.Random(seed)
    pools, knap = _pools(rec)
    # lengths 0..20, once with non-empty intervals (so filters keep exactly that many) and once with any intervals
    out = [_make_input(pools, knap, n, rng, min_len=1) for n in range(21)] + [_make_input(pools, knap, n, rng) for n in range(21)]
    for i in range(cases):
        length = rng.randint(*((0, 60), (60, 200), (200, 500))[i % 3])
        far = i % 3 == 2 or rng.random() < 0.2
        out.append(_make_input(pools, knap, length, rng, offset=rng.choice([10 ** 6, 10 ** 9]) if far else 0, scale=1000 if far else 1))
    return out


TIMER = r"""
import importlib.util, json, sys, time
sys.setrecursionlimit(100000)
spec = importlib.util.spec_from_file_location("m", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
args = json.load(open(sys.argv[2]))
best = float("inf")
try:
    for _ in range(3):
        t = time.perf_counter(); res = m.solve(*args); best = min(best, time.perf_counter() - t)
        if best > 2: break
    print(json.dumps({"seconds": best, "out": len(res) if isinstance(res, (list, str, tuple, dict)) else 0}))
except Exception as e:
    print(json.dumps({"error": type(e).__name__}))
"""


def problem_cost(pack, rec, n1=2000, n2=8000, attempts=3):
    """problem_cost_once, repeated: a violation counts only if every attempt shows it (timing on a busy
    machine is noisy; a real superlinear slowdown shows up every time)."""
    result = None
    for _ in range(attempts):
        result = problem_cost_once(pack, rec, n1, n2)
        if result is None:
            return None
    return result


def problem_cost_once(pack, rec, n1=2000, n2=8000):
    """Time the generated solution on scaled inputs; growth must fit the worst declared complexity of the
    library functions it uses ('n' when it uses none). Returns a violation string or None."""
    import math, random, subprocess, sys
    if rec.get('cost_exempt'):
        return None
    module = general.build(rec, rec['facts'], pack)
    ranks = {v: k for k, v in RANK.items()}
    comp = {m.stem: json.loads(m.read_text())['complexity'] for m in (pack / 'templates' / 'lib').glob('*.json')}
    used = chosen_functions(module.read_text())
    declared = max((comp[f] for f in used if f in comp), key=lambda c: RANK[c], default='n')
    # output-sensitive functions (n+out): the work is input + output, and the declared output bound must hold on the timed inputs
    bounds = [lib_check.output_bound(json.loads((pack / 'templates' / 'lib' / f'{f}.json').read_text())) for f in used if comp.get(f) == 'n+out']
    bounds = [b for b in bounds if isinstance(b, tuple)]
    pools, knap = _pools(rec)
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as ft:
        ft.write(TIMER)

    fixed = _make_input(pools, False, 1, random.Random(0))  # scalar arguments are the same at both sizes

    def timed(n, seed, far):
        args = _make_input(pools, False, n, random.Random(seed), offset=10 ** 6 if far else 0, scale=1000 if far else 1, square_grid=True)
        args = [a if isinstance(a, (list, str)) else (50 if knap else b) for a, b in zip(args, fixed)]  # only sequences grow
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fa:
            json.dump(args, fa)
        try:
            p = subprocess.run([sys.executable, '-I', ft.name, str(module), fa.name], capture_output=True, text=True, timeout=60)
            r = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {'error': 'crash'}
        except subprocess.TimeoutExpired:
            r = {'seconds': math.inf}
        finally:
            Path(fa.name).unlink(missing_ok=True)
        if bounds and 'error' not in r:
            insize = lib_check.input_size(args)
            r['work'] = insize + r.get('out', 0)
            if any(r.get('out', 0) > f * insize + c for f, c in bounds):
                r = {'error': 'output_bound'}  # these inputs break the declared output bound (a precondition): nothing to measure
        return r
    try:
        for far in (False, True):  # values near the tests' values, then far away / large (value-dependent paths)
            a, b = n1, n2
            for attempt in range(3):
                r1, r2 = timed(a, 1, far), timed(b, 2, far)
                if 'error' in r1 or 'error' in r2:
                    break  # these inputs violate a precondition of this problem; nothing to measure
                if r2['seconds'] >= 0.02 or attempt == 2:
                    break
                a, b = a * 4, b * 4
            if 'error' in r1 or 'error' in r2:
                continue
            t1, t2 = r1['seconds'], r2['seconds']
            where = 'far/large values' if far else 'values like the tests'
            if not math.isfinite(t2) or t2 > 5:
                return f'solution takes {t2:.2f}s at n={b} ({where})'
            scale = b / a
            if bounds and r2.get('work', 0) > 1.5 * max(r1.get('work', 1), 1):
                scale = r2['work'] / max(r1['work'], 1)  # growth against input + output size
            exp = math.log(max(t2, 1e-6) / max(t1, 1e-6)) / math.log(scale)
            if t2 >= 0.02 and exp > lib_check.EXPONENT[declared]:
                return f'solution grows like n^{exp:.2f} on {where} but its functions declare {declared}'
        return None
    finally:
        Path(ft.name).unlink(missing_ok=True)
        shutil.rmtree(module.parent, ignore_errors=True)


def reference_on_tests(pack, rec):
    """The reference implementation must give the stored answer on the problem's tests; tests it cannot finish
    (timeout after 2 s, recursion limits, other exceptions) are skipped."""
    import subprocess, sys
    reference = general.build(rec, rec['facts'], pack, reference=True)
    tests = [t for t in rec['tests'] if len(json.dumps(t['args'])) < 5000]
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fh:
        json.dump(tests, fh)
    try:
        p = subprocess.run([sys.executable, '-I', str(ROOT_DIR / 'grow_runner.py'), str(reference), fh.name, '2'],
                           capture_output=True, text=True, timeout=2 * len(tests) + 30)
        res = json.loads(p.stdout.strip().splitlines()[-1]).get('results', [])
    except subprocess.TimeoutExpired:
        return None
    finally:
        Path(fh.name).unlink(missing_ok=True); shutil.rmtree(reference.parent, ignore_errors=True)
    for t, r in zip(tests, res):
        if not r['ok'] and r['error'] is None:  # a wrong value; exceptions mean the slow reference cannot handle the size
            return f"reference fails solve(*{json.dumps(t['args'])[:100]}): got {r['got'] or r['error']}, expected {json.dumps(t['expected'])[:60]}"
    return None


def differential(pack, rec):
    """Compare the generated solution with the schema's reference implementation on random inputs.
    Returns a description of the first disagreement, or None. Inputs on which the reference raises are skipped."""
    import subprocess, sys
    solution = general.build(rec, rec['facts'], pack)
    reference = general.build(rec, rec['facts'], pack, reference=True)
    inputs = random_inputs(rec)
    try:
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fa, tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as fr:
            json.dump(inputs, fa); fr.write(OUTPUTS)
        results = []
        for module in (solution, reference):
            p = subprocess.run([sys.executable, '-I', fr.name, str(module), fa.name], capture_output=True, text=True, timeout=120)
            if p.returncode:
                return f"{module.name} crashed (exit {p.returncode}): {(p.stderr.strip().splitlines() or ['no output'])[-1][:150]}"
            results.append(json.loads(p.stdout))
    except subprocess.TimeoutExpired:
        return 'differential run timed out'
    finally:
        shutil.rmtree(solution.parent, ignore_errors=True); shutil.rmtree(reference.parent, ignore_errors=True)
        Path(fa.name).unlink(missing_ok=True); Path(fr.name).unlink(missing_ok=True)
    for args, got, want in zip(inputs, *results):
        if want[0] == 'error':
            continue
        if got != want:
            return f'solve(*{json.dumps(args)[:120]}) gave {got[1]!r}, reference {want[1]!r}'
    return None


def library_text(pack):
    lines = []
    for meta in sorted((pack / 'templates' / 'lib').glob('*.json')):
        m = json.loads(meta.read_text())
        sig = (pack / 'templates' / 'lib' / f'{meta.stem}.py').read_text().splitlines()[0]
        lines.append(f"- {sig[4:-1]}  [{m['complexity']}]: {' '.join(m['doc'].split())}")
    return '\n'.join(lines)


def pack_text(pack):
    parts = []
    parts.append('=== algorithm library (templates/lib/*.py, append-only; metadata in <name>.json) ===\n' + library_text(pack))
    for rel in ['vocab.json', 'rules.dl', 'algorithms.dl', 'learned.dl', 'templates/solution.py.j2',
                *sorted(str(p.relative_to(pack)) for p in (pack / 'templates/schemas').glob('*.py.j2'))]:
        parts.append(f'=== {rel} ===\n{(pack / rel).read_text()}')
    return '\n'.join(parts)


LAYERS_NOTE = 'Layers: algorithms are standalone functions in templates/lib/<name>.py (one public function, standard library only, no Jinja\nmarkers) with metadata templates/lib/<name>.json:\n  {"doc", "complexity": one of 1 | n | n+out | n log n | n^2 | n*t | n*t*k | cells (n+out = linear in input plus output, needs "output_size": {"max_factor": F, "doc": why len(output) <= F*len(input)+16}), "role": <what the function does, e.g. pairs>,\n   "drives": [roles whose size drives the cost], "requires": [[role, positive|nonnegative|distinct|sorted|nonempty], ...],\n   "generator": [argspec...], "sizes": [N1, N2], "tests": [>= 5 {"args", "expected"}]}\nargspec kinds: int_list{lo,hi,distinct,sorted} (n elements), intervals{lo,hi,maxlen} (n pairs), string{chars} (n characters),\ngrid{chars} (~sqrt(n) x sqrt(n)), scaled_int{factor} (an integer of magnitude factor*n that drives the cost), value{value} (fixed),\npy{src} (a callable). The generator must make the inputs grow with n through those kinds: a generator of fixed values measures nothing\nand is rejected ("generator does not scale"). Complexity 1 (constant time) needs no generator sizes. The library is append-only.\nSelection (costs.dl): algorithms.dl declares candidate(P,F); a candidate is feasible only when every role in its "drives" is bound by a\nbinds(P,Role,A) rule to a parameter A whose size class fits the complexity. Existing binds roles: seq (iterate), grid (grid or int_matrix\nparameter), items, target, terms. A function driven by something else (an integer parameter, a range bound...) needs a new role and a rule\nin learned.dl such as `binds(P,people,A) :- people(P,A).`; otherwise the plan is refused as "too_slow: no feasible function for role R",\nwhich means the driver is unbound, not that the function is slow. Sizes come from size(P,A,Class) facts (statement bounds; else medium\nfor sequences, small for item lists, the tests\' magnitude for integers); guarantees(P,A,Cond) facts state what the statement promises,\nand a function\'s "requires" must be guaranteed (or the plan is refused as unmet_precondition). The fastest feasible function per role wins.\nsolution.py.j2 inlines the chosen functions; schema templates are thin glue that call them. Put algorithmic code in a new library function,\nnever inline in a schema template. Glue may only call the chosen library functions and simple builtins (len, sum, max, min, sorted, any, all,\nabs, int, str, ...), with loops nested at most once and no linear work inside a loop. Every schema has a slow, obviously correct reference implementation\n in templates/reference/<schema>.py.j2; a new schema must come with one, and when you extend a schema with new facts extend\nits reference too (an extended reference must keep the old answers on every stored problem). Regression compares each stored problem: its\ngenerated code against its reference on random inputs, and times it on scaled inputs. Facts describing a problem must use predicates from\nvocab.json (add new ones there with documentation); answer_type rules (types.dl) must cover a new schema\'s output type, added in learned.dl.'


PROMPT = """You maintain a code generator. Problems are described by facts from vocab.json; Datalog rules
(rules.dl, learned.dl) derive a schema and its parameters; Jinja schema templates render the Python solution.
{layers}Datalog syntax: one rule per line ending in '.', literals pred(args), not pred(args) (stratified), A != B;
variables start uppercase; constants with uppercase/odd characters go in double quotes; `head(...) :- .` is a fact.
In templates, `relations.rows(pred, key)`, `relations.one(pred, key)` and `relations.has(pred, key, ...)` query
derived facts (rows include the problem id `key` as first column); `params` is the list of argument names.

Current pack:
{pack}

A problem that the current pack cannot handle:
signature: {signature}
statement: {statement}
example tests: {examples}
note from the translator: {note}
{feedback}
Extend the pack so this problem can be described and solved. First think of at least three nearby variants of
this problem (other constants, the opposite or a related condition, open versus closed bounds, a different
aggregate or output form, the same question over a different input) and make the extension cover them too:
parameterise along those axes, and prefer generalising an existing predicate or schema over adding a narrow new one.
Prefer the smallest general change, in this order:
(1) a new value or parameterised predicate in vocab.json plus template support, (2) new rules in learned.dl,
(3) a new library function with a uses rule in algorithms.dl, (4) a new schema template with its selection rule in learned.dl. Make additions general and parameterised
(for example a condition with a number argument rather than one fixed constant), document them in vocab.json
so a translator can use them, and keep every existing behaviour unchanged. Generated code must keep the usual
optimal complexity: stored problems include large tests (around 10^5 elements) with a 10 second limit per test.

You have no tools: do not try to write files or run commands; put every file's complete content in your reply.
In vocab.json, a value list may contain the placeholders <int>, <char> and <param> (a parameter name).
Reply with only JSON:
{{"files": {{"<path>": "<complete new file content>", ...}},   // vocab.json, learned.dl, algorithms.dl, templates/schemas/*.py.j2, new templates/lib/<name>.py + .json
  "facts": [[...], ...],                                        // this problem's description in the extended vocabulary
  "variants": ["<nearby variant the extension also covers>", ...],
  "summary": "<one sentence>"}}"""


def ask(prompt, model):
    p = subprocess.run(['claude', '-p', '--model', model, '--tools', '', '--no-session-persistence', '--strict-mcp-config'],
                       input=prompt, capture_output=True, text=True, timeout=900, cwd=tempfile.gettempdir())
    try:
        return general.first_json_object(p.stdout)
    except ValueError:
        raise ValueError(f'no JSON in reply: {p.stdout[-300:]} {p.stderr[-200:]}') from None


def changes(pack, files):
    stats = {}
    for rel, new in files.items():
        old = (pack / rel).read_text() if (pack / rel).exists() else ''
        diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm='', n=0))
        stats[rel] = {'new_file': not old, 'added': sum(l.startswith('+') and not l.startswith('+++') for l in diff),
                      'removed': sum(l.startswith('-') and not l.startswith('---') for l in diff)}
    return stats


def new_lint_errors(old_pack, new_pack):
    """Lint errors of new_pack that the old pack did not already have (a proposal is not blamed for old findings)."""
    import general_lint
    old = set(general_lint.lint(old_pack)['errors'])
    return [e for e in general_lint.lint(new_pack)['errors'] if e not in old]


FIXED_FILES = 'rules.dl, types.dl, costs.dl, composition.dl, questions.dl, pack.json, templates/solution.py.j2, templates/composition.j2, solved/, rejected/'
LIB_KEYS = ('doc', 'complexity', 'role', 'drives', 'requires', 'generator', 'sizes', 'tests')


def precheck(pack, proposal, problem=None):
    """Cheap structural check of a growth proposal, before any engine run or test. Returns a list of EVERY missing piece
    found (so the model can fix them all in one round); empty means the proposal is complete enough to be tried.
      - files outside the editable set are named explicitly; library functions are append-only; vocab/metadata are valid JSON
      - every fact of the proposal uses a predicate / value / arity of the (new) vocab; new vocab predicates are documented
      - rule files parse; every body predicate of the new rules is a vocab/driver/head predicate (general_lint)
      - a new schema template has a reference template, a rule deriving schema(P,<name>) and an answer_type rule
      - a new library function has .py + .json, the metadata keys (role, drives, requires, generator, sizes, tests >= 5, output_size
        for n+out), a function of that name, no Jinja markers, a candidate(P,<name>) rule, and a binds rule for each role it drives"""
    import general_lint
    pack = Path(pack)
    files = proposal.get('files') or {}
    out = []
    if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
        return ['"files" must map each path to the complete file content (a string)']
    outside = sorted(p for p in files if not EDITABLE.match(p))
    if outside:
        out.append(f'files outside the editable set: {outside}. Editable: vocab.json, learned.dl, algorithms.dl, templates/schemas/<name>.py.j2, '
                   f'templates/reference/<name>.py.j2, templates/lib/<name>.py and .json. Fixed: {FIXED_FILES}')
    editable = {k: v for k, v in files.items() if EDITABLE.match(k)}
    out += [b for b in edit_violations(pack, editable) if not b.startswith('may not edit')]
    # JSON files must parse
    parsed = {}
    for rel, text in editable.items():
        if rel.endswith('.json'):
            try:
                parsed[rel] = json.loads(text)
            except ValueError as exc:
                out.append(f'{rel} is not valid JSON: {str(exc)[:80]}')
    work = Path(tempfile.mkdtemp(prefix='gprecheck_')) / 'pack'
    try:
        shutil.copytree(pack, work, ignore=shutil.ignore_patterns('solved', 'rejected', '__pycache__'))
        for rel, text in editable.items():
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            (work / rel).write_text(text if text.endswith('\n') else text + '\n')
        # rules
        rules = None
        try:
            rules = general_lint.load_rules(work)
        except Exception as exc:  # noqa: BLE001 - a rule file that does not parse
            out.append(f'a rule file does not parse: {type(exc).__name__}: {str(exc)[:120]}')
        if rules is not None:
            try:
                out += ['static rule check (lint): ' + e for e in new_lint_errors(pack, work)]
            except Exception as exc:  # noqa: BLE001
                out.append(f'static rule check (lint) crashed: {type(exc).__name__}: {str(exc)[:120]}')
        # vocabulary
        voc = None
        if 'vocab.json' in parsed:
            v = parsed['vocab.json']
            if not isinstance(v, dict) or not isinstance(v.get('predicates'), dict):
                out.append('vocab.json must be {"_doc": ..., "predicates": {<pred>: {"args": [...], "doc": ...}}}')
            else:
                voc = v['predicates']
                old = general.vocab(pack)
                for name, spec in voc.items():
                    if not isinstance(spec, dict) or not isinstance(spec.get('args'), list):
                        out.append(f'vocab predicate {name} needs "args": [...]')
                    elif name not in old and not str(spec.get('doc', '')).strip():
                        out.append(f'new vocab predicate {name} has no "doc" (document it so a translator can use it)')
                lost = sorted(set(old) - set(voc))
                if lost:
                    out.append(f'vocab.json drops existing predicates {lost[:6]}; keep them')
        else:
            voc = general.vocab(pack)
        facts = proposal.get('facts')
        if not isinstance(facts, list) or not facts:
            out.append('"facts" (this problem\'s description in the extended vocabulary) is missing or empty')
        elif problem and problem.get('signature') and voc is not None:
            out += ['facts: ' + b for b in general.validate(facts, general.params_of(problem['signature']), voc)]
        # new schemas
        heads = [(h, b) for _, h, b in rules] if rules is not None else []
        def unq(x): return x.strip('"')
        for rel in sorted(editable):
            if rel.startswith('templates/schemas/') and not (pack / rel).exists():
                name = Path(rel).name[:-len('.py.j2')]
                if not any(h[0] == 'schema' and len(h[1]) == 2 and unq(h[1][1]) == name for h, _ in heads):
                    out.append(f'new schema {name}: no rule derives schema(P,{name}) (add a selection rule in learned.dl)')
                if not any(h[0] == 'answer_type' and any(k == 'pos' and p == 'schema' and len(a) == 2 and unq(a[1]) == name for k, p, a in b) for h, b in heads):
                    out.append(f'new schema {name}: no answer_type rule for it (answer_type(P,<type>) :- schema(P,{name}), ... in learned.dl)')
        # new library functions
        stems = sorted({Path(p).stem for p in editable if p.startswith('templates/lib/') and not (pack / p).exists()})
        binds_roles = {unq(h[1][1]) for h, _ in heads if h[0] == 'binds' and len(h[1]) == 3}
        for stem in stems:
            meta = parsed.get(f'templates/lib/{stem}.json')
            src = editable.get(f'templates/lib/{stem}.py')
            if src is not None:
                if not re.search(rf'^def {stem}\(', src, re.M):
                    out.append(f'library function {stem}: templates/lib/{stem}.py defines no `def {stem}(`')
                if any(m in src for m in ('{{', '{%', '{#')):
                    out.append(f'library function {stem}: .py contains Jinja markers')
            if isinstance(meta, dict):
                gaps = [k for k in LIB_KEYS if k not in meta]
                if gaps:
                    out.append(f'library function {stem}: metadata lacks {gaps} (needs {list(LIB_KEYS)})')
                if meta.get('complexity') not in lib_check.EXPONENT:
                    out.append(f'library function {stem}: complexity must be one of {sorted(lib_check.EXPONENT)}')
                else:
                    bound = lib_check.output_bound(meta)
                    if isinstance(bound, str):
                        out.append(f'library function {stem}: {bound}')
                if meta.get('complexity') != '1':
                    sz = meta.get('sizes')
                    if 'generator' in meta and not meta['generator']:
                        out.append(f'library function {stem}: generator is empty')
                    if 'sizes' in meta and not (isinstance(sz, list) and len(sz) == 2 and all(isinstance(x, int) for x in sz) and sz[1] >= 3 * sz[0]):
                        out.append(f'library function {stem}: sizes must be [N1, N2] with N2 >= 3*N1')
                tests = meta.get('tests')
                if 'tests' in meta and not (isinstance(tests, list) and len(tests) >= 5 and all(isinstance(t, dict) and 'args' in t and 'expected' in t for t in tests)):
                    out.append(f'library function {stem}: tests must be a list of >= 5 {{"args", "expected"}}')
                for k in ('drives', 'requires'):
                    if k in meta and not isinstance(meta[k], list):
                        out.append(f'library function {stem}: {k} must be a list')
                for r in meta.get('drives') or []:
                    if isinstance(r, str) and r not in binds_roles:
                        out.append(f'library function {stem}: it drives role {r!r} but no rule binds(P,{r},A) exists (add one in learned.dl)')
            elif meta is not None:
                out.append(f'templates/lib/{stem}.json must be a JSON object')
            if not any(h[0] == 'candidate' and len(h[1]) == 2 and unq(h[1][1]) == stem for h, _ in heads):
                out.append(f'library function {stem}: no candidate(P,{stem}) rule in algorithms.dl, so it can never be chosen')
    finally:
        shutil.rmtree(work.parent, ignore_errors=True)
    return out


def try_proposal(pack, problem, proposal):
    """Apply to a copy; returns (ok, info, copy_dir)."""
    files = proposal.get('files') or {}
    missing = precheck(pack, proposal, problem)
    if missing:
        return False, f'precheck found {len(missing)} problem(s): ' + ' | '.join(f'({i}) {m}' for i, m in enumerate(missing, 1)), None
    work = Path(tempfile.mkdtemp(prefix='ggrow_')) / 'pack'
    shutil.copytree(pack, work)
    for rel, text in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text if text.endswith('\n') else text + '\n')
    try:
        json.loads((work / 'vocab.json').read_text())
        found = new_lint_errors(pack, work)
        if found:
            return False, 'static rule check (lint) rejected the proposal: ' + ' | '.join(found[:5]), work
        visible, hidden = split(problem['tests'])
        rec = general.evaluate(problem, proposal.get('facts') or [], work)
    except Exception as exc:  # noqa: BLE001 - template/rule errors become feedback
        return False, f'{type(exc).__name__}: {str(exc)[:300]}', work
    if rec['status'] != 'solved':
        return False, rec, work
    remember(work, problem, proposal.get('facts') or [])  # the new problem goes through every check too
    try:
        broken = regression(work, only={problem['id']})      # library checks + rejection corpus + this problem only (cheap, fails fast)
        if not broken:
            broken = complexity_regressions(pack, work) + reference_compat(pack, work)
        if not broken:                                        # everything whose generated code changed (exact, see affected)
            broken = regression(work, only={problem['id']} | set(affected(work)))  # (the corpus is cheap: it runs again here)
    except Exception as exc:  # noqa: BLE001 - a check that crashes on the proposal is feedback, not a crash of the loop
        return False, f'checks crashed on this proposal: {type(exc).__name__}: {str(exc)[:200]}', work
    if broken:
        return False, {'regression_broken': broken[:5]}, work
    return True, rec, work


def feedback_text(problem, info):
    if isinstance(info, str):
        return f'\nYour previous proposal failed: {info}\nFix it.\n'
    if 'regression_broken' in info:
        rej = [b for b in info['regression_broken'] if b[1] == 'rejection']
        if rej:
            return (f"\nYour previous proposal made descriptions pass that must stay rejected (the rejection corpus, packs/general/rejected): {rej}\n"
                    'Keep every error(...) rule reachable; do not remove or weaken a check.\n')
        return f"\nYour previous proposal broke previously solved problems: {info['regression_broken']}\nKeep existing behaviour.\n"
    msg = f"status {info['status']}: {info.get('reason') or ''}"
    if info.get('first_failure'):
        visible, _ = split(problem['tests'])
        msg += f" ({info['passed']}/{info['total']} tests passed; a failing case returned {info['first_failure']})"
    return f'\nYour previous proposal did not solve the problem: {msg}\nGenerated code was:\n{info.get("source", "")[:3000]}\nFix it.\n'


def grow_one(pack, problem, model, max_rounds, note):
    visible, _ = split(problem['tests'])
    examples = '; '.join(f"solve(*{json.dumps(t['args'])[:200]}) == {json.dumps(t['expected'])[:80]}" for t in visible[:6])
    rec = {'id': problem['id'], 'rounds': []}
    feedback = ''
    for r in range(1, max_rounds + 1):
        t0 = time.time()
        try:
            proposal = ask(PROMPT.format(layers=LAYERS_NOTE, pack=pack_text(pack), signature=problem['signature'], statement=problem['statement'],
                                         examples=examples, note=note or 'none', feedback=feedback), model)
        except Exception as exc:  # noqa: BLE001
            rec['rounds'].append({'error': str(exc)[:200]}); continue
        ok, info, work = try_proposal(pack, problem, proposal)
        rec['rounds'].append({'seconds': round(time.time() - t0, 1), 'ok': ok, 'summary': proposal.get('summary'),
                              'changes': changes(pack, proposal.get('files') or {}),
                              'info': info if isinstance(info, str) else {k: v for k, v in info.items() if k != 'source'}})
        if ok:
            backup = Path(tempfile.mkdtemp(prefix='ggrow_backup_')) / 'pack'
            shutil.copytree(pack, backup)
            for rel in [*proposal['files'], f"solved/{problem['id']}.json"]:
                (pack / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(work / rel, pack / rel)
            shutil.rmtree(work.parent, ignore_errors=True)
            changed = set(affected(pack)) | {problem['id']}
            after = regression(pack, only=changed)
            if not after:
                update_deps(pack, changed)
            if after:  # should not happen (the copy passed the same checks); roll back rather than keep a broken pack
                shutil.rmtree(pack); shutil.copytree(backup, pack)
                shutil.rmtree(backup.parent, ignore_errors=True)
                rec['rounds'][-1]['info'] = {'rolled_back': after[:5]}
                feedback = feedback_text(problem, {'regression_broken': after[:5]})
                continue
            shutil.rmtree(backup.parent, ignore_errors=True)
            rec['status'] = 'grown'
            rec['facts'] = proposal['facts']
            return rec
        if work:
            shutil.rmtree(work.parent, ignore_errors=True)
        feedback = feedback_text(problem, info)
    rec['status'] = 'failed'
    return rec


REPAIR = """You maintain a code generator. Problems are described by facts from vocab.json; Datalog rules
(rules.dl, learned.dl) derive a schema and its parameters; Jinja schema templates render the Python solution.
{layers}In templates, relations.rows/one/has(pred, key, ...) query derived facts; `params` is the list of argument names.

Current pack:
{pack}

These stored problems now fail (their facts are fixed; tests include large inputs with a 10 second limit per test):
{failing}
{feedback}
Change the schema templates (and learned.dl / vocab.json only if needed) so that every stored problem passes,
including the large tests: use algorithms with the usual optimal complexity for each case. Keep all other behaviour.
You have no tools: do not try to write files or run commands; put every file's complete content in your reply.
Reply with only JSON: {{"files": {{"<path>": "<complete new content>", ...}}, "summary": "<one sentence>"}}"""


def repair(pack, model, max_rounds):
    log, feedback = [], ''
    for r in range(1, max_rounds + 1):
        broken = regression(pack)
        if not broken:
            return log
        failing = []
        for pid, status, why in broken:
            rec = json.loads((solved_dir(pack) / f'{pid}.json').read_text())
            failing.append(f"- {pid} {rec['signature']}: {rec['statement'][:300]}\n  facts: {json.dumps(rec['facts'])}\n  failure: {status} {why}")
        t0 = time.time()
        try:
            proposal = ask(REPAIR.format(layers=LAYERS_NOTE, pack=pack_text(pack), failing='\n'.join(failing), feedback=feedback), model)
        except Exception as exc:  # noqa: BLE001
            log.append({'round': r, 'error': str(exc)[:200]}); continue
        files = proposal.get('files') or {}
        bad = edit_violations(pack, files)
        if bad:
            feedback = '\nRejected: ' + '; '.join(bad) + '\n'; continue
        work = Path(tempfile.mkdtemp(prefix='grepair_')) / 'pack'
        shutil.copytree(pack, work)
        for rel, text in files.items():
            (work / rel).write_text(text if text.endswith('\n') else text + '\n')
        try:
            still = regression(work) + complexity_regressions(pack, work)
        except Exception as exc:  # noqa: BLE001
            still = [('*', 'error', f'{type(exc).__name__}: {exc}'[:200])]
        log.append({'round': r, 'seconds': round(time.time() - t0, 1), 'summary': proposal.get('summary'),
                    'changes': changes(pack, files), 'still_broken': still[:5]})
        print(json.dumps(log[-1], ensure_ascii=False)[:800], flush=True)
        if not still:
            for rel in files:
                shutil.copy(work / rel, pack / rel)
        else:
            feedback = f'\nYour previous proposal left these failing: {still[:5]}\n'
        shutil.rmtree(work.parent, ignore_errors=True)
    return log


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    m = sub.add_parser('remember'); m.add_argument('log', type=Path); m.add_argument('problems', type=Path)
    sub.add_parser('check')
    sub.add_parser('lint')
    dp = sub.add_parser('deps'); dp.add_argument('--update', action='store_true'); dp.add_argument('--who')
    rp = sub.add_parser('repair'); rp.add_argument('--model', default='sonnet'); rp.add_argument('--max-rounds', type=int, default=3)
    g = sub.add_parser('grow'); g.add_argument('problems', type=Path); g.add_argument('--ids', nargs='*')
    g.add_argument('--model', default='sonnet'); g.add_argument('--max-rounds', type=int, default=3)
    g.add_argument('--notes', type=Path, help='log from general.py solve; its uncovered notes are passed on')
    g.add_argument('--log', type=Path)
    args = ap.parse_args()
    pack = PACK.resolve()
    if args.cmd == 'remember':
        probs = {p['id']: p for p in json.loads(args.problems.read_text())}
        n = 0
        for r in json.loads(args.log.read_text()):
            if r['status'] == 'solved':
                remember(pack, probs[r['id']], r['facts']); n += 1
        print('remembered', n, 'regression broken:', regression(pack))
        return
    if args.cmd == 'repair':
        repair(pack, args.model, args.max_rounds)
        broken = regression(pack)
        print('regression ok' if not broken else broken)
        return
    if args.cmd == 'deps':
        if args.update:
            print('updated', len(update_deps(pack)))
        if args.who:
            print('\n'.join(who(pack, args.who)))
        if not args.update and not args.who:
            print(json.dumps(affected(pack), indent=1))
        return
    if args.cmd == 'lint':
        import general_lint
        raise SystemExit(1 if general_lint.main(pack)['errors'] else 0)
    if args.cmd == 'check':
        broken = regression(pack)
        print('regression ok' if not broken else broken)
        n = len(list(rejected_dir(pack).glob('*.json')))
        rej = [b for b in broken if b[1] == 'rejection']
        print(f'rejections ok ({n} cases)' if not rej else f'rejections BROKEN ({len(rej)} of {n} cases)')
        missing = uncovered_errors(pack)
        if missing:
            print(f'note: {len(missing)} error constants have no rejection case: {missing}')
        return
    probs = json.loads(args.problems.read_text())
    if args.ids:
        probs = [p for p in probs if p['id'] in args.ids]
    notes = {}
    if args.notes:
        for r in json.loads(args.notes.read_text()):
            parts = [r.get('uncovered') or r.get('reason'), r.get('near') and 'rule engine: ' + r['near'], r.get('why') and '; '.join(r['why'])]
            notes[r['id']] = ' | '.join(str(x) for x in parts if x)
    log = []
    for p in probs:
        rec = grow_one(pack, p, args.model, args.max_rounds, notes.get(p['id']))
        log.append(rec)
        print(json.dumps({k: rec[k] for k in ('id', 'status')} | {'rounds': [{k: x.get(k) for k in ('ok', 'seconds', 'summary', 'changes')} for x in rec['rounds']]}, ensure_ascii=False), flush=True)
        if args.log:
            args.log.write_text(json.dumps(log, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
