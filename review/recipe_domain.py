"""Rational recipe domain: the unit simplex intersected with closed linear constraints.

Every layer count is between one and three, so the feasible polytope is at most
two dimensional.  All arithmetic uses exact Fractions; vertices and stationary
candidate points are therefore rational witnesses that a receipt can recompute.
"""
from collections.abc import Mapping, Sequence
from fractions import Fraction

from models.rational import parse_rational


class EmptyDomain(ValueError):
    """Raised when the simplex and the constraints have no common point."""


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def parse_constraints(layer_names: Sequence[str], constraints: object) -> tuple[tuple[tuple[Fraction, ...], Fraction], ...]:
    if not _is_sequence(constraints):
        raise ValueError('constraints must be an ordered sequence of (coefficients, upper) pairs')
    index = {name: position for position, name in enumerate(layer_names)}
    normalized = []
    for position, entry in enumerate(constraints):
        if not _is_sequence(entry) or len(entry) != 2:
            raise ValueError(f'constraint {position} must be a (coefficients, upper) pair')
        coefficients, upper = entry
        if not isinstance(coefficients, Mapping):
            raise ValueError(f'constraint {position} coefficients must map layer names to rationals')
        vector = [Fraction()] * len(layer_names)
        for name, coefficient in coefficients.items():
            if type(name) is not str or name not in index:
                raise ValueError(f'constraint {position} references an unknown layer: {name!r}')
            vector[index[name]] = parse_rational(coefficient)
        normalized.append((tuple(vector), parse_rational(upper)))
    return tuple(normalized)


def _rref(matrix: list[list[Fraction]]) -> list[list[Fraction]]:
    rows = [row[:] for row in matrix]
    row_count = len(rows)
    column_count = len(rows[0]) if rows else 0
    pivot_row = 0
    for column in range(column_count):
        source = next((row for row in range(pivot_row, row_count) if rows[row][column] != 0), None)
        if source is None:
            continue
        rows[pivot_row], rows[source] = rows[source], rows[pivot_row]
        pivot = rows[pivot_row][column]
        rows[pivot_row] = [value / pivot for value in rows[pivot_row]]
        for row in range(row_count):
            if row != pivot_row and rows[row][column] != 0:
                factor = rows[row][column]
                rows[row] = [
                    value - factor * rows[pivot_row][target] for target, value in enumerate(rows[row])
                ]
        pivot_row += 1
    return rows


def _solve_unique(equations: Sequence[Sequence[Fraction]], unknowns: int) -> tuple[Fraction, ...] | None:
    """Solve A x = b given augmented rows; return the unique solution or None."""
    rows = _rref([list(row) for row in equations])
    rank = sum(1 for row in rows if any(value != 0 for value in row[:-1]))
    for row in rows:
        if all(value == 0 for value in row[:-1]) and row[-1] != 0:
            return None
    if rank != unknowns:
        return None
    solution = [Fraction()] * unknowns
    for row in rows:
        pivot = next(column for column, value in enumerate(row[:-1]) if value != 0)
        solution[pivot] = row[-1]
    return tuple(solution)


class RecipeDomain:
    """The polytope {w >= 0, sum(w) = 1, A_k . w <= upper_k} over Fractions."""

    def __init__(self, layer_names: Sequence[str], constraints: Sequence[tuple[tuple[Fraction, ...], Fraction]]):
        self.layer_names = tuple(layer_names)
        self.dimension = len(self.layer_names)
        self.constraints = constraints
        # Inequalities c . w <= d, starting with the nonnegativity faces.
        self.inequalities: list[tuple[tuple[Fraction, ...], Fraction]] = []
        for position in range(self.dimension):
            normal = [Fraction()] * self.dimension
            normal[position] = Fraction(-1)
            self.inequalities.append((tuple(normal), Fraction()))
        self.inequalities.extend(constraints)
        self.vertices = self._enumerate_vertices()
        if not self.vertices:
            raise EmptyDomain('the allowed recipe domain is empty')

    def _feasible(self, point: Sequence[Fraction]) -> bool:
        if len(point) != self.dimension or any(value < 0 for value in point):
            return False
        if sum(point) != 1:
            return False
        return all(
            sum(coef * value for coef, value in zip(normal, point)) <= bound
            for normal, bound in self.inequalities
        )

    def _enumerate_vertices(self) -> tuple[tuple[Fraction, ...], ...]:
        n = self.dimension
        equality = [tuple(Fraction(1) for _ in range(n)) + (Fraction(1),)]
        needed = n - 1  # independent active inequalities alongside sum(w) = 1
        points = set()
        if needed == 0:
            candidate = tuple(Fraction(1) for _ in range(n))
            if self._feasible(candidate):
                points.add(candidate)
            return tuple(sorted(points))
        from itertools import combinations
        for active in combinations(range(len(self.inequalities)), needed):
            equations = [list(row) for row in equality]
            for index in active:
                normal, bound = self.inequalities[index]
                equations.append(list(normal) + [bound])
            solution = _solve_unique(equations, n)
            if solution is not None and self._feasible(solution):
                points.add(solution)
        return tuple(sorted(points))

    def quadratic_candidates(
        self, matrix: Sequence[Sequence[Fraction]],
    ) -> tuple[tuple[Fraction, ...], ...]:
        """Vertices plus feasible stationary points of w^T M w on each face."""
        n = self.dimension
        candidates = set(self.vertices)
        symmetry = [
            [matrix[row][column] + matrix[column][row] if row != column else matrix[row][column]
             for column in range(n)]
            for row in range(n)
        ]
        # Interior stationarity: M w = lambda * 1 and sum(w) = 1.
        interior = []
        for row in range(n):
            interior.append(symmetry[row] + [Fraction(-1), Fraction()])
        interior.append([Fraction(1) for _ in range(n)] + [Fraction(), Fraction(1)])
        solution = _solve_unique(interior, n + 1)
        if solution is not None:
            point = solution[:n]
            if self._feasible(point):
                candidates.add(point)
        # One active inequality (a one-codimension face); higher-codimension
        # stationary points are vertices when the layer count is at most three.
        for normal, bound in self.inequalities:
            equations = []
            for row in range(n):
                line = symmetry[row] + [Fraction(-1), Fraction(-normal[row]), Fraction()]
                equations.append(line)
            equations.append([Fraction(1) for _ in range(n)] + [Fraction(), Fraction(), Fraction(1)])
            equations.append(list(normal) + [Fraction(), Fraction(), bound])
            solution = _solve_unique(equations, n + 2)
            if solution is not None:
                point = solution[:n]
                if self._feasible(point):
                    candidates.add(point)
        return tuple(sorted(candidates))
