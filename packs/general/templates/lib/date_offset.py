def date_offset(y, m, d, oy, om, od, form):
    """Calendar arithmetic in the proleptic Gregorian calendar (valid dates assumed).

    form 'days': signed days from (oy, om, od) to (y, m, d); 'abs_days': its absolute value;
    'weekday': day of the week of (y, m, d), Monday = 0 .. Sunday = 6; 'day_of_year': 1-based.
    Constant time.
    """
    def days_from_civil(yy, mm, dd):
        # days since 1970-01-01
        if mm <= 2:
            yy -= 1
        era = yy // 400
        yoe = yy - era * 400
        doy = (153 * (mm + (-3 if mm > 2 else 9)) + 2) // 5 + dd - 1
        doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
        return era * 146097 + doe - 719468

    days = days_from_civil(y, m, d)
    if form == 'days':
        return days - days_from_civil(oy, om, od)
    if form == 'abs_days':
        return abs(days - days_from_civil(oy, om, od))
    if form == 'weekday':
        return (days + 3) % 7
    if form == 'day_of_year':
        return days - days_from_civil(y, 1, 1) + 1
    raise ValueError('unknown form')
