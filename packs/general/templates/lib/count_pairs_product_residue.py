from math import gcd


def count_pairs_product_residue(values, m, r):
    """Pairs i < j with (values[i] * values[j]) % m == r (Python %). Residue classes plus gcd classes."""
    values = list(values)
    n = len(values)
    if n < 2:
        return 0
    if m <= 0:
        total = 0
        for i in range(n):
            for j in range(i + 1, n):
                if (values[i] * values[j]) % m == r:
                    total += 1
        return total
    if r < 0 or r >= m:
        return 0
    cnt = {}
    for v in values:
        key = v % m
        cnt[key] = cnt.get(key, 0) + 1
    selfs = 0
    for res, c in cnt.items():
        if (res * res) % m == r:
            selfs += c
    ordered = 0
    if r == 0:
        classes = {}
        for res, c in cnt.items():
            g = gcd(res, m)
            classes[g] = classes.get(g, 0) + c
        items = list(classes.items())
        for g1, c1 in items:
            for g2, c2 in items:
                if (g1 * g2) % m == 0:
                    ordered += c1 * c2
    else:
        tables = {}
        for res, c in cnt.items():
            g = gcd(res, m)
            if r % g:
                continue
            mm = m // g
            if mm > 1:
                t = ((r // g) * pow(res // g, -1, mm)) % mm
            else:
                t = 0
            table = tables.get(mm)
            if table is None:
                table = {}
                for res2, c2 in cnt.items():
                    k2 = res2 % mm
                    table[k2] = table.get(k2, 0) + c2
                tables[mm] = table
            ordered += c * table.get(t, 0)
    return (ordered - selfs) // 2
