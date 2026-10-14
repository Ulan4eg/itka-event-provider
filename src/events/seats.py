"""Helpers for the seats pattern format, e.g. ``A1-1000,B1-2000``."""

import re

_PATTERN_PART = re.compile(r"^([A-Za-z])(\d+)-(\d+)$")
_SEAT = re.compile(r"^([A-Za-z])(\d+)$")


def parse_seats_pattern(pattern):
    """Return a list of ``(section, first, last)`` tuples."""
    ranges = []
    for part in pattern.split(","):
        match = _PATTERN_PART.match(part.strip())
        if match is None:
            raise ValueError(f"Invalid seats pattern part: {part!r}")
        section, first, last = match.groups()
        ranges.append((section.upper(), int(first), int(last)))
    return ranges


def seat_exists(pattern, seat):
    """Check that the seat id (e.g. ``A15``) exists according to the pattern.

    Raises ValueError if the pattern itself cannot be parsed.
    """
    ranges = parse_seats_pattern(pattern)
    match = _SEAT.match(seat)
    if match is None:
        return False
    section, number = match.group(1).upper(), int(match.group(2))
    return any(
        name == section and first <= number <= last for name, first, last in ranges
    )
