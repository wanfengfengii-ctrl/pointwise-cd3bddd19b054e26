import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from models.outcome import classification_payload, validate_classification
from models.transition_table import ResponseTable, build_response_table
from runs.store import RunStore


@dataclass(frozen=True)
class ApprovedModel:
    model_id: int
    revision_id: int
    machine_model: str
    state_ids: tuple[str, ...]
    table: ResponseTable
    classes: tuple[str, ...]


def initialize_models(connection: sqlite3.Connection) -> None:
    connection.execute('PRAGMA foreign_keys = ON')
    connection.execute(
        '''CREATE TABLE IF NOT EXISTS approved_models (
            model_id INTEGER PRIMARY KEY,
            revision_id INTEGER NOT NULL REFERENCES run_revisions(revision_id),
            snapshot_json TEXT NOT NULL
        )'''
    )


def approve_model(
    store: RunStore, revision_id: int, state_ids: Sequence[str],
    initial: object, transitions: object, classification: object,
) -> int:
    source = store.load_revision(revision_id)
    if (not isinstance(state_ids, Sequence) or isinstance(state_ids, (str, bytes, bytearray))
            or not 1 <= len(state_ids) <= 6):
        raise ValueError('provide one to six private state identifiers')
    states = tuple(state_ids)
    if any(type(state) is not str or not state.strip() for state in states) or len(set(states)) != len(states):
        raise ValueError('private state identifiers must be distinct nonempty strings')
    table = build_response_table(source.catalog.codes, initial, transitions, len(states))
    classes = validate_classification(states, classification)
    payload = {
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


def get_approved_model(store: RunStore, model_id: int) -> ApprovedModel:
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
    revision_id, machine_model, catalog_json, snapshot_json = row
    payload = json.loads(snapshot_json)
    states = tuple(payload['states'])
    table = build_response_table(
        tuple(json.loads(catalog_json)), payload['initial'], payload['transitions'], len(states),
    )
    classes = validate_classification(states, payload['classification'])
    return ApprovedModel(model_id, revision_id, machine_model, states, table, classes)
