def matrix_reorient(mat, form):
    """Reorient a rectangular matrix (list of equal-length sequences); returns a new list of lists.

    form: transpose, rotate_cw, rotate_ccw, rotate_180, flip_horizontal (reverse each row),
    flip_vertical (reverse the order of the rows), anti_transpose. O(rows * cols).
    """
    if form == 'transpose':
        return [list(col) for col in zip(*mat)]
    if form == 'rotate_cw':
        return [list(col) for col in zip(*mat[::-1])]
    if form == 'rotate_ccw':
        return [list(col) for col in zip(*mat)][::-1]
    if form == 'rotate_180':
        return [list(row)[::-1] for row in mat[::-1]]
    if form == 'flip_horizontal':
        return [list(row)[::-1] for row in mat]
    if form == 'flip_vertical':
        return [list(row) for row in mat[::-1]]
    if form == 'anti_transpose':
        return [list(col)[::-1] for col in zip(*mat)][::-1]
    raise ValueError('unknown form: ' + str(form))
