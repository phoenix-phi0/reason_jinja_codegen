def josephus_survivor(n, k, first, start):
    if n < 1 or k < 1:
        raise ValueError('n and k must be positive')
    rel = 0
    for i in range(2, n + 1):
        rel = (rel + k) % i
    return first + ((start - first) % n + rel) % n
