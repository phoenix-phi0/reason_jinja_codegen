"""小 Datalog 求值器：半朴素自底向上 + 分层否定。

规则一行一条：head(...) :- lit, lit, ... .
  lit 可以是  pred(args)      正文字
              not pred(args)  否定（分层：否定不能出现在递归环里）
              A != B          不等（两边须已被正文字绑定，或是常量）
  head(...) :- .              空规则体：一条事实
参数：大写开头是变量，_ 是通配；其余是常量。常量可加双引号，引号内可以有
逗号、括号、% 和空格；大写常量须加引号。% 之后（引号外）是注释。
看不懂的内容一律报错，不会静默丢弃（旧版会把 not、!=、; 悄悄忽略）。

求值：Datalog(rules).add(谓词, 值…) → run()。builtins：全绑定时的过滤谓词。
"""
import functools
import re
import time
from collections import defaultdict


class Timeout(Exception):
    pass


def _check(deadline):
    if deadline is not None and time.time() > deadline:
        raise Timeout("超时")


# ============================================================ 词法与解析

def _strip_comment(line):
    out, quoted = [], False
    for ch in line:
        if ch == '"':
            quoted = not quoted
        if ch == '%' and not quoted:
            break
        out.append(ch)
    if quoted:
        raise ValueError(f"Unterminated quote: {line}")
    return ''.join(out).strip()


def _split_top(text, sep=','):
    """Split on sep outside quotes and parentheses."""
    parts, depth, quoted, cur = [], 0, False, []
    for ch in text:
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch == '(':
            depth += 1
        elif not quoted and ch == ')':
            depth -= 1
            if depth < 0:
                raise ValueError(f"Unbalanced parentheses: {text}")
        if ch == sep and depth == 0 and not quoted:
            parts.append(''.join(cur)); cur = []
        else:
            cur.append(ch)
    if depth or quoted:
        raise ValueError(f"Unbalanced parentheses or quotes: {text}")
    parts.append(''.join(cur))
    return parts


_ATOM = re.compile(r'\s*([a-z_][A-Za-z0-9_]*)\((.*)\)\s*$', re.S)
_TERM = re.compile(r'^(?:"[^"]*"|[A-Za-z0-9_][A-Za-z0-9_.\-]*|-?\d+)$')


def _parse_term(t):
    t = t.strip()
    if not t or not _TERM.match(t):
        raise ValueError(f"Invalid term: {t!r}")
    return t


def _parse_atom(s):
    m = _ATOM.match(s)
    if not m:
        raise ValueError(f"Invalid atom: {s.strip()!r}")
    args = _split_top(m.group(2))
    return m.group(1), tuple(_parse_term(a) for a in args)


def _is_var(a):
    return a[:1].isupper() or a == "_"


def _value(a):
    return a[1:-1] if a.startswith('"') else a


def _parse_literal(s):
    try:
        return _parse_literal_inner(s)
    except ValueError as exc:
        raise ValueError(f"Cannot parse body literal {s.strip()!r} (supported: pred(..), not pred(..), A != B): {exc}") from None


def _parse_literal_inner(s):
    s = s.strip()
    if not s:
        raise ValueError("Empty literal")
    if s.startswith('not ') or s.startswith('not\t'):
        pred, args = _parse_atom(s[4:])
        return ('neg', pred, args)
    if '!=' in s and not _ATOM.match(s):
        left, right = s.split('!=', 1)
        return ('neq', '!=', (_parse_term(left), _parse_term(right)))
    pred, args = _parse_atom(s)
    return ('pos', pred, args)


def parse_rules(text):
    """Returns a list of (head, body); head = (pred, args), body = [(kind, pred, args)]."""
    rules = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line:
            continue
        if ":-" not in line:
            raise ValueError(f"Expected head :- body: {line}")
        if not line.endswith('.'):
            raise ValueError(f"Rule must end with '.': {line}")
        head_text, body_text = line[:-1].split(":-", 1)
        if ':-' in body_text:
            raise ValueError(f"More than one ':-' (one rule per line): {line}")
        head = _parse_atom(head_text)
        body = [] if not body_text.strip() else [_parse_literal(p) for p in _split_top(body_text)]
        bound = {a for kind, _, args in body if kind == 'pos' for a in args if _is_var(a) and a != "_"}
        if any(a == "_" or (_is_var(a) and a not in bound) for a in head[1]):
            raise ValueError(f"Unbound variable in rule head: {line}")
        for kind, pred, args in body:
            if kind in ('neg', 'neq') and any(_is_var(a) and a != '_' and a not in bound for a in args):
                raise ValueError(f"Variable in '{'not ' + pred if kind == 'neg' else '!='}' is not bound by a positive literal: {line}")
            if kind == 'neg' and '_' in args:
                raise ValueError(f"Wildcard inside 'not' is ambiguous; name the variable: {line}")
        rules.append((head, body))
    return rules


@functools.lru_cache(maxsize=128)
def parse_rules_cached(text):
    """parse_rules with a small cache over the rule text: pack rule files are parsed repeatedly
    (generate / engine_for / build), and identical text always yields an identical rule list.
    Returns immutable tuples, so the cached rules cannot be mutated by a caller."""
    return tuple((head, tuple(body)) for head, body in parse_rules(text))


# ============================================================ 求值

class Datalog:
    """元组集合 + 规则；按否定分层，每层半朴素求值。"""

    def __init__(self, rules, builtins=None, deadline=None, explain=False):
        self.rules = [(h, [b if len(b) == 3 else ('pos', b[0], b[1]) for b in body]) for h, body in rules]
        self.db = defaultdict(set)
        self.builtins = builtins or {}
        self.deadline = deadline
        self.explain = explain
        self.derivations = {}  # (pred, args) -> (rule text, [positive body facts], [absent facts]); first derivation only
        self.arities = {}
        for head, body in self.rules:
            self._arity(*head)
            for kind, pred, args in body:
                if kind != 'neq':
                    self._arity(pred, args)
        self.strata = self._stratify()

    def _arity(self, pred, args):
        previous = self.arities.setdefault(pred, len(args))
        if previous != len(args):
            raise ValueError(f"Inconsistent arity for {pred}: {previous} vs {len(args)}")

    def _stratify(self):
        heads = {h[0] for h, _ in self.rules}
        level = defaultdict(int)
        limit = len(heads) + 1
        changed = True
        while changed:
            changed = False
            for (hp, _), body in self.rules:
                for kind, pred, _ in body:
                    if kind == 'neq' or pred in self.builtins:
                        continue
                    need = level[pred] + (1 if kind == 'neg' else 0)
                    if level[hp] < need:
                        level[hp] = need
                        changed = True
                        if need > limit:
                            raise ValueError(f"Negation inside recursion (not stratifiable) involving {hp}")
        groups = defaultdict(list)
        for rule in self.rules:
            groups[level[rule[0][0]]].append(rule)
        return [groups[k] for k in sorted(groups)]

    def add(self, pred, *args):
        self._arity(pred, args)
        self.db[pred].add(tuple(args))

    def _match(self, args, tup, env):
        env = dict(env)
        for a, v in zip(args, tup):
            if a == "_":
                continue
            if _is_var(a):
                if a in env and env[a] != v:
                    return None
                env[a] = v
            elif _value(a) != v:
                return None
        return env

    def _ground(self, args, env):
        return tuple(env[a] if _is_var(a) else _value(a) for a in args)

    def _eval_body(self, body, sources, env=None, i=0):
        env = env or {}
        if i == len(body):
            yield env
            return
        kind, pred, args = body[i]
        if kind == 'neg':
            if self._ground(args, env) not in self.db.get(pred, ()):
                yield from self._eval_body(body, sources, env, i + 1)
            return
        if kind == 'neq':
            a, b = self._ground(args, env)
            if a != b:
                yield from self._eval_body(body, sources, env, i + 1)
            return
        if pred in self.builtins:
            if self.builtins[pred](*[env[a] for a in args]):
                yield from self._eval_body(body, sources, env, i + 1)
            return
        src = sources[i]
        for j, a in enumerate(args):
            key = env.get(a) if _is_var(a) and a != "_" else (None if _is_var(a) else _value(a))
            if key is not None:
                ix = self._ix.get((id(src), j))
                if ix is None:
                    ix = defaultdict(list)
                    for t in src:
                        ix[t[j]].append(t)
                    self._ix[(id(src), j)] = ix
                src = ix.get(key, ())
                break
        for tup in src:
            e = self._match(args, tup, env)
            if e is not None:
                yield from self._eval_body(body, sources, e, i + 1)

    @staticmethod
    def _order(body):
        """Positive literals first (they bind), then filters; relative order otherwise kept."""
        return [b for b in body if b[0] == 'pos'] + [b for b in body if b[0] != 'pos']

    def _run_stratum(self, rules):
        rules = [(h, self._order(b)) for h, b in rules]
        delta = {p: set(self.db[p]) for p in list(self.db)}
        first = True
        while True:
            _check(self.deadline)
            new = defaultdict(set)
            self._ix = {}
            for head, body in rules:
                pos = [j for j, (k, p, _) in enumerate(body) if k == 'pos' and p not in self.builtins]
                drivers = pos if not first and pos else [None]
                if not first and not pos:
                    continue
                for d in drivers:
                    if d is not None and not delta.get(body[d][1]):
                        continue
                    srcs = [delta.get(p, set()) if j == d else self.db.get(p, set()) for j, (_, p, _) in enumerate(body)]
                    for env in self._eval_body(body, srcs):
                        t = self._ground(head[1], env)
                        if t not in self.db[head[0]]:
                            new[head[0]].add(t)
                            if self.explain and (head[0], t) not in self.derivations:
                                self.derivations[(head[0], t)] = self._derivation(head, body, env)
            first = False
            if not any(new.values()):
                break
            for p, ts in new.items():
                self.db[p] |= ts
            delta = new

    # ------------------------------------------------------------ 推导记录（explain=True）
    def _derivation(self, head, body, env):
        used, absent = [], []
        for kind, pred, args in body:
            if kind == 'neq' or pred in self.builtins:
                continue
            if kind == 'neg':
                absent.append((pred, self._ground(args, env)))
                continue
            if '_' in args:  # wildcard: take the first stored tuple that matches
                tup = next((t for t in sorted(self.db.get(pred, ())) if self._match(args, t, env) is not None), None)
                if tup is None:
                    continue
            else:
                tup = self._ground(args, env)
            used.append((pred, tup))
        return self._rule_text(head, body), used, absent

    def why(self, pred, args, depth=4):
        """Derivation tree of a fact (needs explain=True before run()). Returns None if the fact does not hold;
        {'fact': (pred, args), 'given': True} for facts that were added, not derived; otherwise
        {'fact', 'rule', 'because': [subtrees], 'absent': [(pred, args)]}. Subtrees below `depth` are
        cut to {'fact', 'cut': True}. Only the first derivation found is kept."""
        args = tuple(args)
        if args not in self.db.get(pred, ()):
            return None
        rec = self.derivations.get((pred, args))
        if rec is None:
            return {'fact': (pred, args), 'given': True}
        if depth <= 0:
            return {'fact': (pred, args), 'cut': True}
        rule, used, absent = rec
        return {'fact': (pred, args), 'rule': rule, 'because': [self.why(p, a, depth - 1) for p, a in used], 'absent': absent}

    # ------------------------------------------------------------ 近失解释（为什么推不出）
    def near_misses(self, pred, head_filter=None, max_missing=2, limit=5):
        """Why can `pred` not be derived? For every rule with that head, try to satisfy its body while
        allowing up to max_missing positive literals to be absent from the database. Returns the closest
        attempts, nearest first: [{'head': (...), 'rule': text, 'missing': [(pred, args)], 'blocking': [(pred, args)]}]
        where `missing` are facts that would be needed (unbound variables shown as '?') and `blocking` are
        negated literals that hold although they should not. Call after run(). One level only: the body
        predicates are taken as they stand, which is what rule heads such as schema(P,S) need."""
        found = []
        for head, body in self.rules:
            if head[0] != pred:
                continue
            env0, ok = {}, True
            for a, v in zip(head[1], head_filter or ()):
                if v is None:
                    continue
                if _is_var(a):
                    env0[a] = v
                elif _value(a) != v:
                    ok = False
            if not ok:
                continue
            positives = sum(1 for k, p_, _ in body if k == 'pos' and p_ not in self.builtins)
            for env, missing, blocking in self._near(self._order(body), env0, 0, max_missing):
                if not missing and not blocking:
                    continue
                item = {'head': tuple(env.get(a, '?') if _is_var(a) else _value(a) for a in head[1]),
                        'rule': self._rule_text(head, body), 'missing': missing, 'blocking': blocking,
                        'satisfied': positives - len(missing)}
                if item not in found:
                    found.append(item)
        # nearest first: fewest facts to add or remove, then the most body literals already satisfied;
        # one entry per head (the best rule for it)
        found.sort(key=lambda m: (len(m['missing']) + len(m['blocking']), -m['satisfied'], m['head'].count('?'), m['rule']))
        best, seen = [], set()
        for m in found:
            if m['head'] not in seen:
                seen.add(m['head']); best.append(m)
        return best[:limit]

    def _partial(self, args, env):
        return tuple(env.get(a, '?') if _is_var(a) else _value(a) for a in args)

    def _near(self, body, env, i, budget):
        if i == len(body):
            yield env, [], []
            return
        kind, pred, args = body[i]
        bound = all((not _is_var(a)) or a == '_' or a in env for a in args)
        if kind == 'neg':
            blocked = bound and self._ground(args, env) in self.db.get(pred, ())
            for e, m, b in self._near(body, env, i + 1, budget):
                yield e, m, ([(pred, self._ground(args, env))] if blocked else []) + b
            return
        if kind == 'neq':
            if bound:
                a, b = self._ground(args, env)
                if a == b:
                    return
            yield from self._near(body, env, i + 1, budget)
            return
        if pred in self.builtins:
            if bound and not self.builtins[pred](*[env[a] for a in args]):
                return
            yield from self._near(body, env, i + 1, budget)
            return
        matched = False
        for tup in self.db.get(pred, ()):
            e = self._match(args, tup, env)
            if e is not None:
                matched = True
                yield from self._near(body, e, i + 1, budget)
        if budget > 0 and not matched:
            for e, m, b in self._near(body, env, i + 1, budget - 1):
                yield e, [(pred, self._partial(args, env))] + m, b

    @staticmethod
    def _rule_text(head, body):
        def lit(kind, pred, args):
            if kind == 'neq':
                return f'{args[0]} != {args[1]}'
            return ('not ' if kind == 'neg' else '') + f"{pred}({','.join(args)})"
        return f"{head[0]}({','.join(head[1])}) :- {', '.join(lit(*b) for b in body)}."

    def run(self):
        for rules in self.strata:
            self._run_stratum(rules)
        return {p: self.db[p] for p in {h[0] for h, _ in self.rules}}
