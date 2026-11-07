"""Composition without a model: implicit sources, stage chains, condition trees, backward-chaining hints."""
import json, random, shutil, unittest
from pathlib import Path

import general, general_grow
from grow import run_tests

HERE = Path(__file__).resolve().parent
PROBLEMS = {p['id']: p for p in json.loads((HERE / 'examples' / 'composition_problems.json').read_text())}
FACTS = json.loads((HERE / 'examples' / 'composition_facts.json').read_text())


def P(sig, tests):
    return {'id': 't', 'signature': sig, 'statement': '', 'tests': [{'args': a, 'expected': e} for a, e in tests]}


def errors(problem, facts):
    """Names of the error(...) facts the rules derive (the engine is run without the status/type layers)."""
    d = general.engine_for(problem, facts)
    return {row[0] for row in d.db.get('error', ())}


def staged(*stages, extra=()):
    """facts of a two-or-more stage seq_fold chain; each stage is a list of [pred, args...] written for that stage."""
    out = list(extra)
    for i, facts in enumerate(stages, 1):
        out.append(['stage', str(i), 'seq_fold'])
        out += [[f'{i}.{f[0]}', *f[1:]] for f in facts]
    return out


NUM = P('solve(n)', [([5], 0)])
LIST = P('solve(xs)', [([[1, 2]], 0)])
STR = P('solve(s)', [(['ab'], 0)])


class AcceptanceTest(unittest.TestCase):
    def test_four_problems_are_solved_without_a_new_schema(self):
        for pid, problem in PROBLEMS.items():
            with self.subTest(pid):
                rec = general.evaluate(problem, FACTS[pid])
                self.assertEqual(rec['status'], 'solved', rec)
                d = general.engine_for(problem, FACTS[pid])
                self.assertTrue({s for _, s in d.db['schema']} <= {'seq_fold', 'staged', 'range_steps'})

    def test_generated_code_passes_the_glue_whitelist_and_matches_the_reference(self):
        for pid, problem in PROBLEMS.items():
            with self.subTest(pid):
                module = general.build(problem, FACTS[pid])
                ref = general.build(problem, FACTS[pid], reference=True)
                try:
                    source = module.read_text()
                    self.assertEqual(general_grow.glue_violations(source, general_grow.chosen_functions(source)), [])
                    self.assertTrue(all(r['ok'] for r in run_tests(ref, problem['tests'])))
                finally:
                    shutil.rmtree(module.parent, ignore_errors=True); shutil.rmtree(ref.parent, ignore_errors=True)

    def test_stages_are_rendered_in_order_outside_loops(self):
        module = general.build(PROBLEMS['factorial_digit_sum'], FACTS['factorial_digit_sum'])
        try:
            src = module.read_text()
        finally:
            shutil.rmtree(module.parent, ignore_errors=True)
        self.assertLess(src.index('_s1 ='), src.index('str(abs(_s1))'))
        self.assertEqual(src.count('def '), 1)

    def test_stored_composition_problems_are_in_the_regression_set(self):
        for pid in PROBLEMS:
            self.assertTrue((general.PACK / 'solved' / f'{pid}.json').exists(), pid)
        self.assertEqual(general_grow.affected(general.PACK), {})  # the template changes did not alter any rendered solution


class SourceTest(unittest.TestCase):
    def test_range_digits_chars_and_param_sources(self):
        self.assertEqual(general.evaluate(P('solve(a, b)', [([2, 5], 14)]), [['arg', 'a', 'int'], ['arg', 'b', 'int'], ['source', 'range', 'a', 'b'], ['aggregate', 'sum']])['status'], 'solved')
        self.assertEqual(general.evaluate(P('solve(n)', [([9045], 18), ([-12], 3)]), [['arg', 'n', 'int'], ['source', 'digits', 'n'], ['aggregate', 'sum']])['status'], 'solved')
        self.assertEqual(general.evaluate(P('solve(s)', [(['a1b22'], 3)]), [['arg', 's', 'string'], ['source', 'chars', 's'], ['keep', 'digit'], ['map', 'to_int'], ['aggregate', 'count']])['status'], 'solved')
        self.assertEqual(general.evaluate(P('solve(xs)', [([[1, 2, 3]], 6)]), [['arg', 'xs', 'int_list'], ['source', 'param', 'xs'], ['aggregate', 'sum']])['status'], 'solved')

    def test_range_with_literal_bounds(self):
        rec = general.evaluate(P('solve(n)', [([7], 28)]), [['arg', 'n', 'int'], ['source', 'range', '1', '7'], ['aggregate', 'sum']])
        self.assertEqual(rec['status'], 'solved', rec)

    def test_failing_sources(self):
        rules = lambda prob, facts: errors(prob, facts)
        self.assertIn('range_param_not_int', rules(STR, [['arg', 's', 'string'], ['source', 'range', '1', 's'], ['aggregate', 'sum']]))
        self.assertIn('digits_of_non_int', rules(LIST, [['arg', 'xs', 'int_list'], ['source', 'digits', 'xs'], ['aggregate', 'sum']]))
        self.assertIn('chars_of_non_string', rules(NUM, [['arg', 'n', 'int'], ['source', 'chars', 'n'], ['aggregate', 'count']]))
        self.assertIn('two_sources', rules(LIST, [['arg', 'xs', 'int_list'], ['iterate', 'xs'], ['source', 'range', '1', '3'], ['aggregate', 'sum']]))
        # task 10 widened the rule: every sequence-input schema takes a source; a schema without a sequence input (date_calc) still refuses one
        date = P('f(n, y, m, d)', [([1, 2, 3, 4], 0)])
        date_facts = [['arg', 'n', 'int'], ['arg', 'y', 'int'], ['arg', 'm', 'int'], ['arg', 'd', 'int'], ['source', 'digits', 'n'], ['ask', 'date_offset'],
                      ['date_fields', 'y', 'm', 'd'], ['date_origin', '2000', '1', '1']]
        self.assertIn('source_needs_seq_fold', rules(date, date_facts))
        self.assertIn('range_needs_upper_bound', rules(NUM, [['arg', 'n', 'int'], ['source', 'range', '1', '-'], ['aggregate', 'sum']]))

    def test_invalid_source_facts(self):
        bad = lambda f: general.validate([['arg', 'n', 'int'], f], ['n'], general.vocab())
        self.assertTrue(bad(['source', 'range', '1']))            # no upper bound
        self.assertTrue(bad(['source', 'range', '1', 'zzz']))     # not an int or a parameter
        self.assertTrue(bad(['source', 'digits', 'stage1']))      # no such stage in a flat problem
        self.assertTrue(bad(['source', 'param', 'n', '3']))
        self.assertTrue(bad(['source', 'stage', '1']))
        self.assertFalse(bad(['source', 'range', '1', 'n']))

    def test_char_conditions_on_a_numeric_source_are_refused(self):
        self.assertIn('char_condition_on_numbers', errors(NUM, [['arg', 'n', 'int'], ['source', 'range', '1', 'n'], ['keep', 'vowel'], ['aggregate', 'count']]))

    def test_knapsack_items_from_a_range(self):
        rec = general.evaluate(PROBLEMS['frog_jumps'], FACTS['frog_jumps'])
        self.assertEqual(rec['status'], 'solved')
        d = general.engine_for(PROBLEMS['frog_jumps'], FACTS['frog_jumps'])
        self.assertEqual({s for _, s in d.db['schema']}, {'range_steps'})


class StageTest(unittest.TestCase):
    def test_three_stage_chain(self):
        # sum of the digits of the number of digits of n!  (range -> product -> digits count -> digits sum)
        facts = staged([['source', 'range', '1', 'n'], ['aggregate', 'product']],
                       [['source', 'digits', 'stage1'], ['aggregate', 'count']],
                       [['source', 'digits', 'stage2'], ['aggregate', 'sum']], extra=[['arg', 'n', 'int']])
        import math
        tests = [([n], sum(map(int, str(len(str(math.factorial(n))))))) for n in (1, 5, 25, 70, 100)]
        self.assertEqual(general.evaluate(P('solve(n)', tests), facts)['status'], 'solved')

    def test_list_output_feeds_the_next_stage(self):
        facts = staged([['source', 'param', 'xs'], ['keep', 'positive'], ['aggregate', 'list']], [['source', 'stage', '1'], ['aggregate', 'max'], ['if_empty', '0']],
                       extra=[['arg', 'xs', 'int_list']])
        self.assertEqual(general.evaluate(P('solve(xs)', [([[3, -1, 7, 2]], 7), ([[-1]], 0)]), facts)['status'], 'solved')

    def test_type_mismatch_between_stages_is_refused(self):
        # stage 1 gives a list; digits need an integer
        facts = staged([['source', 'param', 'xs'], ['aggregate', 'list']], [['source', 'digits', 'stage1'], ['aggregate', 'sum']], extra=[['arg', 'xs', 'int_list']])
        self.assertIn('stage_type_mismatch', errors(LIST, facts))
        # stage 1 gives an int; chars need a string
        facts = staged([['source', 'range', '1', 'n'], ['aggregate', 'sum']], [['source', 'chars', 'stage1'], ['aggregate', 'count']], extra=[['arg', 'n', 'int']])
        self.assertIn('stage_type_mismatch', errors(NUM, facts))
        # stage 1 gives an int; stage elements need a list
        facts = staged([['source', 'range', '1', 'n'], ['aggregate', 'sum']], [['source', 'stage', '1'], ['aggregate', 'sum']], extra=[['arg', 'n', 'int']])
        self.assertIn('stage_type_mismatch', errors(NUM, facts))

    def test_declared_schema_must_be_the_derived_one(self):
        facts = staged([['source', 'range', '1', 'n'], ['aggregate', 'sum']], [['source', 'digits', 'stage1'], ['select_rank', 'largest', '1']], extra=[['arg', 'n', 'int']])
        self.assertIn('stage_schema_mismatch', errors(NUM, facts))

    def test_unused_stage_output_is_refused(self):
        facts = staged([['source', 'range', '1', 'n'], ['aggregate', 'sum']], [['source', 'range', '1', 'n'], ['aggregate', 'product']], extra=[['arg', 'n', 'int']])
        self.assertIn('stage_output_unused', errors(NUM, facts))

    def test_stage_without_a_schema_is_refused(self):
        facts = staged([['source', 'range', '1', 'n']], [['source', 'range', '1', 'n'], ['aggregate', 'product']], extra=[['arg', 'n', 'int']])
        self.assertIn('stage_no_schema', errors(NUM, facts))

    def test_invalid_stage_facts(self):
        voc, params = general.vocab(), ['n']
        base = [['arg', 'n', 'int']]
        v = lambda facts: general.validate(base + facts, params, voc)
        self.assertTrue(v([['stage', '2', 'seq_fold']]))                                    # numbering must start at 1
        self.assertTrue(v([['stage', '1', 'seq_fold'], ['stage', '3', 'seq_fold']]))
        self.assertTrue(v([['stage', '1', 'seq_fold'], ['2.aggregate', 'sum']]))             # undeclared stage
        self.assertTrue(v([['stage', '1', 'seq_fold'], ['aggregate', 'sum']]))               # flat fact in a staged problem
        self.assertTrue(v([['stage', '1', 'grid_bfs']]))                                     # not a stageable schema
        self.assertTrue(v([['stage', '1', 'seq_fold'], ['1.source', 'digits', 'stage1']]))   # reads itself
        self.assertTrue(v([['stage', '1', 'seq_fold'], ['stage', '2', 'seq_fold'], ['1.source', 'stage', '2']]))  # reads a later stage
        self.assertTrue(v([['stage', '1', 'seq_fold'], ['1.arg', 'n', 'int']]))               # arg is not per stage
        self.assertTrue(v([['stage', '1', 'seq_fold'], ['1.nonsense', 'x']]))
        self.assertFalse(v([['stage', '1', 'seq_fold'], ['stage', '2', 'seq_fold'], ['1.source', 'range', '1', 'n'], ['2.source', 'digits', 'stage1']]))

    def test_unknown_reference_is_refused_by_the_rules(self):
        facts = [['arg', 'n', 'int'], ['source', 'digits', 'stage1'], ['aggregate', 'sum']]
        self.assertIn('unknown_source_ref', errors(NUM, facts))

    def test_produces_table_matches_the_derived_answer_types(self):
        d = general.engine_for(NUM, [['arg', 'n', 'int']])
        for _, agg, typ in d.db['produces']:
            elem = 'string' if typ == 'string_list' or agg == 'join' else 'int'
            if elem == 'string':
                prob, facts = P('solve(s)', [(['ab'], 0)]), [['arg', 's', 'string'], ['source', 'chars', 's'], ['aggregate', agg]]
            else:
                prob, facts = P('solve(xs)', [([[1, 2]], 0)]), [['arg', 'xs', 'int_list'], ['source', 'param', 'xs'], ['aggregate', agg]]
            d2 = general.engine_for(prob, facts)
            self.assertIn(typ, {t for p, t in d2.db['answer_type'] if p == general.KEY}, (agg, typ))


class ConditionTreeTest(unittest.TestCase):
    BASE = [['arg', 'n', 'int'], ['source', 'range', '-20', 'n'], ['aggregate', 'count']]

    def run_tree(self, nodes, root, tests=None):
        return general.evaluate(P('solve(n)', tests or [([30], 0)]), self.BASE + nodes + [['filter', root]])

    def test_and_or_not(self):
        nodes = [['cond', 'a', 'remainder', '3', '0'], ['cond', 'b', 'keep', 'positive'], ['expr', 'nb', 'not', 'b'], ['expr', 'r', 'or', 'a', 'nb']]
        tests = [([n], sum(1 for x in range(-20, n + 1) if x % 3 == 0 or not x > 0)) for n in (30, 0, -5, 60)]
        self.assertEqual(self.run_tree(nodes, 'r', tests)['status'], 'solved')

    def test_random_trees_agree_with_python(self):
        rng = random.Random(7)
        leaves = {'l0': (['remainder', '2', '1'], lambda x: x % 2 == 1), 'l1': (['remainder', '5', '0'], lambda x: x % 5 == 0),
                  'l2': (['bound', 'ge', '3'], lambda x: x >= 3), 'l3': (['bound', 'abs_lt', '12'], lambda x: abs(x) < 12),
                  'l4': (['keep', 'negative'], lambda x: x < 0), 'l5': (['drop', 'zero'], lambda x: x != 0)}
        for trial in range(12):
            nodes = [['cond', k, *v[0]] for k, v in leaves.items()]
            funcs = {k: v[1] for k, v in leaves.items()}
            names = list(leaves)
            for i in range(rng.randint(1, 5)):
                op = rng.choice(['and', 'or', 'not'])
                a, b = rng.choice(names), rng.choice(names)
                name = f'e{i}'
                if op == 'not':
                    nodes.append(['expr', name, 'not', a]); funcs[name] = (lambda f: lambda x: not f(x))(funcs[a])
                else:
                    nodes.append(['expr', name, op, a, b])
                    funcs[name] = (lambda f, g, o: (lambda x: f(x) and g(x)) if o == 'and' else (lambda x: f(x) or g(x)))(funcs[a], funcs[b], op)
                names.append(name)
            root = names[-1]
            # every node must be reachable from the root: keep only what the root uses
            used, todo = set(), [root]
            while todo:
                cur = todo.pop()
                if cur in used:
                    continue
                used.add(cur)
                for n in nodes:
                    if n[1] == cur and n[0] == 'expr':
                        todo += [x for x in n[3:] if x != '-']
            nodes = [n for n in nodes if n[1] in used]
            tests = [([n], sum(1 for x in range(-20, n + 1) if funcs[root](x))) for n in (-25, 0, 10, 40)]
            with self.subTest(trial=trial):
                self.assertEqual(self.run_tree(nodes, root, tests)['status'], 'solved')

    def test_tree_combines_with_flat_filters(self):
        nodes = [['cond', 'a', 'remainder', '3', '0'], ['cond', 'b', 'remainder', '5', '0'], ['expr', 'r', 'or', 'a', 'b']]
        tests = [([n], sum(1 for x in range(-20, n + 1) if x > 0 and (x % 3 == 0 or x % 5 == 0))) for n in (30, 7)]
        rec = general.evaluate(P('solve(n)', tests), self.BASE + [['keep', 'positive']] + nodes + [['filter', 'r']])
        self.assertEqual(rec['status'], 'solved', rec)

    def test_failing_trees(self):
        a, b = ['cond', 'a', 'keep', 'even'], ['cond', 'b', 'keep', 'odd']
        e = lambda facts: errors(NUM, self.BASE + facts)
        self.assertIn('node_defined_twice', e([a, ['cond', 'a', 'keep', 'odd'], ['filter', 'a']]))
        self.assertIn('node_defined_twice', e([a, ['expr', 'a', 'not', 'a'], ['filter', 'a']]))
        self.assertIn('node_defined_twice', e([a, b, ['expr', 'x', 'and', 'a', 'b'], ['expr', 'x', 'or', 'a', 'b'], ['filter', 'x']]))
        self.assertIn('undefined_operand', e([a, ['expr', 'x', 'and', 'a', 'zzz'], ['filter', 'x']]))
        self.assertIn('condition_cycle', e([a, ['expr', 'x', 'and', 'a', 'y'], ['expr', 'y', 'or', 'a', 'x'], ['filter', 'x']]))
        self.assertIn('condition_cycle', e([['expr', 'x', 'not', 'x'], ['filter', 'x']]))
        self.assertIn('undefined_filter', e([a, ['filter', 'zzz']]))
        self.assertIn('two_filters', e([a, b, ['filter', 'a'], ['filter', 'b']]))
        self.assertIn('nodes_without_filter', e([a]))
        self.assertIn('unused_node', e([a, b, ['filter', 'a']]))
        self.assertIn('not_takes_one_operand', e([a, b, ['expr', 'x', 'not', 'a', 'b'], ['filter', 'x']]))
        self.assertIn('binary_takes_two_operands', e([a, ['expr', 'x', 'and', 'a'], ['filter', 'x']]))
        self.assertIn('cond_remainder_zero', e([['cond', 'a', 'remainder', '0', '0'], ['filter', 'a']]))
        self.assertIn('char_condition_on_numbers', e([['cond', 'a', 'keep', 'vowel'], ['filter', 'a']]))
        self.assertIn('cond_numeric_on_characters', errors(STR, [['arg', 's', 'string'], ['iterate', 's'], ['aggregate', 'count'],
                                                                ['cond', 'a', 'bound', 'ge', '3'], ['filter', 'a']]))
        self.assertIn('filter_needs_seq_fold', errors(P('solve(g)', [([['.']], 0)]), [['arg', 'g', 'grid'], ['passable', '.'], ['ask', 'count_components'], ['cond', 'a', 'keep', 'even'], ['filter', 'a']]))

    def test_invalid_condition_facts(self):
        v = lambda f: general.validate([['arg', 'n', 'int'], f], ['n'], general.vocab())
        self.assertTrue(v(['cond', 'a', 'keep', 'prime']))
        self.assertTrue(v(['cond', 'a', 'keep', 'even', '3']))
        self.assertTrue(v(['cond', 'a', 'remainder', '3']))
        self.assertTrue(v(['cond', 'a', 'remainder', 'x', '1']))
        self.assertTrue(v(['cond', 'a', 'bound', 'huge', '1']))
        self.assertTrue(v(['cond', 'a', 'bound', 'ge', 'k']))
        self.assertTrue(v(['expr', 'a', 'xor', 'b', 'c']))
        self.assertTrue(v(['cond', 'a', 'between', '1', '2']))
        self.assertFalse(v(['cond', 'a', 'bound', 'ge', '3']))
        self.assertFalse(v(['expr', 'a', 'not', 'b']))


class PalindromeTest(unittest.TestCase):
    def test_is_palindrome_aggregate(self):
        facts = FACTS['relaxed_palindrome']
        rec = general.evaluate(PROBLEMS['relaxed_palindrome'], facts)
        self.assertEqual(rec['status'], 'solved')
        d = general.engine_for(PROBLEMS['relaxed_palindrome'], facts)
        self.assertEqual({f for _, f in d.db['uses']}, {'sequence_palindrome'})
        self.assertEqual({t for _, t in d.db['answer_type']}, {'bool'})

    def test_wrong_answer_type_is_caught(self):
        prob = P('solve(s)', [(['aba'], 1)])
        self.assertEqual(general.evaluate(prob, [['arg', 's', 'string'], ['source', 'chars', 's'], ['aggregate', 'is_palindrome']])['status'], 'type_mismatch')


class ChainHintTest(unittest.TestCase):
    def test_factorial_digit_sum_chain_is_found(self):
        texts = [t for _, t in general.chains(PROBLEMS['factorial_digit_sum'], [['arg', 'n', 'int']], per_depth=200)]
        self.assertIn('stage1: the integers 1..n, product -> int ; stage2: digits of stage1, sum -> int', texts)

    def test_every_chain_ends_in_the_expected_type_and_reads_the_previous_stage(self):
        for pid in ('factorial_digit_sum', 'relaxed_palindrome'):
            prob = PROBLEMS[pid]
            for n, text in general.chains(prob, [], per_depth=50):
                steps = text.split(' ; ')
                self.assertEqual(len(steps), n)
                self.assertLessEqual(n, 3)
                want = {general.json_type(t['expected']) for t in prob['tests']}
                self.assertIn(steps[-1].rsplit('-> ', 1)[1], want)
                for i, s in enumerate(steps[1:], 1):
                    self.assertIn(f'stage{i}', s.split(':', 1)[1].split(',')[0])

    def test_explain_gives_the_chains_to_the_translator(self):
        text, _ = general.explain(PROBLEMS['factorial_digit_sum'], [['arg', 'n', 'int']])
        self.assertIn('stage chains', text)
        self.assertIn('the integers 1..n, product -> int ; stage2: digits of stage1', text)

    def test_no_chain_when_the_answer_type_is_unreachable(self):
        prob = P('solve(n)', [([3], [[1, 2]])])  # a list of lists cannot come out of a seq_fold chain
        self.assertEqual(general.chains(prob, [['arg', 'n', 'int']]), [])

    def test_prompt_documents_stages(self):
        self.assertIn('stage', general.PROMPT)
        text = general.describe_vocab(general.vocab())
        for word in ('source(', 'stage(', 'cond(', 'expr(', 'filter('):
            self.assertIn(word, text)


if __name__ == '__main__':
    unittest.main()
