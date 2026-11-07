def case_convert(text, source, target):
    seps = {'snake': '_', 'kebab': '-', 'space': ' '}
    if source in seps:
        words = [w for w in text.split(seps[source]) if w]
    elif source in ('camel', 'pascal'):
        words = []
        start = 0
        for i in range(1, len(text)):
            if text[i].isupper():
                words.append(text[start:i])
                start = i
        if text:
            words.append(text[start:])
    else:
        raise ValueError('unknown source case: ' + str(source))
    words = [w.lower() for w in words]
    caps = [w[:1].upper() + w[1:] for w in words]
    if target == 'camel':
        return ''.join(words[:1] + caps[1:])
    if target == 'pascal':
        return ''.join(caps)
    if target == 'snake':
        return '_'.join(words)
    if target == 'kebab':
        return '-'.join(words)
    if target == 'constant':
        return '_'.join(w.upper() for w in words)
    if target == 'space':
        return ' '.join(words)
    if target == 'title':
        return ' '.join(caps)
    raise ValueError('unknown target case: ' + str(target))
