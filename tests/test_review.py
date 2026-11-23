import json
from fractions import Fraction

from archive.retrieve import retrieve
from exchange.receipt import get_receipt
from review.compare import compare_publish
from tests.fixtures import BenchCase, constant_version, masses, sample


class TestReview(BenchCase):
    def test_same_conditional_rate(self):
        left_data = sample('left')
        left_data['transitions']['X'][1] = [0, 1, 0, 0]
        receipt_ids, revisions = self.prepare_pair(left_data)
        left = get_receipt(self.night, receipt_ids[0]).body.replay(('X',))
        right = get_receipt(self.night, receipt_ids[1]).body.replay(('X',))
        self.assertEqual((left.decided_mass, right.decided_mass), (Fraction(1, 2), 1))
        self.assertEqual((left.conditional_rate, right.conditional_rate), (Fraction(1, 2), Fraction(1, 2)))
        report = retrieve(self.night, compare_publish(self.night, *receipt_ids))
        self.assertEqual(report.decision, 'reuse')
        self.assertIsNone(report.retest)
        self.assertEqual(report.request, receipt_ids)
        self.assertEqual(tuple(parent.revision_id for parent in report.parents), revisions)
        self.assertEqual(tuple(parent.receipt_id for parent in report.parents), receipt_ids)

    def test_later_challenge_changes_rate(self):
        receipt_ids, _ = self.prepare_pair()
        left, right = (get_receipt(self.night, receipt_id).body for receipt_id in receipt_ids)
        first_rates = [str(body.replay(('X',)).conditional_rate) for body in (left, right)]
        self.assertEqual(first_rates, ['1/2', '1/2'])
        self.assertEqual(
            masses(left.replay(('X', 'X'))), (Fraction(3, 4), Fraction(1, 4), 0),
        )
        report = retrieve(self.night, compare_publish(self.night, *receipt_ids))
        self.assertEqual(report.decision, 'retest')
        self.assertEqual(report.request, receipt_ids)
        word = report.retest['actions']
        self.assertTrue(all(action in {'X', 'Y'} for action in word))
        self.assertGreaterEqual(word.count('X'), 2)
        actual_rates = [str(body.replay(word).conditional_rate) for body in (left, right)]
        self.assertEqual(actual_rates, ['3/4', '1/2'])
        self.assertEqual(report.retest['left'], {'eligible': True, 'conditional_rate': '3/4'})
        self.assertEqual(report.retest['right'], {'eligible': True, 'conditional_rate': '1/2'})
        parents = [parent.receipt_id for parent in report.parents]
        self.assertEqual(parents, list(receipt_ids))
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'V6',
            'input': {'receipts': list(receipt_ids), 'station_closed': not self.station_file.exists()},
            'expected': {'after_X': ['1/2', '1/2'], 'witness_rates': ['3/4', '1/2']},
            'actual': {'after_X': first_rates, 'witness_rates': actual_rates},
            'downstream_expected': {'decision': 'retest', 'parents': list(receipt_ids)},
            'downstream_actual': {'decision': report.decision, 'parents': parents},
            'code_paths': ['exchange/issue.py', 'exchange/receipt.py', 'review/conditional_rates.py',
                           'review/witness.py', 'review/compare.py', 'archive/retrieve.py'],
            'oracle': 'Y is identity. At the first X the left has 1/4 pass and 1/4 fail. A second X moves its remaining 1/2 to pass. The right stays at 1/2 pass and 1/2 fail.',
        }, sort_keys=True))

    def test_empty_witness(self):
        left = {
            'machine_model': 'RQ-Opt-12',
            'catalog': {'X': '标准挑战', 'Y': '校验等待'},
            'observations': [{'action': 'X'}],
            'state_ids': ['good', 'bad'],
            'initial': [1, 0],
            'transitions': {'X': [[0, 1], [0, 1]], 'Y': [[0, 1], [0, 1]]},
            'classification': {'pass': ['good'], 'fail': ['bad'], 'pending': []},
        }
        ids, _ = self.prepare_pair(left, {**left, 'initial': [0, 1]})
        report = retrieve(self.night, compare_publish(self.night, *ids))
        self.assertEqual(report.decision, 'retest')
        self.assertEqual(report.retest['actions'], [])
        self.assertEqual(report.retest['left'], {'eligible': True, 'conditional_rate': '1'})
        self.assertEqual(report.retest['right'], {'eligible': True, 'conditional_rate': '0'})

    def test_no_outcome_differs_from_zero_rate(self):
        ids, _ = self.prepare_pair(constant_version('pending'), constant_version('fail'))
        report = retrieve(self.night, compare_publish(self.night, *ids))
        self.assertEqual(report.decision, 'retest')
        self.assertEqual(report.retest['left'], {'eligible': False, 'conditional_rate': None})
        self.assertEqual(report.retest['right'], {'eligible': True, 'conditional_rate': '0'})

    def test_action_catalog_mismatch(self):
        left, right = constant_version('fail'), constant_version('fail')
        right['catalog']['Z'] = right['catalog'].pop('Y')
        right['transitions']['Z'] = right['transitions'].pop('Y')
        ids, _ = self.prepare_pair(left, right)
        before = self.archive_counts()
        with self.assertRaises(ValueError):
            compare_publish(self.night, *ids)
        self.assertEqual(self.archive_counts(), before)

    def test_incompatible_machine_models(self):
        left = constant_version('fail')
        right = {**left, 'machine_model': 'RQ-Wrong'}
        ids, _ = self.prepare_pair(left, right)
        with self.assertRaises(ValueError):
            compare_publish(self.night, *ids)
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_unknown_receipt(self):
        ids, _ = self.prepare_pair()
        with self.assertRaises(LookupError):
            compare_publish(self.night, ids[0], max(ids) + 1)
        self.assertEqual(self.archive_counts(), (0, 0, 0))
