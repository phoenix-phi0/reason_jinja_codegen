"""Explanation chain: Datalog derivation records, explain_plan, plan header in the generated solution."""
import json, unittest
from pathlib import Path

import datalog
import general
import general_grow as G


def stored(pid):
    return json.loads((G.solved_dir(general.PACK) / f'{pid}.json').read_text())


class DatalogWhyTest(unittest.TestCase):
    def engine(self, explain=True):
        d = datalog.Datalog(datalog.parse_rules('path(X,Y) :- edge(X,Y).\npath(X,Z) :- path(X,Y), edge(Y,Z).\nlone(X) :- edge(X,Y), not edge(Y,X).'), explain=explain)
        for a, b in (('a', 'b'), ('b', 'c'), ('c', 'd')):
            d.add('edge', a, b)
        d.run()
        return d

    def test_tree(self):
        t = self.engine().why('path', ('a', 'c'))
        self.assertIn('path(X,Z) :- path(X,Y), edge(Y,Z)', t['rule'])
        self.assertEqual({s['fact'] for s in t['because']}, {('path', ('a', 'b')), ('edge', ('b', 'c'))})
        self.assertTrue(all(s.get('given') for s in self.engine().why('path', ('a', 'b'))['because']))

    def test_negation_depth_and_missing(self):
        d = self.engine()
        self.assertEqual(d.why('lone', ('a',))['absent'], [('edge', ('b', 'a'))])
        self.assertIsNone(d.why('path', ('d', 'a')))
        cut = d.why('path', ('a', 'd'), depth=1)
        self.assertTrue(any(s.get('cut') for s in cut['because']))

    def test_off_by_default_and_same_result(self):
        plain, expl = self.engine(False), self.engine(True)
        self.assertEqual(plain.derivations, {})
        self.assertEqual(plain.db['path'], expl.db['path'])


class ExplainPlanTest(unittest.TestCase):
    def test_pair_count_uses_derivation(self):
        rec = stored('g2_count_pairs_sum_divisible_by4')
        d = general.engine_for(rec, rec['facts'], explain=True)
        text = json.dumps(d.why('uses', (general.KEY, 'count_pairs_residue')))
        for needle in ('count_pairs_residue', 'complexity', 'size_class', 'large', 'fits', 'candidate'):
            self.assertIn(needle, text)
        plan = general.explain_plan(rec, rec['facts'])
        for needle in ('schema pair_count', 'function count_pairs_residue', 'complexity(count_pairs_residue, n)',
                       'size(numbers, large)', 'fits(n, large)', 'not beaten', 'answer type int'):
            self.assertIn(needle, plan)

    def test_precondition_listed(self):
        rec = stored('knap_min_coins')
        plan = general.explain_plan(rec, rec['facts'])
        self.assertIn('precondition positive of items', plan)

    def test_no_schema_plan(self):
        self.assertTrue(general.explain_plan({'signature': 'solve(x)'}, [['arg', 'x', 'int']]).startswith('no plan'))

    def test_header_in_solution_and_solve_log(self):
        rec = stored('g2_count_pairs_sum_divisible_by4')
        src = general.build(rec, rec['facts'], plan=True).read_text()
        self.assertTrue(src.startswith('# PLAN'))
        self.assertIn('# function count_pairs_residue', src)
        self.assertNotIn('# PLAN', general.build(rec, rec['facts']).read_text())  # hashed renderings stay plain
        res = general.evaluate(rec, rec['facts'])
        self.assertEqual(res['status'], 'solved')
        self.assertIn('count_pairs_residue', res['plan'])

    def test_deps_unaffected_by_plan(self):
        self.assertEqual(G.affected(general.PACK), {})


if __name__ == '__main__':
    unittest.main()
