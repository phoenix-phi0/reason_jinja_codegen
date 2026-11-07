"""grow.py behaviour without a model: the learner is replaced by a fake."""
import json, shutil, tempfile, unittest
from pathlib import Path
from unittest import mock

import grow

SEED = Path(__file__).resolve().parent / 'packs' / 'growing'

MAX_PROBLEM = {'id': 'Biggest Number', 'signature': 'solve(nums)', 'statement': 'Return the largest element.',
               'tests': [{'args': [[1, 5, 2]], 'expected': 5}, {'args': [[-3]], 'expected': -3},
                         {'args': [[0, 0]], 'expected': 0}, {'args': [[9, 1]], 'expected': 9},
                         {'args': [[4, 8, 8]], 'expected': 8}, {'args': [[-1, -7]], 'expected': -1}]}
GOOD = 'def solve(nums):\n    return max(nums)\n'
BAD = 'def solve(nums):\n    return nums[0]\n'


class GrowTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='grow_test_'))
        self.pack = self.dir / 'pack'
        shutil.copytree(SEED, self.pack)
        # Start from the seed algorithms only, so the tests do not depend on what has been grown.
        lib = json.loads((self.pack / 'library.json').read_text())
        grown = {k for k, v in lib.items() if v['origin'] != 'seed'}
        for k in grown:
            grow.template_path(self.pack, k).unlink(missing_ok=True)
            (self.pack / 'tests' / f'{k}.json').unlink(missing_ok=True)
        (self.pack / 'library.json').write_text(json.dumps({k: v for k, v in lib.items() if k not in grown}))
        rules = [l for l in (self.pack / 'learned.dl').read_text().splitlines()
                 if not l.startswith('alias(') and not any(f'supported({k})' in l for k in grown)]
        (self.pack / 'learned.dl').write_text('\n'.join(rules) + '\n')

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def solve(self, problem, answers, learner='claude'):
        prompts = []
        def fake(prompt, model):
            prompts.append(prompt)
            return answers.pop(0)
        with mock.patch.object(grow, 'ask_claude', fake):
            return grow.solve_one(self.pack, problem, learner, 'fake', 3), prompts

    def test_learn_then_known_then_alias(self):
        rec, _ = self.solve(MAX_PROBLEM, [GOOD])
        self.assertEqual(rec['status'], 'learned')
        rec, _ = self.solve(MAX_PROBLEM, [], learner='none')
        self.assertEqual(rec['status'], 'known')
        renamed = dict(MAX_PROBLEM, id='Maximum of a list')
        rec, _ = self.solve(renamed, [], learner='none')
        self.assertEqual((rec['status'], rec['via']), ('reused', 'biggest_number'))
        self.assertIn('alias(maximum_of_a_list,biggest_number) :- target(python).',
                      (self.pack / 'learned.dl').read_text())

    def test_wrong_code_is_never_admitted_and_feedback_hides_hidden_tests(self):
        rec, prompts = self.solve(MAX_PROBLEM, [BAD, BAD, BAD])
        self.assertEqual(rec['status'], 'failed')
        self.assertFalse(grow.template_path(self.pack, 'biggest_number').exists())
        visible, hidden = grow.split(MAX_PROBLEM['tests'])
        for t in hidden:
            self.assertNotIn(json.dumps(t['args']), prompts[-1])
        self.assertIn('hidden tests failed', prompts[-1])

    def test_feedback_round_can_fix(self):
        rec, _ = self.solve(MAX_PROBLEM, [BAD, GOOD])
        self.assertEqual((rec['status'], rec['model_calls']), ('learned', 2))

    def test_regression_failure_rolls_back(self):
        before = {p.relative_to(self.pack): p.read_bytes() for p in self.pack.rglob('*') if p.is_file()}
        with mock.patch.object(grow, 'regression', lambda pack: ['something']):
            rec, _ = self.solve(MAX_PROBLEM, [GOOD])
        self.assertEqual(rec['status'], 'failed')
        after = {p.relative_to(self.pack): p.read_bytes() for p in self.pack.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_jinja_syntax_in_learned_code_is_kept_verbatim(self):
        code = "def solve(nums):\n    s = '{{ x }} {% if %}'\n    return max(nums) if s else 0\n"
        rec, _ = self.solve(MAX_PROBLEM, [code])
        self.assertEqual(rec['status'], 'learned')
        module = grow.render_task(self.pack, 'biggest_number')
        self.assertIn("'{{ x }} {% if %}'", module.read_text())

    def test_signature_mismatch_is_not_reused(self):
        self.solve(MAX_PROBLEM, [GOOD])
        two_args = dict(MAX_PROBLEM, id='other', signature='solve(a, b)',
                        tests=[{'args': [[1], 2], 'expected': 2}] * 3)
        rec, _ = self.solve(two_args, [], learner='none')
        self.assertEqual(rec['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
