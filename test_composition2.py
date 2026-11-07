"""Task 10 — composition, extended: any sequence-input schema or knapsack as a stage, several sources per stage, sizes of virtual sources,
cross-schema chain hints, the six composition problems."""
import json, math, shutil, unittest
from functools import reduce
from pathlib import Path

import general, general_grow
from grow import run_tests

HERE = Path(__file__).resolve().parent
PROBLEMS = {p['id']: p for p in json.loads((HERE / 'examples' / 'composition2_problems.json').read_text())}
FACTS = json.loads((HERE / 'examples' / 'composition2_facts.json').read_text())


def P(sig, tests):
    return {'id': 't', 'signature': sig, 'statement': '', 'tests': [{'args': a, 'expected': e} for a, e in tests]}


def errors(problem, facts):
    d = general.engine_for(problem, facts)
    return {row[0] for row in d.db.get('error', ())}


def digits_of_factorial(n):
    return [int(c) for c in str(math.factorial(n))]


def stage_facts(*stages, extra=()):
    """facts of a chain: each stage is (schema, [[pred, args...], ...]); stage facts get their '<I>.' prefix."""
    out = list(extra)
    for i, (schema, facts) in enumerate(stages, 1):
        out.append(['stage', str(i), schema])
        out += [[f'{i}.{f[0]}', *f[1:]] for f in facts]
    return out


FACT_STAGE = ('seq_fold', [['source', 'range', '1', 'n'], ['aggregate', 'product']])  # n!
N_ARGS = [['arg', 'n', 'int']]
N_TESTS = [([n], None) for n in (0, 1, 2, 3, 4, 5, 6, 7, 9, 12)]


def with_expected(tests, fn):
    return [(a, fn(*a)) for a, _ in tests]


def gcd_of_digits(n):
    return reduce(math.gcd, digits_of_factorial(n), 0)


def is_palindrome_factorial(n):
    s = str(math.factorial(n)); return s == s[::-1]


def pairs_div3(n):
    d = digits_of_factorial(n)
    return sum(1 for i in range(len(d)) for j in range(i + 1, len(d)) if (d[i] + d[j]) % 3 == 0)


def best_digit_pair_sum(n):
    d = digits_of_factorial(n)
    return max((d[i] + d[j] for i in range(len(d)) for j in range(i + 1, len(d))), default=-1)


def second_largest_digit(n):
    ds = sorted(set(digits_of_factorial(n)), reverse=True)
    return ds[1] if len(ds) > 1 else -1


def balanced(s):
    stack, close = [], {')': '(', ']': '[', '}': '{'}
    for ch in s:
        if ch in '([{': stack.append(ch)
        elif ch in close:
            if not stack or stack.pop() != close[ch]: return False
    return not stack


def encoded_letters(s):
    letters = [c.lower() for c in s if c.isalpha()]
    out, i = '', 0
    while i < len(letters):
        j = i
        while j < len(letters) and letters[j] == letters[i]: j += 1
        out += letters[i] + str(j - i); i = j
    return out


def change_ways(xs, t):
    vals = sorted({x for x in xs if x > 0})
    ways = [1] + [0] * max(t, 0)
    for c in vals:
        for v in range(c, t + 1): ways[v] += ways[v - c]
    return ways[t] if t >= 0 else 0


# (id, signature, facts, tests, expected stage-function schema or None)
SCHEMA_CASES = {
    'seq_reduce': ('f(n)', N_ARGS + stage_facts(FACT_STAGE, ('seq_reduce', [['source', 'digits', 'stage1'], ['fold', 'gcd'], ['if_empty', '0']])),
                   with_expected(N_TESTS, gcd_of_digits)),
    'palindrome_check': ('f(n)', N_ARGS + stage_facts(FACT_STAGE, ('palindrome_check', [['source', 'digits', 'stage1'], ['ask', 'palindrome_check']])),
                         with_expected(N_TESTS, is_palindrome_factorial)),
    'pair_extreme': ('f(n)', N_ARGS + stage_facts(FACT_STAGE, ('pair_extreme', [['source', 'digits', 'stage1'], ['ask', 'best_pair'], ['pair_value', 'sum', 'max'], ['if_empty', '-1']])),
                     with_expected(N_TESTS, best_digit_pair_sum)),
    'seq_rank': ('f(n)', N_ARGS + stage_facts(FACT_STAGE, ('seq_rank', [['source', 'digits', 'stage1'], ['distinct', 'mapped'], ['select_rank', 'largest', '2'], ['if_empty', '-1']])),
                 with_expected(N_TESTS, second_largest_digit)),
    'pair_count': ('f(n)', N_ARGS + stage_facts(FACT_STAGE, ('pair_count', [['source', 'digits', 'stage1'], ['ask', 'count_pairs'], ['pair_test', 'sum', '3', '0']])),
                   with_expected(N_TESTS, pairs_div3)),
    'bracket_match': ('f(s)', [['arg', 's', 'string']] + stage_facts(('seq_fold', [['source', 'chars', 's'], ['drop', 'space'], ['aggregate', 'join']]),
                                                                      ('bracket_match', [['source', 'stage', '1'], ['ask', 'balanced_brackets'], ['bracket_pair', '(', ')'], ['bracket_pair', '[', ']'], ['bracket_pair', '{', '}']])),
                      [([s], balanced(s)) for s in ('', '()', '( )', '([)]', '{[()]}', '((', 'a (b [c] ) d', ')(', '[ ( ] )')]),
    'run_encode': ('f(s)', [['arg', 's', 'string']] + stage_facts(('seq_fold', [['source', 'chars', 's'], ['keep', 'letter'], ['map', 'lower'], ['aggregate', 'join']]),
                                                                  ('run_encode', [['source', 'stage', '1'], ['ask', 'run_length']])),
                   [([s], encoded_letters(s)) for s in ('', 'aab', 'a1a', 'AaBb', 'Mississippi', 'x-x-x y', '123', 'zz9Zz')]),
    'knapsack': ('f(xs, t)', [['arg', 'xs', 'int_list'], ['arg', 't', 'int']] + stage_facts(
        ('seq_fold', [['iterate', 'xs'], ['keep', 'positive'], ['distinct', 'mapped'], ['aggregate', 'list']]),
        ('knapsack', [['items', 'stage1'], ['target', 't'], ['ask', 'count_ways']])),
        [(a, change_ways(*a)) for a in ([[1, 2, 5], 11], [[], 0], [[], 3], [[3, 3, -2, 0, 4], 10], [[-1, -5], 5], [[2, 4], 7], [[1], 0], [[7, 1, 2, 2], 14], [[5, 5, 5], 15])]),
}


def record(pid, sig, facts, tests):
    rec = P(sig, tests); rec['id'] = pid; rec['facts'] = facts; rec['statement'] = pid
    return rec


class EverySchemaAsAStageTest(unittest.TestCase):
    def test_each_schema_is_solved_as_a_stage_and_agrees_with_its_reference(self):
        for name, (sig, facts, tests) in SCHEMA_CASES.items():
            with self.subTest(name):
                rec = record('case_' + name, sig, facts, tests)
                result = general.evaluate(rec, facts)
                self.assertEqual(result['status'], 'solved', result)
                self.assertEqual(result['passed'], len(tests))
                self.assertIsNone(general_grow.differential(general.PACK, rec))

    def test_a_non_fold_stage_is_a_function_checked_as_glue_and_the_fold_stage_stays_inline(self):
        sig, facts, tests = SCHEMA_CASES['pair_count']
        module = general.build(record('case_pc', sig, facts, tests), facts)
        try:
            source = module.read_text()
        finally:
            shutil.rmtree(module.parent, ignore_errors=True)
        self.assertIn('def _stage2(n, _s1):', source)
        self.assertIn('return _stage2(n, _s1)', source)
        self.assertNotIn('def _stage1', source)
        self.assertEqual(general_grow.glue_violations(source, general_grow.chosen_functions(source)), [])
        self.assertNotIn('_stage2', general_grow.chosen_functions(source))

    def test_the_glue_whitelist_covers_stage_functions(self):
        base = 'def solve(xs):\n    return _stage1(xs)\n\n\ndef _stage1(xs):\n%s\n'
        for body, word in (('    while xs:\n        xs = xs[1:]\n    return 0', 'While'),
                           ('    return [sorted(xs) for x in xs]', 'sorted() inside a loop'),
                           ('    return open("f")', 'open')):
            with self.subTest(word):
                bad = general_grow.glue_violations(base % body, set())
                self.assertTrue(any(word in b for b in bad), bad)
        self.assertEqual(general_grow.glue_violations(base % '    return sorted(xs)[0]', set()), [])

    def test_stage_schema_must_match_the_derived_schema(self):
        facts = N_ARGS + stage_facts(FACT_STAGE, ('seq_rank', [['source', 'digits', 'stage1'], ['aggregate', 'sum']]))
        self.assertIn('stage_schema_mismatch', errors(P('f(n)', [([3], 0)]), facts))


class SeveralSourcesTest(unittest.TestCase):
    def test_knapsack_stage_reads_a_parameter_and_an_earlier_stage(self):
        prob = PROBLEMS['coins_for_digit_sum']
        d = general.engine_for(prob, FACTS['coins_for_digit_sum'])
        self.assertIn(('p.2', '_s1'), {(r[0], r[1]) for r in d.db['target']})
        self.assertIn(('p.2', 'coins'), {(r[0], r[1]) for r in d.db['items']})
        self.assertEqual(errors(prob, FACTS['coins_for_digit_sum']), set())

    def test_a_threshold_from_an_earlier_stage_filters_a_parameter_sequence(self):
        prob = PROBLEMS['top_k_even_sum']
        module = general.build(prob, FACTS['top_k_even_sum'])
        try:
            source = module.read_text()
        finally:
            shutil.rmtree(module.parent, ignore_errors=True)
        self.assertIn('x >= _s1', source)
        self.assertEqual(general.evaluate(prob, FACTS['top_k_even_sum'])['status'], 'solved')

    def test_stage_references_are_validated(self):
        voc, params = general.vocab(), ['xs', 'n']
        ok = lambda facts: general.validate(facts, params, voc)
        base = [['arg', 'xs', 'int_list'], ['arg', 'n', 'int'], ['stage', '1', 'seq_fold'], ['stage', '2', 'knapsack'], ['1.iterate', 'xs'], ['1.aggregate', 'list']]
        self.assertEqual(ok(base + [['2.items', 'stage1'], ['2.target', 'n'], ['2.ask', 'count_ways']]), [])
        self.assertTrue(ok(base + [['2.items', 'stage2'], ['2.target', 'n']]))      # not an earlier stage
        self.assertTrue(ok(base + [['2.items', 'zzz'], ['2.target', 'n']]))         # neither parameter nor stage
        self.assertTrue(ok([['arg', 'xs', 'int_list'], ['items', 'stage1'], ['target', 'n']]))   # a flat problem has no stages
        self.assertEqual(ok(base + [['2.bound', 'ge', 'stage1']]), [])
        self.assertTrue(ok(base + [['2.bound', 'ge', 'stage2']]))
        self.assertTrue(ok(base + [['1.bound', 'ge', 'stage1']]))                   # stage 1 has no earlier stage
        self.assertTrue(ok(base + [['2.source', 'range', '1', 'stage2']]))
        self.assertEqual(ok(base + [['2.source', 'range', '1', 'stage1']]), [])
        self.assertTrue(ok([['stage', '1', 'case_convert']]))                       # not a stage schema

    def test_type_checks_between_stages(self):
        sig = P('f(xs, n)', [([[1], 1], 0)])
        base = [['arg', 'xs', 'int_list'], ['arg', 'n', 'int'], ['size', 'n', 'tiny'], ['size', 'xs', 'small'], ['guarantees', 'xs', 'positive'], ['guarantees', 'xs', 'distinct']]
        s1_list = ('seq_fold', [['iterate', 'xs'], ['aggregate', 'list']])
        s1_sum = ('seq_fold', [['iterate', 'xs'], ['aggregate', 'sum']])
        kn = lambda items, target: ('knapsack', [['items', items], ['target', target], ['ask', 'count_ways']])
        self.assertEqual(errors(sig, base + stage_facts(s1_list, kn('stage1', 'n'))) - {'unmet_precondition'}, set())
        self.assertIn('stage_type_mismatch', errors(sig, base + stage_facts(s1_sum, kn('stage1', 'n'))))     # items from an int
        self.assertIn('stage_type_mismatch', errors(sig, base + stage_facts(s1_list, kn('xs', 'stage1'))))   # target from a list
        self.assertIn('stage_output_unused', errors(sig, base + stage_facts(s1_list, kn('xs', 'n'))))
        self.assertIn('stage_ref_bound_needs_seq_fold', errors(sig, base + stage_facts(s1_sum, ('seq_rank', [['iterate', 'xs'], ['select_rank', 'largest', '1'], ['if_empty', '0'], ['bound', 'ge', 'stage1']]))))

    def test_guarantees_flow_through_a_pass_through_stage(self):
        sig = P('f(xs, t)', [([[1], 1], 0)])
        base = [['arg', 'xs', 'int_list'], ['arg', 't', 'int'], ['size', 't', 'tiny'], ['size', 'xs', 'small']]
        kn = ('knapsack', [['items', 'stage1'], ['target', 't'], ['ask', 'count_ways']])
        stage = lambda extra, agg='list': ('seq_fold', [['iterate', 'xs'], ['aggregate', agg]] + extra)
        self.assertIn('unmet_precondition', errors(sig, base + stage_facts(stage([]), kn)))
        self.assertEqual(errors(sig, base + stage_facts(stage([['keep', 'positive'], ['distinct', 'mapped']]), kn)), set())
        # a stage that changes the values passes nothing on
        self.assertIn('unmet_precondition', errors(sig, base + stage_facts(stage([['keep', 'positive'], ['distinct', 'mapped'], ['add', '1']]), kn)))
        # statement guarantees about the parameter reach the next stage through an identity map
        self.assertEqual(errors(sig, base + [['guarantees', 'xs', 'positive'], ['guarantees', 'xs', 'distinct']] + stage_facts(stage([]), kn)), set())


class VirtualSizeTest(unittest.TestCase):
    N = P('f(n, t)', [([5, 5], 0)])

    def sizes(self, facts):
        d = general.engine_for(self.N, facts)
        return {(r[0], r[1]): r[2] for r in d.db.get('vsize', ())}

    def test_range_takes_the_class_of_its_upper_bound(self):
        for cls in ('tiny', 'small', 'medium', 'large', 'huge'):
            facts = [['arg', 'n', 'int'], ['arg', 't', 'int'], ['size', 'n', cls], ['source', 'range', '1', 'n'], ['aggregate', 'sum']]
            self.assertEqual(self.sizes(facts)[('p', '$range')], cls)
        literal = [['arg', 'n', 'int'], ['arg', 't', 'int'], ['source', 'range', '1', '5000'], ['aggregate', 'sum']]
        self.assertEqual(self.sizes(literal)[('p', '$range')], 'medium')

    def test_digits_are_tiny_chars_take_the_size_of_the_string_and_stage_outputs_follow_their_stage(self):
        d = lambda facts, sig='f(n, s)': general.engine_for(P(sig, [([5, 'ab'], 0)]), facts).db
        self.assertIn(('p', '$digits', 'tiny'), set(map(tuple, d([['arg', 'n', 'int'], ['arg', 's', 'string'], ['source', 'digits', 'n'], ['aggregate', 'sum']])['vsize'])))
        self.assertIn(('p', '$chars', 'large'), set(map(tuple, d([['arg', 'n', 'int'], ['arg', 's', 'string'], ['size', 's', 'large'], ['source', 'chars', 's'], ['aggregate', 'count']])['vsize'])))
        staged = d(N_ARGS + [['size', 'n', 'small']] + stage_facts(FACT_STAGE, ('seq_fold', [['source', 'digits', 'stage1'], ['aggregate', 'sum']])), 'f(n)')
        sizes = {(r[0], r[1]): r[2] for r in staged['vsize']}
        self.assertEqual(sizes[('p.1', '$range')], 'small')
        self.assertEqual(sizes[('p.2', '$digits')], 'medium')       # digits of a product can be many
        self.assertEqual(sizes[('p.2', '_s1')], 'vast')              # a product's magnitude is unknown

    def test_a_large_range_feeding_an_n_times_t_stage_is_too_slow(self):
        def facts(n_cls, t_cls):
            return [['arg', 'n', 'int'], ['arg', 't', 'int'], ['size', 'n', n_cls], ['size', 't', t_cls]] + stage_facts(
                ('seq_fold', [['source', 'range', '1', 'n'], ['aggregate', 'list']]), ('knapsack', [['items', 'stage1'], ['target', 't'], ['ask', 'count_ways']]))
        self.assertEqual(errors(self.N, facts('small', 'small')), set())
        self.assertIn('too_slow', errors(self.N, facts('large', 'medium')))
        self.assertIn('too_slow', errors(self.N, facts('medium', 'medium')))
        self.assertEqual(errors(self.N, facts('medium', 'tiny')), set())

    def test_a_vast_range_is_refused_and_an_unbounded_stage_output_cannot_size_a_target(self):
        vast = [['arg', 'n', 'int'], ['arg', 't', 'int'], ['size', 'n', 'vast'], ['source', 'range', '1', 'n'], ['aggregate', 'sum']]
        self.assertIn('too_slow', errors(self.N, vast))
        sum_target = [['arg', 'n', 'int'], ['arg', 't', 'int'], ['size', 'n', 'small'], ['size', 't', 'tiny'], ['guarantees', 'n', 'positive']] + stage_facts(
            ('seq_fold', [['source', 'range', '1', 'n'], ['aggregate', 'sum']]), ('knapsack', [['items', 'zz'], ['target', 'stage1'], ['ask', 'min_count']]))
        self.assertIn('too_slow', errors(P('f(n, t, zz)', [([5, 5, [1]], 0)]), [['arg', 'zz', 'int_list']] + sum_target))

    def test_counting_stages_are_bounded_by_what_they_read(self):
        # the digit sum of an integer parameter is small, so it may be a knapsack target
        prob = PROBLEMS['coins_for_digit_sum']
        d = general.engine_for(prob, FACTS['coins_for_digit_sum'])
        self.assertIn(('p', '1', 'small'), {(r[0], r[1], r[2]) for r in d.db['out_size']})
        # max overlap is at most the number of intervals: it may bound a range
        prob = PROBLEMS['overlap_factorial']
        d = general.engine_for(prob, FACTS['overlap_factorial'])
        self.assertEqual(errors(prob, FACTS['overlap_factorial']), set())


class SixProblemsTest(unittest.TestCase):
    def test_each_problem_has_enough_tests_and_a_hand_written_description(self):
        self.assertEqual(len(PROBLEMS), 6)
        for pid, prob in PROBLEMS.items():
            self.assertGreaterEqual(len(prob['tests']), 8, pid)
            self.assertIn(pid, FACTS)

    def test_the_six_problems_are_solved_without_a_new_schema(self):
        for pid, prob in PROBLEMS.items():
            with self.subTest(pid):
                result = general.evaluate(prob, FACTS[pid])
                self.assertEqual(result['status'], 'solved', result)
                self.assertEqual(result['passed'], len(prob['tests']))
                schemas = {s for _, s in general.engine_for(prob, FACTS[pid]).db['schema']}
                self.assertEqual(schemas - {'staged'}, schemas & set(general.vocab()['stage']['values']['schema']))

    def test_the_references_agree_and_the_glue_passes(self):
        for pid, prob in PROBLEMS.items():
            with self.subTest(pid):
                module = general.build(prob, FACTS[pid])
                ref = general.build(prob, FACTS[pid], reference=True)
                try:
                    source = module.read_text()
                    self.assertEqual(general_grow.glue_violations(source, general_grow.chosen_functions(source)), [])
                    self.assertTrue(all(r['ok'] for r in run_tests(ref, prob['tests'])))
                finally:
                    shutil.rmtree(module.parent, ignore_errors=True); shutil.rmtree(ref.parent, ignore_errors=True)

    def test_they_are_stored_with_the_same_facts(self):
        for pid in PROBLEMS:
            rec = json.loads((general.PACK / 'solved' / f'{pid}.json').read_text())
            self.assertEqual(rec['facts'], FACTS[pid])
            self.assertEqual(rec['tests'], PROBLEMS[pid]['tests'])

    def test_expected_values_come_from_brute_force_not_from_the_system(self):
        ns = {'__file__': str(HERE / 'examples' / 'make_composition2.py')}
        exec((HERE / 'examples' / 'make_composition2.py').read_text().split('def ints(')[0], ns)
        for pid, prob in PROBLEMS.items():
            for t in prob['tests']:
                self.assertEqual(ns[pid](*t['args']), t['expected'], (pid, t['args']))


class RankedChainTest(unittest.TestCase):
    def texts(self, prob, facts, **kw):
        return [t for _, t in general.chains(prob, facts, **kw)]

    def test_chains_cross_schemas(self):
        texts = self.texts(PROBLEMS['overlap_factorial'], [['arg', 'intervals', 'interval_list']], per_depth=50)
        self.assertIn('stage1: intervals, interval_scan(max_overlap) -> int ; stage2: the integers 1..stage1, product -> int', texts, 'overlap chain missing')
        texts = self.texts(PROBLEMS['coins_for_digit_sum'], [['arg', 'coins', 'int_list'], ['arg', 'n', 'int']], per_depth=400)
        self.assertIn('stage1: digits of n, sum -> int ; stage2: items coins with target stage1, knapsack(min_count) -> int', texts, 'coins chain missing')
        texts = self.texts(PROBLEMS['digit_pairs_div3'], [['arg', 'n', 'int']], per_depth=400)
        self.assertIn('stage1: the integers 1..n, product -> int ; stage2: digits of stage1, pair_count(count) -> int', texts, 'factorial pair chain missing')

    def test_every_stage_after_the_first_reads_the_previous_one_and_the_chain_ends_in_the_expected_type(self):
        for pid, flat in (('coins_for_digit_sum', [['arg', 'coins', 'int_list'], ['arg', 'n', 'int']]), ('longest_letter_run', [['arg', 's', 'string']]),
                          ('overlap_factorial', [['arg', 'intervals', 'interval_list']])):
            prob = PROBLEMS[pid]
            want = {general.json_type(t['expected']) for t in prob['tests']}
            for n, text in general.chains(prob, flat, per_depth=60):
                steps = text.split(' ; ')
                self.assertEqual(len(steps), n)
                self.assertIn(steps[-1].rsplit('-> ', 1)[1], want)
                for i, s in enumerate(steps[1:], 1):
                    self.assertIn(f'stage{i}', s.split(':', 1)[1].split(', ')[0])

    def test_ranked_by_how_many_facts_the_first_stage_satisfies(self):
        prob = PROBLEMS['top_k_even_sum']
        flat = [['arg', 'nums', 'int_list'], ['arg', 'k', 'int'], ['iterate', 'nums'], ['keep', 'even'], ['distinct', 'mapped'], ['select_rank', 'largest', 'k'], ['if_empty', '0']]
        ranked = general.ranked_chains(prob, flat)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]['steps'][0][3], 'seq_rank')
        supports = [c['support'] for c in ranked]
        self.assertEqual(supports, sorted(supports, reverse=True))
        self.assertGreaterEqual(ranked[0]['support'], 5)
        # another set of facts ranks another first stage first
        flat2 = [['arg', 'nums', 'int_list'], ['arg', 'k', 'int'], ['iterate', 'nums'], ['ask', 'count_pairs'], ['pair_test', 'sum', '3', '0']]
        self.assertEqual(general.ranked_chains(prob, flat2)[0]['steps'][0][3], 'pair_count')

    def test_an_aggregate_only_counts_for_the_variant_it_selects(self):
        d = general.engine_for(PROBLEMS['top_k_even_sum'], [['arg', 'nums', 'int_list'], ['arg', 'k', 'int']])
        facts = [['iterate', 'nums'], ['aggregate', 'sum'], ['keep', 'even']]
        self.assertEqual(general.first_stage_support(facts, 'seq_fold', 'sum', d), 3)
        self.assertEqual(general.first_stage_support(facts, 'seq_fold', 'count', d), 2)
        self.assertEqual(general.first_stage_support(facts, 'pair_count', 'count', d), 1)   # only iterate

    def test_the_hint_reaches_the_translator_with_support_marks(self):
        prob = PROBLEMS['top_k_even_sum']
        flat = [['arg', 'nums', 'int_list'], ['arg', 'k', 'int'], ['keep', 'even'], ['select_rank', 'largest', 'k'], ['if_empty', '0']]   # no iterate: no schema yet
        text, _ = general.explain(prob, flat)
        self.assertIn('seq_rank(kth)', text)
        self.assertIn('of your facts]', text)


class IgnoredElementFactsTest(unittest.TestCase):
    FLAT = [['arg', 's', 'string'], ['iterate', 's'], ['keep', 'letter'], ['map', 'lower'], ['ask', 'run_length'], ['run_output', 'longest_run']]

    def test_element_facts_on_a_schema_that_ignores_them_are_rejected_not_dropped(self):
        prob = PROBLEMS['longest_letter_run']
        self.assertEqual(errors(prob, self.FLAT), {'element_fact_ignored'})
        # the same facts without keep / map are fine for run_encode alone, and the filters are fine on seq_fold
        self.assertEqual(errors(prob, [f for f in self.FLAT if f[0] not in ('keep', 'map')]), set())
        self.assertEqual(errors(prob, FACTS['longest_letter_run']), set())

    def test_the_rejection_explains_how_to_compose(self):
        rec = general.evaluate(PROBLEMS['longest_letter_run'], self.FLAT)
        self.assertEqual(rec['status'], 'rejected')
        self.assertTrue(any('two stages' in w for w in rec['why']), rec)

    def test_the_hinted_retry_turns_the_flat_description_into_a_chain(self):
        prob = PROBLEMS['longest_letter_run']
        calls = []

        def extractor(problem, model, voc, hint=''):
            calls.append(hint)
            return (FACTS['longest_letter_run'], None) if hint else (self.FLAT, None)
        rec = general.solve_problem(prob, general.vocab(), general.PACK, 'fake', extractor=extractor)
        self.assertEqual(rec['status'], 'solved', rec.get('reason'))
        self.assertEqual(rec['path'], 'near_miss_retry')
        self.assertEqual(len(calls), 2)
        self.assertIn('two stages', calls[1])


if __name__ == '__main__':
    unittest.main()
