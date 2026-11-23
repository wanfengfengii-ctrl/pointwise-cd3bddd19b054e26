from collections.abc import Sequence
from dataclasses import dataclass

from exchange.envelope import canonical_json, read_json_object
from models.outcome import Outcome, classification_payload, summarize_outcome, validate_classification
from models.transition_table import ResponseTable, build_response_table, propagate_distribution


_FIELDS = {'initial', 'transitions', 'classification'}


@dataclass(frozen=True)
class EvidenceBody:
    table: ResponseTable
    classes: tuple[str, ...]

    def replay(self, actions: Sequence[str]) -> Outcome:
        distribution = propagate_distribution(self.table, actions)
        return summarize_outcome(distribution, self.classes)


def build_body(table: ResponseTable, classes: tuple[str, ...]) -> EvidenceBody:
    return EvidenceBody(table, classes)


def encode_body(body: EvidenceBody) -> str:
    positions = range(len(body.table.initial))
    return canonical_json({
        **body.table.as_payload(),
        'classification': classification_payload(positions, body.classes),
    })


def decode_body(encoded: str) -> EvidenceBody:
    payload = read_json_object(encoded, _FIELDS)
    initial = payload['initial']
    transitions = payload['transitions']
    if not isinstance(initial, list) or not isinstance(transitions, dict):
        raise ValueError('body requires an initial vector and action matrices')
    positions = range(len(initial))
    table = build_response_table(tuple(transitions), initial, transitions, len(positions))
    classes = validate_classification(positions, payload['classification'])
    return build_body(table, classes)
