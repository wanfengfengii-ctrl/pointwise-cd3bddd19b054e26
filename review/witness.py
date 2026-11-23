from collections.abc import Sequence
from dataclasses import dataclass

from models.outcome import Outcome
from review.conditional_rates import rates_differ
from review.pairing import EvidencePair


@dataclass(frozen=True)
class VerifiedWitness:
    actions: tuple[str, ...]
    left: Outcome
    right: Outcome


def verify_witness(pair: EvidencePair, actions: Sequence[str]) -> VerifiedWitness:
    if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes, bytearray)):
        raise ValueError('a witness must be an ordered action sequence')
    word = tuple(actions)
    left = pair.left.body.replay(word)
    right = pair.right.body.replay(word)
    if left.is_decidable == right.is_decidable and not rates_differ(left, right):
        raise ValueError('candidate procedure does not distinguish the evidence pair')
    return VerifiedWitness(word, left, right)
