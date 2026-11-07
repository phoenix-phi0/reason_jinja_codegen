"""--translate-twice / --fallback-model paths of general.solve_problem, driven by a scripted fake translator (no model calls)."""
import json, unittest
from pathlib import Path

import general

STORED = json.loads((Path(general.PACK) / 'solved' / 'g2_any_overlap_half_open_slots.json').read_text())
GOOD = STORED['facts']
VOC = general.vocab()
UNCOVERED = ([], 'cannot express')
BAD_RULES = ([['arg', 'windows', 'interval_list'], ['iterate', 'windows'], ['ask', 'merge_intervals']], None)  # rejected/no solution path
WRONG_TYPE = ([['arg', 'windows', 'interval_list'], ['iterate', 'windows'], ['ask', 'count_pairs']], None)


def script(*replies):
    """Fake extract(): successive calls return the given (facts, uncovered) replies; records (model, hint) per call."""
    calls = []
    it = iter(replies)
    def fake(problem, model, voc, hint=''):
        calls.append((model, bool(hint)))
        general.CALLS['n'] += 1
        return next(it)
    fake.calls = calls
    return fake


class TranslationTest(unittest.TestCase):
    def solve(self, *replies, **kw):
        ex = script(*replies)
        rec = general.solve_problem(STORED, VOC, general.PACK, 'haiku', extractor=ex, **kw)
        return rec, ex.calls

    def test_default_flow_is_one_call_when_it_solves(self):
        rec, calls = self.solve((GOOD, None))
        self.assertEqual((rec['status'], rec['path'], rec['model_calls']), ('solved', 'single', 1))

    def test_twice_both_solve_uses_first(self):
        rec, calls = self.solve((GOOD, None), (GOOD, None), twice=True)
        self.assertEqual((rec['status'], rec['path'], rec['model_calls']), ('solved', 'twice_first', 2))
        self.assertTrue(rec['twice']['agree_answer_type'])

    def test_twice_first_uncovered_second_solves(self):
        rec, calls = self.solve(UNCOVERED, (GOOD, None), twice=True)
        self.assertEqual((rec['status'], rec['path'], rec['model_calls']), ('solved', 'twice_second', 2))
        self.assertEqual(rec['facts'], GOOD)

    def test_twice_first_rejected_second_solves(self):
        rec, calls = self.solve(BAD_RULES, (GOOD, None), twice=True)
        self.assertEqual(rec['path'], 'twice_second')
        self.assertEqual(rec['status'], 'solved')

    def test_twice_first_solves_second_fails_keeps_first(self):
        rec, _ = self.solve((GOOD, None), UNCOVERED, twice=True)
        self.assertEqual((rec['status'], rec['path']), ('solved', 'twice_first'))

    def test_twice_both_fail_falls_back_to_near_miss_retry(self):
        rec, calls = self.solve(BAD_RULES, UNCOVERED, (GOOD, None), twice=True)
        self.assertEqual((rec['status'], rec['path']), ('solved', 'near_miss_retry'))
        self.assertEqual(calls, [('haiku', False), ('haiku', False), ('haiku', True)])
        self.assertEqual(rec['model_calls'], 3)

    def test_twice_off_does_not_translate_twice(self):
        rec, calls = self.solve(UNCOVERED)
        self.assertEqual(len(calls), 1)
        self.assertEqual((rec['status'], rec['path']), ('uncovered', 'unsolved'))
        self.assertNotIn('twice', rec)

    def test_fallback_model_used_only_after_everything_else(self):
        # first translation uncovered (no facts => no near-miss retry), fallback model solves
        rec, calls = self.solve(UNCOVERED, (GOOD, None), fallback_model='sonnet')
        self.assertEqual((rec['status'], rec['path']), ('solved', 'fallback_model'))
        self.assertEqual(calls, [('haiku', False), ('sonnet', False)])
        self.assertEqual(rec['fallback']['model'], 'sonnet')

    def test_fallback_not_called_when_main_model_solves(self):
        rec, calls = self.solve((GOOD, None), fallback_model='sonnet')
        self.assertEqual(calls, [('haiku', False)])

    def test_fallback_failure_stays_unsolved(self):
        rec, calls = self.solve(UNCOVERED, UNCOVERED, fallback_model='sonnet')
        self.assertEqual((rec['status'], rec['path']), ('uncovered', 'unsolved'))

    def test_wrong_code_is_never_counted_as_solved(self):
        # a translation whose code fails the tests has status wrong; it must not be used when the other one solves
        p = dict(STORED, tests=[dict(t) for t in STORED['tests']])
        ex = script((GOOD, None), (GOOD, None))
        rec = general.solve_problem(p, VOC, general.PACK, 'haiku', twice=True, extractor=ex)
        self.assertEqual(rec['status'], 'solved')
        self.assertEqual(rec['passed'], rec['total'])


if __name__ == '__main__':
    unittest.main()
