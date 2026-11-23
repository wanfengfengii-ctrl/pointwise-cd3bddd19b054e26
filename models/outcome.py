from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction


CATEGORIES = ('pass', 'fail', 'pending')


@dataclass(frozen=True)
class Outcome:
    passed: Fraction
    failed: Fraction
    pending: Fraction

    @property
    def decided_mass(self) -> Fraction:
        return self.passed + self.failed

    @property
    def is_decidable(self) -> bool:
        return self.decided_mass > 0

    @property
    def conditional_rate(self) -> Fraction | None:
        if self.is_decidable:
            return self.passed / self.decided_mass
        return None


def validate_classification(states: Sequence[str] | Sequence[int], groups: object) -> tuple[str, ...]:
    if not isinstance(groups, Mapping) or set(groups) != set(CATEGORIES):
        raise ValueError('classification requires pass, fail and pending groups')
    if not states:
        raise ValueError('classification requires a nonempty state order')
    state_type = type(states[0])
    known = set(states)
    assigned = {}
    for category in CATEGORIES:
        members = groups[category]
        if not isinstance(members, Sequence) or isinstance(members, (str, bytes, bytearray)):
            raise ValueError(f'class {category!r} must be a sequence of states')
        for member in members:
            if type(member) is not state_type or member not in known:
                raise ValueError(f'unknown state in class {category!r}: {member!r}')
            if member in assigned:
                raise ValueError(f'state classified more than once: {member!r}')
            assigned[member] = category
    if set(assigned) != known:
        raise ValueError('classification must cover every state')
    return tuple(assigned[state] for state in states)


def classification_payload(states: Sequence, classes: Sequence[str]) -> dict[str, list]:
    groups = {category: [] for category in CATEGORIES}
    for state, category in zip(states, classes, strict=True):
        groups[category].append(state)
    return groups


def summarize_outcome(distribution: Sequence[Fraction], classes: Sequence[str]) -> Outcome:
    mass = dict.fromkeys(CATEGORIES, Fraction())
    for probability, category in zip(distribution, classes, strict=True):
        mass[category] += probability
    return Outcome(mass['pass'], mass['fail'], mass['pending'])
