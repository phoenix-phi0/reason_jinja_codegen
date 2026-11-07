"""Builds examples/composition2_problems.json (task 10): six composition problems with brute-force references and tests, plus the
hand-written facts (examples/composition2_facts.json). Run: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python examples/make_composition2.py"""
import json, math, random
from pathlib import Path

HERE = Path(__file__).resolve().parent
rng = random.Random(10)


def top_k_even_sum(nums, k):
    evens = sorted({x for x in nums if x % 2 == 0}, reverse=True)
    return sum(evens[:k])


def digit_pairs_div3(n):
    digits = [int(c) for c in str(math.factorial(n))]
    return sum(1 for i in range(len(digits)) for j in range(i + 1, len(digits)) if (digits[i] + digits[j]) % 3 == 0)


def change_ways_digit_sum(coins, t):
    ways = [1] + [0] * t
    for c in set(coins):
        for v in range(c, t + 1):
            ways[v] += ways[v - c]
    return sum(int(d) for d in str(ways[t]))


def coins_for_digit_sum(coins, n):
    s = sum(int(d) for d in str(n))
    best = [0] + [None] * s
    for v in range(1, s + 1):
        opts = [best[v - c] + 1 for c in coins if c <= v and best[v - c] is not None]
        best[v] = min(opts) if opts else None
    return -1 if best[s] is None else best[s]


def longest_letter_run(s):
    letters = [c.lower() for c in s if c.isalpha()]
    best = run = 0
    for i, c in enumerate(letters):
        run = run + 1 if i and letters[i - 1] == c else 1
        best = max(best, run)
    return best


def overlap_factorial(iv):
    pts = {p for s, e in iv for p in (s, e)}
    m = max((sum(1 for s, e in iv if s < e and s <= x < e) for x in pts), default=0)
    return math.factorial(m)


def ints(n, lo, hi):
    return [rng.randint(lo, hi) for _ in range(n)]


def intervals(n, hi=30):
    out = []
    for _ in range(n):
        a = rng.randint(0, hi); out.append([a, a + rng.randint(-1, 9)])
    return out


SIG = {
    'top_k_even_sum': 'top_k_even_sum(nums, k)', 'digit_pairs_div3': 'digit_pairs_div3(n)',
    'change_ways_digit_sum': 'change_ways_digit_sum(coins, t)', 'coins_for_digit_sum': 'coins_for_digit_sum(coins, n)',
    'longest_letter_run': 'longest_letter_run(s)', 'overlap_factorial': 'overlap_factorial(intervals)'}
FN = {n: globals()[n] for n in SIG}
STATEMENT = {
    'top_k_even_sum': 'nums is a list of positive integers and k >= 1. Return the sum of the k largest distinct even values of nums (all of them if there are fewer than k distinct even values; 0 if there are none).',
    'digit_pairs_div3': 'Write n! (n >= 0) in decimal. Count the pairs of positions i < j whose two digits add up to a multiple of 3.',
    'change_ways_digit_sum': 'coins is a list of distinct positive integers (unlimited supply of each), t >= 0. Let w be the number of ways to pay exactly t, where the order of the coins does not matter. Return the sum of the decimal digits of w.',
    'coins_for_digit_sum': 'coins is a list of positive integers (unlimited supply of each), n >= 0. Let s be the sum of the decimal digits of n. Return the minimum number of coins that add up to exactly s, or -1 if that is impossible.',
    'longest_letter_run': 'Ignore every character of s that is not a letter and ignore case. In the remaining sequence of letters, return the length of the longest run of equal adjacent letters (0 if there are no letters).',
    'overlap_factorial': 'intervals is a list of [start, end) integer pairs (an interval with end <= start is empty and counts nowhere). Let m be the largest number of intervals that cover a common point. Return m! (0! = 1).'}
ARGS = {
    'top_k_even_sum': [([], 1), ([1, 3, 5], 2), ([2], 3), ([4, 4, 4], 2), ([2, 8, 6, 4], 2), ([2, 8, 6, 4], 10), ([7, 10, 10, 3, 8, 2], 3), ([1, 2], 1), ([100, 98, 98, 2, 1], 2)]
    + [(ints(rng.randint(1, 25), 1, 40), rng.randint(1, 6)) for _ in range(6)],
    'digit_pairs_div3': [(0,), (1,), (2,), (3,), (5,), (10,), (15,), (30,), (52,), (100,), (143,)],
    'change_ways_digit_sum': [([1], 0), ([1], 5), ([2], 3), ([1, 2, 5], 11), ([1, 2, 5], 100), ([2, 5, 3, 6], 10), ([3], 9), ([7, 11], 50), ([1, 5, 10, 25, 50], 200), ([4, 9], 2)],
    'coins_for_digit_sum': [([1], 0), ([2], 7), ([5, 2], 129), ([1, 3, 4], 99), ([7], 25), ([4, 6], 11), ([3, 5], 6789), ([10, 1], 999), ([2, 3], 1000000), ([9, 8], 55)],
    'longest_letter_run': [('',), ('a',), ('aab',), ('a1a',), ('AaBb',), ('ab ba', ), ('Mississippi',), ('x-x-x y',), ('123',), ('hello  wOrld!!', ), ('aaa b aaaa', ), ('zz9Zz',)],
    'overlap_factorial': [([],), ([[1, 1]],), ([[0, 3]],), ([[0, 3], [3, 5]],), ([[0, 3], [2, 5]],), ([[0, 5], [1, 4], [2, 3]],), ([[5, 2], [1, 2]],), ([[0, 10], [0, 10], [0, 10], [9, 11]],), ([[1, 4], [2, 6], [3, 7], [10, 12], [11, 13]],)]
    + [(intervals(rng.randint(1, 8)),) for _ in range(4)],
}
FACTS = {
    'top_k_even_sum': [['arg', 'nums', 'int_list'], ['arg', 'k', 'int'], ['guarantees', 'nums', 'positive'], ['stage', '1', 'seq_rank'], ['stage', '2', 'seq_fold'],
                       ['1.iterate', 'nums'], ['1.keep', 'even'], ['1.distinct', 'mapped'], ['1.select_rank', 'largest', 'k'], ['1.if_empty', '0'],
                       ['2.iterate', 'nums'], ['2.keep', 'even'], ['2.distinct', 'mapped'], ['2.bound', 'ge', 'stage1'], ['2.aggregate', 'sum']],
    'digit_pairs_div3': [['arg', 'n', 'int'], ['stage', '1', 'seq_fold'], ['stage', '2', 'pair_count'],
                         ['1.source', 'range', '1', 'n'], ['1.aggregate', 'product'],
                         ['2.source', 'digits', 'stage1'], ['2.ask', 'count_pairs'], ['2.pair_test', 'sum', '3', '0']],
    'change_ways_digit_sum': [['arg', 'coins', 'int_list'], ['arg', 't', 'int'], ['guarantees', 'coins', 'positive'], ['unique', 'coins'], ['stage', '1', 'knapsack'], ['stage', '2', 'seq_fold'],
                              ['1.items', 'coins'], ['1.target', 't'], ['1.ask', 'count_ways'],
                              ['2.source', 'digits', 'stage1'], ['2.aggregate', 'sum']],
    'coins_for_digit_sum': [['arg', 'coins', 'int_list'], ['arg', 'n', 'int'], ['guarantees', 'coins', 'positive'], ['stage', '1', 'seq_fold'], ['stage', '2', 'knapsack'],
                            ['1.source', 'digits', 'n'], ['1.aggregate', 'sum'],
                            ['2.items', 'coins'], ['2.target', 'stage1'], ['2.ask', 'min_count']],
    'longest_letter_run': [['arg', 's', 'string'], ['stage', '1', 'seq_fold'], ['stage', '2', 'run_encode'],
                           ['1.source', 'chars', 's'], ['1.keep', 'letter'], ['1.map', 'lower'], ['1.aggregate', 'join'],
                           ['2.source', 'stage', '1'], ['2.ask', 'run_length'], ['2.run_output', 'longest_run']],
    'overlap_factorial': [['arg', 'intervals', 'interval_list'], ['stage', '1', 'interval_scan'], ['stage', '2', 'seq_fold'],
                          ['1.iterate', 'intervals'], ['1.ask', 'max_overlap'],
                          ['2.source', 'range', '1', 'stage1'], ['2.aggregate', 'product']],
}
problems = []
for pid in SIG:
    tests = [{'args': list(a), 'expected': FN[pid](*a)} for a in ARGS[pid]]
    problems.append({'id': pid, 'signature': SIG[pid], 'statement': STATEMENT[pid], 'tests': tests})
(HERE / 'composition2_problems.json').write_text(json.dumps(problems, indent=1) + '\n')
(HERE / 'composition2_facts.json').write_text(json.dumps(FACTS, indent=1) + '\n')
print({p['id']: len(p['tests']) for p in problems})
