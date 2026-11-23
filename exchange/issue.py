from exchange.body import build_body, encode_body
from exchange.envelope import EvidenceEnvelope, seal_envelope
from exchange.layered_body import build_layered_body, encode_layered_body
from models.approval import get_approval
from runs.store import RunStore


def issue(store: RunStore, model_id: int) -> EvidenceEnvelope:
    model = get_approval(store, model_id)
    if hasattr(model, 'layers'):
        body = build_layered_body(model.layers, model.transitions, model.classes)
        return seal_envelope(
            model.machine_model, model.model_id, model.revision_id,
            encode_layered_body(body), version=2,
        )
    body = build_body(model.table, model.classes)
    return seal_envelope(model.machine_model, model.model_id, model.revision_id, encode_body(body))
