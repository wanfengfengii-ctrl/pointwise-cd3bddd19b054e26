import json
import sqlite3
from dataclasses import dataclass

from archive.provenance import ReportParent, initialize_provenance, insert_report_parents


@dataclass(frozen=True)
class PublishedReport:
    report_id: int
    machine_model: str
    request: tuple[int, int]
    decision: str
    retest: dict | None
    parents: tuple[ReportParent, ReportParent]

    def as_dict(self) -> dict:
        return {
            'report_id': self.report_id,
            'machine_model': self.machine_model,
            'request': {'left_receipt_id': self.request[0], 'right_receipt_id': self.request[1]},
            'decision': self.decision,
            'retest': self.retest,
            'parents': [parent.as_dict() for parent in self.parents],
        }


def initialize_archive(connection: sqlite3.Connection) -> None:
    connection.execute('PRAGMA foreign_keys = ON')
    with connection:
        connection.execute(
            '''CREATE TABLE IF NOT EXISTS report_identifiers (
                report_id INTEGER PRIMARY KEY AUTOINCREMENT
            )'''
        )
        connection.execute(
            '''CREATE TABLE IF NOT EXISTS reports (
                report_id INTEGER PRIMARY KEY REFERENCES report_identifiers(report_id),
                machine_model TEXT NOT NULL,
                left_receipt_id INTEGER NOT NULL REFERENCES received_evidence(receipt_id),
                right_receipt_id INTEGER NOT NULL REFERENCES received_evidence(receipt_id),
                decision TEXT NOT NULL CHECK (decision IN ('reuse', 'retest')),
                retest_json TEXT,
                CHECK ((decision = 'retest') = (retest_json IS NOT NULL))
            )'''
        )
        initialize_provenance(connection)
        connection.execute(
            '''CREATE TABLE IF NOT EXISTS publication_receipts (
                report_id INTEGER PRIMARY KEY REFERENCES reports(report_id)
            )'''
        )
    from archive.recipe_publish import initialize_recipe_archive
    initialize_recipe_archive(connection)


def next_report_id(connection: sqlite3.Connection) -> int:
    """Allocate a globally unique report number inside the caller's transaction."""
    if not connection.in_transaction:
        raise ValueError('report identifiers are allocated inside the report transaction')
    cursor = connection.execute('INSERT INTO report_identifiers DEFAULT VALUES')
    return cursor.lastrowid


def publish_report(
    connection: sqlite3.Connection, machine_model: str, request: tuple[int, int],
    decision: str, retest: dict | None, parents: tuple[ReportParent, ReportParent],
) -> int:
    if (tuple(parent.position for parent in parents) != (0, 1)
            or tuple(parent.receipt_id for parent in parents) != request
            or any(parent.machine_model != machine_model for parent in parents)):
        raise ValueError('report provenance does not match its ordered request')
    if decision not in ('reuse', 'retest') or (decision == 'retest') != (retest is not None):
        raise ValueError('report decision and retest evidence disagree')
    if connection.in_transaction:
        raise ValueError('publication requires an idle connection')
    if retest is not None and not isinstance(retest, dict):
        raise ValueError('retest evidence must be an object')
    retest_json = None if retest is None else json.dumps(
        retest, allow_nan=False, sort_keys=True, separators=(',', ':'),
    )
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        report_id = next_report_id(connection)
        connection.execute(
            '''INSERT INTO reports (report_id, machine_model, left_receipt_id, right_receipt_id, decision, retest_json)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (report_id, machine_model, request[0], request[1], decision, retest_json),
        )
        insert_report_parents(connection, report_id, parents)
        connection.execute('INSERT INTO publication_receipts (report_id) VALUES (?)', (report_id,))
    return report_id
