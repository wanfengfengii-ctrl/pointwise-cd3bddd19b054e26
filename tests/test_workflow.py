from archive.retrieve import retrieve
from review.compare import compare_publish
from tests.fixtures import MACHINE, BenchCase, sample


class TestWorkflow(BenchCase):
    def test_longer_procedure_distinguishes_six_state_versions(self):
        state_ids = ['start', 'step1', 'step2', 'step3', 'good', 'bad']
        identity = [[int(source == target) for target in range(6)] for source in range(6)]
        sources = [1, 2, 3, 4, 4, 5]
        left_x = [[int(destination == target) for target in range(6)] for destination in sources]
        right_x = [row[:] for row in left_x]
        right_x[3] = [0, 0, 0, 0, 0, 1]
        classes = {'pending': state_ids[:4], 'pass': ['good'], 'fail': ['bad']}
        left = {
            'machine_model': MACHINE,
            'catalog': {'X': '标准挑战', 'Y': '校验等待', 'Z': '目视核对'},
            'observations': [{'action': 'X'}, {'action': 'Z'}],
            'state_ids': state_ids,
            'initial': [1, 0, 0, 0, 0, 0],
            'transitions': {'X': left_x, 'Y': identity, 'Z': identity},
            'classification': classes,
        }
        right = {**left, 'transitions': {'Z': identity, 'X': right_x, 'Y': identity}}
        ids, _ = self.prepare_pair(left, right)
        report = retrieve(self.night, compare_publish(self.night, *ids))
        self.assertEqual(report.decision, 'retest')
        self.assertTrue(all(action in left['catalog'] for action in report.retest['actions']))
        self.assertGreaterEqual(report.retest['actions'].count('X'), 4)
        self.assertEqual(report.retest['left'], {'eligible': True, 'conditional_rate': '1'})
        self.assertEqual(report.retest['right'], {'eligible': True, 'conditional_rate': '0'})

    def test_private_state_order_does_not_affect_review(self):
        left = sample('left')
        right = sample('left')
        order = (2, 0, 3, 1)
        right['state_ids'] = [left['state_ids'][position] for position in order]
        right['initial'] = [left['initial'][position] for position in order]
        right['transitions'] = {
            action: [[matrix[source][target] for target in order] for source in order]
            for action, matrix in left['transitions'].items()
        }
        ids, _ = self.prepare_pair(left, right)
        report = retrieve(self.night, compare_publish(self.night, *ids))
        self.assertEqual(report.decision, 'reuse')
        self.assertIsNone(report.retest)
