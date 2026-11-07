"""Growth proposal pre-check (general_grow.precheck) and output-sensitive complexity (n+out)."""
import json, shutil, tempfile, unittest
from pathlib import Path

import general
import general_grow as G
import lib_check

SIG = {'signature': 'solve(s)'}
FACTS = [['arg', 's', 'string'], ['iterate', 's'], ['ask', 'digits_of_number']]
META = {'doc': 'x', 'complexity': 'n', 'role': 'demo', 'drives': ['seq'], 'requires': [], 'generator': [{'kind': 'string', 'chars': 'ab'}],
        'sizes': [1000, 10000], 'tests': [{'args': ['a'], 'expected': 1}] * 5}
CODE = 'def demo_fn(s):\n    return len(s)\n'


def lib(meta=None, code=CODE, name='demo_fn'):
    return {f'templates/lib/{name}.py': code, f'templates/lib/{name}.json': json.dumps(meta or META)}


CAND = 'candidate(P,demo_fn) :- iterate(P,A).\n'


class PrecheckTest(unittest.TestCase):
    def pre(self, files, facts=FACTS, problem=SIG):
        return G.precheck(general.PACK, {'files': files, 'facts': facts}, problem)

    def has(self, found, *needles):
        self.assertTrue(any(all(n in f for n in needles) for f in found), found)

    def algos(self):
        return (general.PACK / 'algorithms.dl').read_text() + CAND

    def test_empty_complete_proposal_passes(self):
        files = {**lib(), 'algorithms.dl': self.algos()}
        self.assertEqual(self.pre(files), [])

    def test_files_outside_editable_set_are_named(self):
        found = self.pre({'rules.dl': 'x.', 'templates/solution.py.j2': 'y', 'templates/algorithms_note.txt': 'z'})
        self.has(found, 'outside the editable set', 'rules.dl', 'templates/solution.py.j2', 'algorithms_note.txt')

    def test_unknown_fact_predicate_and_value(self):
        found = self.pre({}, facts=[['arg', 's', 'string'], ['run_direction', 'decode'], ['keep', 'bogus_cond']])
        self.has(found, 'unknown predicate run_direction')
        self.has(found, 'keep', 'bogus_cond')

    def test_fact_uses_predicate_added_by_the_proposal_vocab(self):
        v = json.loads((general.PACK / 'vocab.json').read_text())
        v['predicates']['run_direction'] = {'args': ['dir'], 'values': {'dir': ['decode']}, 'doc': 'decode runs'}
        facts = [['arg', 's', 'string'], ['run_direction', 'decode']]
        self.assertEqual(self.pre({'vocab.json': json.dumps(v)}, facts=facts), [])
        v['predicates']['run_direction']['doc'] = ''
        self.has(self.pre({'vocab.json': json.dumps(v)}, facts=facts), 'run_direction', 'no "doc"')

    def test_vocab_json_invalid_or_dropping_predicates(self):
        self.has(self.pre({'vocab.json': '{oops'}), 'vocab.json is not valid JSON')
        v = json.loads((general.PACK / 'vocab.json').read_text())
        del v['predicates']['keep']
        self.has(self.pre({'vocab.json': json.dumps(v)}), 'drops existing predicates', 'keep')

    def test_missing_facts(self):
        self.has(G.precheck(general.PACK, {'files': {}}, SIG), '"facts"')

    def test_dead_rule_predicate_in_new_rules(self):
        learned = (general.PACK / 'learned.dl').read_text() + '\ncandidate(P,count_pairs_residue) :- aggregat(P,count).\n'
        self.has(self.pre({'learned.dl': learned}), 'lint', 'aggregat')

    def test_unparsable_rule_file(self):
        self.has(self.pre({'learned.dl': 'this is not datalog'}), 'does not parse')

    def test_new_schema_needs_reference_selection_and_answer_type(self):
        found = self.pre({'templates/schemas/demo_sch.py.j2': '# glue\n'})
        self.has(found, 'new schema', 'reference implementation')
        self.has(found, 'demo_sch', 'no rule derives schema')
        self.has(found, 'demo_sch', 'no answer_type rule')

    def test_new_schema_complete(self):
        learned = ((general.PACK / 'learned.dl').read_text()
                   + '\nschema(P,demo_sch) :- iterate(P,A), ask(P,demo).\nanswer_type(P,int) :- schema(P,demo_sch).\n')
        files = {'templates/schemas/demo_sch.py.j2': '# glue\n', 'templates/reference/demo_sch.py.j2': '# ref\n', 'learned.dl': learned}
        self.assertEqual(self.pre(files), [])

    def test_new_library_function_missing_pieces(self):
        found = self.pre({'templates/lib/demo_fn.py': CODE})
        self.has(found, 'demo_fn', 'needs both')
        self.has(found, 'no candidate(P,demo_fn)')
        self.has(self.pre({'templates/lib/demo_fn.json': json.dumps(META)}), 'needs both')

    def test_library_metadata_gaps_all_reported_at_once(self):
        meta = {'doc': 'x', 'complexity': 'n'}
        found = self.pre(lib(meta))
        self.has(found, 'metadata lacks', 'role', 'drives', 'requires', 'generator', 'sizes', 'tests')
        self.has(found, 'no candidate')

    def test_library_metadata_bad_values(self):
        bad = dict(META, complexity='n^7', tests=[{'args': [], 'expected': 0}], sizes=[10, 20], drives=['no_such_role'])
        found = self.pre({**lib(bad), 'algorithms.dl': self.algos()})
        self.has(found, 'complexity must be one of')
        self.has(found, 'tests must be a list of >= 5')
        self.has(found, 'sizes must be')
        self.has(found, 'no_such_role', 'binds')

    def test_library_code_problems(self):
        found = self.pre({**lib(code='def other(s):\n    return "{{ x }}"\n'), 'algorithms.dl': self.algos()})
        self.has(found, 'defines no `def demo_fn(`')
        self.has(found, 'Jinja markers')

    def test_existing_library_function_may_not_change(self):
        found = self.pre({'templates/lib/digit_sums.py': 'def digit_sums(v):\n    return v\n'})
        self.has(found, 'already exists and may not be changed')

    def test_n_plus_out_needs_output_size(self):
        found = self.pre({**lib(dict(META, complexity='n+out')), 'algorithms.dl': self.algos()})
        self.has(found, 'demo_fn', 'output_size')
        ok = dict(META, complexity='n+out', output_size={'max_factor': 9, 'doc': 'counts are single digits'})
        self.assertEqual(self.pre({**lib(ok), 'algorithms.dl': self.algos()}), [])

    def test_all_omissions_listed_in_one_feedback(self):
        found = self.pre({'rules.dl': 'x.', 'templates/schemas/s2.py.j2': '#'}, facts=[['nope', 'x']])
        self.assertGreaterEqual(len(found), 4, found)

    def test_try_proposal_returns_precheck_feedback_without_running_checks(self):
        ok, info, work = G.try_proposal(general.PACK, dict(SIG, id='x', tests=[]), {'files': {'rules.dl': 'x.'}, 'facts': FACTS})
        self.assertFalse(ok)
        self.assertIsNone(work)
        self.assertIn('precheck found', info)
        self.assertIn('rules.dl', info)
        self.assertIn('Fix it', G.feedback_text({}, info))


class OutputSensitiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='tnout_'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def check(self, name, code, meta):
        d = self.tmp / name
        d.mkdir(exist_ok=True)
        (d / f'{name}.py').write_text(code)
        (d / f'{name}.json').write_text(json.dumps(meta))
        return lib_check.check_one(d / f'{name}.py')

    DECODE = ('def {n}(s):\n    out = []\n    for ch in s:\n        out.append(ch * 3)\n    return "".join(out)\n')
    META = {'doc': 'x', 'complexity': 'n+out', 'role': 'dec', 'drives': ['seq'], 'requires': [],
            'generator': [{'kind': 'string', 'chars': 'abc'}], 'sizes': [20000, 100000],
            'tests': [{'args': [s], 'expected': s and ''.join(c * 3 for c in s)} for s in ('', 'a', 'ab', 'abc', 'zz')],
            'output_size': {'max_factor': 3, 'doc': 'each character is repeated three times'}}

    def test_declared_bound_that_holds_passes(self):
        meta = json.loads(json.dumps(self.META)); meta['tests'][0]['expected'] = ''
        problems, m = self.check('okdec', self.DECODE.format(n='okdec'), meta)
        self.assertEqual(problems, [], problems)
        self.assertGreater(m['input_sizes'][1], 3 * 100000 * 0.9)  # work counts input + output

    def test_bound_too_small_is_refused(self):
        meta = json.loads(json.dumps(self.META)); meta['tests'][0]['expected'] = ''
        meta['output_size']['max_factor'] = 2
        problems, _ = self.check('baddec', self.DECODE.format(n='baddec'), meta)
        self.assertTrue(any('exceeds the declared bound' in p for p in problems), problems)

    def test_missing_or_malformed_output_size_is_refused(self):
        meta = dict(self.META); del meta['output_size']
        problems, _ = self.check('nodecl', self.DECODE.format(n='nodecl'), meta)
        self.assertTrue(any('needs output_size' in p for p in problems), problems)
        meta = dict(self.META, output_size={'max_factor': 0, 'doc': 'x'})
        problems, _ = self.check('zero', self.DECODE.format(n='zero'), meta)
        self.assertTrue(any('max_factor' in p for p in problems), problems)
        meta = dict(self.META, complexity='n')
        problems, _ = self.check('stray', self.DECODE.format(n='stray'), meta)
        self.assertTrue(any('only allowed with complexity' in p for p in problems), problems)

    def test_quadratic_output_sensitive_function_is_still_caught(self):
        code = 'def quad(s):\n    out = ""\n    for ch in s:\n        out = out + ch + out[-1:]\n    return out\n'
        meta = json.loads(json.dumps(self.META))
        meta['tests'] = [{'args': [s], 'expected': None} for s in ('', 'a', 'ab', 'abc', 'zz')]
        meta['output_size'] = {'max_factor': 3, 'doc': 'x'}
        meta['generator'] = [{'kind': 'string', 'chars': 'abc'}]
        meta['sizes'] = [2000, 20000]
        # quad's output is 2n here (bound holds) but its time is quadratic in n: must fail the growth check or the unit tests
        for t in meta['tests']:
            t['expected'] = None
        problems, _ = self.check('quad', code, meta)
        self.assertTrue(problems)

    def test_costs_rules_treat_n_plus_out_like_a_linear_function(self):
        d = general.engine_for({'id': 'p', 'signature': 'solve(s)'}, FACTS, general.PACK)
        self.assertIn(('n+out',), d.db.get('single_driver', set()))
        self.assertIn(('n+out', 'large'), d.db.get('fits', set()))

    def test_problem_cost_scales_with_input_plus_output(self):
        # a temporary pack whose digit_sums-like function declares n+out; problem_cost must accept it and use 'work' = input + output
        work = self.tmp / 'pack_cost'
        shutil.copytree(general.PACK, work, ignore=shutil.ignore_patterns('solved', 'rejected', '__pycache__'))
        meta_path = work / 'templates' / 'lib' / 'caesar_shift.json'
        rec = json.loads((general.PACK / 'solved' / 'glm2_caesar_shift.json').read_text())
        meta = json.loads(meta_path.read_text())
        self.assertEqual(G.problem_cost(work, rec), None)
        meta['complexity'] = 'n+out'
        meta['output_size'] = {'max_factor': 1, 'doc': 'output has the length of the input'}
        meta_path.write_text(json.dumps(meta))
        self.assertEqual(G.problem_cost(work, rec), None)
        meta['output_size']['max_factor'] = 1
        self.assertEqual(lib_check.output_bound(meta), (1.0, 16.0))


if __name__ == '__main__':
    unittest.main()
