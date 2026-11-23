import sqlite3
import sys

from archive.export import export_report
from archive.publish import initialize_archive
from archive.retrieve import retrieve
from exchange.issue import issue
from exchange.receipt import get_receipt, initialize_receipts, receive
from models.approval import get_approved_model, initialize_models
from models.transition_table import propagate_distribution
from review.compare import compare_publish
from review.conditional_rates import find_rate_witness
from review.eligibility import find_eligibility_witness
from tests.fixtures import MACHINE, BenchCase, sample


class TestArchive(BenchCase):
    def test_publish_failure_is_atomic(self):
        ids, _ = self.prepare_pair()
        first_id = compare_publish(self.night, *ids)
        previous = export_report(self.night, first_id)
        before = self.archive_counts()
        self.night.executescript(
            '''CREATE TABLE test_commit_gate (permitted_id INTEGER PRIMARY KEY);
               CREATE TABLE test_commit_attempt (
                   report_id INTEGER REFERENCES test_commit_gate(permitted_id)
                       DEFERRABLE INITIALLY DEFERRED
               );
               CREATE TRIGGER test_fail_at_commit AFTER INSERT ON publication_receipts
               BEGIN
                   INSERT INTO test_commit_attempt VALUES (NEW.report_id);
               END;'''
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY'):
            compare_publish(self.night, *ids)
        self.reopen_night()
        self.assertEqual(self.archive_counts(), before)
        self.assertEqual(export_report(self.night, first_id), previous)
        self.assertEqual(self.night.execute('SELECT count(*) FROM test_commit_attempt').fetchone()[0], 0)
        with self.assertRaises(LookupError):
            retrieve(self.night, first_id + 1)

    def test_second_parent_write_rolls_back(self):
        ids, _ = self.prepare_pair()
        before = self.archive_counts()
        self.night.execute(
            '''CREATE TRIGGER test_reject_second_parent BEFORE INSERT ON report_parents
               WHEN NEW.position = 1
               BEGIN
                   SELECT RAISE(ABORT, 'second parent refused');
               END'''
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'second parent refused'):
            compare_publish(self.night, *ids)
        self.reopen_night()
        self.assertEqual(self.archive_counts(), before)
        with self.assertRaises(LookupError):
            retrieve(self.night, 1)

    def test_read_original_after_correction(self):
        ids, revisions = self.prepare_pair()
        old_id = compare_publish(self.night, *ids)
        old = retrieve(self.night, old_id)
        old_export = export_report(self.night, old_id)
        self.reopen_station()
        corrected = sample('left')
        corrected['observations'][0]['note'] = '更正后复核'
        new_revision, new_model = self.seed_version(corrected, revisions[1])
        new_receipt = receive(self.night, issue(self.store, new_model), MACHINE)
        self.disconnect_station()
        new_id = compare_publish(self.night, ids[0], new_receipt)
        newer = retrieve(self.night, new_id)
        self.assertEqual(newer.decision, 'reuse')
        self.assertEqual(newer.parents[1].revision_id, new_revision)
        self.assertEqual(newer.parents[1].receipt_id, new_receipt)
        self.reopen_night()

        computation = {function.__code__ for function in (
            compare_publish, find_rate_witness, find_eligibility_witness, propagate_distribution,
        )}
        calls = []

        def profile(frame, event, arg):
            if event == 'call' and frame.f_code in computation:
                calls.append(frame.f_code.co_name)

        previous_profiler = sys.getprofile()
        sys.setprofile(profile)
        try:
            after = retrieve(self.night, old_id)
            after_export = export_report(self.night, old_id)
        finally:
            sys.setprofile(previous_profiler)
        self.assertEqual(calls, [])
        self.assertEqual(after, old)
        self.assertEqual(after_export, old_export)
        self.assertEqual(after.decision, 'retest')
        self.assertEqual(after.request, ids)
        self.assertEqual(tuple(parent.receipt_id for parent in after.parents), ids)
        self.assertEqual(tuple(parent.revision_id for parent in after.parents), revisions)

    def test_reinitialize_preserves_user_data(self):
        ids, revisions = self.prepare_pair(disconnect=False)
        report_id = compare_publish(self.night, *ids)
        frozen = export_report(self.night, report_id)
        original_revision = self.store.load_revision(revisions[1])
        receipt = get_receipt(self.night, ids[1])
        approval = get_approved_model(self.store, receipt.envelope.model_id)
        counts = self.run_counts(), self.approval_count(), self.receipt_count(), self.archive_counts()
        self.disconnect_station()
        self.reopen_station()
        self.reopen_night()
        for _ in range(2):
            self.store.initialize()
            initialize_models(self.site)
            initialize_receipts(self.night)
            initialize_archive(self.night)
        self.assertEqual(self.store.load_revision(revisions[1]), original_revision)
        self.assertEqual(get_approved_model(self.store, approval.model_id), approval)
        self.assertEqual(get_receipt(self.night, ids[1]), receipt)
        self.assertEqual(export_report(self.night, report_id), frozen)
        self.assertEqual(
            (self.run_counts(), self.approval_count(), self.receipt_count(), self.archive_counts()), counts,
        )

    def test_unknown_report(self):
        with self.assertRaises(LookupError):
            retrieve(self.night, 1)
        with self.assertRaises(LookupError):
            export_report(self.night, 1)
