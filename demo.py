import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.export import export_report
from archive.publish import initialize_archive
from archive.retrieve import retrieve
from exchange.issue import issue
from exchange.receipt import initialize_receipts, receive
from models.approval import approve_model, initialize_models
from models.rational import format_rational
from models.replay import replay
from review.compare import compare_publish
from runs.intake import record_run
from runs.store import RunStore


def register_version(store, data, predecessor_id=None):
    revision_id = record_run(
        store, data['machine_model'], data['catalog'], data['observations'], predecessor_id,
    )
    model_id = approve_model(
        store, revision_id, data['state_ids'], data['initial'], data['transitions'], data['classification'],
    )
    return revision_id, model_id


def display_outcome(outcome):
    rate = outcome.conditional_rate
    return {
        'mass': [format_rational(value) for value in (outcome.passed, outcome.failed, outcome.pending)],
        'eligible': outcome.is_decidable,
        'conditional_rate': None if rate is None else format_rational(rate),
    }


def run_demo(root, left_data, right_data):
    station = root / 'station.sqlite3'
    offline = root / 'closed-station.sqlite3'
    shift = root / 'night.sqlite3'
    machine_model = left_data['machine_model']
    with closing(sqlite3.connect(shift)) as night:
        initialize_receipts(night)
        initialize_archive(night)
        with closing(sqlite3.connect(station)) as source:
            store = RunStore(source)
            store.initialize()
            initialize_models(source)
            old_revision, old_model = register_version(store, left_data)
            new_revision, new_model = register_version(store, right_data, old_revision)
            bench = {
                side: {label: display_outcome(replay(store, model_id, word))
                       for label, word in (('X', ('X',)), ('XX', ('X', 'X')))}
                for side, model_id in (('left', old_model), ('right', new_model))
            }
            left_id = receive(night, issue(store, old_model).to_json(), machine_model)
            right_id = receive(night, issue(store, new_model).to_json(), machine_model)
        station.rename(offline)
        first_id = compare_publish(night, left_id, right_id)
        first_export = export_report(night, first_id)

        offline.rename(station)
        with closing(sqlite3.connect(station)) as source:
            store = RunStore(source)
            corrected = dict(right_data)
            corrected['observations'] = [
                {**row, 'note': '夜班核对后补记已阅'} for row in right_data['observations']
            ]
            _, corrected_model = register_version(store, corrected, new_revision)
            corrected_id = receive(night, issue(store, corrected_model), machine_model)
        station.rename(offline)
        later_id = compare_publish(night, left_id, corrected_id)
        later = retrieve(night, later_id).as_dict()
    with closing(sqlite3.connect(shift)) as night:
        reopened_export = export_report(night, first_id)
    if first_export != reopened_export:
        raise RuntimeError('historical report changed after correction')
    return {'bench': bench, 'original_report': json.loads(reopened_export), 'later_report': later}


def main():
    samples = Path(__file__).resolve().parent / 'samples'
    left = json.loads((samples / 'left.json').read_text(encoding='utf-8'))
    right = json.loads((samples / 'right.json').read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='rongqiao-demo-') as directory:
        result = run_demo(Path(directory), left, right)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
