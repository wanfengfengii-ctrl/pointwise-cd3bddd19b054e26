import json
import sqlite3

from archive.retrieve import retrieve


def export_report(connection: sqlite3.Connection, report_id: int) -> str:
    snapshot = retrieve(connection, report_id)
    return json.dumps(snapshot.as_dict(), ensure_ascii=True, sort_keys=True, separators=(',', ':'))
