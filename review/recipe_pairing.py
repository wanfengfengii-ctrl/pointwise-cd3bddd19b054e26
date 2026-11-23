import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from exchange.layered_body import LayeredEvidenceBody
from exchange.receipt import ReceivedEvidence, get_receipt


@dataclass(frozen=True)
class RecipePair:
    left: ReceivedEvidence
    right: ReceivedEvidence
    layer_names: tuple[str, ...]
    actions_catalog: tuple[str, ...]

    @property
    def request(self) -> tuple[int, int]:
        return self.left.receipt_id, self.right.receipt_id


def _layered(receipt: ReceivedEvidence, position: str) -> LayeredEvidenceBody:
    if receipt.envelope.version != 2 or not isinstance(receipt.body, LayeredEvidenceBody):
        raise ValueError(f'{position} receipt must be a version 2 layered evidence item')
    return receipt.body


def resolve_recipe_pair(
    connection: sqlite3.Connection, left_receipt_id: int, right_receipt_id: int,
) -> RecipePair:
    left = get_receipt(connection, left_receipt_id)
    right = get_receipt(connection, right_receipt_id)
    left_body = _layered(left, 'left')
    right_body = _layered(right, 'right')
    if left.envelope.machine_model != right.envelope.machine_model:
        raise ValueError('recipe comparison requires the same machine model')
    left_codes = tuple(code for code, _ in left_body.transitions)
    right_codes = tuple(code for code, _ in right_body.transitions)
    if left_codes != right_codes:
        raise ValueError('recipe comparison requires identical public action codes')
    left_names = set(left_body.layer_names)
    right_names = set(right_body.layer_names)
    if left_names != right_names:
        raise ValueError('recipe comparison requires the same layer name set')
    return RecipePair(left, right, tuple(sorted(left_names)), left_codes)


def validate_procedure(action_catalog: Sequence[str], actions: object) -> tuple[str, ...]:
    if (not isinstance(actions, Sequence) or isinstance(actions, (str, bytes, bytearray))):
        raise ValueError('a challenge procedure must be an ordered action sequence')
    word = tuple(actions)
    known = set(action_catalog)
    for action in word:
        if type(action) is not str or action not in known:
            raise ValueError(f'unknown action: {action!r}')
    return word
