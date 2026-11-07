"""Static rule checks (general_lint): clean pack, and a failing-case test for every check."""
import shutil, tempfile, unittest
from pathlib import Path

import general
import general_grow as G
import general_lint as L


class LintTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='tlint_'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def with_rules(self, extra, name='learned.dl'):
        work = self.tmp / 'pack'
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(general.PACK, work, ignore=shutil.ignore_patterns('solved'))
        with open(work / name, 'a') as f:
            f.write('\n' + extra + '\n')
        return work

    def test_current_pack_has_no_errors_or_redundancy(self):
        res = L.lint(general.PACK)
        self.assertEqual(res['errors'], [])
        self.assertEqual([w for w in res['warnings'] if w.startswith('redundant')], [])

    def test_dead_rule_typo_is_rejected(self):
        res = L.lint(self.with_rules('candidate(P,count_pairs_residue) :- iterate(P,A), aggregat(P,count).'))
        self.assertTrue(any('dead rule' in e and 'aggregat' in e for e in res['errors']), res)

    def test_negated_typo_is_also_dead(self):
        res = L.lint(self.with_rules('candidate(P,x_fn) :- iterate(P,A), not keeep(P,even).'))
        self.assertTrue(any('keeep' in e for e in res['errors']), res)

    def test_driver_and_vocab_predicates_are_not_dead(self):
        res = L.lint(self.with_rules('candidate(P,x_fn) :- iterate(P,A), size(P,A,tiny), assumed_size(P,A), guarantees(P,A,positive).'))
        self.assertEqual(res['errors'], [])

    def test_contradiction_on_functional_predicate(self):
        res = L.lint(self.with_rules('answer_type(P,int) :- ask(P,zzz_q), iterate(P,A).\nanswer_type(P,bool) :- iterate(P,B), ask(P,zzz_q).', 'learned.dl'))
        self.assertTrue(any(e.startswith('contradiction') for e in res['errors']), res)

    def test_same_constants_or_different_bodies_are_no_contradiction(self):
        res = L.lint(self.with_rules('answer_type(P,int) :- ask(P,zzz_q), iterate(P,A).\nanswer_type(P,int) :- iterate(P,B), ask(P,zzz_q).\n'
                                     'answer_type(P,bool) :- ask(P,zzz_r), iterate(P,A).'))
        self.assertFalse(any(e.startswith('contradiction') for e in res['errors']), res)

    def test_redundant_rules_warn(self):
        res = L.lint(self.with_rules('candidate(P,x_fn) :- iterate(P,A), ask(P,count).\ncandidate(P,x_fn) :- ask(P,count), iterate(P,B).\n'
                                     'candidate(P,y_fn) :- iterate(P,A).\ncandidate(P,y_fn) :- iterate(P,A), ask(P,count).'))
        text = '\n'.join(res['warnings'])
        self.assertIn('x_fn', text)
        self.assertIn('subsumed by', text)
        self.assertEqual(res['errors'], [])

    def test_unused_vocabulary_predicate_warns(self):
        work = self.with_rules('')
        import json
        v = json.loads((work / 'vocab.json').read_text())
        v['predicates']['never_used_pred'] = {'args': ['param'], 'doc': 'x'}
        (work / 'vocab.json').write_text(json.dumps(v))
        res = L.lint(work)
        self.assertTrue(any('never_used_pred' in w for w in res['warnings']))

    def test_admission_rejects_dead_rule_but_not_old_findings(self):
        work = self.with_rules('candidate(P,count_pairs_residue) :- aggregat(P,count).')
        self.assertTrue(G.new_lint_errors(general.PACK, work))
        self.assertEqual(G.new_lint_errors(general.PACK, general.PACK), [])
        ok, info, w = G.try_proposal(general.PACK, {'id': 'x', 'tests': []},
                                     {'files': {'learned.dl': (work / 'learned.dl').read_text()}})
        self.assertFalse(ok)
        self.assertIn('lint', str(info))
        if w:
            shutil.rmtree(w.parent, ignore_errors=True)

    def test_consolidate_attempt_rejects_lint_errors(self):
        import general_consolidate as C
        work = self.with_rules('candidate(P,count_pairs_residue) :- aggregat(P,count).')
        facts = {f.stem: [] for f in G.solved_dir(general.PACK).glob('*.json')}
        ok, info, w = C.attempt(general.PACK, {'files': {'learned.dl': (work / 'learned.dl').read_text()}, 'facts': facts})
        self.assertFalse(ok)
        self.assertIn('lint', info)
        if w:
            shutil.rmtree(w.parent, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
