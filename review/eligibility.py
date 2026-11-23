from collections import deque

from models.transition_table import Distribution, ResponseTable
from review.pairing import EvidencePair


def _support(row: Distribution) -> int:
    return sum(1 << position for position, value in enumerate(row) if value > 0)


def _decidable_states(classes: tuple[str, ...]) -> int:
    return sum(1 << position for position, category in enumerate(classes) if category in ('pass', 'fail'))


def _successors(table: ResponseTable) -> dict[str, tuple[int, ...]]:
    return {action: tuple(_support(row) for row in matrix) for action, matrix in table.by_action}


def _advance(support: int, successors: tuple[int, ...]) -> int:
    result = 0
    for position, reachable in enumerate(successors):
        if support & (1 << position):
            result |= reachable
    return result


def find_eligibility_witness(pair: EvidencePair) -> tuple[str, ...] | None:
    left, right = pair.left.body, pair.right.body
    left_decides = _decidable_states(left.classes)
    right_decides = _decidable_states(right.classes)
    left_steps, right_steps = _successors(left.table), _successors(right.table)
    initial = (_support(left.table.initial), _support(right.table.initial))
    queue = deque([initial])
    previous = {initial: None}

    # With nonnegative mass, support propagates by union of positive edges.
    # Revisiting the same pair of supports cannot reveal a new continuation.
    while queue:
        current = queue.popleft()
        left_support, right_support = current
        if bool(left_support & left_decides) != bool(right_support & right_decides):
            actions = []
            while previous[current] is not None:
                current, action = previous[current]
                actions.append(action)
            return tuple(reversed(actions))
        for action in pair.actions:
            following = (
                _advance(left_support, left_steps[action]),
                _advance(right_support, right_steps[action]),
            )
            if following not in previous:
                previous[following] = (current, action)
                queue.append(following)
    return None
