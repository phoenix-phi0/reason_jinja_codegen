def josephus_order(n, k, first, start):
    if n < 1 or k < 1:
        raise ValueError('n and k must be positive')
    tree = [0] * (n + 1)
    for i in range(1, n + 1):
        tree[i] = i & -i
    top = 1
    while top * 2 <= n:
        top *= 2
    order = []
    idx = (start - first) % n
    m = n
    while m > 0:
        idx = (idx + k - 1) % m
        want = idx + 1
        pos = 0
        pw = top
        while pw:
            nxt = pos + pw
            if nxt <= n and tree[nxt] < want:
                pos = nxt
                want -= tree[nxt]
            pw >>= 1
        pos += 1
        order.append(first + pos - 1)
        j = pos
        while j <= n:
            tree[j] -= 1
            j += j & -j
        m -= 1
    return order
