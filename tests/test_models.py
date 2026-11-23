from fractions import Fraction

from models.approval import get_approved_model
from models.replay import replay
from runs.intake import record_run
from tests.fixtures import BenchCase, masses, sample


class TestModels(BenchCase):
    def test_pending_can_later_pass(self):
        data = sample('left')
        revision_id, model_id = self.seed_version(data)
        revision = self.store.load_revision(revision_id)
        self.assertEqual([row.as_record() for row in revision.observations], data['observations'])
        self.assertEqual(get_approved_model(self.store, model_id).revision_id, revision_id)
        empty = replay(self.store, model_id, ())
        first = replay(self.store, model_id, ('X',))
        second = replay(self.store, model_id, ('X', 'X'))
        self.assertEqual(masses(empty), (0, 0, 1))
        self.assertFalse(empty.is_decidable)
        self.assertIsNone(empty.conditional_rate)
        self.assertEqual(masses(first), (Fraction(1, 4), Fraction(1, 4), Fraction(1, 2)))
        self.assertEqual(first.conditional_rate, Fraction(1, 2))
        self.assertEqual(masses(second), (Fraction(3, 4), Fraction(1, 4), 0))
        self.assertEqual(second.conditional_rate, Fraction(3, 4))

    def test_cross_model_predecessor(self):
        left, right = sample('left'), sample('right')
        right['machine_model'] = 'RQ-Opt-13'
        left_revision = self.record_version(left)
        right_revision = self.record_version(right)
        before = self.run_counts()
        with self.assertRaises(ValueError):
            self.record_version(left, right_revision)
        self.assertEqual(self.run_counts(), before)
        self.assertEqual(self.store.load_revision(left_revision).machine_model, left['machine_model'])
        self.assertEqual(self.store.load_revision(right_revision).machine_model, right['machine_model'])

    def test_bad_observation_action_does_not_register(self):
        data = sample('left')
        rows = data['observations'] + [{'action': 'BAD', 'row': 'late-row'}]
        with self.assertRaises(ValueError):
            record_run(self.store, data['machine_model'], data['catalog'], rows)
        self.assertEqual(self.run_counts(), (0, 0))

    def test_action_order(self):
        data = sample('left')
        data['transitions']['Y'][1] = [0, 0, 0, 1]
        _, model_id = self.seed_version(data)
        yx = replay(self.store, model_id, ('Y', 'X'))
        xy = replay(self.store, model_id, ('X', 'Y'))
        self.assertEqual(masses(yx), (Fraction(1, 4), Fraction(1, 4), Fraction(1, 2)))
        self.assertEqual(masses(xy), (Fraction(1, 4), Fraction(3, 4), 0))
        self.assertEqual(yx.conditional_rate, Fraction(1, 2))
        self.assertEqual(xy.conditional_rate, Fraction(1, 4))

    def test_unknown_replay_input(self):
        _, model_id = self.seed_version(sample('left'))
        with self.assertRaises(LookupError):
            replay(self.store, model_id + 1, ())
        with self.assertRaises(ValueError):
            replay(self.store, model_id, ('X', 'UNREGISTERED'))

    def test_bad_transition_row(self):
        data = sample('left')
        revision_id = self.record_version(data)
        data['transitions']['X'][0] = [0, '1/4', '1/4', '1/4']
        with self.assertRaises(ValueError):
            self.approve_version(revision_id, data)
        self.assertEqual(self.approval_count(), 0)

    def test_invalid_initial_or_classification(self):
        revision_id = self.record_version(sample('left'))
        for defect in ('nonunit initial', 'negative initial', 'overlap', 'omission'):
            with self.subTest(defect=defect):
                data = sample('left')
                if defect == 'nonunit initial':
                    data['initial'] = ['1/2', 0, 0, 0]
                elif defect == 'negative initial':
                    data['initial'] = [2, -1, 0, 0]
                elif defect == 'overlap':
                    data['classification']['fail'].append(data['state_ids'][2])
                else:
                    data['classification']['pending'].pop()
                with self.assertRaises(ValueError):
                    self.approve_version(revision_id, data)
                self.assertEqual(self.approval_count(), 0)
