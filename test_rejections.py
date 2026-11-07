"""Rejection corpus (packs/general/rejected): it passes, covers every error constant, and a rule removal that frees a case is refused."""
import json, re, shutil, tempfile, unittest
from pathlib import Path

import general
import general_grow as G

RESTORED = ['missing_shift_by', 'missing_circle_step', 'missing_case_to', 'missing_range_to', 'missing_date_origin',
            'range_count_needs_order', 'range_steps_use_once']


def drop_rule(pack, error, new_name=None):
    """Copy of the pack (without the stored problems) in which the rules deriving error(<error>,P) are removed
    (or renamed to new_name)."""
    work = Path(tempfile.mkdtemp(prefix='trej_')) / 'pack'
    shutil.copytree(pack, work, ignore=shutil.ignore_patterns('solved'))
    text = (work / 'learned.dl').read_text()
    out, hit = [], 0
    for line in text.splitlines():
        if line.startswith(f'error({error},'):
            hit += 1
            if new_name:
                out.append(line.replace(f'error({error},', f'error({new_name},', 1))
            continue
        out.append(line)
    assert hit, error
    (work / 'learned.dl').write_text('\n'.join(out) + '\n')
    return work


class RejectionCorpusTest(unittest.TestCase):
    def tearDown(self):
        for w in getattr(self, 'work', []):
            shutil.rmtree(w.parent, ignore_errors=True)

    def pack_without(self, error, new_name=None):
        w = drop_rule(general.PACK, error, new_name)
        self.work = getattr(self, 'work', []) + [w]
        return w

    def test_corpus_passes(self):
        self.assertEqual(G.rejections(general.PACK), [])

    def test_every_error_constant_has_a_case(self):
        self.assertGreater(len(G.error_constants(general.PACK)), 150)
        self.assertEqual(G.uncovered_errors(general.PACK), [])

    def test_cases_are_well_formed(self):
        consts = {c.strip('"') for c in G.error_constants(general.PACK)}
        files = sorted(G.rejected_dir(general.PACK).glob('*.json'))
        self.assertGreaterEqual(len(files), len(consts))
        for f in files:
            case = json.loads(f.read_text())
            self.assertLessEqual(set(case), {'signature', 'facts', 'error', 'also', 'extra_rules'}, f.name)
            self.assertEqual(f.stem, case['error'], f.name)
            self.assertIn(case['error'], consts, f.name)
            self.assertTrue(all(isinstance(x, list) and all(isinstance(y, str) for y in x) for x in case['facts']), f.name)
            self.assertTrue(set(case.get('also', [])) <= consts, f.name)

    def test_checks_that_consolidation_removed_are_protected(self):
        for error in RESTORED:
            with self.subTest(error=error):
                self.assertIn(f'error({error},', (general.PACK / 'learned.dl').read_text())   # the rule exists ...
                broken = G.rejections(self.pack_without(error))                              # ... and the corpus notices its loss
                self.assertEqual([b[0] for b in broken], [error])
                self.assertIn('no longer rejected', broken[0][2])

    def test_changed_error_is_reported(self):
        broken = G.rejections(self.pack_without('missing_circle_step', 'circle_step_gone'))
        self.assertEqual([b[0] for b in broken], ['missing_circle_step'])
        self.assertIn("['circle_step_gone'] instead of ['missing_circle_step']", broken[0][2])

    def test_accepted_description_fails_its_case(self):
        work = self.pack_without('two_shift_by', 'two_shift_by')                     # unchanged copy
        path = G.rejected_dir(work) / 'missing_shift_by.json'
        case = json.loads(path.read_text())
        case['facts'].append(['shift_by', 'n'])                                      # the missing fact is now given
        path.write_text(json.dumps(case))
        broken = G.check_rejection(str(work), str(path))
        self.assertEqual(len(broken), 1)
        self.assertIn('no longer rejected', broken[0][2])

    def test_extra_error_fails_case_without_also(self):
        work = self.pack_without('two_shift_by', 'two_shift_by')
        path = G.rejected_dir(work) / 'missing_shift_by.json'
        case = json.loads(path.read_text())
        case['facts'].append(['circle_step', 'k'])                                   # a second, unrelated mistake
        path.write_text(json.dumps(case))
        broken = G.check_rejection(str(work), str(path))
        self.assertIn('instead of', broken[0][2])

    def test_regression_runs_the_corpus(self):
        work = self.pack_without('missing_shift_by')
        broken = G.regression(work)
        self.assertEqual([b[:2] for b in broken], [('missing_shift_by', 'rejection')])
        self.assertEqual(G.regression(work, corpus=False, only=set()), [])           # library checks only; skipping the corpus works

    def rule_free_pack_text(self, error):
        w = self.pack_without(error)
        return (w / 'learned.dl').read_text()

    def test_try_proposal_refuses_rule_removal(self):
        rec = json.loads((general.PACK / 'solved' / 'glm2_caesar_shift.json').read_text())
        proposal = {'files': {'learned.dl': self.rule_free_pack_text('missing_shift_by')}, 'facts': rec['facts']}
        ok, info, w = G.try_proposal(general.PACK, rec, proposal)
        if w:
            shutil.rmtree(w.parent, ignore_errors=True)
        self.assertFalse(ok)
        self.assertEqual(info['regression_broken'][0][:2], ('missing_shift_by', 'rejection'))
        text = G.feedback_text(rec, info)
        self.assertIn('must stay rejected', text)
        self.assertIn('missing_shift_by', text)

    def test_consolidate_attempt_refuses_rule_removal(self):
        import general_consolidate as C
        facts = {f.stem: json.loads(f.read_text())['facts'] for f in G.solved_dir(general.PACK).glob('*.json')}
        ok, info, w = C.attempt(general.PACK, {'files': {'learned.dl': self.rule_free_pack_text('range_steps_use_once')}, 'facts': facts})
        if w:
            shutil.rmtree(w.parent, ignore_errors=True)
        self.assertFalse(ok)
        self.assertEqual(info['broken'][0][:2], ('range_steps_use_once', 'rejection'))


if __name__ == '__main__':
    unittest.main()
