from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

from models.rational import format_rational, parse_rational


Distribution = tuple[Fraction, ...]
Matrix = tuple[Distribution, ...]


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


@dataclass(frozen=True)
class ResponseTable:
    initial: Distribution
    by_action: tuple[tuple[str, Matrix], ...]

    @property
    def action_codes(self) -> tuple[str, ...]:
        return tuple(code for code, _ in self.by_action)

    def matrix_for(self, action: str) -> Matrix:
        for code, matrix in self.by_action:
            if action == code:
                return matrix
        raise ValueError(f'unknown action: {action!r}')

    def as_payload(self) -> dict:
        return {
            'initial': [format_rational(probability) for probability in self.initial],
            'transitions': {
                code: [[format_rational(probability) for probability in row] for row in matrix]
                for code, matrix in self.by_action
            },
        }


def validate_distribution(values: object, size: int, label: str = 'distribution') -> Distribution:
    if not _is_sequence(values) or len(values) != size:
        raise ValueError(f'{label} must have {size} entries')
    distribution = tuple(parse_rational(value) for value in values)
    if any(value < 0 for value in distribution) or sum(distribution) != 1:
        raise ValueError(f'{label} must contain nonnegative probabilities with mass one')
    return distribution


def validate_action_codes(action_codes: object) -> tuple[str, ...]:
    if not _is_sequence(action_codes) or not 2 <= len(action_codes) <= 3:
        raise ValueError('response table requires two or three distinct action codes')
    codes = tuple(action_codes)
    if any(not isinstance(code, str) or not code or code != code.strip() for code in codes):
        raise ValueError('response table requires nonempty trimmed action codes')
    if len(set(codes)) != len(codes):
        raise ValueError('response table requires distinct action codes')
    return codes


def build_transitions(
    action_codes: Sequence[str], transitions: object, state_count: int,
) -> tuple[tuple[str, Matrix], ...]:
    if type(state_count) is not int or not 1 <= state_count <= 6:
        raise ValueError('models require one to six states')
    codes = validate_action_codes(action_codes)
    if not isinstance(transitions, Mapping) or set(transitions) != set(codes):
        raise ValueError('transition actions must match the action catalog')
    tables = []
    for code in sorted(codes):
        matrix = transitions[code]
        if not _is_sequence(matrix) or len(matrix) != state_count:
            raise ValueError(f'action {code!r} must contain {state_count} rows')
        tables.append((code, tuple(
            validate_distribution(row, state_count, f'{code} row {position}')
            for position, row in enumerate(matrix)
        )))
    return tuple(tables)


def build_response_table(
    action_codes: Sequence[str], initial: object, transitions: object, state_count: int,
) -> ResponseTable:
    initial_distribution = validate_distribution(initial, state_count, 'initial distribution')
    return ResponseTable(initial_distribution, build_transitions(action_codes, transitions, state_count))


def advance_distribution(mass: Distribution, matrix: Matrix) -> Distribution:
    return tuple(
        sum((source * weight for source, weight in zip(mass, column) if source and weight), Fraction())
        for column in zip(*matrix)
    )


def propagate_distribution(table: ResponseTable, actions: Sequence[str]) -> Distribution:
    if not _is_sequence(actions):
        raise ValueError('a challenge procedure must be an ordered action sequence')
    mass = table.initial
    for action in actions:
        if not isinstance(action, str):
            raise ValueError(f'invalid action: {action!r}')
        mass = advance_distribution(mass, table.matrix_for(action))
    return mass
