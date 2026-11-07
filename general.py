"""Generalising generator: statement -> feature facts (model) -> rules -> schema template -> code.

The model only translates the statement into facts from packs/general/vocab.json; it never
writes code here. Which algorithm skeleton is used, and with what parameters and defaults,
is decided by the Datalog rules in packs/general/rules.dl (+ learned.dl).

  python general.py solve problems.json [--ids ...] [--model haiku] [--log out.json]
  python general.py facts problems.json --facts given.json   # skip the model, use given facts

Statuses: solved (all tests pass) / rejected (rules raised error(...) or derived no schema) /
          invalid (facts outside the vocabulary) / wrong (generated code failed tests).
"""
import argparse, hashlib, json, re, shutil, subprocess, tempfile, threading, time
from collections import OrderedDict
from pathlib import Path

from generate import generate
from grow import run_tests

ROOT = Path(__file__).resolve().parent
PACK = ROOT / 'packs' / 'general'
KEY = 'p'
CALLS = {'n': 0}   # model calls made by this process (extract + ask_model); solve_problem logs the per-problem delta


def vocab(pack=PACK):
    return json.loads((pack / 'vocab.json').read_text())['predicates']


def params_of(signature):
    inner = signature[signature.index('(') + 1:signature.rindex(')')]
    return [a.split('=')[0].strip() for a in inner.split(',') if a.strip()]


STAGE_PRED = re.compile(r'^(\d+)\.([A-Za-z_]\w*)$')
STAGE_REF = re.compile(r'^stage(\d+)$')
FLAT_IN_STAGED = ('arg', 'size', 'guarantees', 'unique', 'stage')  # facts that stay at the top of a staged problem
STAGE_ARG_PREDS = ('items', 'target')  # facts whose parameter may be the output of an earlier stage (written stageJ, stored as the variable _sJ)


def split_stage(pred):
    """'2.keep' -> (2, 'keep'); an ordinary predicate -> (None, pred)."""
    m = STAGE_PRED.match(pred)
    return (int(m.group(1)), m.group(2)) if m else (None, pred)


def _int_or_param(val, params, stage=None):
    """An integer literal, an int parameter or (in stage `stage`) the output of an earlier stage written stageJ."""
    m = STAGE_REF.match(val)
    return bool(re.fullmatch(r'-?\d+', val)) or val in params or bool(m and stage is not None and int(m.group(1)) < stage)


def earlier_stage_ref(val, stage):
    m = STAGE_REF.match(val)
    return bool(m and stage is not None and int(m.group(1)) < stage)


def composition_problems(pred, args, stage, params, voc):
    """Checks that depend on more than one argument: source and cond leaves."""
    bad = []
    if pred == 'source':
        kind, x, y = (list(args) + ['-', '-'])[:3]
        if kind == 'param':
            if x not in params or y != '-':
                bad.append(f'source param takes one parameter name: {list(args)!r}')
        elif kind == 'range':
            if not (_int_or_param(x, params, stage) and _int_or_param(y, params, stage)):
                bad.append(f'source range takes two integers or int parameters (lo, hi): {list(args)!r}')
        elif kind in ('digits', 'chars'):
            m = STAGE_REF.match(x)
            if y != '-' or not (x in params or (m and stage is not None and int(m.group(1)) < stage)):
                bad.append(f'source {kind} takes a parameter or an earlier stage (stage1, ...): {list(args)!r}')
        elif kind == 'stage':
            if y != '-' or not (x.isdigit() and stage is not None and int(x) < stage):
                bad.append(f'source stage takes the index of an earlier stage: {list(args)!r}')
    elif pred == 'cond':
        nid, kind, a, b = (list(args) + ['-'] * 4)[:4]
        keep_vals = voc['keep']['values']['cond']
        if kind in ('keep', 'drop'):
            if a not in keep_vals or b != '-':
                bad.append(f'cond {kind} takes one condition from {keep_vals}: {list(args)!r}')
        elif kind == 'remainder':
            if not (re.fullmatch(r'-?\d+', a) and re.fullmatch(r'-?\d+', b)):
                bad.append(f'cond remainder takes two integers (m, r): {list(args)!r}')
        elif kind == 'bound':
            if a not in voc['bound']['values']['op'] or not re.fullmatch(r'-?\d+', b):
                bad.append(f'cond bound takes an op from {voc["bound"]["values"]["op"]} and an integer: {list(args)!r}')
    return bad


def validate(facts, params, voc):
    """Returns a list of problems with the facts; empty means every fact is in the vocabulary.
    A fact of a staged problem is written '<I>.<pred>' (stage I); optional trailing arguments may be omitted."""
    bad = []
    declared = sorted(int(f[1]) for f in facts if isinstance(f, list) and len(f) == 3 and f[0] == 'stage' and f[1].isdigit())
    if declared and declared != list(range(1, len(declared) + 1)):
        bad.append(f'stages must be declared once each and numbered 1..n, got {declared}')
    for f in facts:
        if not isinstance(f, list) or not f or not all(isinstance(x, str) for x in f):
            bad.append(f'not a list of strings: {f!r}'); continue
        stage, pred = split_stage(f[0])
        args = f[1:]
        spec = voc.get(pred)
        if spec is None:
            bad.append(f'unknown predicate {pred}'); continue
        if stage is not None:
            if stage not in declared:
                bad.append(f'{f[0]}: stage {stage} is not declared with a stage fact'); continue
            if pred == 'stage' or pred in FLAT_IN_STAGED:
                bad.append(f'{f[0]}: {pred} is not a per-stage fact'); continue
        elif declared and pred not in FLAT_IN_STAGED:
            bad.append(f'{pred}: in a staged problem every other fact must be written <stage>.{pred}'); continue
        tail = spec.get('optional_tail', 0)
        if not len(spec['args']) - tail <= len(args) <= len(spec['args']):
            bad.append(f'{pred} takes {len(spec["args"])} args: {f!r}'); continue
        for name, val in zip(spec['args'], args):
            allowed = spec.get('values', {}).get(name)
            if name == 'param' and val not in params and not (pred in STAGE_ARG_PREDS and earlier_stage_ref(val, stage)):
                bad.append(f'{pred}: {val!r} is not a parameter {params}')
            elif name == 'char' and len(val) != 1:
                bad.append(f'{pred}: {val!r} is not one character')
            elif name == 'int' and not re.fullmatch(r'-?\d+', val):
                bad.append(f'{pred}: {val!r} is not an integer')
            elif pred == 'source' and name == 'kind':
                if val not in allowed:  # here 'param' is a literal kind, not the placeholder for a parameter name
                    bad.append(f'{pred}: {val!r} not in {allowed}')
            elif allowed:
                ok = (val in [v for v in allowed if v not in ('param', '<param>')]
                      or (pred == 'bound' and name == 'n' and earlier_stage_ref(val, stage))
                      or ('<int>' in allowed and re.fullmatch(r'-?\d+', val))
                      or ('<char>' in allowed and len(val) == 1)
                      or (('param' in allowed or '<param>' in allowed) and val in params))
                if not ok:
                    bad.append(f'{pred}: {val!r} not in {allowed}')
        bad += composition_problems(pred, args, stage, params, voc)
    return bad


PROMPT = """Translate a programming problem into facts from a fixed vocabulary. Do not write code.

Vocabulary (each fact is a JSON list: predicate name followed by its arguments, all strings):
{vocab}

Problem signature: {signature}
Problem statement:
{statement}

Rules: use only predicates and values listed above; 'param' arguments must be one of {params};
describe every parameter with an arg fact; include defaults only when the statement differs from them.
If some aspect of the problem cannot be described with this vocabulary, still give every fact that does apply
(at least the arg facts and whatever describes the input and the question) and add "uncovered": "<what is missing>".
Never bend a fact to fit: a fact that misdescribes the problem is worse than an uncovered note.
Composition: where the elements come from can be stated with source (integers of a range, digits of a number, characters of a
string); a filter with and/or/not over several conditions is a cond/expr/filter tree. When the answer is computed in steps, each
feeding the next (e.g. the digit sum of n!: product of 1..n, then the digits of that, then their sum), declare stages
["stage","1","seq_fold"], ["stage","2","seq_fold"], ... and write every fact of stage I as "<I>.<predicate>", e.g.
["1.source","range","1","n"], ["1.aggregate","product"], ["2.source","digits","stage1"], ["2.aggregate","sum"] (arg facts stay unprefixed).
Any stage can use any schema that has a sequence or scalar result: write ["stage","2","pair_count"] (or seq_rank, seq_reduce, palindrome_check,
run_encode, pair_extreme, bracket_match, interval_scan, knapsack) and give the stage's own facts, e.g. ["2.source","digits","stage1"],
["2.ask","count_pairs"], ["2.pair_test","sum","3","0"]. A stage may read several things: a parameter and an earlier stage's output, e.g. a
knapsack stage ["2.items","coins"], ["2.target","stage1"], ["2.ask","min_count"], a threshold ["2.bound","ge","stage1"], or a range bound
["2.source","range","1","stage1"]; an output can only feed an input of its type (int -> digits / range bound / target / bound; list -> source / items;
string -> chars / a string source).
Use a single stage (plain facts) whenever one schema already describes the problem.{hint}
You have no tools: do not try to write files or run commands. Reply with only JSON: {{"facts": [[...], ...]}}"""

HINT = """

The rule engine looked at your previous facts {facts} and reports:
{near}
If the statement really provides what is asked for (a fact a nearby schema needs, a guarantee such as "positive integers",
a stated size bound, the right output form), add those facts (and remove the uncovered note); otherwise keep the note and
explain which of the listed facts would misdescribe the problem."""


def describe_vocab(voc):
    lines = []
    for name, spec in voc.items():
        vals = '; '.join(f'{k} in {v}' for k, v in spec.get('values', {}).items())
        lines.append(f'- {name}({", ".join(spec["args"])}){" — " + vals if vals else ""}: {spec["doc"]}')
    return '\n'.join(lines)


def first_json_object(text):
    """The first complete JSON object in a model reply (replies sometimes carry prose or a second object)."""
    dec = json.JSONDecoder()
    start = 0
    while True:
        i = text.find('{', start)
        if i < 0:
            raise ValueError(f'no JSON object in reply: {text[-300:]}')
        try:
            obj, _ = dec.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        start = i + 1


def extract(problem, model, voc, hint=''):
    CALLS['n'] += 1
    prompt = PROMPT.format(vocab=describe_vocab(voc), signature=problem['signature'],
                           statement=problem['statement'], params=params_of(problem['signature']), hint=hint)
    p = subprocess.run(['claude', '-p', '--model', model, '--tools', '', '--no-session-persistence', '--strict-mcp-config'],
                       input=prompt, capture_output=True, text=True, timeout=300, cwd=tempfile.gettempdir())
    try:
        data = first_json_object(p.stdout)
    except ValueError:
        raise ValueError(f'extractor gave no JSON: {p.stdout[-200:]} {p.stderr[-200:]}') from None
    norm = lambda v: str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
    facts = [[norm(v) for v in f] if isinstance(f, list) else f for f in data.get('facts', [])]
    return facts, data.get('uncovered')


def grouped_facts(problem, facts, pack=PACK):
    """The fact base the rules see: problem(P), the extracted facts (with the problem key prepended)
    and the library facts (algorithm, complexity, role, drives, requires) from templates/lib/*.json."""
    grouped = {'problem': [[KEY]], 'algorithm': [], 'complexity': [], 'role': [], 'drives': [], 'requires': []}
    for meta in sorted((pack / 'templates' / 'lib').glob('*.json')):
        m = json.loads(meta.read_text())
        grouped['algorithm'].append([meta.stem])
        grouped['complexity'].append([meta.stem, m['complexity']])
        grouped['role'].append([meta.stem, m.get('role', meta.stem)])
        for d in m.get('drives', ['seq']):
            grouped['drives'].append([meta.stem, d])
        for role, cond in m.get('requires', []):
            grouped['requires'].append([meta.stem, role, cond])
    voc = vocab(pack)
    stages = sorted(int(f[1]) for f in facts if f[0] == 'stage')
    for f in facts:
        stage, pred = split_stage(f[0])
        args = list(f[1:])
        pad = len(voc[pred]['args']) - len(args) if pred in voc else 0
        args += ['-'] * pad  # omitted optional trailing arguments
        if stage and pred in STAGE_ARG_PREDS and earlier_stage_ref(args[0], stage):
            args[0] = '_s' + STAGE_REF.match(args[0]).group(1)  # the stage variable the earlier stage was rendered into
        grouped.setdefault(pred, []).append([sub_key(stage) if stage else KEY, *args])
        if pred == 'source' and args[0] == 'range':  # a literal bound has no size fact of its own: give it the class of its magnitude
            lo, hi = args[1], args[2]
            if re.fullmatch(r'-?\d+', hi):
                grouped.setdefault('size', []).append([sub_key(stage) if stage else KEY, hi, size_class(abs(int(hi)))])
            if re.fullmatch(r'-?\d+', lo) and int(lo) > 0:  # the integers lo..hi are positive and distinct
                grouped.setdefault('guarantees', []).append([sub_key(stage) if stage else KEY, '$range', 'positive'])
        if f[0] == 'items_literal':  # what a literal item list guarantees can be read off the literal itself
            nums = [int(x) for x in re.findall(r'-?\d+', f[1])]
            if nums and min(nums) > 0:
                grouped.setdefault('guarantees', []).append([KEY, f[1], 'positive'])
            if nums and len(set(nums)) == len(nums):
                grouped.setdefault('guarantees', []).append([KEY, f[1], 'distinct'])
    # sizes: the statement's bounds come as size facts; otherwise sequences are assumed medium (a typical
    # constraint) and integers take the magnitude seen in the tests
    stated = {row[1] for row in grouped.get('size', [])}
    for i, name in enumerate(params_of(problem['signature'])):
        if name in stated:
            continue
        vals = [t['args'][i] for t in problem.get('tests', []) if i < len(t['args'])]
        if vals and all(isinstance(v, (list, str)) for v in vals):
            # item lists (coin denominations etc.) take the size seen in the tests; the main sequence is assumed at least medium
            observed = size_class(max(len(v) for v in vals))
            is_items = any(row[1] == name for row in grouped.get('items', []))
            cls = observed if is_items else max(observed, 'medium', key=SIZE_ORDER.index)
        elif vals and all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
            cls = size_class(max(abs(v) for v in vals))
        else:
            continue
        grouped.setdefault('size', []).append([KEY, name, cls])
        grouped.setdefault('assumed_size', []).append([KEY, name])  # derived, not stated: may be asked about
    if stages:
        add_stage_facts(grouped, stages)
    return grouped


def sub_key(stage):
    """The key of the sub-problem that stands for stage `stage` of a staged problem."""
    return f'{KEY}.{stage}'


def add_stage_facts(grouped, stages):
    """A staged problem P is a chain of sub-problems P.1 ... P.n; the facts that describe stage I are keyed on P.I, so
    every rule written for a flat problem applies to a stage unchanged. The parameters' facts (arg, size, ...) are shared."""
    for i in stages:
        q = sub_key(i)
        grouped.setdefault('substage', []).append([KEY, str(i), q])
        grouped.setdefault('parent', []).append([q, KEY])
        for j in stages:
            if j < i:
                grouped.setdefault('before', []).append([KEY, str(j), str(i)])
                grouped.setdefault('stage_ref', []).append([q, f'stage{j}', str(j)])
                grouped.setdefault('stage_var', []).append([q, str(j), f'_s{j}'])
        for pred in ('arg', 'size', 'assumed_size', 'guarantees', 'unique'):
            for row in list(grouped.get(pred, [])):
                if row[0] == KEY:
                    grouped[pred].append([q, *row[1:]])
    grouped.setdefault('last_stage', []).append([KEY, str(stages[-1])])


SIZE_ORDER = ['tiny', 'small', 'medium', 'large', 'huge', 'vast']


def size_class(n):
    for cls, limit in (('tiny', 100), ('small', 1000), ('medium', 10 ** 5), ('large', 10 ** 6), ('huge', 10 ** 7)):
        if n <= limit:
            return cls
    return 'vast'


_PACK_CACHE_MAX = 8
_PACK_CACHE = OrderedDict()     # (pack path, fingerprint) -> (config json, rules tuple); immutable values
_CACHE_LOCK = threading.Lock()  # every global cache is mutated only under this lock


def pack_fingerprint(pack=PACK):
    """On-disk state (path + mtime_ns + size + content digest) of only the files that participate in
    generation: pack.json, the rule files, vocab.json and everything under the template directory
    (which carries the library metadata; __pycache__ excluded). A same-size, same-mtime rewrite still
    shifts the fingerprint because the content is hashed; data outside these trees (solved / rejected
    corpora) is never scanned."""
    pack = Path(pack).resolve()
    items = []

    def add(path):
        st = path.stat()
        items.append((path.relative_to(pack).as_posix(), st.st_mtime_ns, st.st_size,
                      hashlib.sha256(path.read_bytes()).hexdigest()))

    add(pack / 'pack.json')
    config = json.loads((pack / 'pack.json').read_text())
    for name in config['rules']:
        add(pack / name)
    if (pack / 'vocab.json').exists():
        add(pack / 'vocab.json')
    tdir = pack / config.get('templates', 'templates')
    for p in sorted(tdir.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts:
            add(p)
    return tuple(items)


def _pack_state(pack):
    """Parsed rules and pack config, cached per fingerprint; the cached values are immutable
    (config as JSON text, rules as nested tuples)."""
    import datalog
    key = (str(pack), pack_fingerprint(pack))
    with _CACHE_LOCK:
        hit = _PACK_CACHE.get(key)
        if hit is not None:
            _PACK_CACHE.move_to_end(key)
            return hit
    config = json.loads((pack / 'pack.json').read_text())
    rules = []
    for name in config['rules']:
        rules += datalog.parse_rules_cached((pack / name).read_text())
    value = (json.dumps(config, sort_keys=True), tuple(rules))
    with _CACHE_LOCK:
        _PACK_CACHE[key] = value
        while len(_PACK_CACHE) > _PACK_CACHE_MAX:
            _PACK_CACHE.popitem(last=False)
    return value


def build_engine(problem, facts, pack, explain=False, extra_rules='', extra_grouped=None):
    """A fresh, request-owned Datalog engine loaded with the pack rules and this problem's facts, run.
    extra_rules: rule text appended for this run only (the rejection corpus uses it to reach guards that
    facts cannot). extra_grouped: additional grouped facts (e.g. want_reference) that must not leak into
    a shared Run's engine."""
    import datalog
    pack = Path(pack).resolve()
    config_json, rules = _pack_state(pack)
    if extra_rules:
        rules = rules + tuple(datalog.parse_rules_cached(extra_rules))
    d = datalog.Datalog(list(rules), explain=explain)
    sources = [json.loads(config_json).get('facts', {}), grouped_facts(problem, facts, pack)]
    if extra_grouped:
        sources.append(extra_grouped)
    for source in sources:
        for pred, rows in source.items():
            for row in rows:
                d.add(pred, *row)
    d.run()
    return d


class Run:
    """One evaluation request: the several passes over one problem (type check, generate, plan
    explanation, refusal advice) share this request's engines — the plain run happens once and the
    explain run lazily once, and the plan text is computed once. The engines are owned by the request,
    so a caller mutating one cannot pollute any other request; cross-request caches hold only
    immutable parsed rules and pack state."""

    def __init__(self, problem, facts, pack=PACK):
        self.problem, self.facts, self.pack = problem, facts, Path(pack).resolve()
        self._engines = {}
        self._plan = None

    def engine(self, explain=False):
        d = self._engines.get(explain)
        if d is None:
            d = self._engines[explain] = build_engine(self.problem, self.facts, self.pack, explain)
        return d

    def plan_text(self):
        if self._plan is None:
            self._plan = explain_plan(self.problem, self.facts, self.pack, run=self)
        return self._plan


def engine_for(problem, facts, pack=PACK, explain=False, extra_rules=''):
    """A Datalog engine loaded with the pack rules and this problem's facts, already run. Returns a
    fresh engine the caller owns: mutating it cannot affect any other request. Within one evaluation,
    the passes should share engines through general.Run (or by passing them down) instead of calling
    engine_for repeatedly."""
    return build_engine(problem, facts, Path(pack).resolve(), explain, extra_rules)


def _lit(fact):
    pred, args = fact
    if args and (args[0] == KEY or args[0].startswith(KEY + '.')):  # the problem key is noise
        args = args[1:] if args[0] == KEY else ('stage ' + args[0][len(KEY) + 1:],) + tuple(args[1:])
    return f"{pred}({', '.join(map(str, args))})"


def _tree_lines(t, indent=0, out=None):
    out = [] if out is None else out
    pad = '  ' * indent
    if t is None:
        return out
    if t.get('given') or t.get('cut'):
        out.append(f"{pad}{_lit(t['fact'])}" + ('  [given]' if t.get('given') else '  [...]'))
        return out
    out.append(f"{pad}{_lit(t['fact'])}  <= {t['rule']}")
    for a in t['absent']:
        out.append(f"{pad}  (and {_lit(a)} does not hold)")
    for sub in t['because']:
        _tree_lines(sub, indent + 1, out)
    return out


def explain_plan(problem, facts, pack=PACK, depth=4, run=None):
    """Why this plan: schema, library functions (candidate -> ok (sizes, fits) -> not beaten), answer type,
    preconditions checked, stages. Built from the derivation records of the Datalog engine (explain=True)."""
    try:
        d = run.engine(True) if run is not None else engine_for(problem, facts, pack, explain=True)
    except ValueError as exc:
        return f'no plan: rules failed: {str(exc)[:200]}'
    lines = []

    def section(title, pred, args, dep=depth):
        t = d.why(pred, args, dep)
        if t is not None:
            lines.append(title)
            lines.extend('  ' + x for x in _tree_lines(t))
        return t

    schemas = sorted(r[1] for r in d.db.get('schema', ()) if r[0] == KEY)
    if not schemas:
        return 'no plan: no schema is derived'
    for sc in schemas:
        section(f'schema {sc}, because:', 'schema', (KEY, sc))
    for stage in sorted(d.db.get('substage', ())):
        if stage[0] == KEY:
            lines.append(f'stage {stage[1]}: schema {sorted(r[1] for r in d.db.get("schema", ()) if r[0] == stage[2])}')
    keys = [KEY] + [r[2] for r in sorted(d.db.get('substage', ())) if r[0] == KEY]
    for key in keys:
        for _, f in sorted(r for r in d.db.get('uses', ()) if r[0] == key):
            tag = '' if key == KEY else f' (stage key {key})'
            lines.append(f'function {f}{tag}: candidate -> ok (complexity, sizes, fits) -> not beaten')
            ok = d.why('ok', (key, f), depth)
            if ok:
                lines.extend('  ' + x for x in _tree_lines(ok))
            role = next(r[1] for r in d.db.get('role', ()) if r[0] == f)
            slower = sorted(g for (k, g) in d.db.get('ok', ()) if k == key and g != f and any(r == (g, role) for r in d.db.get('role', ())))
            lines.append(f'  not beaten: ' + (f'beats the slower ok function(s) {", ".join(slower)} of role {role}' if slower
                                                else f'no other function of role {role} is ok'))
            for _, role, cond in sorted(r for r in d.db.get('requires', ()) if r[0] == f):
                bound = [r[2] for r in d.db.get('binds', ()) if r[0] == key and r[1] == role]
                for a in bound:
                    if (key, a, cond) in d.db.get('guaranteed', ()):
                        why = d.why('guaranteed', (key, a, cond), depth)
                        lines.append(f'  precondition {cond} of {role} `{a}` checked: guaranteed')
                        lines.extend('    ' + x for x in _tree_lines(why))
                    elif (key, f, cond) in d.db.get('waived', ()):
                        lines.append(f'  precondition {cond} of {role} `{a}` checked: waived')
                        lines.extend('    ' + x for x in _tree_lines(d.why('waived', (key, f, cond), depth)))
    for key in keys:
        for r in sorted(r for r in d.db.get('answer_type', ()) if r[0] == key):
            section(f'answer type {r[1]}, because:', 'answer_type', r)
    return '\n'.join(lines)


def param_types(problem, facts):
    """Type of each parameter: from the arg facts when given, else from the JSON types of the tests' arguments."""
    kinds = {f[1]: f[2] for f in facts if f and f[0] == 'arg' and len(f) == 3}
    out = {}
    for i, name in enumerate(params_of(problem['signature'])):
        seen = {json_type(t['args'][i]) for t in problem.get('tests', []) if i < len(t['args'])} - {'empty_list'}
        k = kinds.get(name) or (seen.pop() if len(seen) == 1 else None)
        if k in ('int', 'string', 'int_list', 'string_list', 'interval_list'):
            out[name] = k
    return out


NOT_PROBLEM_FACTS = ('arg', 'size', 'assumed_size', 'guarantees', 'unique', 'stage', 'items_literal')


def first_stage_support(facts, schema, variant, d):
    """How many of the problem's own facts (flat facts, or facts of stage 1) the first stage of a chain already satisfies: facts whose predicate
    describes that schema (schema_fact table of composition.dl); an aggregate / ask fact only counts when it selects this very variant."""
    preds = {p for s, p in d.db.get('schema_fact', ()) if s == schema}
    asks = {a for s, v, a in d.db.get('variant_ask', ()) if s == schema and v == variant}
    n = 0
    for f in facts:
        stage, pred = split_stage(f[0])
        if stage not in (None, 1) or pred in NOT_PROBLEM_FACTS or pred not in preds:
            continue
        if pred == 'aggregate' and (schema != 'seq_fold' or f[1] != variant):
            continue
        if pred == 'ask' and f[1] not in asks:
            continue
        n += 1
    return n


def chain_candidates(problem, facts, pack=PACK, depth=3, run=None):
    """Backward-chaining search over the stage tables of composition.dl: every chain of at most `depth` stages (any sequence-input schema, or
    knapsack with items + target) that starts from the problem's parameters, feeds each stage's output into the next and ends in an answer type
    the tests expect. Returns [{'steps': [(source description, stage label, output type, schema, variant)], 'support': k}]."""
    try:
        d = run.engine() if run is not None else engine_for(problem, facts, pack)
    except ValueError:
        return []
    consumes, source_elem, elem_of = set(d.db.get('consumes', ())), dict(d.db.get('source_elem', ())), dict(d.db.get('elem_of', ()))
    needs = {(a, t) for a, t in d.db.get('needs_elem', ())}
    needs_any = {a for a, _ in needs}
    produces = {(a, t) for _, a, t in d.db.get('produces', ())}
    takes = [tuple(r) for r in d.db.get('stage_takes', ())]
    takes2 = [tuple(r) for r in d.db.get('stage_takes2', ())]
    want = {json_type(t['expected']) for t in problem.get('tests', [])} - {'empty_list'}
    if not want:
        return []
    want |= {'int_list'} if 'empty_list' in {json_type(t['expected']) for t in problem.get('tests', [])} else set()
    params = param_types(problem, facts)

    def sequences(avail):
        """(description, sequence type) of every sequence value a whole-sequence stage can read."""
        for name, t in avail:
            yield name, t
            if t == 'int':
                yield f'the integers 1..{name}', 'int_list'
                yield f'digits of {name}', 'int_list'

    def stage_options(avail):
        """(description, element type) of every source a stage can read, given the values available: [(name, type)]."""
        for name, t in avail:
            if name.startswith('stage'):
                if ('stage', t) in consumes:
                    yield f'elements of {name}', elem_of[t]
                if ('digits', t) in consumes:
                    yield f'digits of {name}', source_elem['digits']
                if ('range_bound', t) in consumes:
                    yield f'the integers 1..{name}', source_elem['range']
                if ('chars', t) in consumes:
                    yield f'characters of {name}', source_elem['chars']
            else:
                if ('param', t) in consumes:
                    yield f'elements of {name}', elem_of[t]
                if ('range', t) in consumes:
                    yield f'the integers 1..{name}', source_elem['range']
                if ('digits', t) in consumes:
                    yield f'digits of {name}', source_elem['digits']
                if ('chars', t) in consumes:
                    yield f'characters of {name}', source_elem['chars']

    results, seen = [], set()

    def add(chain):
        if chain[-1][2] in want and tuple(chain) not in seen:
            seen.add(tuple(chain)); results.append(chain)

    def extend(steps, avail, latest):
        if len(steps) >= depth:
            return
        i = len(steps) + 1
        for desc, elem in stage_options(avail if not steps else [latest]):  # seq_fold: one source (the previous stage's output after stage 1)
            for agg in sorted(needs_any | {'count', 'distinct_count', 'is_palindrome'}):
                if agg in needs_any and (agg, elem) not in needs:
                    continue
                for a, out in sorted(produces):
                    if a != agg or (agg == 'list' and elem != ('int' if out == 'int_list' else 'string')):
                        continue
                    chain = steps + [(desc, agg, out, 'seq_fold', agg)]
                    add(chain)
                    extend(chain, avail, (f'stage{i}', out))
        for desc, seq_t in sequences(avail if not steps else [latest]):  # whole-sequence schemas
            for schema, variant, in_t, out in takes:
                if in_t == seq_t:
                    chain = steps + [(desc, f'{schema}({variant})', out, schema, variant)]
                    add(chain)
                    extend(chain, avail, (f'stage{i}', out))
        for schema, variant, items_t, target_t, out in takes2:  # items + target, at least one of them the previous stage's output
            pool = list(avail) + ([latest] if steps else [])
            for iname, it in pool:
                for tname, tt in pool:
                    if it != items_t or tt != target_t or (steps and latest[0] not in (iname, tname)):
                        continue
                    chain = steps + [(f'items {iname} with target {tname}', f'{schema}({variant})', out, schema, variant)]
                    add(chain)
                    extend(chain, avail, (f'stage{i}', out))

    extend([], sorted(params.items()), None)
    collapsing = ('count', 'distinct_count', 'max', 'min', 'is_palindrome')

    def score(chain):  # stages that throw the data away (count / extreme / bool), or just re-read a list, say little
        return sum(c[1] in collapsing or (c[3] != 'seq_fold' and c[2] in ('int', 'bool')) or c[0].startswith('elements of stage') for c in chain[:-1]) * 10 + sum(c[0].startswith('elements of stage') for c in chain)

    return [{'steps': c, 'support': first_stage_support(facts, c[0][3], c[0][4], d), 'score': score(c)} for c in results]


def chain_text(chain):
    return ' ; '.join(f'stage{i}: {s[0]}, {s[1]} -> {s[2]}' for i, s in enumerate(chain['steps'], 1))


def ranked_chains(problem, facts, pack=PACK, depth=3, per_depth=3, run=None):
    """The chains of chain_candidates, best first: the more of the problem's facts the first stage already satisfies the better, then shorter,
    then chains that keep their data. At most `per_depth` per length, preferring different starting stages: [{'steps', 'support', 'score', 'text', 'length'}]."""
    cands = chain_candidates(problem, facts, pack, depth, run=run)
    for c in cands:
        c['text'], c['length'] = chain_text(c), len(c['steps'])
    cands.sort(key=lambda c: (-c['support'], c['length'], c['score'], c['text']))
    picked = []
    for n in range(1, depth + 1):
        level, firsts, chosen = [c for c in cands if c['length'] == n], set(), []
        for c in level:  # prefer chains that differ in how they start
            if c['steps'][0][:2] not in firsts and len(chosen) < per_depth:
                firsts.add(c['steps'][0][:2]); chosen.append(c)
        chosen += [c for c in level if c not in chosen][:max(0, per_depth - len(chosen))]
        picked += chosen
    picked.sort(key=lambda c: (-c['support'], c['length'], c['score'], c['text']))
    return picked


def chains(problem, facts, pack=PACK, depth=3, per_depth=3):
    """Backward-chaining hint: stage chains that start from the problem's parameters and end in the answer type the tests expect, ranked by how
    many of the problem's facts the first stage already satisfies, then shortest first, at most `per_depth` per length: [(length, text)]."""
    return [(c['length'], c['text']) for c in ranked_chains(problem, facts, pack, depth, per_depth)]


def explain(problem, facts, pack=PACK, max_missing=2, run=None):
    """Nearest schemas and what they lack, as text for the translator / growth, plus the raw near misses."""
    try:
        d = run.engine() if run is not None else engine_for(problem, facts, pack)
    except ValueError as exc:
        return f'rules failed: {str(exc)[:200]}', []
    if d.db.get('schema'):
        return 'a schema is derived: ' + ', '.join(s for _, s in sorted(d.db.get('schema', ()))), []
    near = d.near_misses('schema', (KEY, None), max_missing=max_missing)
    lines = []
    for m in near:
        fmt = lambda lit: f"{lit[0]}({', '.join(a for a in lit[1][1:])})"
        parts = []
        if m['missing']:
            parts.append('needs ' + ' and '.join(fmt(x) for x in m['missing']))
        if m['blocking']:
            parts.append('blocked by ' + ' and '.join(fmt(x) for x in m['blocking']))
        lines.append(f"schema {m['head'][1]}: " + '; '.join(parts))
    hints = ranked_chains(problem, facts, pack, per_depth=6, run=run)
    if hints:
        lines.append('stage chains that could produce the expected answer type from the parameters, best first (write them as stage facts '
                     '"stage I <schema>", "<I>.source", "<I>.aggregate", "<I>.ask", ... if the question really decomposes this way; a chain whose first stage '
                     'is marked with [uses k of your facts] already matches k of the facts you gave): '
                     + ' | '.join(c['text'] + (f" [uses {c['support']} of your facts]" if c['support'] else '') for c in hints))
    return ('\n'.join(lines) if lines else 'no schema rule comes within reach'), near


LIST_TYPES = {'int_list', 'string_list', 'list_of_lists'}


def json_type(v):
    if isinstance(v, bool):
        return 'bool'
    if isinstance(v, int):
        return 'int'
    if v is None:
        return 'none'
    if isinstance(v, str):
        return 'string'
    if isinstance(v, list):
        if not v:
            return 'empty_list'
        if all(isinstance(x, int) and not isinstance(x, bool) for x in v):
            return 'int_list'
        if all(isinstance(x, str) for x in v):
            return 'string_list'
        if all(isinstance(x, list) for x in v):
            return 'list_of_lists'
        return 'list'
    return type(v).__name__


def type_mismatch(problem, facts, pack=PACK, engine=None, run=None):
    """Compare the answer type the rules derive with the types of the tests' expected values.
    Returns a description of the mismatch, or None (also None when no answer type is derived)."""
    d = engine or (run.engine() if run is not None else engine_for(problem, facts, pack))
    derived = {t for p, t in d.db.get('answer_type', ()) if p == KEY}
    if not derived:
        return None
    if (KEY,) in d.db.get('nullable', ()):
        derived.add('none')
    observed = {json_type(t['expected']) for t in problem['tests']}
    bad = {o for o in observed if o not in derived and not (o == 'empty_list' and derived & LIST_TYPES)}
    if bad:
        return f"rules derive answer type {sorted(derived)} but the tests expect {sorted(observed)}"
    return None


SIZE_CLASSES = SIZE_ORDER
COND_TEXT = {'positive': 'is a positive integer', 'nonnegative': 'is a non-negative integer', 'nonzero': 'is non-zero',
             'distinct': 'is distinct from the others (no repeated values)', 'sorted': 'is in sorted order',
             'nonempty': 'exists (the input is never empty)'}


def questions(problem, facts, pack=PACK, run=None):
    """Natural-language questions derived from ask_guarantee / ask_size: what the statement would have to say
    for the refused plan to become admissible. Each is {'id', 'kind', 'param', 'cond'?, 'text'}."""
    try:
        d = run.engine() if run is not None else engine_for(problem, facts, pack)
    except ValueError:
        return []
    roles = {}
    for _, r, a in d.db.get('binds', ()):
        roles.setdefault(a, set()).add(r)
    out = []
    for _, a, c in sorted(d.db.get('ask_guarantee', ())):
        scalar = roles.get(a, set()) <= {'target', 'terms'}
        what = f'the value of `{a}`' if scalar else f'every element of `{a}`'
        out.append({'id': f'g:{a}:{c}', 'kind': 'guarantee', 'param': a, 'cond': c,
                    'text': f'Does the statement guarantee that {what} {COND_TEXT.get(c, "is " + c)}?'})
    for _, a in sorted(d.db.get('ask_size', ())):
        out.append({'id': f's:{a}', 'kind': 'size', 'param': a,
                    'text': f'Does the statement bound the length (or magnitude, for an integer) of `{a}` (give the bound)?'})
    return out


ASK_PROMPT = """You answer questions about a programming problem statement. Use ONLY the signature and statement below.
Do not solve the problem and do not assume typical constraints: if the statement does not say it, the answer is "not stated".

Signature: {signature}
Statement:
{statement}

Questions:
{questions}

For each question answer with "yes" (the statement explicitly guarantees it), "no" (it explicitly contradicts it) or
"not stated". For a question about a bound answer instead with the size class of the stated bound: {classes}
(tiny <= 1e2, small <= 1e3, medium <= 1e5, large <= 1e6, huge <= 1e7, vast beyond) or "not stated".
Every answer other than "not stated" needs "quote": the exact words copied from the statement that justify it.
You have no tools. Reply with only JSON: {{"answers": [{{"id": "<question id>", "answer": "...", "quote": "..."}}]}}"""


def ask_model(problem, qs, model):
    """One claude call that sees only signature + statement + questions. Returns the raw answer list."""
    CALLS["n"] += 1
    prompt = ASK_PROMPT.format(signature=problem['signature'], statement=problem['statement'], classes=', '.join(SIZE_CLASSES),
                               questions='\n'.join(f"{q['id']}: {q['text']}" for q in qs))
    p = subprocess.run(['claude', '-p', '--model', model, '--tools', '', '--no-session-persistence', '--strict-mcp-config'],
                       input=prompt, capture_output=True, text=True, timeout=300, cwd=tempfile.gettempdir())
    return first_json_object(p.stdout).get('answers', [])


def answer_questions(problem, qs, model, answerer=None):
    """Answers verified against the statement: an answer other than 'not stated' whose quote is not a substring of the
    statement (or is empty), or that does not fit the question, is downgraded to 'not stated'. `answerer(problem, qs)`
    replaces the model call (tests). Returns [{'id', 'answer', 'quote', 'raw'?}]."""
    try:
        raw = (answerer or (lambda p, q: ask_model(p, q, model)))(problem, qs)
    except Exception as exc:  # noqa: BLE001
        raw = []
        err = f'answerer error: {exc}'[:200]
    else:
        err = None
    by_id = {r.get('id'): r for r in raw if isinstance(r, dict)}
    norm = lambda s: re.sub(r'\s+', ' ', s)
    out = []
    for q in qs:
        r = by_id.get(q['id'], {})
        ans, quote = str(r.get('answer', 'not stated')).strip().lower(), r.get('quote')
        final = ans
        valid_values = {'yes', 'no'} if q['kind'] == 'guarantee' else set(SIZE_CLASSES) | {'no'}
        if ans != 'not stated' and ans not in valid_values:
            final = 'not stated'
        elif ans != 'not stated' and not (isinstance(quote, str) and quote.strip() and norm(quote.strip()) in norm(problem['statement'])):
            final = 'not stated'
        rec = {'id': q['id'], 'answer': final, 'quote': quote if final != 'not stated' else None}
        if final != ans:
            rec['raw'] = {'answer': ans, 'quote': quote}
        if err:
            rec['error'] = err
        out.append(rec)
    return out


def answer_facts(qs, answers):
    """yes -> guarantees(A,C); a size class -> size(A,class); anything else adds nothing."""
    by_id = {a['id']: a for a in answers}
    facts = []
    for q in qs:
        a = by_id.get(q['id'], {}).get('answer')
        if q['kind'] == 'guarantee' and a == 'yes':
            facts.append(['guarantees', q['param'], q['cond']])
        elif q['kind'] == 'size' and a in SIZE_CLASSES:
            facts.append(['size', q['param'], a])
    return facts


def ask_back(problem, facts, rec, pack=PACK, model='haiku', answerer=None, rounds=2):
    """When the rules refused for unmet preconditions / too_slow, ask the statement, apply verified answers and
    re-evaluate (at most `rounds` times). Returns (facts, rec); rec gets questions / answers / solved_after_questions."""
    for _ in range(rounds):
        if rec['status'] != 'rejected' or not any(k in rec.get('reason', '') for k in ('unmet_precondition', 'too_slow')):
            break
        qs = questions(problem, facts, pack)
        if not qs:
            break
        answers = answer_questions(problem, qs, model, answerer)
        rec.setdefault('questions', []).extend(q['text'] for q in qs)
        rec.setdefault('answers', []).extend(answers)
        new = [f for f in answer_facts(qs, answers) if f not in facts]
        if not new:
            break
        facts = facts + new
        rec2 = evaluate(problem, facts, pack)
        for k in ('status', 'reason', 'why', 'near', 'passed', 'total', 'first_failure', 'source'):
            rec.pop(k, None)
        rec.update(rec2)
        rec['facts_added'] = rec.get('facts_added', []) + new
        if rec2['status'] == 'solved':
            rec['solved_after_questions'] = True
    if 'questions' in rec:
        rec.setdefault('solved_after_questions', False)
    return facts, rec


def build(problem, facts, pack=PACK, reference=False, plan=False, run=None):
    """Facts -> rules -> template -> module path. Raises ValueError with the rule errors.
    plan=True prepends explain_plan as a header comment to the solution (never for the hashed renderings).
    The plain inference is shared with the rest of the same evaluation through `run`; a reference build
    needs the extra want_reference fact, so it builds its own engine instead of the run's."""
    grouped = grouped_facts(problem, facts, pack)
    if reference:
        engine = build_engine(problem, facts, pack, extra_grouped={'want_reference': [[KEY]]})
    else:
        engine = run.engine() if run is not None else build_engine(problem, facts, pack)
    out = Path(tempfile.mkdtemp(prefix='general_'))
    generate({'facts': grouped, 'data': {KEY: {'params': params_of(problem['signature'])}}}, out, pack, engine=engine)
    path = (out / 'reference.py') if reference else (out / 'solution.py')
    if plan and not reference:
        text = (run.plan_text() if run is not None else explain_plan(problem, facts, pack)).replace('\r', '')
        path.write_text('# PLAN (why the rules chose this code)\n' + ''.join(f'# {l}\n' for l in text.splitlines()) + path.read_text())
    return path


ERROR_ADVICE = {
    'element_fact_ignored': 'keep / drop / remainder / map / scale / add / distinct facts are only read by a seq_fold, seq_rank, seq_reduce or palindrome_check '
                            'description; to filter or map the elements and then apply another schema (run_encode, pair_count, bracket_match, knapsack ...) '
                            'declare two stages: stage 1 a seq_fold with those facts and aggregate list (or join for characters), stage 2 the other schema '
                            'reading it with ["2.source","stage","1"] (see the composition paragraph)',
    'source_needs_seq_fold': 'this schema does not read a source: use iterate with a parameter, or put the source in an earlier stage',
    'stage_type_mismatch': 'a stage output feeds an input of another type (int -> digits / range bound / target / bound; list -> source / items; string -> chars)',
    'stage_output_unused': 'every stage but the last must be read by a later stage (source stage I, digits of stageI, items / target / bound stageI ...)',
    'stage_schema_mismatch': 'the schema named in a stage fact must be the schema its own facts derive',
    'stage_ref_bound_needs_seq_fold': 'a bound against an earlier stage (["I.bound","ge","stageJ"]) is only available in a seq_fold stage',
    'two_sources': 'a stage reads one sequence: give one source / iterate',
}


def evaluate(problem, facts, pack=PACK):
    voc = vocab(pack)
    bad = validate(facts, params_of(problem['signature']), voc)
    if bad:
        return {'status': 'invalid', 'reason': bad[:5]}
    run = Run(problem, facts, pack)
    try:
        mismatch = type_mismatch(problem, facts, pack, run=run)
        if mismatch:
            return {'status': 'type_mismatch', 'reason': mismatch}
        module = build(problem, facts, pack, plan=True, run=run)
    except ValueError as exc:
        rec = {'status': 'rejected', 'reason': str(exc)[:300]}
        if 'no_schema' in str(exc):
            rec['near'] = explain(problem, facts, pack, run=run)[0]
        advice = []
        try:
            advice = [ERROR_ADVICE[e] for e in sorted({r[0] for r in run.engine().db.get('error', ())}) if e in ERROR_ADVICE]
        except ValueError:
            pass
        if advice:
            rec['why'] = advice
        if 'too_slow' in str(exc) or 'unmet_precondition' in str(exc):
            d = run.engine()
            rec['why'] = advice + [f'no feasible function for role {r} (its drives roles must be bound by a binds rule and its complexity must fit the sizes)' for _, r in sorted(d.db.get('why_slow', ()))] + \
                         [f'{f} requires {c}, which the statement does not guarantee' for _, f, c in sorted(d.db.get('unmet', ()))]
        return rec
    try:
        res = run_tests(module, problem['tests'])
        source = module.read_text()
    finally:
        shutil.rmtree(module.parent, ignore_errors=True)
    passed = sum(r['ok'] for r in res)
    rec = {'status': ('solved' if passed == len(res) else 'wrong') if res else 'untested', 'passed': passed, 'total': len(res),
           'plan': run.plan_text()}
    if rec['status'] == 'wrong':
        rec['first_failure'] = next(r for r in res if not r['ok'])
        rec['source'] = source
    return rec


def translate_eval(p, voc, pack, model, extractor=None, hint=''):
    """One translation + evaluation: returns (facts, uncovered, rec) with rec = evaluate(...) or {'status': 'uncovered'}."""
    t0 = time.time()
    try:
        facts, uncovered = (extractor or extract)(p, model, voc, hint=hint) if hint else (extractor or extract)(p, model, voc)
    except Exception as exc:  # noqa: BLE001
        facts, uncovered = [], f'extractor error: {exc}'[:200]
    rec = evaluate(p, facts, pack) if facts and not uncovered else {'status': 'uncovered'}
    rec['extract_seconds'] = round(time.time() - t0, 1)
    return facts, uncovered, rec


def answer_types(p, facts, pack):
    try:
        d = engine_for(p, facts, pack)
    except ValueError:
        return set()
    return {t for k, t in d.db.get('answer_type', ()) if k == KEY}


def solve_problem(p, voc, pack, model, twice=False, fallback_model=None, ask=True, extractor=None, answerer=None):
    """Translate + evaluate one problem. Paths (rec['path']):
      single          one translation solved it (the default flow)
      twice_first / twice_second   --translate-twice: both translations solved (first used) / only one solved (that one used)
      ask_back        solved after consulting the statement; near_miss_retry: solved on the hinted retry
      fallback_model  the fallback model's single translation solved it;  unsolved: nothing worked
    rec['model_calls'] counts every claude call spent on the problem; rec['twice'] records both translations' statuses."""
    calls0 = CALLS['n']
    rec = {'id': p['id']}
    facts, uncovered, rec1 = translate_eval(p, voc, pack, model, extractor)
    second = None
    if twice:
        facts_b, unc_b, rec_b = translate_eval(p, voc, pack, model, extractor)
        ok_a, ok_b = rec1['status'] == 'solved', rec_b['status'] == 'solved'
        types_a = answer_types(p, facts, pack) if ok_a else set()
        types_b = answer_types(p, facts_b, pack) if ok_b else set()
        rec['twice'] = {'first': rec1['status'], 'second': rec_b['status'], 'second_facts': facts_b,
                        'agree_answer_type': (types_a == types_b) if (ok_a and ok_b) else None}
        if ok_a:
            rec['path'] = 'twice_first'
        elif ok_b:
            facts, uncovered, rec1 = facts_b, unc_b, rec_b
            rec['path'] = 'twice_second'
        # both failed: continue with the first translation through the usual ask-back / near-miss flow
    rec['facts'] = facts
    if uncovered:
        rec['uncovered'] = uncovered
    rec.update(rec1)
    if rec['status'] == 'solved':
        rec.setdefault('path', 'single')
    if ask and facts and not uncovered and rec['status'] != 'solved':
        facts, rec = ask_back(p, facts, rec, pack, model, answerer)
        rec['facts'] = facts
        if rec.get('solved_after_questions'):
            rec['path'] = 'ask_back'
    if rec['status'] in ('uncovered', 'rejected', 'invalid', 'type_mismatch') and facts:
        # ask the rules what is missing and give the translator one more try with that hint
        near_text, near = explain(p, facts, pack)
        rec['near'] = near_text
        reasons = rec.get('why') or ([str(rec['reason'])] if rec['status'] in ('type_mismatch', 'invalid') else [])
        if near or reasons:
            hint = HINT.format(facts=json.dumps(facts), near='\n'.join(map(str, reasons)) if reasons else near_text)
            facts2, uncovered2, rec2 = translate_eval(p, voc, pack, model, extractor, hint=hint)
            rec['retry_seconds'] = rec2.pop('extract_seconds')
            rec['retry'] = {'facts': facts2, 'uncovered': uncovered2, 'status': rec2['status']}
            if rec2['status'] == 'solved':
                rec.update(rec2); rec['facts'] = facts2; rec.pop('uncovered', None); rec['solved_on_retry'] = True
                rec['path'] = 'near_miss_retry'
    if fallback_model and rec['status'] == 'uncovered':
        facts3, unc3, rec3 = translate_eval(p, voc, pack, fallback_model, extractor)
        rec['fallback'] = {'model': fallback_model, 'facts': facts3, 'uncovered': unc3, 'status': rec3['status']}
        if rec3['status'] == 'solved':
            rec.update(rec3); rec['facts'] = facts3; rec.pop('uncovered', None); rec['path'] = 'fallback_model'
    rec.setdefault('path', 'unsolved')
    if rec['status'] != 'solved':
        rec['path'] = 'unsolved'
    rec['model_calls'] = CALLS['n'] - calls0
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['solve', 'facts'])
    ap.add_argument('problems', type=Path)
    ap.add_argument('--ids', nargs='*')
    ap.add_argument('--model', default='haiku')
    ap.add_argument('--facts', type=Path, help='JSON {problem_id: [[pred, ...], ...]} for the facts command')
    ap.add_argument('--pack', type=Path, default=PACK)
    ap.add_argument('--log', type=Path)
    ap.add_argument('--no-ask', action='store_true', help='do not consult the statement when a plan is refused')
    ap.add_argument('--translate-twice', action='store_true', help='translate independently twice and keep the one that solves (off by default)')
    ap.add_argument('--fallback-model', default=None, help='when the main model ends uncovered after all retries, translate once with this model (off by default)')
    args = ap.parse_args()
    problems = json.loads(args.problems.read_text())
    if args.ids:
        problems = [p for p in problems if p['id'] in args.ids]
    given = json.loads(args.facts.read_text()) if args.facts else {}
    voc, log = vocab(args.pack), []
    pack = args.pack.resolve()
    for p in problems:
        if args.cmd == 'facts':
            rec = {'id': p['id']}
            facts = given.get(p['id'], [])
            rec['facts'] = facts
            rec.update(evaluate(p, facts, pack) if facts else {'status': 'uncovered'})
        else:
            rec = solve_problem(p, voc, pack, args.model, twice=args.translate_twice,
                                fallback_model=args.fallback_model, ask=not args.no_ask)
        log.append(rec)
        print(json.dumps({k: v for k, v in rec.items() if k != 'source'}, ensure_ascii=False), flush=True)
        if args.log:
            args.log.write_text(json.dumps(log, ensure_ascii=False, indent=1))
    counts = {}
    for r in log:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    print('SUMMARY', json.dumps(counts))
    print('SOLVED_AFTER_QUESTIONS', sum(bool(r.get('solved_after_questions')) for r in log), 'ASKED', sum('questions' in r for r in log))


if __name__ == '__main__':
    main()
