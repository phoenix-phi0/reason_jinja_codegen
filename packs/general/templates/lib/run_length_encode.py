def run_length_encode(text, form, omit_one):
    """Group maximal runs of equal adjacent elements of a string (or list) and report them in the given form."""
    if form not in ('char_count', 'count_char', 'pairs', 'run_count', 'longest'):
        raise ValueError('unknown form')
    runs = []
    prev = None
    count = 0
    for ch in text:
        if count and ch == prev:
            count += 1
        else:
            if count:
                runs.append((prev, count))
            prev = ch
            count = 1
    if count:
        runs.append((prev, count))
    if form == 'pairs':
        return [[ch, n] for ch, n in runs]
    if form == 'run_count':
        return len(runs)
    if form == 'longest':
        return max((n for _, n in runs), default=0)
    parts = []
    for ch, n in runs:
        num = '' if (omit_one and n == 1) else str(n)
        if form == 'char_count':
            parts.append(str(ch) + num)
        else:
            parts.append(num + str(ch))
    return ''.join(parts)
