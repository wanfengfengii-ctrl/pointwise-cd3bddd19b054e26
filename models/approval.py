import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from models.outcome import Outcome, classification_payload, summarize_outcome, validate_classification
from models.transition_table import (
    ResponseTable,
    build_response_table,
    build_transitions,
    propagate_distribution,
    validate_distribution,
)
from runs.store import RunStore


@dataclass(frozen=True)
class ApprovedModel:
    model_id: int
    revision_id: int
    machine_model: str
    state_ids: tuple[str, ...]
    table: ResponseTable
    classes: tuple[str, ...]


@dataclass(frozen=True)
class ApprovedLayeredModel:
    model_id: int
    revision_id: int
    machine_model: str
    state_ids: tuple[str, ...]
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


def initialize_models(connection: sqlite3.Connection) -> None:
    connection.execute('PRAGMA foreign_keys = ON')
    connection.execute(
        '''CREATE TABLE IF NOT EXISTS approved_models (
            model_id INTEGER PRIMARY KEY,
            revision_id INTEGER NOT NULL REFERENCES run_revisions(revision_id),
            snapshot_json TEXT NOT NULL
        )'''
    )


def _validate_state_ids(state_ids: object) -> tuple[str, ...]:
    if (not isinstance(state_ids, Sequence) or isinstance(state_ids, (str, bytes, bytearray))
            or not 1 <= len(state_ids) <= 6):
        raise ValueError('provide one to six private state identifiers')
    states = tuple(state_ids)
    if any(type(state) is not str or not state.strip() for state in states) or len(set(states)) != len(states):
        raise ValueError('private state identifiers must be distinct nonempty strings')
    return states


def approve_model(
    store: RunStore, revision_id: int, state_ids: Sequence[str],
    initial: object, transitions: object, classification: object,
) -> int:
    source = store.load_revision(revision_id)
    states = _validate_state_ids(state_ids)
    table = build_response_table(source.catalog.codes, initial, transitions, len(states))
    classes = validate_classification(states, classification)
    payload = {
        'kind': 'model',
        'states': states,
        'classification': classification_payload(states, classes),
        **table.as_payload(),
    }
    if store.connection.in_transaction:
        raise ValueError('model approval requires an idle connection')
    with store.connection:
        cursor = store.connection.execute(
            'INSERT INTO approved_models (revision_id, snapshot_json) VALUES (?, ?)',
            (revision_id, json.dumps(payload, sort_keys=True, separators=(',', ':'))),
        )
    return cursor.lastrowid


def _validate_layers(layers: object, state_count: int) -> tuple[tuple[str, tuple], ...]:
    if not isinstance(layers, Mapping) or not 1 <= len(layers) <= 3:
        raise ValueError('provide one to three named initial layers')
    normalized = []
    seen = set()
    for name, initial in layers.items():
        if type(name) is not str or not name or name != name.strip():
            raise ValueError('layer names must be nonempty trimmed strings')
        if name in seen:
            raise ValueError(f'duplicate layer name: {name!r}')
        seen.add(name)
        normalized.append((name, validate_distribution(initial, state_count, f'layer {name!r}')))
    return tuple(sorted(normalized))


def approve_layered_model(
    store: RunStore, revision_id: int, state_ids: Sequence[str],
    layers: Mapping[str, object], transitions: object, classification: object,
) -> int:
    source = store.load_revision(revision_id)
    states = _validate_state_ids(state_ids)
    state_count = len(states)
    normalized_layers = _validate_layers(layers, state_count)
    tables = build_transitions(source.catalog.codes, transitions, state_count)
    classes = validate_classification(states, classification)
    payload = {
        'kind': 'layered',
        'states': states,
        'layers': {
            name: [str(probability) for probability in initial]
            for name, initial in normalized_layers
        },
        'transitions': {
            code: [[str(probability) for probability in row] for row in matrix]
            for code, matrix in tables
        },
        'classification': classification_payload(states, classes),
    }
    if store.connection.in_transaction:
        raise ValueError('model approval requires an idle connection')
    with store.connection:
        cursor = store.connection.execute(
            'INSERT INTO approved_models (revision_id, snapshot_json) VALUES (?, ?)',
            (revision_id, json.dumps(payload, sort_keys=True, separators=(',', ':'))),
        )
    return cursor.lastrowid


def _load_snapshot(store: RunStore, model_id: int) -> tuple[int, str, str, dict]:
    if type(model_id) is not int or not 1 <= model_id < 2**63:
        raise ValueError('model ID must be a positive SQLite integer')
    row = store.connection.execute(
        '''SELECT approved_models.revision_id, run_revisions.machine_model,
                  run_revisions.catalog_json, approved_models.snapshot_json
           FROM approved_models JOIN run_revisions USING (revision_id)
           WHERE approved_models.model_id = ?''',
        (model_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f'unknown approved model: {model_id}')
    return row


def get_approved_model(store: RunStore, model_id: int) -> ApprovedModel:
    revision_id, machine_model, catalog_json, snapshot_json = _load_snapshot(store, model_id)
    payload = json.loads(snapshot_json)
    if payload.get('kind') == 'layered':
        raise ValueError(f'approval {model_id} is a layered model; use get_approved_layered_model')
    states = tuple(payload['states'])
    table = build_response_table(
        tuple(json.loads(catalog_json)), payload['initial'], payload['transitions'], len(states),
    )
    classes = validate_classification(states, payload['classification'])
    return ApprovedModel(model_id, revision_id, machine_model, states, table, classes)


def get_approved_layered_model(store: RunStore, model_id: int) -> ApprovedLayeredModel:
    revision_id, machine_model, catalog_json, snapshot_json = _load_snapshot(store, model_id)
    payload = json.loads(snapshot_json)
    if payload.get('kind') != 'layered':
        raise ValueError(f'approval {model_id} is not a layered model')
    states = tuple(payload['states'])
    state_count = len(states)
    catalog_codes = tuple(json.loads(catalog_json))
    normalized_layers = _validate_layers(payload['layers'], state_count)
    tables = build_transitions(catalog_codes, payload['transitions'], state_count)
    classes = validate_classification(states, payload['classification'])
    return ApprovedLayeredModel(
        model_id, revision_id, machine_model, states, normalized_layers, tables, classes,
    )


def get_approval(store: RunStore, model_id: int):
    """Return either an ApprovedModel or an ApprovedLayeredModel for the approval ID."""
    _, _, _, snapshot_json = _load_snapshot(store, model_id)
    payload = json.loads(snapshot_json)
    if payload.get('kind') == 'layered':
        return get_approved_layered_model(store, model_id)
    return get_approved_model(store, model_id)
