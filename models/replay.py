from collections.abc import Sequence

from models.approval import get_approved_model
from models.outcome import Outcome, summarize_outcome
from models.transition_table import propagate_distribution
from runs.store import RunStore


def replay(store: RunStore, model_id: int, actions: Sequence[str]) -> Outcome:
    model = get_approved_model(store, model_id)
    distribution = propagate_distribution(model.table, actions)
    return summarize_outcome(distribution, model.classes)
