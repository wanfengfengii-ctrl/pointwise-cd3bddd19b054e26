from exchange.body import build_body, encode_body
from exchange.envelope import EvidenceEnvelope, seal_envelope
from models.approval import get_approved_model
from runs.store import RunStore


def issue(store: RunStore, model_id: int) -> EvidenceEnvelope:
    model = get_approved_model(store, model_id)
    body = build_body(model.table, model.classes)
    return seal_envelope(model.machine_model, model.model_id, model.revision_id, encode_body(body))
