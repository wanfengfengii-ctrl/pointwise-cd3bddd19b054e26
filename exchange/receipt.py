import sqlite3
from dataclasses import dataclass

from exchange.body import EvidenceBody, decode_body
from exchange.envelope import EvidenceEnvelope, verify_envelope


@dataclass(frozen=True)
class ReceivedEvidence:
    receipt_id: int
    envelope: EvidenceEnvelope
    body: EvidenceBody


def initialize_receipts(connection: sqlite3.Connection) -> None:
    connection.execute('PRAGMA foreign_keys = ON')
    connection.execute(
        '''CREATE TABLE IF NOT EXISTS received_evidence (
            receipt_id INTEGER PRIMARY KEY,
            envelope_json TEXT NOT NULL
        )'''
    )


def receive(
    connection: sqlite3.Connection, envelope: EvidenceEnvelope | str, expected_model: str,
) -> int:
    if not isinstance(expected_model, str) or not expected_model or expected_model != expected_model.strip():
        raise ValueError('expected model must be a nonempty trimmed string')
    if isinstance(envelope, str):
        envelope = EvidenceEnvelope.from_json(envelope)
    verify_envelope(envelope)
    if envelope.machine_model != expected_model:
        raise ValueError('received evidence belongs to a different machine model')
    decode_body(envelope.body)
    if connection.in_transaction:
        raise ValueError('receipt registration requires an idle connection')
    with connection:
        cursor = connection.execute(
            'INSERT INTO received_evidence (envelope_json) VALUES (?)', (envelope.to_json(),),
        )
    return cursor.lastrowid


def get_receipt(connection: sqlite3.Connection, receipt_id: int) -> ReceivedEvidence:
    if type(receipt_id) is not int or not 1 <= receipt_id < 2**63:
        raise ValueError('receipt ID must be a positive SQLite integer')
    row = connection.execute(
        'SELECT envelope_json FROM received_evidence WHERE receipt_id = ?', (receipt_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f'unknown evidence receipt: {receipt_id}')
    envelope = EvidenceEnvelope.from_json(row[0])
    verify_envelope(envelope)
    return ReceivedEvidence(receipt_id, envelope, decode_body(envelope.body))
