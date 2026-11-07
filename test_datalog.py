"""Datalog engine: parsing, stratified negation, and a randomized differential test.

The naive oracle below is independent of the engine (ground enumeration per layer).
If clingo is importable (e.g. ~/opt/logic-venv/bin/python test_datalog.py), it is used as a second oracle.
"""
import itertools, random, unittest

from datalog import Datalog, parse_rules

try:
    import clingo
except ImportError:
    clingo = None

ARITY = {'p0': 1, 'p1': 2, 'p2': 1, 'p3': 2, 'p4': 1, 'p5': 2}
LAYER = {p: i // 2 for i, p in enumerate(ARITY)}
CONST = ['a', 'b', 'c']
VARS = ['X', 'Y', 'Z']


def run(text, facts):
    d = Datalog(parse_rules(text))
    for p, rows in facts.items():
        for r in rows:
            d.add(p, *r)
    d.run()
    return {p: set(d.db.get(p, set())) for p in ARITY}


def random_program(rng):
    rules = []
    for _ in range(rng.randint(1, 7)):
        head = rng.choice(list(ARITY))
        pos, neg, neq = [], [], []
        for _ in range(rng.randint(1, 3)):
            pred = rng.choice([p for p in ARITY if LAYER[p] <= LAYER[head]])
            pos.append((pred, [rng.choice(VARS) if rng.random() < .8 else rng.choice(CONST) for _ in range(ARITY[pred])]))
        bound = sorted({a for _, args in pos for a in args if a in VARS})
        lower = [p for p in ARITY if LAYER[p] < LAYER[head]]
        if lower and bound and rng.random() < .6:
            pred = rng.choice(lower)
            neg.append((pred, [rng.choice(bound) if rng.random() < .8 else rng.choice(CONST) for _ in range(ARITY[pred])]))
        if len(bound) >= 2 and rng.random() < .3:
            neq.append(tuple(rng.sample(bound, 2)))
        hargs = [rng.choice(bound) if bound and rng.random() < .85 else rng.choice(CONST) for _ in range(ARITY[head])]
        lits = [f"{p}({','.join(a)})" for p, a in pos] + [f"not {p}({','.join(a)})" for p, a in neg] + [f'{a} != {b}' for a, b in neq]
        rules.append(f"{head}({','.join(hargs)}) :- {', '.join(lits)}.")
    facts = {p: {tuple(rng.choice(CONST) for _ in range(n)) for _ in range(rng.randint(0, 5))} for p, n in ARITY.items()}
    return '\n'.join(rules), facts


def naive(text, facts):
    db = {p: set(facts.get(p, ())) for p in ARITY}
    rules = parse_rules(text)
    for layer in sorted(set(LAYER.values())):
        changed = True
        while changed:
            changed = False
            for (hp, ha), body in rules:
                if LAYER[hp] != layer:
                    continue
                names = sorted({a for _, _, args in body for a in args if a in VARS})
                for vals in itertools.product(CONST, repeat=len(names)):
                    env = dict(zip(names, vals))
                    g = lambda args: tuple(env.get(a, a) for a in args)
                    ok = all((g(args) in db[p]) if k == 'pos' else (g(args) not in db[p]) if k == 'neg'
                             else g(args)[0] != g(args)[1] for k, p, args in body)
                    if ok and g(ha) not in db[hp]:
                        db[hp].add(g(ha)); changed = True
    return db


def by_clingo(text, facts):
    ctl = clingo.Control(['--warn=none'])
    ctl.add('base', [], text + '\n' + '\n'.join(f"{p}({','.join(r)})." for p, rows in facts.items() for r in rows))
    ctl.ground([('base', [])])
    db = {p: set() for p in ARITY}
    with ctl.solve(yield_=True) as h:
        for m in h:
            for s in m.symbols(atoms=True):
                db[s.name].add(tuple(str(a) for a in s.arguments))
    return db


class DatalogTest(unittest.TestCase):
    def test_negation(self):
        got = run('p(X) :- a(X), not b(X).', {'a': [('1',), ('2',)], 'b': [('2',)]})
        self.assertEqual(Datalog(parse_rules('p(X) :- a(X), not b(X).')).strata.__len__(), 1)
        d = Datalog(parse_rules('p(X) :- a(X), not b(X).')); d.add('a', '1'); d.add('a', '2'); d.add('b', '2'); d.run()
        self.assertEqual(d.db['p'], {('1',)})

    def test_negation_over_derived_predicate_is_stratified(self):
        d = Datalog(parse_rules('reach(X) :- start(X).\nreach(Y) :- reach(X), e(X,Y).\nunreached(X) :- node(X), not reach(X).'))
        for row in [('s',)]:
            d.add('start', *row)
        for x, y in [('s', 'a'), ('a', 'b')]:
            d.add('e', x, y)
        for n in 'sabc':
            d.add('node', n)
        d.run()
        self.assertEqual(d.db['unreached'], {('c',)})

    def test_negation_in_recursion_rejected(self):
        with self.assertRaises(ValueError):
            Datalog(parse_rules('p(X) :- a(X), not q(X).\nq(X) :- a(X), not p(X).'))

    def test_unsupported_syntax_is_rejected(self):
        for rule in ['p(X) :- a(X), X > 1.', 'p(X) :- a(X) ; b(X).', 'p(X) :- a(X) b(X).', 'p(X) :- not b(X).',
                     'p(X) :- a(X), not b(_).', 'p(X) :- a(X)', 'p(X) :- a(Y), X != Y.']:
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                parse_rules(rule)

    def test_quoted_constants(self):
        d = Datalog(parse_rules('p(X) :- pair("a,b (c) 5%",X).\nq("Up, down") :- .'))
        d.add('pair', 'a,b (c) 5%', '1'); d.run()
        self.assertEqual((d.db['p'], d.db['q']), ({('1',)}, {('Up, down',)}))

    def test_random_programs_match_oracles(self):
        rng = random.Random(20261106)
        for i in range(1500):
            text, facts = random_program(rng)
            got = run(text, facts)
            self.assertEqual(got, naive(text, facts), text)
            if clingo:
                self.assertEqual(got, by_clingo(text, facts), text)


if __name__ == '__main__':
    unittest.main()


class NearMissTest(unittest.TestCase):
    RULES = '''schema(P,knapsack) :- items(P,I), target(P,T), ask(P,Q), knap_question(Q).
knap_question(min_count) :- .
schema(P,seq_fold) :- iterate(P,A), aggregate(P,G).
schema(P,grid_bfs) :- grid(P,A), ask(P,shortest_path), not has_start(P).
has_start(P) :- start(P,K,V).
'''

    def engine(self, facts):
        d = Datalog(parse_rules(self.RULES))
        for f in facts:
            d.add(*f)
        d.run()
        return d

    def test_reports_the_single_missing_fact(self):
        d = self.engine([('target', 'p', 'amount'), ('ask', 'p', 'min_count')])
        near = d.near_misses('schema', ('p', None))
        self.assertEqual(near[0]['head'], ('p', 'knapsack'))
        self.assertEqual(near[0]['missing'], [('items', ('p', '?'))])
        self.assertEqual(near[0]['blocking'], [])

    def test_reports_blocking_negation(self):
        d = self.engine([('grid', 'p', 'g'), ('ask', 'p', 'shortest_path'), ('start', 'p', 'char', 'S')])
        near = d.near_misses('schema', ('p', None))
        self.assertEqual(near[0]['head'], ('p', 'grid_bfs'))
        self.assertEqual((near[0]['missing'], near[0]['blocking']), ([], [('has_start', ('p',))]))

    def test_nearest_first_and_budget(self):
        d = self.engine([('iterate', 'p', 'xs')])
        near = d.near_misses('schema', ('p', None), max_missing=1)
        self.assertEqual([m['head'] for m in near], [('p', 'seq_fold')])  # knapsack needs 3 facts: over budget
        near = d.near_misses('schema', ('p', None), max_missing=3)
        self.assertEqual(near[0]['head'], ('p', 'seq_fold'))
        self.assertIn(('p', 'knapsack'), [m['head'] for m in near])

    def test_more_satisfied_literals_rank_nearer(self):
        d = self.engine([('iterate', 'p', 'xs'), ('target', 'p', 'xs'), ('ask', 'p', 'min_count')])
        heads = [m['head'][1] for m in d.near_misses('schema', ('p', None), max_missing=2)]
        self.assertEqual(heads[0], 'knapsack')  # 3 of 4 literals satisfied beats seq_fold's 1 of 2
        self.assertEqual(len(heads), len(set(heads)))  # one entry per schema

    def test_derivable_head_is_not_a_near_miss(self):
        d = self.engine([('iterate', 'p', 'xs'), ('aggregate', 'p', 'sum')])
        self.assertNotIn(('p', 'seq_fold'), [m['head'] for m in d.near_misses('schema', ('p', None))])
