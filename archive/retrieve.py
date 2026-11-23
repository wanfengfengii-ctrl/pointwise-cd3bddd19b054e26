import json
import sqlite3

from archive.provenance import load_report_parents
from archive.publish import PublishedReport


def retrieve(connection: sqlite3.Connection, report_id: int) -> PublishedReport:
    if type(report_id) is not int or not 1 <= report_id < 2**63:
        raise ValueError('report ID must be a positive SQLite integer')
    row = connection.execute(
        '''SELECT reports.machine_model, reports.left_receipt_id, reports.right_receipt_id,
                  reports.decision, reports.retest_json
           FROM reports JOIN publication_receipts USING (report_id)
           WHERE reports.report_id = ?''',
        (report_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f'unknown published report: {report_id}')
    machine_model, left_id, right_id, decision, retest_json = row
    parents = load_report_parents(connection, report_id)
    if tuple(parent.receipt_id for parent in parents) != (left_id, right_id):
        raise ValueError(f'provenance does not match request for report {report_id}')
    return PublishedReport(
        report_id, machine_model, (left_id, right_id), decision,
        None if retest_json is None else json.loads(retest_json), parents,
    )
