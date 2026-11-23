from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from exchange.envelope import canonical_json, read_json_object
from models.outcome import Outcome, classification_payload, summarize_outcome, validate_classification
from models.transition_table import (
    ResponseTable,
    build_transitions,
    propagate_distribution,
    validate_distribution,
)


_FIELDS = {'layers', 'transitions', 'classification'}


@dataclass(frozen=True)
class LayeredEvidenceBody:
    layers: tuple[tuple[str, tuple], ...]
    transitions: tuple[tuple[str, tuple], ...]
    classes: tuple[str, ...]

    @property
    def layer_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.layers)

    def initial_for(self, layer_name: str) -> tuple:
        for name, initial in self.layers:
            if name == layer_name:
                return initial
        raise ValueError(f'unknown layer: {layer_name!r}')

    def replay_layer(self, layer_name: str, actions: Sequence[str]) -> Outcome:
        table = ResponseTable(self.initial_for(layer_name), self.transitions)
        distribution = propagate_distribution(table, actions)
        return summarize_outcome(distribution, self.classes)


def build_layered_body(
    layers: Sequence[tuple[str, tuple]], transitions: tuple, classes: tuple[str, ...],
) -> LayeredEvidenceBody:
    return LayeredEvidenceBody(tuple(sorted(layers)), transitions, classes)


def encode_layered_body(body: LayeredEvidenceBody) -> str:
    state_count = len(body.layers[0][1])
    positions = range(state_count)
    return canonical_json({
        'layers': {
            name: [str(probability) for probability in initial]
            for name, initial in body.layers
        },
        'transitions': {
            code: [[str(probability) for probability in row] for row in matrix]
            for code, matrix in body.transitions
        },
        'classification': classification_payload(positions, body.classes),
    })


def _validate_layer_payload(layers: object, state_count: int) -> tuple[tuple[str, tuple], ...]:
    if not isinstance(layers, Mapping) or not 1 <= len(layers) <= 3:
        raise ValueError('body requires one to three named layers')
    normalized = []
    seen = set()
    for name, initial in layers.items():
        if type(name) is not str or not name or name != name.strip() or name in seen:
            raise ValueError('layer names must be distinct nonempty trimmed strings')
        seen.add(name)
        normalized.append((name, validate_distribution(initial, state_count, f'layer {name!r}')))
    return tuple(sorted(normalized))


def decode_layered_body(encoded: str) -> LayeredEvidenceBody:
    payload = read_json_object(encoded, _FIELDS)
    layers, transitions = payload['layers'], payload['transitions']
    if not isinstance(layers, Mapping) or not isinstance(transitions, Mapping):
        raise ValueError('layered body requires layer vectors and action matrices')
    state_count = len(next(iter(layers.values()))) if layers else 0
    normalized_layers = _validate_layer_payload(layers, state_count)
    tables = build_transitions(tuple(transitions), transitions, state_count)
    classes = validate_classification(range(state_count), payload['classification'])
    return build_layered_body(normalized_layers, tables, classes)
