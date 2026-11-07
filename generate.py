"""Generic facts -> Datalog -> emit plan -> Jinja -> Python modules."""
import argparse, ast, bisect, hashlib, json, threading
from collections import OrderedDict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from datalog import Datalog, parse_rules, parse_rules_cached

ROOT = Path(__file__).resolve().parent

# Per-pack caches, keyed by on-disk state (path + mtime_ns + size of the relevant files), so repeated
# generate()/build() calls over the same pack share parsed rules and the compiled template environment.
# Any change to a rule file or template shifts the key and forces a re-parse / re-compile.
_RULES_CACHE = OrderedDict()
_ENV_CACHE = OrderedDict()
_RULES_CACHE_MAX = 32
_ENV_CACHE_MAX = 8
_CACHE_LOCK = threading.Lock()   # every global cache is mutated only under this lock


def _stat_key(paths):
    """Path + mtime + size + content digest: rapid rewrites within timestamp granularity are still seen."""
    return tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size,
                  hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths)


def pack_rules(pack, config):
    """The pack's parsed rules, re-parsed only when a rule file changes. Each rule file is read once;
    the cache key is its content digest, so what was hashed is exactly what was parsed."""
    config = json.loads((pack / 'pack.json').read_text(encoding='utf-8'))
    files = [(name, inside(pack, name).read_bytes()) for name in config['rules']]
    key = tuple((name, hashlib.sha256(text).hexdigest()) for name, text in files)
    with _CACHE_LOCK:
        rules = _RULES_CACHE.get(key)
    if rules is None:
        rules = tuple(r for _, text in files for r in parse_rules_cached(text.decode('utf-8')))
        with _CACHE_LOCK:
            _RULES_CACHE[key] = rules
            while len(_RULES_CACHE) > _RULES_CACHE_MAX:
                _RULES_CACHE.popitem(last=False)
    return list(rules)


def pack_env(pack, config):
    """A Jinja environment per pack template directory, reused (keeping compiled templates) until any
    template file changes on disk. The cache is a bounded LRU."""
    tdir = inside(pack, config.get('templates', 'templates'))
    key = _stat_key(sorted(p for p in tdir.rglob('*') if p.is_file()))
    skey = str(tdir)
    with _CACHE_LOCK:
        hit = _ENV_CACHE.get(skey)
        if hit is not None and hit[0] == key:
            _ENV_CACHE.move_to_end(skey)
            return hit[1]
    env = Environment(loader=FileSystemLoader(tdir), undefined=StrictUndefined, keep_trailing_newline=True)
    env.filters['pyrepr'] = repr
    with _CACHE_LOCK:
        _ENV_CACHE[skey] = (key, env)
        while len(_ENV_CACHE) > _ENV_CACHE_MAX:
            _ENV_CACHE.popitem(last=False)
    return env


def inside(root, relative):
    path = Path(relative)
    resolved = (root / path).resolve()
    if not relative or path.is_absolute() or not resolved.is_relative_to(root):
        raise ValueError(f'Path outside root: {relative!r}')
    return resolved


class _FactsView(dict):
    """Dict-like facts context for one template render: each predicate's rows are copied once, lazily,
    on first access, and the copies belong to this render only. Like the plain dicts it replaces,
    an unknown predicate raises KeyError (so Jinja's StrictUndefined still reports it). Known limit:
    whole-view serialization ({{ facts }}, facts|tojson) sees the empty underlying storage and yields
    nothing — templates that need that must copy() the view or access each predicate first."""

    def __init__(self, rows_by_pred):
        self._rows = rows_by_pred
        self._copies = {}

    def __missing__(self, pred):
        if pred not in self._rows:
            raise KeyError(pred)
        if pred not in self._copies:
            self._copies[pred] = [list(row) for row in self._rows[pred]]
        return self._copies[pred]

    def __contains__(self, pred):
        return pred in self._rows

    def get(self, pred, default=None):
        return self[pred] if pred in self._rows else default

    def keys(self):
        return self._rows.keys()

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        return len(self._rows)

    def items(self):
        return ((pred, self[pred]) for pred in self._rows)

    def values(self):
        return (self[pred] for pred in self._rows)

    def copy(self):
        return {pred: [list(row) for row in rows] for pred, rows in self.items()}

    def __repr__(self):
        return repr(dict(self.items()))

    def __eq__(self, other):
        if isinstance(other, _FactsView):
            other = dict(other.items())
        return isinstance(other, dict) and dict(self.items()) == other

    def __ne__(self, other):
        return not self.__eq__(other)


class Relations:
    def __init__(self, db):
        self.db = db
        self._sorted = {}   # predicate -> sorted tuple of its tuples; built once, shared read-only

    def sorted_rows(self, predicate):
        """All tuples of a predicate in sorted order, computed once per predicate."""
        rows = self._sorted.get(predicate)
        if rows is None:
            rows = self._sorted[predicate] = tuple(sorted(self.db.get(predicate, set())))
        return rows

    def rows(self, predicate, *prefix):
        """Fresh copies of the rows matching the prefix. The rows are sorted, so bisect locates the
        start of the matching run and the scan stops at the first non-matching row."""
        pre = tuple(prefix)
        rows = self.sorted_rows(predicate)
        if not pre:
            return [list(row) for row in rows]
        out, i = [], bisect.bisect_left(rows, pre)
        while i < len(rows):
            row = rows[i]
            if row[:len(pre)] != pre:
                break
            out.append(list(row))
            i += 1
        return out

    def has(self, predicate, *values):
        return tuple(values) in self.db.get(predicate, set())

    def one(self, predicate, *prefix):
        rows = self.rows(predicate, *prefix)
        if len(rows) != 1 or len(rows[0]) != len(prefix) + 1:
            raise ValueError(f'Expected one value for {predicate}{prefix}, got {rows}')
        return rows[0][-1]


def generate(spec, output, pack=ROOT / 'packs' / 'python', engine=None):
    """engine: an already-run Datalog whose facts are exactly this spec's facts (plus the pack's own);
    passing one lets a caller share the inference run instead of repeating it. The engine belongs to
    the caller: this function never mutates a shared one."""
    pack = Path(pack).resolve()
    output = Path(output).resolve()
    config = json.loads((pack / 'pack.json').read_text(encoding='utf-8'))
    if engine is None:
        engine = Datalog(pack_rules(pack, config))
        for source in (config.get('facts', {}), spec.get('facts', {})):
            for predicate, rows in source.items():
                for row in rows:
                    if not isinstance(row, list) or not all(isinstance(v, str) for v in row):
                        raise ValueError(f'{predicate}: facts must be arrays of strings')
                    engine.add(predicate, *row)
        inferred = engine.run()
    else:
        inferred = {p: engine.db[p] for p in {head[0] for head, _ in engine.rules}}
    relations = Relations(engine.db)
    errors = relations.rows('error')
    if errors:
        raise ValueError(f'Rules rejected input: {errors}')
    env = pack_env(pack, config)
    data = spec.get('data', {})
    # The full fact context is built once per generate() call (per-predicate sort cached in Relations);
    # the _FactsView below copies each predicate's rows lazily, once per render, so a template cannot
    # mutate what other emit rows see — and no copy happens at all for templates that never touch facts.
    facts_rows = {p: relations.sorted_rows(p) for p in sorted(engine.db)}
    rendered = {}
    plan = relations.rows('emit')
    if not plan:
        raise ValueError('No emit(template, path, key) facts were derived')
    for row in plan:
        if len(row) != 3:
            raise ValueError(f'emit requires template, path, key: {row}')
        template, relative, key = row
        target = inside(output, relative)
        if target == output / 'inference.json' or target in rendered:
            raise ValueError(f'Duplicate or reserved output: {relative}')
        if target.suffix != '.py':
            raise ValueError(f'Only Python outputs are supported: {relative}')
        inside(inside(pack, config.get('templates', 'templates')), template)
        context = dict(data=data, item=data[key] if key else data, key=key,
                       relations=relations, facts=_FactsView(facts_rows))
        source = env.get_template(template).render(**context)
        ast.parse(source, filename=relative)
        compile(source, relative, 'exec')
        rendered[target] = source
    # Finish rendering and validation before writing any artifact.
    report = {'pack': str(pack), 'plan': plan,
              'inferred': {p: sorted(rows) for p, rows in sorted(inferred.items())}}
    for target, source in rendered.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding='utf-8')
    (output / 'inference.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return [str(path.relative_to(output)) for path in rendered]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path)
    parser.add_argument('--pack', type=Path, default=ROOT / 'packs' / 'python')
    parser.add_argument('--out', type=Path, default=ROOT / 'generated')
    args = parser.parse_args()
    paths = generate(json.loads(args.spec.read_text(encoding='utf-8')), args.out, args.pack)
    print('\n'.join(paths))
