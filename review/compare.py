import sqlite3
from dataclasses import dataclass

from archive.provenance import ReportParent
from archive.publish import publish_report
from review.conditional_rates import find_rate_witness
from review.eligibility import find_eligibility_witness
from review.instructions import RetestInstruction, build_retest_instruction
from review.pairing import EvidencePair, resolve_pair
from review.witness import verify_witness


@dataclass(frozen=True)
class Comparison:
    pair: EvidencePair
    retest: RetestInstruction | None

    @property
    def decision(self) -> str:
        return 'reuse' if self.retest is None else 'retest'


def _compare(pair: EvidencePair) -> Comparison:
    word = find_eligibility_witness(pair)
    if word is None:
        word = find_rate_witness(pair)
    if word is None:
        return Comparison(pair, None)
    return Comparison(pair, build_retest_instruction(verify_witness(pair, word)))


def _parents(pair: EvidencePair) -> tuple[ReportParent, ReportParent]:
    left = pair.left.envelope
    right = pair.right.envelope
    return (
        ReportParent(0, pair.left.receipt_id, left.machine_model, left.model_id, left.revision_id, left.fingerprint),
        ReportParent(1, pair.right.receipt_id, right.machine_model, right.model_id, right.revision_id, right.fingerprint),
    )


def compare_publish(connection: sqlite3.Connection, left_receipt_id: int, right_receipt_id: int) -> int:
    pair = resolve_pair(connection, left_receipt_id, right_receipt_id)
    comparison = _compare(pair)
    return publish_report(
        connection, pair.left.envelope.machine_model, pair.request, comparison.decision,
        None if comparison.retest is None else comparison.retest.as_dict(), _parents(pair),
    )
