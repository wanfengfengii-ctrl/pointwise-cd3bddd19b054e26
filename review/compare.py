import sqlite3
from dataclasses import dataclass

from archive.provenance import ReportParent
from archive.publish import publish_report
from archive.recipe_publish import publish_recipe_report
from models.rational import parse_rational
from review.conditional_rates import find_rate_witness
from review.eligibility import find_eligibility_witness
from review.instructions import RetestInstruction, build_retest_instruction
from review.pairing import EvidencePair, resolve_pair
from review.recipe_decision import decide_recipe
from review.recipe_pairing import resolve_recipe_pair
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


def compare_recipe_publish(
    connection: sqlite3.Connection, left_receipt_id: int, right_receipt_id: int,
    actions, constraints, tolerance,
) -> int:
    pair = resolve_recipe_pair(connection, left_receipt_id, right_receipt_id)
    verdict, _domain, tolerance_value, word = decide_recipe(pair, actions, constraints, tolerance)
    # Preserve the request exactly as submitted: original coefficient maps and order.
    request_constraints = tuple(
        (dict(coefficients), parse_rational(upper)) for coefficients, upper in constraints
    )
    return publish_recipe_report(
        connection,
        pair.left.envelope.machine_model,
        pair.request,
        word,
        request_constraints,
        tolerance_value,
        verdict.decision,
        verdict.retest_payload(pair.layer_names, word),
        _recipe_parents(pair),
    )


def _recipe_parents(pair) -> tuple[ReportParent, ReportParent]:
    left = pair.left.envelope
    right = pair.right.envelope
    return (
        ReportParent(0, pair.left.receipt_id, left.machine_model, left.model_id, left.revision_id, left.fingerprint),
        ReportParent(1, pair.right.receipt_id, right.machine_model, right.model_id, right.revision_id, right.fingerprint),
    )
