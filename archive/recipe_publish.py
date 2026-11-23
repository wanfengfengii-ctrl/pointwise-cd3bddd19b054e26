import json
import sqlite3
from dataclasses import dataclass
from fractions import Fraction

from archive.provenance import ReportParent
from models.rational import format_rational


@dataclass(frozen=True)
class RecipePublishedReport:
    report_id: int
    machine_model: str
    left_receipt_id: int
    right_receipt_id: int
    actions: tuple[str, ...]
    constraints: tuple[tuple[dict, Fraction], ...]
    tolerance: Fraction
    decision: str
    retest: dict | None
    parents: tuple[ReportParent, ReportParent]

    @property
    def request(self) -> tuple[int, int]:
        return self.left_receipt_id, self.right_receipt_id

    def as_dict(self) -> dict:
        return {
            'report_id': self.report_id,
            'machine_model': self.machine_model,
            'request': {
                'left_receipt_id': self.left_receipt_id,
                'right_receipt_id': self.right_receipt_id,
                'actions': list(self.actions),
                'constraints': [
                    [dict(coefficients), format_rational(upper)]
                    for coefficients, upper in self.constraints
                ],
                'tolerance': format_rational(self.tolerance),
            },
            'decision': self.decision,
            'retest': self.retest,
            'parents': [parent.as_dict() for parent in self.parents],
        }


def initialize_recipe_archive(connection: sqlite3.Connection) -> None:
    connection.execute('PRAGMA foreign_keys = ON')
    with connection:
        connection.execute(
            '''CREATE TABLE IF NOT EXISTS recipe_reports (
                report_id INTEGER PRIMARY KEY REFERENCES report_identifiers(report_id),
                machine_model TEXT NOT NULL,
                left_receipt_id INTEGER NOT NULL REFERENCES received_evidence(receipt_id),
                right_receipt_id INTEGER NOT NULL REFERENCES received_evidence(receipt_id),
                request_json TEXT NOT NULL,
                decision TEXT NOT NULL CHECK (decision IN ('reuse', 'retest')),
                retest_json TEXT,
                CHECK ((decision = 'retest') = (retest_json IS NOT NULL))
            )'''
        )
        connection.execute(
            '''CREATE TABLE IF NOT EXISTS recipe_report_parents (
                report_id INTEGER NOT NULL REFERENCES recipe_reports(report_id),
                position INTEGER NOT NULL CHECK (position IN (0, 1)),
                receipt_id INTEGER NOT NULL REFERENCES received_evidence(receipt_id),
                machine_model TEXT NOT NULL,
                model_id INTEGER NOT NULL,
                revision_id INTEGER NOT NULL,
                fingerprint TEXT NOT NULL,
                PRIMARY KEY (report_id, position)
            )'''
        )
        connection.execute(
            '''CREATE TABLE IF NOT EXISTS recipe_publication_receipts (
                report_id INTEGER PRIMARY KEY REFERENCES recipe_reports(report_id)
            )'''
        )


def _encode_request(
    actions: tuple[str, ...], constraints: tuple[tuple[dict, Fraction], ...], tolerance: Fraction,
) -> str:
    return json.dumps(
        {
            'actions': list(actions),
            'constraints': [
                [dict(coefficients), format_rational(upper)]
                for coefficients, upper in constraints
            ],
            'tolerance': format_rational(tolerance),
        },
        allow_nan=False,
        sort_keys=True,
        separators=(',', ':'),
    )


def publish_recipe_report(
    connection: sqlite3.Connection,
    machine_model: str,
    request: tuple[int, int],
    actions: tuple[str, ...],
    constraints: tuple[tuple[dict, Fraction], ...],
    tolerance: Fraction,
    decision: str,
    retest: dict | None,
    parents: tuple[ReportParent, ReportParent],
) -> int:
    if (tuple(parent.position for parent in parents) != (0, 1)
            or tuple(parent.receipt_id for parent in parents) != request
            or any(parent.machine_model != machine_model for parent in parents)):
        raise ValueError('report provenance does not match its ordered request')
    if decision not in ('reuse', 'retest') or (decision == 'retest') != (retest is not None):
        raise ValueError('report decision and retest evidence disagree')
    if retest is not None and not isinstance(retest, dict):
        raise ValueError('retest evidence must be an object')
    if connection.in_transaction:
        raise ValueError('publication requires an idle connection')
    request_json = _encode_request(actions, constraints, tolerance)
    retest_json = None if retest is None else json.dumps(
        retest, allow_nan=False, sort_keys=True, separators=(',', ':'),
    )
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        from archive.publish import next_report_id
        report_id = next_report_id(connection)
        connection.execute(
            '''INSERT INTO recipe_reports (
                   report_id, machine_model, left_receipt_id, right_receipt_id, request_json, decision, retest_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (report_id, machine_model, request[0], request[1], request_json, decision, retest_json),
        )
        connection.executemany(
            '''INSERT INTO recipe_report_parents (
                   report_id, position, receipt_id, machine_model, model_id, revision_id, fingerprint
               ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
            ((report_id, parent.position, parent.receipt_id, parent.machine_model,
              parent.model_id, parent.revision_id, parent.fingerprint) for parent in parents),
        )
        connection.execute(
            'INSERT INTO recipe_publication_receipts (report_id) VALUES (?)', (report_id,),
        )
    return report_id


def retrieve_recipe_report(connection: sqlite3.Connection, report_id: int) -> RecipePublishedReport:
    if type(report_id) is not int or not 1 <= report_id < 2**63:
        raise ValueError('report ID must be a positive SQLite integer')
    row = connection.execute(
        '''SELECT machine_model, left_receipt_id, right_receipt_id, request_json, decision, retest_json
           FROM recipe_reports JOIN recipe_publication_receipts USING (report_id)
           WHERE report_id = ?''',
        (report_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f'unknown published recipe report: {report_id}')
    machine_model, left_id, right_id, request_json, decision, retest_json = row
    request = json.loads(request_json)
    parents_rows = connection.execute(
        '''SELECT position, receipt_id, machine_model, model_id, revision_id, fingerprint
           FROM recipe_report_parents WHERE report_id = ? ORDER BY position''',
        (report_id,),
    ).fetchall()
    if len(parents_rows) != 2 or (parents_rows[0][0], parents_rows[1][0]) != (0, 1):
        raise ValueError(f'incomplete provenance for recipe report {report_id}')
    parents = (ReportParent(*parents_rows[0]), ReportParent(*parents_rows[1]))
    if tuple(parent.receipt_id for parent in parents) != (left_id, right_id):
        raise ValueError(f'provenance does not match request for recipe report {report_id}')
    constraints = tuple(
        (dict(coefficients), Fraction(upper)) for coefficients, upper in request['constraints']
    )
    return RecipePublishedReport(
        report_id,
        machine_model,
        left_id,
        right_id,
        tuple(request['actions']),
        tuple((coefficients, Fraction(upper)) for coefficients, upper in constraints),
        Fraction(request['tolerance']),
        decision,
        None if retest_json is None else json.loads(retest_json),
        parents,
    )


def export_recipe_report(connection: sqlite3.Connection, report_id: int) -> str:
    snapshot = retrieve_recipe_report(connection, report_id)
    return json.dumps(snapshot.as_dict(), ensure_ascii=True, sort_keys=True, separators=(',', ':'))
