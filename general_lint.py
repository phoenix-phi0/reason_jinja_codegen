"""Static checks over a pack's Datalog rule files (no problem needed, no model).

  dead rule         a body predicate that is neither a vocabulary predicate, a driver fact nor the head of any rule  -> error
  contradiction     a functional predicate derived with different constants by two rules whose bodies are the
                    same up to variable renaming (and the heads agree on every variable)                              -> error
  redundant rule    same head, body equal to / a superset of another rule's body up to renaming                      -> warning
  unused vocabulary a vocabulary predicate in no rule body and in no template (relations.rows/one/has('<pred>')) -> warning

  python general_grow.py lint        (also called when a proposal is admitted)
"""
import json, re
from pathlib import Path

import datalog

DRIVER = {'problem', 'algorithm', 'complexity', 'role', 'drives', 'requires', 'size', 'assumed_size', 'guarantees', 'want_reference',
          'substage', 'parent', 'last_stage', 'before', 'stage_ref', 'stage_var'}
FUNCTIONAL = {'schema', 'answer_type', 'map_fn', 'use_mode', 'order_mode', 'neighbours', 'no_answer'}


def load_rules(pack):
    config = json.loads((pack / 'pack.json').read_text())
    out = []
    for name in config['rules']:
        for head, body in datalog.parse_rules((pack / name).read_text()):
            out.append((name, head, body))
    return out


def _lit_text(lit):
    kind, pred, args = lit
    return f"{'not ' if kind == 'neg' else ''}{pred}({','.join(args)})"


def rule_text(head, body):
    return f"{head[0]}({','.join(head[1])}) :- {', '.join(_lit_text(l) for l in body)}."


def _match(small, big, env, fixed):
    """Is there a renaming of the non-fixed variables of `small` (a list of literals) mapping each literal onto a
    literal of `big`?  env: variable -> term, extended by backtracking."""
    if not small:
        return True
    (kind, pred, args), rest = small[0], small[1:]
    for k2, p2, a2 in big:
        if (kind, pred, len(args)) != (k2, p2, len(a2)):
            continue
        e, ok = dict(env), True
        for x, y in zip(args, a2):
            if datalog._is_var(x):
                if x in fixed and x != y:
                    ok = False; break
                if e.setdefault(x, y) != y:
                    ok = False; break
            elif x != y:
                ok = False; break
        if ok and _match(rest, big, e, fixed):
            return True
    return False


def _heads_align(h1, h2, loose=False):
    """Same predicate/arity; variable positions of h1 map consistently onto h2's. Returns the renaming or None."""
    if h1[0] != h2[0] or len(h1[1]) != len(h2[1]):
        return None
    env = {}
    for x, y in zip(h1[1], h2[1]):
        if datalog._is_var(x) and datalog._is_var(y):
            if env.setdefault(x, y) != y:
                return None
        elif x != y and not loose:
            return None
    return env


def _subset(r1, r2, loose=False):
    """body of r1 ⊆ body of r2 up to renaming, with equal heads (variables of the head are tied)."""
    env = _heads_align(r1[0], r2[0], loose)
    if env is None:
        return False
    fixed = set(env)
    # head variables of r1 are pre-bound to r2's head variables
    return _match(list(r1[1]), list(r2[1]), env, fixed)


def lint(pack):
    """Returns {'errors': [...], 'warnings': [...]} (strings)."""
    pack = Path(pack)
    rules = load_rules(pack)
    voc = set(json.loads((pack / 'vocab.json').read_text())['predicates'])
    heads = {h[0] for _, h, _ in rules}
    errors, warnings = [], []
    for name, head, body in rules:
        for kind, pred, _ in body:
            if kind in ('pos', 'neg') and pred not in voc | DRIVER | heads:
                errors.append(f'dead rule ({name}): body predicate {pred} is not a vocabulary predicate, driver fact or rule head: {rule_text(head, body)}')
    # redundancy / contradiction (only positive+negative literals; != literals are matched as literals too)
    for i, (n1, h1, b1) in enumerate(rules):
        for j, (n2, h2, b2) in enumerate(rules):
            if i == j:
                continue
            if _subset((h1, b1), (h2, b2)) and (not _subset((h2, b2), (h1, b1)) or i < j):
                kind = 'duplicate of' if _subset((h2, b2), (h1, b1)) else 'subsumed by'
                warnings.append(f'redundant rule ({n2}): {rule_text(h2, b2)}  [{kind} {n1}: {rule_text(h1, b1)}]')
            if i < j and h1[0] in FUNCTIONAL and h1[0] == h2[0] and len(h1[1]) == len(h2[1]) and h1 != h2:
                # heads equal up to renaming in variable positions, different in at least one constant
                env, diff, ok = {}, False, True
                for x, y in zip(h1[1], h2[1]):
                    xv, yv = datalog._is_var(x), datalog._is_var(y)
                    if xv and yv:
                        ok &= env.setdefault(x, y) == y
                    elif not xv and not yv:
                        diff |= x != y
                    else:
                        ok = False
                if ok and diff and _subset((h1, b1), (h2, b2), True) and _subset((h2, b2), (h1, b1), True):
                    errors.append(f'contradiction: {n1}: {rule_text(h1, b1)}  vs  {n2}: {rule_text(h2, b2)}')
    in_body = {p for _, _, b in rules for _, p, _ in b}
    tpl = ''.join(p.read_text() for p in (pack / 'templates').rglob('*.j2'))
    used_tpl = set(re.findall(r"relations\.(?:rows|one|has)\(\s*['\"]([A-Za-z0-9_]+)['\"]", tpl))
    for pred in sorted(voc):
        if pred not in in_body and pred not in used_tpl:
            warnings.append(f'unused vocabulary predicate: {pred} appears in no rule body and no template')
    # dedupe (symmetric duplicates)
    seen, w2 = set(), []
    for w in warnings:
        if w not in seen:
            seen.add(w); w2.append(w)
    return {'errors': errors, 'warnings': w2}


def main(pack):
    res = lint(pack)
    for e in res['errors']:
        print('ERROR', e)
    for w in res['warnings']:
        print('WARN ', w)
    print(f"lint: {len(res['errors'])} errors, {len(res['warnings'])} warnings")
    return res
