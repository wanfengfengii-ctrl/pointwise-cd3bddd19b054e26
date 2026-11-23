import json
from dataclasses import replace
from fractions import Fraction

from exchange.envelope import seal_envelope
from exchange.issue import issue
from exchange.receipt import get_receipt, receive
from tests.fixtures import MACHINE, BenchCase, masses, sample


class TestExchange(BenchCase):
    def test_issue_and_receive_two_revisions(self):
        left_data, right_data = sample('left'), sample('right')
        old_revision, old_model = self.seed_version(left_data)
        new_revision, new_model = self.seed_version(right_data, old_revision)
        self.assertEqual(self.store.load_revision(new_revision).predecessor_id, old_revision)
        envelopes = (issue(self.store, old_model), issue(self.store, new_model))
        self.assertEqual(issue(self.store, old_model).to_json(), envelopes[0].to_json())
        receipt_ids = tuple(receive(self.night, envelope.to_json(), MACHINE) for envelope in envelopes)
        self.assertNotEqual(*receipt_ids)
        self.disconnect_station()
        self.assertFalse(self.station_file.exists())
        received = tuple(get_receipt(self.night, receipt_id) for receipt_id in receipt_ids)
        for data, receipt, envelope, revision_id, model_id in zip(
            (left_data, right_data), received, envelopes, (old_revision, new_revision), (old_model, new_model),
        ):
            self.assertEqual(receipt.envelope, envelope)
            self.assertEqual((envelope.revision_id, envelope.model_id), (revision_id, model_id))
            for private_id in data['state_ids']:
                self.assertNotIn(private_id, envelope.to_json())
            for observation in data['observations']:
                self.assertNotIn(observation['row'], envelope.to_json())
        quarter = Fraction(1, 4)
        half = Fraction(1, 2)
        expected = (
            ((), (0, 0, 1), (0, 0, 1)),
            (('X',), (quarter, quarter, half), (half, half, 0)),
            (('X', 'X'), (3 * quarter, quarter, 0), (half, half, 0)),
        )
        for word, left, right in expected:
            with self.subTest(word=word):
                self.assertEqual(masses(received[0].body.replay(word)), left)
                self.assertEqual(masses(received[1].body.replay(word)), right)

    def test_unknown_model_cannot_be_issued(self):
        with self.assertRaises(LookupError):
            issue(self.store, 1)

    def test_reject_mismatching_body(self):
        _, left_model = self.seed_version(sample('left'))
        _, right_model = self.seed_version(sample('right'))
        left = issue(self.store, left_model)
        right = issue(self.store, right_model)
        self.assertNotEqual(left.body, right.body)
        changed_body = replace(left, body=right.body)
        changed_source = replace(left, revision_id=right.revision_id)
        for envelope in (changed_body, changed_source):
            with self.subTest(envelope=envelope.fingerprint, revision=envelope.revision_id):
                with self.assertRaises(ValueError):
                    receive(self.night, envelope, MACHINE)
        self.assertEqual(self.receipt_count(), 0)

    def test_wrong_model_or_incomplete_body(self):
        _, model = self.seed_version(sample('left'))
        envelope = issue(self.store, model)
        with self.assertRaises(ValueError):
            receive(self.night, envelope, 'RQ-Wrong')
        incomplete = json.loads(envelope.body)
        incomplete['transitions']['X'].pop()
        resealed = seal_envelope(MACHINE, model, envelope.revision_id, json.dumps(incomplete))
        with self.assertRaises(ValueError):
            receive(self.night, resealed, MACHINE)
        self.assertEqual(self.receipt_count(), 0)
