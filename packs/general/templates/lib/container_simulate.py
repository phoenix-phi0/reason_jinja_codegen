def container_simulate(kinds, values, discipline, output, empty):
    """Simulate a FIFO queue (discipline 'fifo') or LIFO stack (discipline 'lifo').

    kinds[i] is 1 for push (values[i] is pushed), 0 for pop, 2 for peek.
    A pop or peek on an empty container yields `empty` and counts as a miss.
    output: 'results' (list of values returned by pops and peeks), 'remaining'
    (contents, oldest first for fifo, bottom first for lifo), 'size' (number of
    remaining items) or 'empty_count' (number of misses).
    """
    if len(kinds) != len(values):
        raise ValueError('kinds and values must have the same length')
    if discipline not in ('fifo', 'lifo'):
        raise ValueError('unknown discipline')
    if output not in ('results', 'remaining', 'size', 'empty_count'):
        raise ValueError('unknown output')
    lifo = discipline == 'lifo'
    items = []
    head = 0
    out = []
    misses = 0
    for k, v in zip(kinds, values):
        if k == 1:
            items.append(v)
        elif k == 0 or k == 2:
            if len(items) - head == 0:
                out.append(empty)
                misses += 1
            elif k == 0:
                if lifo:
                    out.append(items.pop())
                else:
                    out.append(items[head])
                    head += 1
            else:
                out.append(items[-1] if lifo else items[head])
        else:
            raise ValueError('unknown operation kind')
    remaining = items[head:]
    if output == 'results':
        return out
    if output == 'remaining':
        return remaining
    if output == 'size':
        return len(remaining)
    return misses
