def run_length_decode(text, form):
    # Expand a run-length encoded string. form 'char_count' reads each run as the character
    # followed by its decimal count; 'count_char' reads the count first. A missing count means 1.
    # Run characters must not be digits. One pass, O(n + len(output)).
    if form not in ('char_count', 'count_char'):
        raise ValueError('unknown form')
    out = []
    n = len(text)
    i = 0
    if form == 'count_char':
        while i < n:
            j = i
            while j < n and '0' <= text[j] <= '9':
                j += 1
            if j >= n:
                raise ValueError('count without a character')
            count = int(text[i:j]) if j > i else 1
            out.append(text[j] * count)
            i = j + 1
    else:
        while i < n:
            ch = text[i]
            j = i + 1
            while j < n and '0' <= text[j] <= '9':
                j += 1
            count = int(text[i + 1:j]) if j > i + 1 else 1
            out.append(ch * count)
            i = j
    return ''.join(out)
