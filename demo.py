import json
import sqlite3
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.export import export_report
from archive.publish import initialize_archive
from archive.retrieve import retrieve
from exchange.issue import issue
from exchange.receipt import get_receipt, initialize_receipts, receive
from models.approval import approve_layered_model, approve_model, initialize_models
from models.rational import format_rational
from models.replay import replay
from review.compare import compare_publish, compare_recipe_publish
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


def register_layered_version(store, data, side_key, predecessor_id=None, c_override=None):
    side = data[side_key]
    layers = dict(side['layers'])
    if c_override is not None:
        layers['C'] = c_override
    revision_id = record_run(
        store, data['machine_model'], data['catalog'], data['observations'], predecessor_id,
    )
    model_id = approve_layered_model(
        store, revision_id, side['state_ids'], layers,
        side['transitions'], side['classification'],
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


def _recipe_witness(night, report, left_id, right_id, actions):
    """Independently recompute a retest recipe from the two held receipts."""
    weights = {entry['layer']: Fraction(entry['weight']) for entry in report.retest['recipe']}
    recomputed = {}
    for receipt_id, side_key in ((left_id, 'left'), (right_id, 'right')):
        body = get_receipt(night, receipt_id).body
        passed = sum(weights[name] * body.replay_layer(name, actions).passed for name in weights)
        decided = sum(
            weights[name] * body.replay_layer(name, actions).decided_mass for name in weights
        )
        recomputed[side_key] = {
            'eligible': decided > 0,
            'conditional_rate': None if decided == 0 else format_rational(passed / decided),
        }
    return recomputed


def run_recipe_demo(root, recipe_data):
    station = root / 'recipe-station.sqlite3'
    offline = root / 'recipe-closed-station.sqlite3'
    shift = root / 'recipe-night.sqlite3'
    machine_model = recipe_data['machine_model']
    actions = tuple(recipe_data['actions'])
    with closing(sqlite3.connect(shift)) as night:
        initialize_receipts(night)
        initialize_archive(night)
        with closing(sqlite3.connect(station)) as source:
            store = RunStore(source)
            store.initialize()
            initialize_models(source)
            left_revision, left_model = register_layered_version(store, recipe_data, 'left')
            _, right_model = register_layered_version(store, recipe_data, 'right', left_revision)
            layer_bench = {}
            for side_key, model_id in (('left', left_model), ('right', right_model)):
                body = issue(store, model_id)
                layer_bench[side_key] = {'version': body.version}
            left_id = receive(night, issue(store, left_model).to_json(), machine_model)
            right_id = receive(night, issue(store, right_model).to_json(), machine_model)
            # Per-layer witness recomputation while the station is still open.
            open_check = {}
            for receipt_id, side_key in ((left_id, 'left'), (right_id, 'right')):
                body = get_receipt(night, receipt_id).body
                open_check[side_key] = {
                    name: display_outcome(body.replay_layer(name, actions))
                    for name in body.layer_names
                }
        station.rename(offline)

        half_constraints = [({'C': 1}, '1/2'), ({'C': -1}, '-1/2')]
        retest_id = compare_recipe_publish(
            night, left_id, right_id, actions, half_constraints, Fraction(1, 4),
        )
        reuse_id = compare_recipe_publish(
            night, left_id, right_id, actions, half_constraints, Fraction(1, 3),
        )
        point_constraints = [({'C': 1}, 1), ({'C': -1}, -1)]
        pending_id = compare_recipe_publish(
            night, left_id, right_id, actions, point_constraints, 0,
        )
        retest_report = retrieve(night, retest_id)
        witness = _recipe_witness(night, retest_report, left_id, right_id, actions)
        station_closing = {
            'retest_report': json.loads(export_report(night, retest_id)),
            'reuse_report': json.loads(export_report(night, reuse_id)),
            'pending_point_report': json.loads(export_report(night, pending_id)),
            'receipt_recomputation': witness,
        }
        if witness != {
            'left': retest_report.retest['left'],
            'right': retest_report.retest['right'],
        }:
            raise RuntimeError('receipt recomputation does not match the signed retest report')
    with closing(sqlite3.connect(shift)) as night:
        reopened = {
            report_id: json.loads(export_report(night, report_id))
            for report_id in (retest_id, reuse_id, pending_id)
        }
    if reopened[retest_id] != station_closing['retest_report']:
        raise RuntimeError('recipe report changed after the station database was moved')
    return {
        'layer_bench': layer_bench,
        'open_shift_layer_replay': open_check,
        'closing': station_closing,
        'reopened_exports': reopened,
    }


def main():
    samples = Path(__file__).resolve().parent / 'samples'
    left = json.loads((samples / 'left.json').read_text(encoding='utf-8'))
    right = json.loads((samples / 'right.json').read_text(encoding='utf-8'))
    recipes = json.loads((samples / 'recipes.json').read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='rongqiao-demo-') as directory:
        root = Path(directory)
        result = run_demo(root, left, right)
        recipe_result = run_recipe_demo(root, recipes)
    print(json.dumps(
        {'version1_review': result, 'recipe_review': recipe_result},
        ensure_ascii=False, indent=2, sort_keys=True,
    ))


if __name__ == '__main__':
    main()
