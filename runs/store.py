import json
import sqlite3

from runs.action_catalog import ActionCatalog, validate_catalog
from runs.observations import Observation
from runs.revisions import RunRevision


class RunStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        self.connection.execute('PRAGMA foreign_keys = ON')
        with self.connection:
            self.connection.execute(
                '''CREATE TABLE IF NOT EXISTS run_revisions (
                    revision_id INTEGER PRIMARY KEY,
                    machine_model TEXT NOT NULL,
                    catalog_json TEXT NOT NULL,
                    predecessor_id INTEGER REFERENCES run_revisions(revision_id)
                )'''
            )
            self.connection.execute(
                '''CREATE TABLE IF NOT EXISTS run_observations (
                    revision_id INTEGER NOT NULL REFERENCES run_revisions(revision_id),
                    position INTEGER NOT NULL CHECK (position >= 0),
                    action TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    PRIMARY KEY (revision_id, position)
                )'''
            )

    def save_revision(
        self, machine_model: str, catalog: ActionCatalog,
        observations: tuple[Observation, ...], predecessor_id: int | None,
    ) -> int:
        if self.connection.in_transaction:
            raise ValueError('revision registration requires an idle connection')
        catalog_json = json.dumps(dict(catalog.entries), sort_keys=True, separators=(',', ':'))
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            cursor = self.connection.execute(
                '''INSERT INTO run_revisions (machine_model, catalog_json, predecessor_id)
                   VALUES (?, ?, ?)''',
                (machine_model, catalog_json, predecessor_id),
            )
            revision_id = cursor.lastrowid
            self.connection.executemany(
                '''INSERT INTO run_observations (revision_id, position, action, record_json)
                   VALUES (?, ?, ?, ?)''',
                ((revision_id, position, row.action, row.record_json)
                 for position, row in enumerate(observations)),
            )
        return revision_id

    def load_revision(self, revision_id: int) -> RunRevision:
        if type(revision_id) is not int or not 1 <= revision_id < 2**63:
            raise ValueError('revision ID must be a positive SQLite integer')
        row = self.connection.execute(
            'SELECT machine_model, catalog_json, predecessor_id FROM run_revisions WHERE revision_id = ?',
            (revision_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown run revision: {revision_id}')
        machine_model, catalog_json, predecessor_id = row
        observations = self.connection.execute(
            '''SELECT action, record_json FROM run_observations
               WHERE revision_id = ? ORDER BY position''',
            (revision_id,),
        )
        return RunRevision(
            revision_id, machine_model, validate_catalog(json.loads(catalog_json)),
            tuple(Observation(action, record) for action, record in observations), predecessor_id,
        )
