def count_pairs_residue(values, op, m, r):
    """Pairs i < j with (a op b) % m == r for op 'sum' (a + b) or 'difference' (a - b), a = values[i], b = values[j]. O(n)."""
    if r % m != r:
        return 0
    cnt = {}
    good = 0
    for b in values:
        rb = b % m
        need = (r - rb) % m if op == 'sum' else (r + rb) % m
        good += cnt.get(need, 0)
        cnt[rb] = cnt.get(rb, 0) + 1
    return good
