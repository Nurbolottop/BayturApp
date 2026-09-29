def parse_version(v):
    parts = []
    for p in (v or '').split('+')[0].split('-')[0].split('.'):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_below(version, minimum):
    if not version:
        return False
    return parse_version(version) < parse_version(minimum)
