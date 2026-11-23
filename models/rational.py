import re
from fractions import Fraction


_RATIONAL = re.compile(r'[+-]?[0-9]+(?:/[0-9]+)?')


def parse_rational(value: object) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if type(value) is int:
        return Fraction(value)
    if isinstance(value, str) and _RATIONAL.fullmatch(value):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as error:
            raise ValueError(f'invalid rational: {value!r}') from error
    raise ValueError(f'expected an integer or a fraction, got {value!r}')


def format_rational(value: Fraction) -> str:
    return str(value)
