import sqlite3
from dataclasses import dataclass

from exchange.receipt import ReceivedEvidence, get_receipt


@dataclass(frozen=True)
class EvidencePair:
    left: ReceivedEvidence
    right: ReceivedEvidence
    actions: tuple[str, ...]

    @property
    def request(self) -> tuple[int, int]:
        return self.left.receipt_id, self.right.receipt_id


def resolve_pair(connection: sqlite3.Connection, left_receipt_id: int, right_receipt_id: int) -> EvidencePair:
    left = get_receipt(connection, left_receipt_id)
    right = get_receipt(connection, right_receipt_id)
    if left.envelope.version != 1 or right.envelope.version != 1:
        raise ValueError('the V1 comparison requires two version 1 evidence items')
    if left.envelope.machine_model != right.envelope.machine_model:
        raise ValueError('comparison requires the same machine model')
    actions = left.body.table.action_codes
    if actions != right.body.table.action_codes:
        raise ValueError('comparison requires identical public action codes')
    return EvidencePair(left, right, actions)
