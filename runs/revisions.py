from dataclasses import dataclass

from runs.action_catalog import ActionCatalog
from runs.observations import Observation


@dataclass(frozen=True)
class RunRevision:
    revision_id: int
    machine_model: str
    catalog: ActionCatalog
    observations: tuple[Observation, ...]
    predecessor_id: int | None


def validate_predecessor(
    machine_model: str, predecessor_id: int | None, predecessor: RunRevision | None,
) -> None:
    if predecessor_id is None:
        return
    if predecessor is None or predecessor.revision_id != predecessor_id:
        raise ValueError(f'unknown predecessor revision: {predecessor_id!r}')
    if predecessor.machine_model != machine_model:
        raise ValueError('predecessor belongs to a different machine model')
