import json
from fractions import Fraction

from models.approval import (
    approve_layered_model,
    approve_model,
    get_approved_layered_model,
    get_approved_model,
)
from tests.fixtures import SAMPLES, BenchCase, sample


class TestLayeredApproval(BenchCase):
    def _layered_inputs(self):
        data = json.loads((SAMPLES / 'recipes.json').read_text(encoding='utf-8'))
        side = data['left']
        return data, side

    def test_approve_layered_model_snapshots_layers(self):
        data, side = self._layered_inputs()
        revision = self.record_version(data)
        model_id = approve_layered_model(
            self.store, revision, side['state_ids'], side['layers'],
            side['transitions'], side['classification'],
        )
        approved = get_approved_layered_model(self.store, model_id)
        self.assertEqual(approved.layer_names, ('A', 'B', 'C'))
        self.assertEqual(approved.replay_layer('A', ('X',)).conditional_rate, Fraction(0))
        self.assertEqual(approved.replay_layer('B', ('X',)).conditional_rate, Fraction(1))
        self.assertFalse(approved.replay_layer('C', ('X',)).is_decidable)

    def test_approval_freezes_caller_input(self):
        data, side = self._layered_inputs()
        revision = self.record_version(data)
        layers = dict(side['layers'])
        model_id = approve_layered_model(
            self.store, revision, side['state_ids'], layers,
            side['transitions'], side['classification'],
        )
        layers['A'] = [1, 0, 0]
        approved = get_approved_layered_model(self.store, model_id)
        self.assertEqual(approved.initial_for('A'), (Fraction(1, 2), Fraction(0), Fraction(1, 2)))

    def test_layer_validation_rules(self):
        data, side = self._layered_inputs()
        revision = self.record_version(data)
        bad_cases = [
            ('empty layers', {}),
            ('four layers', {name: side['layers']['A'] for name in ('A', 'B', 'C', 'D')}),
            ('blank name', {'  ': side['layers']['A']}),
            ('bad mass', {'A': ['1/2', 0, 0]}),
            ('negative mass', {'A': [1, -1, 1]}),
        ]
        for label, layers in bad_cases:
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    approve_layered_model(
                        self.store, revision, side['state_ids'], layers,
                        side['transitions'], side['classification'],
                    )
        self.assertEqual(self.approval_count(), 0)

    def test_layered_and_plain_approval_are_distinct(self):
        data, side = self._layered_inputs()
        revision = self.record_version(data)
        plain = sample('left')
        plain_revision = self.record_version(plain)
        plain_id = approve_model(
            self.store, plain_revision, plain['state_ids'], plain['initial'],
            plain['transitions'], plain['classification'],
        )
        layered_id = approve_layered_model(
            self.store, revision, side['state_ids'], side['layers'],
            side['transitions'], side['classification'],
        )
        with self.assertRaises(ValueError):
            get_approved_model(self.store, layered_id)
        with self.assertRaises(ValueError):
            get_approved_layered_model(self.store, plain_id)

    def test_unknown_layer_replay_rejected(self):
        data, side = self._layered_inputs()
        revision = self.record_version(data)
        model_id = approve_layered_model(
            self.store, revision, side['state_ids'], side['layers'],
            side['transitions'], side['classification'],
        )
        approved = get_approved_layered_model(self.store, model_id)
        with self.assertRaises(ValueError):
            approved.replay_layer('MISSING', ('X',))
        with self.assertRaises(ValueError):
            approved.replay_layer('A', ('X', 'NOPE'))
