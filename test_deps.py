"""Dependency tracking: stored deps, affected(), who(), soundness of the incremental regression."""
import json, shutil, tempfile, unittest
from pathlib import Path

import general
import general_grow as G


class DepsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='tdeps_'))
        cls.pack = cls.tmp / 'pack'
        shutil.copytree(general.PACK, cls.pack)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fresh(self):
        work = self.tmp / 'work'
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(self.pack, work)
        return work

    def test_stored_deps_are_current(self):
        recs = [json.loads(f.read_text()) for f in G.solved_dir(general.PACK).glob('*.json')]
        self.assertTrue(recs)
        for r in recs:
            self.assertEqual(set(r['deps']), {'schema', 'uses', 'solution_sha256', 'reference_sha256'}, r['id'])
        self.assertEqual(G.affected(general.PACK), {})

    def test_who_function_and_schema(self):
        self.assertIn('g2_count_pairs_sum_divisible_by4', G.who(general.PACK, 'count_pairs_residue'))
        self.assertIn('g2_count_pairs_sum_divisible_by4', G.who(general.PACK, 'pair_count'))
        self.assertEqual(G.who(general.PACK, 'no_such_thing_xyz'), [])

    def test_missing_deps_or_render_failure_is_affected(self):
        work = self.fresh()
        f = sorted(G.solved_dir(work).glob('*.json'))[0]
        rec = json.loads(f.read_text()); del rec['deps']; f.write_text(json.dumps(rec))
        self.assertEqual(G.affected(work), {rec['id']: 'no stored deps'})
        rec['deps'] = {'solution_sha256': 'x', 'reference_sha256': 'y'}
        rec['facts'] = [['arg', 'nope', 'int_list']]
        f.write_text(json.dumps(rec))
        self.assertIn('render failed', G.affected(work)[rec['id']])

    def test_rule_edit_soundness(self):
        """Delete one candidate rule: affected == problems whose rendered code changed, and a full regression finds no
        failure outside that set."""
        work = self.fresh()
        rules = work / 'algorithms.dl'
        lines = rules.read_text().splitlines()
        victim = next(l for l in lines if l.startswith('candidate(P,count_pairs_residue) :- pair_test(P,O,M,R)'))
        rules.write_text('\n'.join(l for l in lines if l != victim) + '\n')
        aff = G.affected(work)
        self.assertIn('g2_count_pairs_sum_divisible_by4', aff)
        # ground truth by brute force: re-render everything and compare to the original sources
        truth = set()
        for f in G.solved_dir(self.pack).glob('*.json'):
            rec = json.loads(f.read_text())
            try:
                new = G.render_deps(work, rec)
            except Exception:  # noqa: BLE001
                truth.add(rec['id']); continue
            if (new['solution_sha256'], new['reference_sha256']) != (rec['deps']['solution_sha256'], rec['deps']['reference_sha256']):
                truth.add(rec['id'])
        self.assertEqual(set(aff), truth)
        self.assertLess(len(aff), len(list(G.solved_dir(work).glob('*.json'))))
        outside = [b for b in G.regression(work) if b[0] not in aff and b[0] != 'library']
        self.assertEqual(outside, [])
        self.assertFalse([b for b in G.regression(work, only=set(aff)) if b[0] not in aff])

    def test_update_deps_after_edit_makes_affected_empty(self):
        work = self.fresh()
        (work / 'templates/schemas/pair_count.py.j2').write_text((work / 'templates/schemas/pair_count.py.j2').read_text() + '\n# touched\n')
        aff = G.affected(work)
        self.assertTrue(aff and all(i in G.who(self.pack, 'pair_count') for i in aff))
        G.update_deps(work, set(aff))
        self.assertEqual(G.affected(work), {})


if __name__ == '__main__':
    unittest.main()
