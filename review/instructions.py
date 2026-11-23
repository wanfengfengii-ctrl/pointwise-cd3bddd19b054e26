from dataclasses import dataclass
from fractions import Fraction

from models.rational import format_rational
from review.witness import VerifiedWitness


@dataclass(frozen=True)
class RetestInstruction:
    actions: tuple[str, ...]
    left_eligible: bool
    left_rate: Fraction | None
    right_eligible: bool
    right_rate: Fraction | None

    def as_dict(self) -> dict:
        return {
            'actions': list(self.actions),
            'left': {
                'eligible': self.left_eligible,
                'conditional_rate': None if self.left_rate is None else format_rational(self.left_rate),
            },
            'right': {
                'eligible': self.right_eligible,
                'conditional_rate': None if self.right_rate is None else format_rational(self.right_rate),
            },
        }


def build_retest_instruction(witness: VerifiedWitness) -> RetestInstruction:
    left, right = witness.left, witness.right
    return RetestInstruction(
        witness.actions, left.is_decidable, left.conditional_rate,
        right.is_decidable, right.conditional_rate,
    )
