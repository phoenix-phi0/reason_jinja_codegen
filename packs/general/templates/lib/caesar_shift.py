def caesar_shift(text, amount, kind, backward):
    spans = {'lower': [('a', 26)], 'upper': [('A', 26)], 'alpha': [('a', 26), ('A', 26)], 'digit': [('0', 10)]}[kind]
    if backward:
        amount = -amount
    table = {}
    for start, size in spans:
        base = ord(start)
        for i in range(size):
            table[base + i] = chr(base + (i + amount) % size)
    return text.translate(table)
