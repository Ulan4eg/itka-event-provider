import pytest

from src.events.seats import parse_seats_pattern, seat_exists


def test_parse_pattern():
    assert parse_seats_pattern("A1-1000,B1-2000") == [("A", 1, 1000), ("B", 1, 2000)]


def test_parse_invalid_pattern():
    with pytest.raises(ValueError):
        parse_seats_pattern("A1-10,oops")


@pytest.mark.parametrize(
    ("seat", "expected"),
    [
        ("A1", True),
        ("A10", True),
        ("A11", False),
        ("B5", True),
        ("B6", False),
        ("C1", False),
        ("A0", False),
        ("15", False),
    ],
)
def test_seat_exists(seat, expected):
    assert seat_exists("A1-10,B1-5", seat) is expected
