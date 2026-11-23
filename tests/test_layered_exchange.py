import json
from fractions import Fraction

from exchange.envelope import EvidenceEnvelope, canonical_json, seal_envelope
from exchange.issue import issue
from exchange.layered_body import LayeredEvidenceBody
from exchange.receipt import get_receipt, receive
from models.approval import approve_layered_model
from tests.fixtures import MACHINE, SAMPLES, BenchCase


def recipe_sample():
    return json.loads((SAMPLES / 'recipes.json').read_text(encoding='utf-8'))


class TestLayeredExchange(BenchCase):
    def seed_layered(self, side_key, predecessor=None, c_override=None):
        data = recipe_sample()
        side = data[side_key]
        layers = dict(side['layers'])
        if c_override is not None:
            layers['C'] = c_override
        revision = self.record_version(data, predecessor)
        model_id = approve_layered_model(
            self.store, revision, side['state_ids'], layers,
            side['transitions'], side['classification'],
        )
        return revision, model_id

    def test_v2_envelope_body_and_fingerprint(self):
        revision, model_id = self.seed_layered('left')
        envelope = issue(self.store, model_id)
        self.assertEqual(envelope.version, 2)
        payload = json.loads(envelope.body)
        self.assertEqual(set(payload), {'layers', 'transitions', 'classification'})
        receipt_id = receive(self.night, envelope.to_json(), MACHINE)
        receipt = get_receipt(self.night, receipt_id)
        self.assertEqual(receipt.envelope, envelope)
        self.assertIsInstance(receipt.body, LayeredEvidenceBody)
        self.assertEqual(receipt.body.layer_names, ('A', 'B', 'C'))
        # Private state identifiers and raw rows never leave the station.
        for state in recipe_sample()['left']['state_ids']:
            self.assertNotIn(state, envelope.to_json())
        for row in recipe_sample()['observations']:
            self.assertNotIn(row['row'], envelope.to_json())

    def test_replay_layer_matches_contract_rates(self):
        _, left_model = self.seed_layered('left')
        _, right_model = self.seed_layered('right')
        ids = (
            receive(self.night, issue(self.store, left_model).to_json(), MACHINE),
            receive(self.night, issue(self.store, right_model).to_json(), MACHINE),
        )
        for receipt_id in ids:
            body = get_receipt(self.night, receipt_id).body
            rates = {
                name: body.replay_layer(name, ('X',)).conditional_rate
                for name in body.layer_names
            }
            self.assertEqual(rates, {'A': Fraction(0), 'B': Fraction(1), 'C': None})

    def test_deterministic_issue_and_bad_body_rejection(self):
        _, model_id = self.seed_layered('left')
        first = issue(self.store, model_id)
        second = issue(self.store, model_id)
        self.assertEqual(first.to_json(), second.to_json())
        # A body whose layer no longer has unit mass is a bad item.
        tampered = json.loads(first.body)
        tampered['layers']['A'] = [1, 1, 0]
        resealed = seal_envelope(MACHINE, model_id, first.revision_id, json.dumps(tampered), version=2)
        with self.assertRaises(ValueError):
            receive(self.night, resealed, MACHINE)
        # A valid-looking but modified body carrying the original fingerprint
        # is rejected because fingerprint and body no longer agree.
        swapped = json.loads(first.body)
        swapped['layers']['A'] = [0, 1, 0]
        stale = EvidenceEnvelope(
            first.version, first.machine_model, first.model_id, first.revision_id,
            canonical_json(swapped), first.fingerprint,
        )
        with self.assertRaises(ValueError):
            receive(self.night, stale, MACHINE)
        self.assertEqual(self.receipt_count(), 0)

    def test_invalid_layered_bodies_are_rejected(self):
        _, model_id = self.seed_layered('left')
        envelope = issue(self.store, model_id)
        valid = json.loads(envelope.body)
        defects = [
            {'layers': {**valid['layers'], 'D': valid['layers']['A']}},
            {'layers': {}, 'transitions': valid['transitions'], 'classification': valid['classification']},
            {'layers': {**valid['layers'], 'A': ['1/2', 0, 0]}},
            {**valid, 'extra': 1},
            {'layers': valid['layers']},
        ]
        for index, defect in enumerate(defects):
            with self.subTest(defect=index):
                with self.assertRaises(ValueError):
                    receive(
                        self.night,
                        seal_envelope(MACHINE, model_id, envelope.revision_id, json.dumps(defect), version=2),
                        MACHINE,
                    )
        self.assertEqual(self.receipt_count(), 0)

    def test_duplicate_json_fields_rejected(self):
        _, model_id = self.seed_layered('left')
        envelope = issue(self.store, model_id)
        encoded = envelope.body
        duplicated = encoded[:-1] + ',"layers":{}}'
        resealed = seal_envelope(MACHINE, model_id, envelope.revision_id, duplicated, version=2)
        with self.assertRaises(ValueError):
            receive(self.night, resealed, MACHINE)
        self.assertEqual(self.receipt_count(), 0)

    def test_unknown_layer_and_action_on_receipt(self):
        _, model_id = self.seed_layered('left')
        receipt_id = receive(self.night, issue(self.store, model_id).to_json(), MACHINE)
        body = get_receipt(self.night, receipt_id).body
        with self.assertRaises(ValueError):
            body.replay_layer('A', ('Z',))
        with self.assertRaises(ValueError):
            body.replay_layer('NONE', ())
