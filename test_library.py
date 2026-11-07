"""The algorithm library and the rules that keep it from being merged away or bypassed."""
import json, shutil, tempfile, unittest
from pathlib import Path

import general_grow as gg
import lib_check

PACK = gg.PACK
ONLY = {'g3_count_overlapping_half_open_slot_pairs', 'g2_count_pairs_sum_divisible_by4', 'ho_inversion_count'}  # problems the edits below touch


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='libtest_'))
        self.pack = self.dir / 'pack'
        shutil.copytree(PACK, self.pack)
        # drop the large tests so that only the checks under test can catch a slowdown
        for f in (self.pack / 'solved').glob('*.json'):
            rec = json.loads(f.read_text())
            rec['tests'] = [t for t in rec['tests'] if not t.get('scale')]
            f.write_text(json.dumps(rec))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_library_functions_pass_their_checks(self):
        problems, report = lib_check.check_all(self.pack / 'templates' / 'lib')
        self.assertEqual(problems, [])
        self.assertGreaterEqual(len(report), 16)

    def test_library_is_append_only(self):
        lib = 'templates/lib/count_pairs_difference_bound.py'
        self.assertTrue(gg.edit_violations(self.pack, {lib: 'def count_pairs_difference_bound(v, c, l):\n    return 0\n'}))
        self.assertTrue(gg.edit_violations(self.pack, {}, [lib]))
        self.assertTrue(gg.edit_violations(self.pack, {'templates/lib/new_fn.py': 'def new_fn():\n    pass\n'}))
        self.assertEqual(gg.edit_violations(self.pack, {'templates/lib/new_fn.py': 'x', 'templates/lib/new_fn.json': '{}'}), [])
        self.assertEqual(gg.edit_violations(self.pack, {lib: (self.pack / lib).read_text()}), [])

    def test_selection_rules_cannot_fall_back_to_brute_force(self):
        rules = self.pack / 'algorithms.dl'
        rules.write_text('\n'.join(l for l in rules.read_text().splitlines() if 'count_pairs_' not in l or 'brute' in l) + '\n')
        # ho_inversion_count has 150000-element tests, so its stored size is large: brute force is not feasible
        # and the rules refuse the problem instead of quietly choosing the quadratic function
        broken = {pid: (kind, why) for pid, kind, why in gg.regression(self.pack, only=ONLY)}
        self.assertEqual(broken['ho_inversion_count'][0], 'rejected'); self.assertIn('too_slow', broken['ho_inversion_count'][1])
        # with a small stated size brute force is feasible; then the complexity check sees the worse choice
        rec_path = self.pack / 'solved/ho_inversion_count.json'
        rec = json.loads(rec_path.read_text())
        rec['facts'] = [f for f in rec['facts'] if f[0] != 'size'] + [['size', 'values', 'small']]
        rec_path.write_text(json.dumps(rec))
        old_rec = self.pack.parent / 'old' / 'solved' / 'ho_inversion_count.json'
        old_rec.parent.mkdir(parents=True); shutil.copytree(PACK, self.pack.parent / 'old', dirs_exist_ok=True); old_rec.write_text(json.dumps(rec))
        worse = {pid for pid, *_ in gg.complexity_regressions(self.pack.parent / 'old', self.pack)}
        self.assertIn('ho_inversion_count', worse)

    def test_glue_may_not_inline_an_algorithm(self):
        glue = self.pack / 'templates/schemas/pair_count.py.j2'
        text = glue.read_text().replace("{% if fn == 'count_pairs_residue' %}", "{% if false %}", 1)
        text = text.replace("{% elif fn == 'count_pairs_brute' %}\n    good = count_pairs_brute(values, lambda a, b: {{ conds|join(' and ') }})",
                            "{% elif true %}\n    good = 0\n    for i in range(len(values)):\n        for j in range(i + 1, len(values)):\n            a, b = values[i], values[j]\n            good += bool({{ conds|join(' and ') }})")
        glue.write_text(text)
        broken = {pid: kind for pid, kind, _ in gg.regression(self.pack, only=ONLY)}
        self.assertEqual(broken.get('g2_count_pairs_sum_divisible_by4'), 'glue')

    def _edit_interval_glue(self, needle_after, inserted):
        glue = self.pack / 'templates/schemas/interval_scan.py.j2'
        text = glue.read_text()
        self.assertIn(needle_after, text)
        glue.write_text(text.replace(needle_after, needle_after + inserted, 1))

    def test_codex_attack_wrong_at_size_18_and_hidden_quadratic(self):
        self._edit_interval_glue("{% if relations.has('ask', key, 'overlap_pairs') %}\n",
                                 "    if len(pairs) == 18:\n        return -1\n    ignored = sum(map(pairs.count, pairs))\n")
        kinds = {pid: kind for pid, kind, _ in gg.regression(self.pack, only=ONLY)}
        self.assertEqual(kinds.get('g3_count_overlapping_half_open_slot_pairs'), 'glue')  # map() is not whitelisted

    def test_wrong_answer_at_size_18_is_caught_by_the_reference(self):
        self._edit_interval_glue("{% if relations.has('ask', key, 'overlap_pairs') %}\n", "    if len(pairs) == 18:\n        return -1\n")
        kinds = {pid: kind for pid, kind, _ in gg.regression(self.pack, only=ONLY)}
        self.assertEqual(kinds.get('g3_count_overlapping_half_open_slot_pairs'), 'differs_from_reference')

    def test_goose_attacks_zero_above_100_and_nested_map(self):
        self._edit_interval_glue("    good = interval_overlapping_pairs(pairs, {{ reach }})\n",
                                 "    good = good if len(pairs) < 100 else 0\n")
        kinds = {pid: kind for pid, kind, _ in gg.regression(self.pack, only=ONLY)}
        self.assertEqual(kinds.get('g3_count_overlapping_half_open_slot_pairs'), 'differs_from_reference')
        shutil.rmtree(self.pack); shutil.copytree(PACK, self.pack)
        self._edit_interval_glue("    good = interval_overlapping_pairs(pairs, {{ reach }})\n",
                                 "    good += sum(map(lambda a: sum(map(lambda b: 0, pairs)), pairs)) if len(pairs) >= 100 else 0\n")
        kinds = {pid: kind for pid, kind, _ in gg.regression(self.pack, only=ONLY)}
        self.assertEqual(kinds.get('g3_count_overlapping_half_open_slot_pairs'), 'glue')

    def test_dishonest_complexity_declaration_is_rejected(self):
        lib = self.pack / 'templates/lib'
        (lib / 'slow.py').write_text('def slow(values):\n    """Declared linear, really quadratic."""\n    return sum(1 for x in values for y in values)\n')
        meta = {'doc': 'x', 'complexity': 'n', 'sizes': [100, 400],
                'generator': [{'kind': 'value', 'value': []}],
                'tests': [{'args': [[1] * k], 'expected': k * k} for k in range(5)]}
        (lib / 'slow.json').write_text(json.dumps(meta))
        problems, _ = lib_check.check_all(lib, use_cache=False)
        self.assertTrue(any('slow' in p and 'scale' in p for p in problems), problems)  # empty generator
        meta['generator'] = [{'kind': 'int_list', 'lo': 0, 'hi': 9}]
        (lib / 'slow.json').write_text(json.dumps(meta))
        problems, _ = lib_check.check_all(lib, use_cache=False)
        self.assertTrue(any('slow' in p and ('grows like' in p or '>' in p) for p in problems), problems)  # really quadratic

    def test_new_schema_needs_reference_and_references_keep_their_answers(self):
        self.assertTrue(gg.edit_violations(self.pack, {'templates/schemas/new_one.py.j2': 'x'}))
        self.assertEqual(gg.edit_violations(self.pack, {'templates/schemas/new_one.py.j2': 'x', 'templates/reference/new_one.py.j2': 'y'}), [])
        self.assertTrue(gg.edit_violations(self.pack, {}, ['templates/reference/pair_count.py.j2']))
        ref = self.pack / 'templates/reference/pair_count.py.j2'
        original = ref.read_text()
        ref.write_text(original + '\n')  # an extension that changes no answer
        self.assertEqual(gg.reference_compat(PACK, self.pack), [])
        ref.write_text(original.replace('            good += 1\n', '            good += 2\n'))  # changes stored answers
        self.assertTrue(gg.reference_compat(PACK, self.pack))

    def test_fixed_library_edge_cases(self):
        import sys
        sys.path.insert(0, str(self.pack / 'templates/lib'))
        from grid_shortest_path import grid_shortest_path
        from knap_count_ways import knap_count_ways
        from count_pairs_sum_bound import count_pairs_sum_bound
        import general
        self.assertIsNone(grid_shortest_path(['11'], ['1'], [-1, 0], [0, 0], False))
        self.assertIsNone(grid_shortest_path(['11'], ['1'], [2, 0], [0, 0], False))
        self.assertEqual(knap_count_ways([], 0, False, False, 1), 0)
        with self.assertRaises(ValueError):
            count_pairs_sum_bound([0.3, 0.4], 'lt', 1.0)
        self.assertEqual(general.evaluate({'signature': 'solve(xs)', 'tests': []}, [['arg', 'xs', 'int_list'], ['iterate', 'xs'], ['aggregate', 'sum']])['status'], 'untested')

    def test_round2_special_cases_beyond_small_sizes_and_values(self):
        cases = ["    if len(pairs) >= 201:\n        return -1\n",
                 "    if pairs and pairs[0][0] >= 1000:\n        return -1\n"]
        for inserted in cases:
            with self.subTest(inserted=inserted):
                shutil.rmtree(self.pack); shutil.copytree(PACK, self.pack)
                self._edit_interval_glue("    good = interval_overlapping_pairs(pairs, {{ reach }})\n", inserted)
                kinds = {pid: kind for pid, kind, _ in gg.regression(self.pack, only=ONLY)}
                self.assertEqual(kinds.get('g3_count_overlapping_half_open_slot_pairs'), 'differs_from_reference')

    def test_round2_copying_inside_a_loop(self):
        for inserted in ("    scratch = []\n    for p in pairs:\n        scratch = scratch + [0]\n",
                         "    waste = ''\n    for pair in pairs:\n        waste = str(pair) + waste\n"):
            with self.subTest(inserted=inserted):
                shutil.rmtree(self.pack); shutil.copytree(PACK, self.pack)
                self._edit_interval_glue("    good = interval_overlapping_pairs(pairs, {{ reach }})\n", inserted)
                kinds = {pid: kind for pid, kind, _ in gg.regression(self.pack, only=ONLY)}
                self.assertEqual(kinds.get('g3_count_overlapping_half_open_slot_pairs'), 'glue')

    def test_round2_decoy_argument_hides_a_quadratic_function(self):
        lib = self.pack / 'templates/lib'
        (lib / 'decoy_overlap.py').write_text(
            'def decoy_overlap(pairs, reach, decoy):\n    """Overlapping pairs (claimed n log n)."""\n'
            '    return sum(1 for i in range(len(pairs)) for j in range(i + 1, len(pairs))\n'
            '               if max(pairs[i][0], pairs[j][0]) < min(pairs[i][1], pairs[j][1]) + reach)\n')
        (lib / 'decoy_overlap.json').write_text(json.dumps({
            'doc': 'x', 'complexity': 'n log n', 'sizes': [1000, 4000], 'role': 'overlap_pairs', 'drives': ['seq'],
            'generator': [{'kind': 'value', 'value': []}, {'kind': 'value', 'value': 0}, {'kind': 'int_list', 'lo': 0, 'hi': 9}],
            'tests': [{'args': [[[0, 1]] * k, 0, []], 'expected': k * (k - 1) // 2} for k in range(5)]}))
        rules = self.pack / 'algorithms.dl'
        rules.write_text(rules.read_text().replace('candidate(P,interval_overlapping_pairs) :-', 'candidate(P,decoy_overlap) :-'))
        glue = self.pack / 'templates/schemas/interval_scan.py.j2'
        glue.write_text(glue.read_text().replace('good = interval_overlapping_pairs(pairs, {{ reach }})', 'good = decoy_overlap(pairs, {{ reach }}, pairs)'))
        self.assertEqual(lib_check.check_all(lib, use_cache=False)[0], [])  # the library check alone is fooled
        kinds = {pid: kind for pid, kind, _ in gg.regression(self.pack, only=ONLY)}
        self.assertEqual(kinds.get('g3_count_overlapping_half_open_slot_pairs'), 'cost')

    def test_round3_false_alarms_are_gone(self):
        self._edit_interval_glue("    good = interval_overlapping_pairs(pairs, {{ reach }})\n",
                                 "    count = 0\n    for pair in pairs:\n        count = count + 1\n")
        glue = self.pack / 'templates/schemas/interval_scan.py.j2'
        glue.write_text(glue.read_text().replace('key=lambda p: (p[0], p[1])', 'key=lambda p: (sum((p[0],)), p[1])'))
        self.assertEqual(gg.regression(self.pack, only=ONLY), [])

    def test_round3_sequence_repetition_inside_a_loop(self):
        self._edit_interval_glue("    good = interval_overlapping_pairs(pairs, {{ reach }})\n",
                                 "    if pairs and pairs[0][0] >= 1000:\n        for p in pairs:\n            scratch = [0] * len(pairs)\n")
        kinds = {pid: kind for pid, kind, _ in gg.regression(self.pack, only=ONLY)}
        self.assertEqual(kinds.get('g3_count_overlapping_half_open_slot_pairs'), 'glue')

    def test_round3_timing_grids_grow_in_both_directions(self):
        import random
        rec = json.loads((self.pack / 'solved/grid_islands.json').read_text())
        pools, knap = gg._pools(rec)
        sizes = [len(gg._make_input(pools, knap, n, random.Random(0), square_grid=True)[0]) for n in (2000, 8000, 32000)]
        self.assertEqual(sizes, [44, 89, 178])

    def test_prompt_templates_format_with_their_arguments(self):
        import general_consolidate as gc
        prob = json.loads((self.pack / 'solved/ho_inversion_count.json').read_text())
        texts = [gg.PROMPT.format(layers=gg.LAYERS_NOTE, pack=gg.pack_text(self.pack), signature=prob['signature'],
                                  statement=prob['statement'], examples='e', note='n', feedback=''),
                 gg.REPAIR.format(layers=gg.LAYERS_NOTE, pack=gg.pack_text(self.pack), failing='f', feedback=''),
                 gc.PROMPT.format(layers=gg.LAYERS_NOTE, pack=gg.pack_text(self.pack), problems=gc.problems_text(self.pack), feedback='')]
        for t in texts:
            self.assertIn('Layers:', t)
            self.assertIn('reference implementation', t)

    def test_grow_one_runs_end_to_end_with_a_fake_model(self):
        from unittest import mock
        prob = json.loads((self.pack / 'solved/ho_inversion_count.json').read_text())
        prob = dict(prob, id='fake_new_problem')
        reply = {'files': {}, 'facts': prob['facts'], 'summary': 'reuse'}
        with mock.patch.object(gg, 'ask', lambda prompt, model: reply), mock.patch.object(gg, 'regression', lambda pack, only=None: []):
            rec = gg.grow_one(self.pack, prob, 'fake', 1, None)
        self.assertEqual(rec['status'], 'grown', rec)


if __name__ == '__main__':
    unittest.main()
