import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from runs.action_catalog import ActionCatalog


@dataclass(frozen=True)
class Observation:
    action: str
    record_json: str

    def as_record(self) -> dict:
        return json.loads(self.record_json)


def normalize_observations(
    catalog: ActionCatalog, rows: Sequence[Mapping[str, object]],
) -> tuple[Observation, ...]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ValueError('observations must be an ordered sequence of records')
    observations = []
    for position, row in enumerate(rows):
        if not isinstance(row, Mapping) or any(not isinstance(key, str) for key in row):
            raise ValueError(f'observation {position} must be a JSON object')
        action = catalog.require_code(row.get('action'))
        try:
            record = json.dumps(dict(row), allow_nan=False, sort_keys=True, separators=(',', ':'))
        except (TypeError, ValueError, RecursionError) as error:
            raise ValueError(f'observation {position} is not JSON data') from error
        observations.append(Observation(action, record))
    return tuple(observations)
