"""Exact recipe comparison over the allowed rational simplex domain."""
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from models.outcome import Outcome
from models.rational import format_rational, parse_rational
from review.recipe_domain import RecipeDomain, parse_constraints
from review.recipe_pairing import RecipePair, validate_procedure


@dataclass(frozen=True)
class SideProfile:
    # Per-layer terminal outcomes aligned with the common sorted layer names.
    outcomes: tuple[Outcome, ...]
    passed: tuple[Fraction, ...]
    decided: tuple[Fraction, ...]

    def passed_mass(self, weights: Sequence[Fraction]) -> Fraction:
        return sum((weight * value for weight, value in zip(weights, self.passed)), Fraction())

    def decided_mass(self, weights: Sequence[Fraction]) -> Fraction:
        return sum((weight * value for weight, value in zip(weights, self.decided)), Fraction())

    def eligible_at(self, weights: Sequence[Fraction]) -> bool:
        return self.decided_mass(weights) > 0

    def rate_at(self, weights: Sequence[Fraction]) -> Fraction | None:
        denominator = self.decided_mass(weights)
        if denominator == 0:
            return None
        return self.passed_mass(weights) / denominator


def _profile(body, layer_names: Sequence[str], actions: Sequence[str]) -> SideProfile:
    outcomes = tuple(body.replay_layer(name, actions) for name in layer_names)
    return SideProfile(
        outcomes,
        tuple(outcome.passed for outcome in outcomes),
        tuple(outcome.decided_mass for outcome in outcomes),
    )


def parse_tolerance(tolerance: object) -> Fraction:
    value = parse_rational(tolerance)
    if value < 0:
        raise ValueError('tolerance must be nonnegative')
    return value


def _outer(left: Sequence[Fraction], right: Sequence[Fraction]) -> list[list[Fraction]]:
    return [[a * b for b in right] for a in left]


def _matrix_sum(*matrices: list[list[Fraction]]) -> list[list[Fraction]]:
    size = len(matrices[0])
    return [
        [sum((matrix[row][column] for matrix in matrices), Fraction()) for column in range(size)]
        for row in range(size)
    ]


def _matrix_difference(
    positive: list[list[Fraction]], negative: list[list[Fraction]],
) -> list[list[Fraction]]:
    size = len(positive)
    return [
        [positive[row][column] - negative[row][column] for column in range(size)]
        for row in range(size)
    ]


def _evaluate(matrix: Sequence[Sequence[Fraction]], point: Sequence[Fraction]) -> Fraction:
    return sum(
        (point[row] * matrix[row][column] * point[column]
         for row in range(len(point)) for column in range(len(point))),
        Fraction(),
    )


def _side_payload(profile: SideProfile, point: Sequence[Fraction]) -> dict:
    eligible = profile.eligible_at(point)
    rate = profile.rate_at(point)
    return {
        'eligible': eligible,
        'conditional_rate': None if rate is None else format_rational(rate),
    }


@dataclass(frozen=True)
class RecipeVerdict:
    decision: str
    witness: tuple[Fraction, ...] | None
    left: SideProfile
    right: SideProfile

    def retest_payload(self, layer_names: Sequence[str], actions: Sequence[str]) -> dict | None:
        if self.witness is None:
            return None
        point = self.witness
        return {
            'recipe': [
                {'layer': name, 'weight': format_rational(weight)}
                for name, weight in zip(layer_names, point)
            ],
            'actions': list(actions),
            'left': _side_payload(self.left, point),
            'right': _side_payload(self.right, point),
        }


def decide_recipe(
    pair: RecipePair, actions: object, constraints: object, tolerance: object,
) -> tuple[RecipeVerdict, RecipeDomain, tuple[Fraction, ...], tuple[str, ...]]:
    word = validate_procedure(pair.actions_catalog, actions)
    tolerance_value = parse_tolerance(tolerance)
    parsed_constraints = parse_constraints(pair.layer_names, constraints)
    domain = RecipeDomain(pair.layer_names, parsed_constraints)
    left = _profile(pair.left.body, pair.layer_names, word)
    right = _profile(pair.right.body, pair.layer_names, word)

    # Eligibility is linear; two closed sets agree everywhere iff they agree
    # at every vertex of the polytope.
    for point in domain.vertices:
        if left.eligible_at(point) != right.eligible_at(point):
            return RecipeVerdict('retest', point, left, right), domain, tolerance_value, word

    # On the jointly decidable region:
    # |P_l/D_l - P_r/D_r| <= t  <=>  +/- (P_l D_r - P_r D_l) - t D_l D_r <= 0.
    p_l_d_r = _outer(left.passed, right.decided)
    p_r_d_l = _outer(right.passed, left.decided)
    d_l_d_r = _outer(left.decided, right.decided)
    spread = _matrix_difference(p_l_d_r, p_r_d_l)
    upper = _matrix_sum(spread, [[-tolerance_value * value for value in row] for row in d_l_d_r])
    lower = _matrix_sum([[-value for value in row] for row in spread],
                        [[-tolerance_value * value for value in row] for row in d_l_d_r])
    # Each side of the absolute-value bound is a quadratic form; the extrema
    # of either form occur at a vertex or a stationary point of its own.
    candidates = tuple(set(domain.quadratic_candidates(upper))
                       | set(domain.quadratic_candidates(lower)))
    for point in candidates:
        # Points where a side is not eligible are harmless zeros; a strict
        # violation can only happen where both sides are decidable.
        if not left.eligible_at(point) or not right.eligible_at(point):
            continue
        if _evaluate(upper, point) > 0 or _evaluate(lower, point) > 0:
            return RecipeVerdict('retest', point, left, right), domain, tolerance_value, word
    return RecipeVerdict('reuse', None, left, right), domain, tolerance_value, word
