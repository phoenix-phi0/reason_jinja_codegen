def number_digits(n, kind, base, form):
    import sys
    try:
        sys.set_int_max_str_digits(0)
    except AttributeError:
        pass
    if n < 0:
        raise ValueError('n must be non-negative')
    if kind == 'factorial':
        v = 1
        for i in range(2, n + 1):
            v *= i
    elif kind == 'fibonacci':
        a, b = 0, 1
        for _ in range(n):
            a, b = b, a + b
        v = a
    elif kind == 'power':
        v = abs(base) ** n
    else:
        raise ValueError('unknown kind')
    s = str(abs(v))
    if form == 'sum':
        return sum(map(int, s))
    if form == 'count':
        return len(s)
    if form == 'max_digit':
        return int(max(s))
    if form == 'trailing_zeros':
        return 0 if v == 0 else len(s) - len(s.rstrip('0'))
    raise ValueError('unknown form')
