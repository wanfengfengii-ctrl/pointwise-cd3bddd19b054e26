import sqlite3
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ReportParent:
    position: int
    receipt_id: int
    machine_model: str
    model_id: int
    revision_id: int
    fingerprint: str

    def as_dict(self) -> dict:
        return asdict(self)


def initialize_provenance(connection: sqlite3.Connection) -> None:
    connection.execute(
        '''CREATE TABLE IF NOT EXISTS report_parents (
            report_id INTEGER NOT NULL REFERENCES reports(report_id),
            position INTEGER NOT NULL CHECK (position IN (0, 1)),
            receipt_id INTEGER NOT NULL REFERENCES received_evidence(receipt_id),
            machine_model TEXT NOT NULL,
            model_id INTEGER NOT NULL,
            revision_id INTEGER NOT NULL,
            fingerprint TEXT NOT NULL,
            PRIMARY KEY (report_id, position)
        )'''
    )


def insert_report_parents(
    connection: sqlite3.Connection, report_id: int, parents: tuple[ReportParent, ReportParent],
) -> None:
    if not connection.in_transaction:
        raise ValueError('parent writes require the report transaction')
    connection.executemany(
        '''INSERT INTO report_parents (
               report_id, position, receipt_id, machine_model, model_id, revision_id, fingerprint
           ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
        ((report_id, parent.position, parent.receipt_id, parent.machine_model,
          parent.model_id, parent.revision_id, parent.fingerprint) for parent in parents),
    )


def load_report_parents(connection: sqlite3.Connection, report_id: int) -> tuple[ReportParent, ReportParent]:
    rows = connection.execute(
        '''SELECT position, receipt_id, machine_model, model_id, revision_id, fingerprint
           FROM report_parents WHERE report_id = ? ORDER BY position''',
        (report_id,),
    ).fetchall()
    if len(rows) != 2 or (rows[0][0], rows[1][0]) != (0, 1):
        raise ValueError(f'incomplete provenance for report {report_id}')
    return ReportParent(*rows[0]), ReportParent(*rows[1])
