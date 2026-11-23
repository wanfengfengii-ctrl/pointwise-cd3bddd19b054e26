import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.publish import initialize_archive
from exchange.issue import issue
from exchange.receipt import initialize_receipts, receive
from models.approval import approve_model, initialize_models
from runs.intake import record_run
from runs.store import RunStore


MACHINE = 'RQ-Opt-12'
SAMPLES = Path(__file__).resolve().parents[1] / 'samples'


def sample(side):
    return json.loads((SAMPLES / f'{side}.json').read_text(encoding='utf-8'))


def constant_version(category):
    return {
        'machine_model': MACHINE,
        'catalog': {'X': '标准挑战', 'Y': '校验等待'},
        'observations': [{'action': 'X', 'row': 'constant-case'}],
        'state_ids': ['private-constant-state'],
        'initial': [1],
        'transitions': {'X': [[1]], 'Y': [[1]]},
        'classification': {
            label: ['private-constant-state'] if label == category else []
            for label in ('pass', 'fail', 'pending')
        },
    }


def masses(outcome):
    return outcome.passed, outcome.failed, outcome.pending


class BenchCase(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory(prefix='rongqiao-test-')))
        self.station_file = root / 'station.sqlite3'
        self.offline_file = root / 'station-offline.sqlite3'
        self.night_file = root / 'night.sqlite3'
        self.site = sqlite3.connect(self.station_file)
        self.night = sqlite3.connect(self.night_file)
        self.addCleanup(self.close_databases)
        self.store = RunStore(self.site)
        self.store.initialize()
        initialize_models(self.site)
        initialize_receipts(self.night)
        initialize_archive(self.night)

    def close_databases(self):
        self.night.close()
        if self.site is not None:
            self.site.close()

    def disconnect_station(self):
        self.site.close()
        self.site = None
        self.station_file.rename(self.offline_file)

    def reopen_station(self):
        self.offline_file.rename(self.station_file)
        self.site = sqlite3.connect(self.station_file)
        self.store = RunStore(self.site)

    def reopen_night(self):
        self.night.close()
        self.night = sqlite3.connect(self.night_file)

    def record_version(self, data, predecessor_id=None):
        return record_run(self.store, data['machine_model'], data['catalog'], data['observations'], predecessor_id)

    def approve_version(self, revision_id, data):
        return approve_model(
            self.store, revision_id, data['state_ids'], data['initial'], data['transitions'], data['classification'],
        )

    def seed_version(self, data, predecessor_id=None):
        revision = self.record_version(data, predecessor_id)
        return revision, self.approve_version(revision, data)

    def prepare_pair(self, left_data=None, right_data=None, *, disconnect=True):
        left_data = sample('left') if left_data is None else left_data
        right_data = sample('right') if right_data is None else right_data
        left_revision, left_model = self.seed_version(left_data)
        predecessor = left_revision if left_data['machine_model'] == right_data['machine_model'] else None
        right_revision, right_model = self.seed_version(right_data, predecessor)
        left_id = receive(self.night, issue(self.store, left_model).to_json(), left_data['machine_model'])
        right_id = receive(self.night, issue(self.store, right_model).to_json(), right_data['machine_model'])
        if disconnect:
            self.disconnect_station()
        return (left_id, right_id), (left_revision, right_revision)

    def archive_counts(self):
        return self.night.execute(
            '''SELECT (SELECT count(*) FROM reports),
                      (SELECT count(*) FROM report_parents),
                      (SELECT count(*) FROM publication_receipts)'''
        ).fetchone()

    def approval_count(self):
        return self.site.execute('SELECT count(*) FROM approved_models').fetchone()[0]

    def run_counts(self):
        return self.site.execute(
            'SELECT (SELECT count(*) FROM run_revisions), (SELECT count(*) FROM run_observations)'
        ).fetchone()

    def receipt_count(self):
        return self.night.execute('SELECT count(*) FROM received_evidence').fetchone()[0]
