from collections import deque
from fractions import Fraction

from models.outcome import Outcome, summarize_outcome
from models.transition_table import Distribution, advance_distribution
from review.pairing import EvidencePair


def _comparison_mass(outcome: Outcome) -> Fraction:
    return outcome.decided_mass


def rates_differ(left: Outcome, right: Outcome) -> bool:
    return left.passed * _comparison_mass(right) != _comparison_mass(left) * right.passed


class _Basis:
    def __init__(self):
        self.rows: dict[int, list[Fraction]] = {}

    def admit(self, vector: list[Fraction]) -> bool:
        # Keep the first nonzero coordinate of each stored row normalized to one.
        for column, _ in enumerate(vector):
            coefficient = vector[column]
            if not coefficient:
                continue
            pivot = self.rows.get(column)
            if pivot is None:
                self.rows[column] = [value / coefficient for value in vector]
                return True
            for position in range(column, len(vector)):
                vector[position] -= coefficient * pivot[position]
        return False


def _joint_vector(left: Distribution, right: Distribution) -> list[Fraction]:
    return [left_mass * right_mass for left_mass in left for right_mass in right]


def find_rate_witness(pair: EvidencePair) -> tuple[str, ...] | None:
    left, right = pair.left.body, pair.right.body
    queue = deque([((), left.table.initial, right.table.initial)])
    basis = _Basis()
    left_steps = dict(left.table.by_action)
    right_steps = dict(right.table.by_action)

    # The cross product of the two output masses is linear on the joint vector.
    # An action maps each joint vector linearly via that action's two matrices.
    # Keep the actual reaching word and marginals for each independent vector.
    while queue:
        word, left_mass, right_mass = queue.popleft()
        if not basis.admit(_joint_vector(left_mass, right_mass)):
            continue
        left_outcome = summarize_outcome(left_mass, left.classes)
        right_outcome = summarize_outcome(right_mass, right.classes)
        if rates_differ(left_outcome, right_outcome):
            return word
        for action in pair.actions:
            queue.append((
                word + (action,),
                advance_distribution(left_mass, left_steps[action]),
                advance_distribution(right_mass, right_steps[action]),
            ))
    return None
