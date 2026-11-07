"""Algorithm library checks: packs/general/templates/lib/<name>.py + <name>.json.

Metadata (<name>.json):
  {"doc": str, "complexity": "n" | "n log n" | "n^2" | "n*t" | "n*t*k" | "cells",
   "generator": [argspec, ...], "sizes": [N1, N2], "tests": [{"args": [...], "expected": ...}, ...]}
argspec (inputs that satisfy the function's preconditions, scaled by n):
  {"kind": "int_list", "lo": a, "hi": b, "distinct": bool, "sorted": bool}   n elements
  {"kind": "intervals", "lo": a, "hi": b, "maxlen": L}                       n pairs [s, e], s <= e
  {"kind": "grid", "chars": "10"}                                            about sqrt(n) x sqrt(n)
  {"kind": "value", "value": v}                                              fixed argument
  {"kind": "py", "src": "lambda a, b: ..."}                                 a callable argument
  {"kind": "scaled_int", "factor": f}                                        int(f * n): an integer whose magnitude drives the cost
  {"kind": "string", "chars": "abc"}                                        n characters

Output-sensitive complexity "n+out" (time linear in input size plus output size) additionally needs
  "output_size": {"max_factor": F, "constant": C (optional, default 16), "doc": "how the generator/preconditions bound the output"}
meaning len(output) <= F * (input elements) + C for every input that satisfies the preconditions. The check verifies that bound on the
generated inputs (the output of lists and strings is measured by len; other outputs count 0) and measures the growth against
input size + output size instead of input size alone.

Timing problems are re-measured (3 attempts) and count only if every attempt shows them.
Checks: every unit test passes; the generator really scales (input size at N2 >= N2/2 and >= 2.5x the size at N1);
inputs too fast to time are enlarged 4x (twice at most); growth matches the declared complexity
(exponent <= EXPONENT[complexity]); time at N2 <= ABS_SECONDS. Results are cached by file hash.
"""
import hashlib, importlib.util, json, math, random, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIB = ROOT / 'packs' / 'general' / 'templates' / 'lib'
EXPONENT = {'1': 0.3, 'n': 1.35, 'n+out': 1.35, 'n log n': 1.45, 'cells': 1.35, 'n^2': 2.4, 'n*t': 1.35, 'n*t*k': 1.35}
ABS_SECONDS = 2.0
MIN_TIMED = 0.02
CACHE = ROOT / '.lib_check_cache.json'


def gen_args(spec, n, seed):
    rng = random.Random(seed)
    out = []
    for a in spec:
        k = a['kind']
        if k == 'int_list':
            if a.get('distinct'):
                xs = rng.sample(range(a['lo'], a['hi'] + 1), min(n, a['hi'] - a['lo'] + 1))
            else:
                xs = [rng.randint(a['lo'], a['hi']) for _ in range(n)]
            out.append(sorted(xs) if a.get('sorted') else xs)
        elif k == 'intervals':
            iv = []
            for _ in range(n):
                s = rng.randint(a['lo'], a['hi'])
                iv.append([s, s + rng.randint(0, a['maxlen'])])
            out.append(iv)
        elif k == 'grid':
            side = max(1, int(math.sqrt(n)))
            out.append([''.join(rng.choice(a['chars']) for _ in range(side)) for _ in range(side)])
        elif k == 'grid_last':
            side = max(1, int(math.sqrt(n)))
            out.append([side - 1, side - 1])
        elif k == 'string':
            out.append(''.join(rng.choice(a['chars']) for _ in range(n)))
        elif k == 'value':
            out.append(a['value'])
        elif k == 'py':
            out.append({'py': a['src']})
        elif k == 'scaled_int':
            out.append(int(a['factor'] * n))
        else:
            raise ValueError(f'unknown argspec kind {k}')
    return out


def materialise(args):
    """JSON args; {"py": "<lambda source>"} stands for a callable argument (trusted library metadata only)."""
    return [eval(a['py'], {}) if isinstance(a, dict) and set(a) == {'py'} else a for a in json.loads(json.dumps(args))]


TIMER = r'''
import importlib.util, json, resource, sys, time
resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))
sys.setrecursionlimit(1000000)
spec = importlib.util.spec_from_file_location("f", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
fn = getattr(m, sys.argv[3]); args = [eval(a["py"], {}) if isinstance(a, dict) and set(a) == {"py"} else a for a in json.load(open(sys.argv[2]))]
best = float("inf")
for _ in range(3):
    t = time.perf_counter(); fn(*args); best = min(best, time.perf_counter() - t)
    if best > 2: break
print(best)
'''


def spec_size(spec, n):
    """How much work the generator spec asks for at n: elements of lists/strings/intervals, cells of grids,
    the value of scaled integers. Fixed values count nothing."""
    size = 0
    for a in spec:
        k = a['kind']
        if k in ('int_list', 'intervals', 'string'):
            size += n
        elif k == 'grid':
            size += max(1, int(math.sqrt(n))) ** 2
        elif k == 'scaled_int':
            size += int(a['factor'] * n)
    return size


def input_size(args):
    """Elements in list and string arguments (cells for grids); scalars count 0."""
    size = 0
    for a in args:
        if isinstance(a, str):
            size += len(a)
        elif isinstance(a, list):
            size += sum(len(x) if isinstance(x, str) else 1 for x in a)
    return size


class TimingFailed(Exception):
    """The timing run crashed (MemoryError, exception on generated input...): the function fails its check."""


def _time(path, name, args):
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fa, tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as ft:
        json.dump(args, fa); ft.write(TIMER)
    try:
        p = subprocess.run([sys.executable, '-I', ft.name, str(path), fa.name, name], capture_output=True, text=True, timeout=30)
        if p.returncode:
            raise TimingFailed((p.stderr.strip().splitlines() or ['no output'])[-1][:150])
        return float(p.stdout.strip())
    except subprocess.TimeoutExpired:
        return math.inf
    finally:
        Path(fa.name).unlink(missing_ok=True); Path(ft.name).unlink(missing_ok=True)


def output_bound(meta):
    """(max_factor, constant) declared by a function of complexity n+out, None for the other complexities,
    or a string describing what is wrong with the declaration."""
    spec = meta.get('output_size')
    if meta.get('complexity') != 'n+out':
        return None if spec is None else 'output_size is only allowed with complexity "n+out"'
    if not isinstance(spec, dict):
        return 'complexity "n+out" needs output_size {"max_factor": F, "doc": ...} describing how the output is bounded'
    factor, const = spec.get('max_factor'), spec.get('constant', 16)
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)  # noqa: E731
    if not num(factor) or factor <= 0 or not num(const) or const < 0:
        return 'output_size.max_factor must be a positive number (and constant a non-negative number)'
    if not isinstance(spec.get('doc'), str) or not spec['doc'].strip():
        return 'output_size.doc must say why the output is bounded'
    return float(factor), float(const)


def output_size(result):
    return len(result) if isinstance(result, (list, str, tuple, dict)) else 0


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return getattr(m, path.stem)


def check_one(path):
    """Returns (problems, measurement)."""
    meta_path = path.with_suffix('.json')
    if not meta_path.exists():
        return [f'{path.stem}: missing {meta_path.name}'], None
    meta = json.loads(meta_path.read_text())
    problems = []
    src = path.read_text()
    if any(m in src for m in ('{{', '{%', '{#')):
        problems.append(f'{path.stem}: contains Jinja markers')
    if meta.get('complexity') not in EXPONENT:
        problems.append(f"{path.stem}: complexity must be one of {sorted(EXPONENT)}")
    if len(meta.get('tests', [])) < 5:
        problems.append(f'{path.stem}: needs at least 5 unit tests')
    bound = output_bound(meta)
    if isinstance(bound, str):
        problems.append(f'{path.stem}: {bound}')
    fn = load(path)
    for t in meta.get('tests', []):
        try:
            got = json.loads(json.dumps(fn(*materialise(t['args']))))
        except Exception as exc:  # noqa: BLE001
            got = f'{type(exc).__name__}: {exc}'
        if got != t['expected']:
            problems.append(f"{path.stem}: test {json.dumps(t['args'])[:80]} expected {t['expected']!r} got {got!r}"[:200])
            break
    measurement = None
    if not problems and meta.get('complexity') == '1':
        return problems, {'constant': True}  # no size to scale
    if not problems:
        n1, n2 = meta.get('sizes', [5000, 20000])
        if n2 < 3 * n1:
            problems.append(f'{path.stem}: sizes must differ by at least 3x to measure growth')
        for attempt in range(3):
            a1, a2 = gen_args(meta['generator'], n1, 1), gen_args(meta['generator'], n2, 2)
            s1, s2 = spec_size(meta['generator'], n1), spec_size(meta['generator'], n2)
            if s2 < n2 / 2 or s2 < 2.5 * s1:
                problems.append(f'{path.stem}: generator does not scale with n (input sizes {s1}, {s2} for n={n1}, {n2})')
                break
            if isinstance(bound, tuple):  # n+out: the declared output bound must hold on the generator's inputs; work = input + output
                outs = []
                for a, s in ((a1, s1), (a2, s2)):
                    o = output_size(fn(*materialise(a)))
                    outs.append(o)
                    if o > bound[0] * input_size(a) + bound[1]:
                        problems.append(f'{path.stem}: output of {o} exceeds the declared bound {bound[0]:g}*input+{bound[1]:g} (input {input_size(a)})')
                if problems:
                    break
                s1, s2 = s1 + outs[0], s2 + outs[1]
            try:
                t1, t2 = _time(path, path.stem, a1), _time(path, path.stem, a2)
            except TimingFailed as exc:
                problems.append(f'{path.stem}: timing run failed on generated input (memory limit 2 GB, 30 s): {exc}')
                break
            if t2 >= MIN_TIMED or not math.isfinite(t2) or attempt == 2:
                break
            n1, n2 = n1 * 4, n2 * 4  # too fast to measure: enlarge the inputs
        if not problems:
            exp = math.log(max(t2, 1e-6) / max(t1, 1e-6)) / math.log(s2 / s1) if math.isfinite(t2) else math.inf
            measurement = {'sizes': [n1, n2], 'input_sizes': [s1, s2], 'seconds': [round(t1, 4), round(t2, 4) if math.isfinite(t2) else None], 'exponent': round(exp, 2)}
            if not math.isfinite(t2) or t2 > ABS_SECONDS:
                problems.append(f'{path.stem}: {t2:.2f}s at n={n2} > {ABS_SECONDS}s')
            elif t2 >= MIN_TIMED and exp > EXPONENT[meta['complexity']]:
                problems.append(f"{path.stem}: declared {meta['complexity']} but grows like n^{exp:.2f}")
    return problems, measurement


def check_one_repeated(path, attempts=3):
    """check_one, repeated while it reports only timing problems: those count only if every attempt shows them."""
    problems, measurement = check_one(path)
    for _ in range(attempts - 1):
        timing_only = problems and all(('grows like' in p or 's at n=' in p) for p in problems)
        if not timing_only:
            break
        problems, measurement = check_one(path)
    return problems, measurement


def check_all(lib=LIB, use_cache=True):
    cache = json.loads(CACHE.read_text()) if use_cache and CACHE.exists() else {}
    problems, report = [], {}
    for path in sorted(lib.glob('*.py')):
        h = hashlib.sha256(path.read_bytes() + (path.with_suffix('.json').read_bytes() if path.with_suffix('.json').exists() else b'')).hexdigest()
        if h in cache:
            report[path.stem] = cache[h]; continue
        p, m = check_one_repeated(path)
        problems += p
        report[path.stem] = m
        if not p:
            cache[h] = m
    for meta in sorted(lib.glob('*.json')):
        if not meta.with_suffix('.py').exists():
            problems.append(f'{meta.stem}: metadata without code')
    if use_cache:
        CACHE.write_text(json.dumps(cache))
    return problems, report


if __name__ == '__main__':
    probs, rep = check_all(use_cache='--no-cache' not in sys.argv)
    for k, v in rep.items():
        print(f'{k:36} {v}')
    print('OK' if not probs else '\n'.join(probs))
