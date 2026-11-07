from math import gcd


def count_rule_range(lo, hi, rules, default, form):
    # Integers x in lo..hi (inclusive) whose verdict is yes. The verdict of x is that of the first
    # rule [d, verdict] (in list order) with x % d == 0, else default. form: count or sum.
    # Inclusion-exclusion over the earlier divisors: constant time for a fixed rule list.
    if form not in ('count', 'sum'):
        raise ValueError('form must be count or sum')
    ds = []
    for rule in rules:
        d = abs(int(rule[0]))
        if d == 0:
            raise ValueError('divisor must be non-zero')
        ds.append(d)
    if len(ds) > 20:
        raise ValueError('too many rules')
    if lo > hi:
        return 0

    def multiples(step):
        a = (lo - 1) // step
        b = hi // step
        if form == 'count':
            return b - a
        return step * (b * (b + 1) // 2 - a * (a + 1) // 2)

    def first_match(base, earlier):
        # x divisible by base and by none of the earlier divisors
        total = 0
        k = len(earlier)
        for mask in range(1 << k):
            step = base
            sign = 1
            for i in range(k):
                if (mask >> i) & 1:
                    step = step // gcd(step, earlier[i]) * earlier[i]
                    sign = -sign
            total += sign * multiples(step)
        return total

    result = 0
    for i, rule in enumerate(rules):
        if rule[1]:
            result += first_match(ds[i], ds[:i])
    if default:
        result += first_match(1, ds)
    return result
