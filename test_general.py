"""packs/general without a model: facts -> rules -> schema -> code."""
import shutil, unittest

import general
from grow import run_tests


def P(sig, tests):
    return {'id': 't', 'signature': sig, 'statement': '', 'tests': [{'args': a, 'expected': e} for a, e in tests]}


class GeneralTest(unittest.TestCase):
    def check(self, problem, facts):
        rec = general.evaluate(problem, facts)
        self.assertEqual(rec['status'], 'solved', rec)

    def status(self, problem, facts):
        return general.evaluate(problem, facts)

    def test_one_schema_many_parameter_combinations(self):
        nums = P('solve(xs)', [([[3, -2, 0, 5, -7]], None)])
        cases = [
            ([['keep', 'odd'], ['aggregate', 'sum']], 1),
            ([['keep', 'negative'], ['map', 'abs'], ['aggregate', 'max'], ['if_empty', '0']], 7),
            ([['drop', 'zero'], ['aggregate', 'product']], 210),
            ([['keep', 'positive'], ['map', 'square'], ['aggregate', 'list']], [9, 25]),
            ([['aggregate', 'distinct_count']], 5),
        ]
        for extra, expected in cases:
            with self.subTest(extra=extra):
                prob = P('solve(xs)', [([[3, -2, 0, 5, -7]], expected)])
                self.check(prob, [['arg', 'xs', 'int_list'], ['iterate', 'xs'], *extra])

    def test_defaults_come_from_negation(self):
        maze = P('solve(g)', [([['..#', '#..', '...']], 4), ([['.#', '#.']], -1)])
        # no connect, start, goal or unreachable facts: 4-neighbourhood, corners and -1 are derived defaults
        self.check(maze, [['arg', 'g', 'grid'], ['passable', '.'], ['ask', 'shortest_path']])
        diag = P('solve(g)', [([['#.', '.#']], 1)])
        self.check(diag, [['arg', 'g', 'grid'], ['passable', '#'], ['connect', '8'], ['ask', 'count_components']])
        self.assertEqual(self.status(P('solve(g)', [([['#.', '.#']], 1)]),
                                     [['arg', 'g', 'grid'], ['passable', '#'], ['ask', 'count_components']])['status'], 'wrong')

    def test_knapsack_modes(self):
        g = [['items', 'c'], ['target', 'a'], ['guarantees', 'c', 'positive'], ['guarantees', 'c', 'distinct']]
        self.check(P('solve(c, a)', [([[1, 2, 5], 5], 4)]), g + [['ask', 'count_ways']])
        self.check(P('solve(c, a)', [([[1, 2], 3], 3)]), g + [['ask', 'count_ways'], ['order', 'matters']])
        self.check(P('solve(c, a)', [([[1, 1, 2], 2], 2)]), g[:3] + [['ask', 'count_ways'], ['use', 'once']])
        self.check(P('solve(c, a)', [([[2], 3], -1)]), g + [['ask', 'min_count']])

    def test_preconditions_sizes_and_types_are_reasoned_about(self):
        knap = [['items', 'c'], ['target', 'a'], ['ask', 'count_ways']]
        rec = self.status(P('solve(c, a)', [([[1, 2, 5], 5], 4)]), knap)  # statement guarantees nothing about c
        self.assertEqual(rec['status'], 'rejected'); self.assertIn('unmet_precondition', rec['reason'])
        self.assertTrue(any('positive' in w for w in rec['why']))
        # a stated bound makes the DP infeasible: medium items x medium target
        rec = self.status(P('solve(c, a)', [([[1, 2, 5], 5], 4)]), knap + [['guarantees', 'c', 'positive'], ['guarantees', 'c', 'distinct'],
                                                                  ['size', 'c', 'medium'], ['size', 'a', 'medium']])
        self.assertEqual(rec['status'], 'rejected'); self.assertIn('too_slow', rec['reason'])
        # pair counting on a medium-size list may not fall back to brute force (a product bound has no fast function)
        pairs = [['arg', 'xs', 'int_list'], ['iterate', 'xs'], ['ask', 'count_pairs'], ['pair_bound', 'product', 'lt', '10'], ['size', 'xs', 'medium']]
        rec = self.status(P('solve(xs)', [([[1, 2]], 1)]), pairs)
        self.assertEqual(rec['status'], 'rejected'); self.assertIn('too_slow', rec['reason'])
        self.assertEqual(self.status(P('solve(xs)', [([[1, 2]], 1)]), pairs[:-1] + [['size', 'xs', 'small']])['status'], 'solved')
        # the fastest feasible function wins: residue counting, not brute force
        d = general.engine_for(P('solve(xs)', [([[1, 3]], 1)]), [['arg', 'xs', 'int_list'], ['iterate', 'xs'], ['ask', 'count_pairs'], ['pair_test', 'sum', '4', '0']])
        self.assertEqual({f for _, f in d.db['uses']}, {'count_pairs_residue'})
        # answer type: asking for a count when the tests expect a list is caught before any code runs
        rec = self.status(P('solve(xs)', [([[1, 2]], [1])]), [['arg', 'xs', 'int_list'], ['iterate', 'xs'], ['keep', 'odd'], ['aggregate', 'count']])
        self.assertEqual(rec['status'], 'type_mismatch')

    def test_near_miss_explanation(self):
        text, near = general.explain(P('solve(n, k)', [([5, 2], 1)]), [['arg', 'n', 'int'], ['arg', 'k', 'int'], ['target', 'n'], ['ask', 'count_ways']])
        self.assertTrue(text.startswith('schema knapsack: needs items(?)'), text)
        self.assertEqual(near[0]['missing'], [('items', ('p', '?'))])

    def test_rules_reject_inconsistent_descriptions(self):
        xs = P('solve(xs)', [([[1]], 1)])
        for facts, reason in [
            ([['iterate', 'xs'], ['aggregate', 'max']], 'missing_if_empty'),
            ([['arg', 'xs', 'int_list'], ['iterate', 'xs'], ['keep', 'vowel'], ['aggregate', 'count']], 'char_condition_on_numbers'),
            ([['items', 'xs'], ['target', 'xs'], ['ask', 'count_ways'], ['use', 'once'], ['order', 'matters']], 'ordered_once_not_supported'),
            ([['arg', 'xs', 'int_list']], 'no_schema'),
        ]:
            with self.subTest(reason=reason):
                rec = self.status(xs, facts)
                self.assertEqual(rec['status'], 'rejected', rec)
                self.assertIn(reason, rec['reason'])

    def test_vocabulary_is_enforced(self):
        xs = P('solve(xs)', [([[1]], 1)])
        for facts in ([['iterate', 'ys'], ['aggregate', 'sum']], [['iterate', 'xs'], ['aggregate', 'median']],
                      [['iterate', 'xs'], ['aggregate', 'max'], ['if_empty', 'int']], [['frobnicate', 'xs']]):
            with self.subTest(facts=facts):
                self.assertEqual(self.status(xs, facts)['status'], 'invalid')


class AskBackTest(unittest.TestCase):
    STATEMENT = 'Given coins, a list of distinct positive integers, and an amount, count the ways to make the amount.'
    KNAP = [['items', 'c'], ['target', 'a'], ['ask', 'count_ways']]

    def problem(self):
        p = P('solve(c, a)', [([[1, 2, 5], 5], 4)])
        p['statement'] = self.STATEMENT
        return p

    def run_ask(self, answers, facts=None):
        p = self.problem()
        facts = facts or self.KNAP
        rec = general.evaluate(p, facts)
        self.assertEqual(rec['status'], 'rejected')
        seen = []
        def fake(problem, qs):
            seen.append((problem, qs))
            return [dict(a, id=q['id']) for q, a in zip(qs, answers(qs))]
        facts2, rec = general.ask_back(p, facts, rec, answerer=fake)
        return facts2, rec, seen

    def test_questions_are_derived_from_rules(self):
        qs = general.questions(self.problem(), self.KNAP)
        self.assertEqual({q['id'] for q in qs}, {'g:c:positive', 'g:c:distinct'})
        self.assertIn('Does the statement guarantee that every element of `c` is a positive integer?', [q['text'] for q in qs])
        # derived (not stated) sizes are marked assumed; stated ones are not
        g = general.grouped_facts(self.problem(), self.KNAP)
        self.assertEqual({r[1] for r in g['assumed_size']}, {'c', 'a'})
        g = general.grouped_facts(self.problem(), self.KNAP + [['size', 'c', 'small']])
        self.assertNotIn('c', {r[1] for r in g['assumed_size']})
        d = general.engine_for(P('solve(xs)', [([[1, 2]], 1)]), [['arg', 'xs', 'int_list'], ['iterate', 'xs'], ['ask', 'count_pairs'],
                                                                 ['pair_bound', 'product', 'lt', '10']])
        self.assertEqual(d.db['ask_size'], {('p', 'xs')})
        qs = general.questions(P('solve(xs)', [([[1, 2]], 1)]), [['arg', 'xs', 'int_list'], ['iterate', 'xs'], ['ask', 'count_pairs'],
                                                                 ['pair_bound', 'product', 'lt', '10']])
        self.assertIn('bound the length', qs[0]['text'])

    def test_yes_with_valid_quote_solves(self):
        quotes = {'positive': 'distinct positive integers', 'distinct': 'distinct positive integers'}
        facts, rec, _ = self.run_ask(lambda qs: [{'answer': 'yes', 'quote': quotes[q['cond']]} for q in qs])
        self.assertEqual(rec['status'], 'solved', rec)
        self.assertTrue(rec['solved_after_questions'])
        self.assertIn(['guarantees', 'c', 'positive'], facts)
        self.assertEqual(len(rec['questions']), 2)

    def test_fabricated_quote_is_refused(self):
        facts, rec, _ = self.run_ask(lambda qs: [{'answer': 'yes', 'quote': 'all coins are positive'} for q in qs])
        self.assertEqual(rec['status'], 'rejected')
        self.assertFalse(rec['solved_after_questions'])
        self.assertTrue(all(a['answer'] == 'not stated' for a in rec['answers']))
        self.assertEqual(facts, self.KNAP)
        # a missing / empty quote is just as bad
        _, rec, _ = self.run_ask(lambda qs: [{'answer': 'yes', 'quote': ''} for q in qs])
        self.assertEqual(rec['status'], 'rejected')

    def test_not_stated_and_no_add_nothing(self):
        for ans in ({'answer': 'not stated'}, {'answer': 'no', 'quote': 'distinct positive integers'}):
            facts, rec, _ = self.run_ask(lambda qs: [dict(ans) for q in qs])
            self.assertEqual(rec['status'], 'rejected'); self.assertEqual(facts, self.KNAP)
            self.assertFalse(rec['solved_after_questions'])

    def test_only_signature_statement_and_questions_reach_the_answerer(self):
        _, _, seen = self.run_ask(lambda qs: [{'answer': 'not stated'} for q in qs])
        problem, qs = seen[0]
        prompt = general.ASK_PROMPT.format(signature=problem['signature'], statement=problem['statement'], classes='x',
                                           questions='\n'.join(q['text'] for q in qs))
        self.assertNotIn('[[1, 2, 5], 5]', prompt)  # no tests in the prompt

    def test_size_answer_adds_size_class(self):
        pairs = [['arg', 'xs', 'int_list'], ['iterate', 'xs'], ['ask', 'count_pairs'], ['pair_bound', 'product', 'lt', '10']]
        p = P('solve(xs)', [([[1, 2]], 1)])
        p['statement'] = 'Count pairs i<j with xs[i]*xs[j] < 10. The list has at most 500 elements.'
        rec = general.evaluate(p, pairs)
        self.assertEqual(rec['status'], 'rejected')
        ans = lambda pr, qs: [{'id': 's:xs', 'answer': 'small', 'quote': 'at most 500 elements'}]
        facts, rec = general.ask_back(p, pairs, rec, answerer=ans)
        self.assertIn(['size', 'xs', 'small'], facts)
        self.assertEqual(rec['status'], 'solved', rec)
        # an invalid class or fabricated quote adds nothing
        for a in ({'answer': 'gigantic', 'quote': 'at most 500 elements'}, {'answer': 'small', 'quote': 'at most 50 elements'}):
            rec = general.evaluate(p, pairs)
            facts, rec = general.ask_back(p, pairs, rec, answerer=lambda pr, qs: [dict(a, id='s:xs')])
            self.assertEqual(facts, pairs); self.assertEqual(rec['status'], 'rejected')


if __name__ == '__main__':
    unittest.main()
