from collections.abc import Mapping, Sequence

from runs.action_catalog import validate_catalog
from runs.observations import normalize_observations
from runs.revisions import validate_predecessor
from runs.store import RunStore


def record_run(
    store: RunStore, machine_model: str, catalog: Mapping[str, str],
    observations: Sequence[Mapping[str, object]], predecessor_id: int | None = None,
) -> int:
    if not isinstance(machine_model, str) or not machine_model or machine_model != machine_model.strip():
        raise ValueError('machine model must be a nonempty trimmed string')
    actions = validate_catalog(catalog)
    rows = normalize_observations(actions, observations)
    predecessor = None
    if predecessor_id is not None:
        try:
            predecessor = store.load_revision(predecessor_id)
        except LookupError as error:
            raise ValueError(f'unknown predecessor revision: {predecessor_id}') from error
    validate_predecessor(machine_model, predecessor_id, predecessor)
    return store.save_revision(machine_model, actions, rows, predecessor_id)
