"""Runtime-reuse optimisation: caching must not change results, must be isolated per pack and per
problem, and must be invalidated when pack files (rules, templates, libraries, vocab, pack.json) change."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

import datalog
import general
import generate as gen
from generate import Relations, generate


RULES = 'emit("t.py.j2","m.py","m") :- .\n'


def make_pack(root, rule_text, template_text):
    pack = root / 'pack'
    (pack / 'templates').mkdir(parents=True)
    (pack / 'pack.json').write_text(json.dumps({'rules': ['rules.dl'], 'templates': 'templates'}))
    (pack / 'rules.dl').write_text(rule_text)
    (pack / 'templates' / 't.py.j2').write_text(template_text)
    return pack


class RelationsCache(unittest.TestCase):
    def setUp(self):
        self.db = {'p': {('b', '2'), ('a', '1')}, 'q': {('x',)}}
        self.r = Relations(self.db)

    def test_rows_sorted_and_prefixed(self):
        self.assertEqual(self.r.rows('p'), [['a', '1'], ['b', '2']])
        self.assertEqual(self.r.rows('p', 'a'), [['a', '1']])
        self.assertEqual(self.r.rows('p', 'zz'), [])

    def test_mutation_does_not_leak_into_cache(self):
        first = self.r.rows('p')
        first[0][0] = 'hacked'
        first.append(['junk'])
        self.assertEqual(self.r.rows('p'), [['a', '1'], ['b', '2']])

    def test_one_semantics_unchanged(self):
        self.assertEqual(self.r.one('p', 'a'), '1')
        with self.assertRaises(ValueError):
            self.r.one('p')          # two rows
        with self.assertRaises(ValueError):
            self.r.one('q', 'x')     # row wider than the prefix


class GenerateCaches(unittest.TestCase):
    def test_same_spec_same_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = make_pack(root, RULES, 'key={{ key }}\n')
            spec = {'facts': {}, 'data': {'m': {}}}
            out1, out2 = root / 'o1', root / 'o2'
            generate(dict(spec), out1, pack)
            generate(dict(spec), out2, pack)
            self.assertEqual((out1 / 'm.py').read_text(), (out2 / 'm.py').read_text())

    def test_template_change_invalidates_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = make_pack(root, RULES, 'v1 = {{ key }}\n')
            spec = {'facts': {}, 'data': {'m': {}}}
            out = root / 'o'
            generate(spec, out, pack)
            self.assertIn('v1 = m', (out / 'm.py').read_text())
            (pack / 'templates' / 't.py.j2').write_text('v2 = {{ key }}\n')
            generate(spec, out, pack)
            self.assertIn('v2 = m', (out / 'm.py').read_text())

    def test_rule_change_invalidates_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = make_pack(root, 'error(E) :- .\nemit("t.py.j2","m.py","m") :- error(E).\n', 'x\n')
            spec = {'facts': {}, 'data': {'m': {}}}
            with self.assertRaises(ValueError):
                generate(spec, root / 'o', pack)
            (pack / 'rules.dl').write_text(RULES)
            paths = generate(spec, root / 'o', pack)
            self.assertEqual(paths, ['m.py'])


class EngineCache(unittest.TestCase):
    P = {'id': 't', 'signature': 'solve(n)', 'statement': 's', 'tests': []}
    F = [['arg', 'n', 'int'], ['source', 'range', '1', 'n'], ['aggregate', 'sum']]

    def test_engines_are_isolated_per_request(self):
        """engine_for returns a fresh engine the caller owns: equal results, but mutating one request's
        engine can never pollute another request's engine."""
        d1 = general.engine_for(self.P, self.F)
        d2 = general.engine_for(self.P, self.F)
        self.assertIsNot(d1, d2)
        self.assertEqual(sorted(d1.db['schema']), sorted(d2.db['schema']))
        d1.db['schema'].add(('polluted',))
        self.assertNotIn(('polluted',), d2.db['schema'])

    def test_different_facts_different_engine(self):
        d1 = general.engine_for(self.P, self.F)
        d2 = general.engine_for(self.P, self.F + [['size', 'n', 'tiny']])
        self.assertIsNot(d1, d2)

    def test_explain_not_faked_from_plain_engine(self):
        plain = general.engine_for(self.P, self.F, explain=False)
        expl = general.engine_for(self.P, self.F, explain=True)
        self.assertIsNot(plain, expl)
        self.assertEqual(plain.derivations, {})
        self.assertNotEqual(expl.derivations, {})
        schema = sorted(r[1] for r in expl.db.get('schema', ()) if r[0] == general.KEY)
        self.assertTrue(schema)
        self.assertIsNotNone(expl.why('schema', (general.KEY, schema[0])))

    def test_pack_change_invalidates(self):
        """Cache invalidation is tested on a temporary copy of the pack: changing a rule file (even a
        same-size, same-mtime rewrite) must give a fresh engine, and the real pack is never touched."""
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'pack'
            shutil.copytree(general.PACK, copy)
            fp1 = general.pack_fingerprint(copy)
            d1 = general.engine_for(self.P, self.F, pack=copy)
            rule_file = copy / 'learned.dl'
            if not rule_file.exists():
                rule_file = next(p for p in sorted(copy.glob('*.dl')))
            st = rule_file.stat()
            text = rule_file.read_text()
            # content rewrite of the same size, with the original mtime restored: only the content
            # digest can see it, and it must still invalidate
            rule_file.write_text(text[:1] + ('x' if text[1] != 'x' else 'y') + text[2:])
            os.utime(rule_file, ns=(st.st_atime_ns, st.st_mtime_ns))
            self.assertEqual(rule_file.stat().st_size, st.st_size)
            self.assertNotEqual(general.pack_fingerprint(copy), fp1)  # same size + mtime rewrite is seen
            d2 = general.engine_for(self.P, self.F, pack=copy)
            self.assertIsNot(d1, d2)
            self.assertEqual(sorted(d1.db['schema']), sorted(d2.db['schema']))
            # the cached state must hold the NEW rule text, not a stale entry keyed by old content
            config = json.loads((copy / 'pack.json').read_text())
            all_rules = tuple(r for name in config['rules'] for r in datalog.parse_rules_cached((copy / name).read_text()))
            self.assertEqual(general._pack_state(copy)[1], all_rules)

    def test_prefix_lookup_matches_full_scan(self):
        db = {'p': {(f'{i:04d}', str(j)) for i in range(50) for j in range(3)} | {('z', '1')}}
        r = gen.Relations(db)
        for pre in [(), ('0',), ('00',), ('0010',), ('z',), ('zz',)]:
            self.assertEqual(r.rows('p', *pre),
                             [list(row) for row in sorted(db['p']) if row[:len(pre)] == pre],
                             f'prefix {pre!r}')

    def test_same_problem_results_and_explanation_unchanged(self):
        from test_composition import FACTS, PROBLEMS
        pid = 'leap_year_count'
        d1 = general.engine_for(PROBLEMS[pid], FACTS[pid])
        d2 = general.engine_for(PROBLEMS[pid], FACTS[pid])
        self.assertEqual({p: sorted(rows) for p, rows in d1.db.items()},
                         {p: sorted(rows) for p, rows in d2.db.items()})
        plan = general.explain_plan(PROBLEMS[pid], FACTS[pid])
        self.assertIn('schema seq_fold', plan)

    def test_generated_code_matches_before_baseline(self):
        """The optimised pipeline must generate byte-identical solution code to the before/ baseline
        for the same problem and facts."""
        from test_composition import FACTS, PROBLEMS
        pid = 'leap_year_count'
        before_dir = (Path(__file__).resolve().parent / 'reports' / 'performance_20261108' / 'before').resolve()
        spec = {'facts': general.grouped_facts(PROBLEMS[pid], FACTS[pid], general.PACK),
                'data': {general.KEY: {'params': general.params_of(PROBLEMS[pid]['signature'])}}}
        with tempfile.TemporaryDirectory() as tmp:
            current = Path(tmp) / 'cur'
            generate(spec, current, general.PACK)
            script = (
                'import json, sys, tempfile\n'
                'from pathlib import Path\n'
                f'sys.path.insert(0, {str(before_dir)!r})\n'
                f'sys.path.insert(1, {str(general.ROOT)!r})\n'
                'import general as before_general\n'
                'spec = json.loads(sys.argv[1])\n'
                f'print(before_general.generate(spec, Path(sys.argv[2]), Path({str(general.PACK)!r}))[0])\n'
            )
            before_out = Path(tmp) / 'before_out'
            before_out.mkdir()
            proc = subprocess.run([sys.executable, '-c', script, json.dumps(spec), str(before_out)],
                                  capture_output=True, text=True, cwd=str(before_dir), timeout=120,
                                  env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            name = proc.stdout.strip().splitlines()[-1]
            self.assertEqual((current / name).read_text(), (before_out / name).read_text())

    def test_pack_cache_bounded_and_pack_isolated(self):
        for i in range(general._PACK_CACHE_MAX + 5):
            general.engine_for(self.P, self.F + [['size', 'n', 'tiny']], explain=bool(i % 2), extra_rules=f'x{i}(a) :- .')
        self.assertLessEqual(len(general._PACK_CACHE), general._PACK_CACHE_MAX)
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'copy'
            shutil.copytree(general.PACK, copy)
            d = general.engine_for(self.P, self.F, pack=copy)
            copy_keys = [k for k in general._PACK_CACHE if str(copy.resolve()) in k[0]]
            self.assertTrue(copy_keys)
            self.assertEqual(general._PACK_CACHE[copy_keys[0]][0],
                             json.dumps(json.loads((copy / 'pack.json').read_text()), sort_keys=True))
            self.assertIsNot(d, general.engine_for(self.P, self.F))

    def test_evaluate_shares_inference_runs(self):
        from test_composition import FACTS, PROBLEMS
        pid = 'leap_year_count'
        real_run = datalog.Datalog.run
        runs = []
        def counting(self, *a, **k):
            runs.append(1)
            return real_run(self, *a, **k)
        with mock.patch.object(datalog.Datalog, 'run', counting):
            rec = general.evaluate(PROBLEMS[pid], FACTS[pid])
        self.assertEqual(rec['status'], 'solved')
        # one shared plain run (type check + generate) + one explain run; the baseline did four per problem
        self.assertEqual(len(runs), 2)
        self.assertIn('schema seq_fold', rec['plan'])

    def test_facts_context_is_isolated_per_render(self):
        # template A mutates the facts it sees; template B (another emit row) must not see it
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = make_pack(root, 'emit("t.py.j2","a.py","a") :- .\nemit("t.py.j2","b.py","b") :- .\n',
                             '{% if key == "a" %}{% set _ = facts.extra.append(["X"]) %}{% endif %}{{ facts.extra|length }}')
            spec = {'facts': {'extra': [['a']]}, 'data': {'a': {}, 'b': {}}}
            out = root / 'o'
            generate(spec, out, pack)
            self.assertEqual((out / 'a.py').read_text(), '2')   # mutation visible in its own render
            self.assertEqual((out / 'b.py').read_text(), '1')   # but not in another render
            # unknown predicates stay strict (KeyError -> StrictUndefined), like the plain dicts before
            with self.assertRaises(KeyError):
                gen._FactsView({'extra': (('a',),)})['zz']
            v = gen._FactsView({'extra': (('a',), ('b',))})
            v['extra'][0][0] = 'hacked'
            self.assertEqual(gen._FactsView({'extra': (('a',), ('b',))})['extra'], [['a'], ['b']])
            self.assertEqual(list(v['extra']), [['hacked'], ['b']])
            self.assertEqual(v.copy(), {'extra': [['hacked'], ['b']]})
            self.assertEqual(v, {'extra': [['hacked'], ['b']]})


if __name__ == '__main__':
    unittest.main()

