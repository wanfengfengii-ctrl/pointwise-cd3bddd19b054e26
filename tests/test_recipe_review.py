import json
import sqlite3
from fractions import Fraction

from archive.export import export_report
from archive.retrieve import retrieve
from exchange.issue import issue
from exchange.receipt import get_receipt, receive
from models.approval import approve_layered_model
from review.compare import compare_publish, compare_recipe_publish
from review.recipe_domain import RecipeDomain, parse_constraints
from tests.fixtures import SAMPLES, BenchCase


def recipe_sample():
    return json.loads((SAMPLES / 'recipes.json').read_text(encoding='utf-8'))


class RecipeBench(BenchCase):
    def setUp(self):
        super().setUp()
        self.recipe = recipe_sample()

    def seed_layered(self, side_key, predecessor=None, c_override=None):
        data = self.recipe
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

    def prepare_recipe_pair(self, *, right_c_override=None):
        left_revision, left_model = self.seed_layered('left')
        _, right_model = self.seed_layered('right', left_revision, right_c_override)
        left_id = receive(self.night, issue(self.store, left_model).to_json(), self.recipe['machine_model'])
        right_id = receive(self.night, issue(self.store, right_model).to_json(), self.recipe['machine_model'])
        self.disconnect_station()
        return left_id, right_id


class TestRecipeScenarios(RecipeBench):
    ACTIONS = ('X',)

    def test_full_simplex_tolerance_boundary(self):
        left_id, right_id = self.prepare_recipe_pair()
        strict = retrieve(
            self.night, compare_recipe_publish(self.night, left_id, right_id, self.ACTIONS, [], Fraction(1, 4)),
        )
        boundary = retrieve(
            self.night, compare_recipe_publish(self.night, left_id, right_id, self.ACTIONS, [], Fraction(1, 3)),
        )
        self.assertEqual(strict.decision, 'retest')
        self.assertEqual(boundary.decision, 'reuse')
        self.assertIsNone(boundary.retest)
        weights = {entry['layer']: entry['weight'] for entry in strict.retest['recipe']}
        self.assertEqual(weights, {'A': '1/2', 'B': '1/2', 'C': '0'})
        self.assertEqual(strict.retest['actions'], ['X'])
        self.assertEqual(strict.retest['left'], {'eligible': True, 'conditional_rate': '2/3'})
        self.assertEqual(strict.retest['right'], {'eligible': True, 'conditional_rate': '1/3'})

    def test_half_constraint_keeps_witness_inside_domain(self):
        left_id, right_id = self.prepare_recipe_pair()
        constraints = [({'C': 1}, '1/2'), ({'C': -1}, '-1/2')]
        retest = retrieve(
            self.night,
            compare_recipe_publish(self.night, left_id, right_id, self.ACTIONS, constraints, Fraction(1, 4)),
        )
        reuse = retrieve(
            self.night,
            compare_recipe_publish(self.night, left_id, right_id, self.ACTIONS, constraints, Fraction(1, 3)),
        )
        self.assertEqual((retest.decision, reuse.decision), ('retest', 'reuse'))
        weights = {entry['layer']: Fraction(entry['weight']) for entry in retest.retest['recipe']}
        # The witness lies on the requested face and remains independently
        # recomputable from the two receipts.
        self.assertEqual(weights['C'], Fraction(1, 2))
        self.assertEqual(weights['A'] + weights['B'], Fraction(1, 2))
        self.assertTrue(all(value >= 0 for value in weights.values()))
        for receipt_id, side_key in ((left_id, 'left'), (right_id, 'right')):
            body = get_receipt(self.night, receipt_id).body
            passed = sum(
                weights[name] * body.replay_layer(name, self.ACTIONS).passed for name in weights
            )
            decided = sum(
                weights[name] * body.replay_layer(name, self.ACTIONS).decided_mass for name in weights
            )
            expected = {
                'eligible': decided > 0,
                'conditional_rate': None if decided == 0 else str(passed / decided),
            }
            self.assertEqual(retest.retest[side_key], expected)

    def test_single_pending_point_is_reuse(self):
        left_id, right_id = self.prepare_recipe_pair()
        point = [({'C': 1}, 1), ({'C': -1}, -1)]
        report = retrieve(
            self.night, compare_recipe_publish(self.night, left_id, right_id, self.ACTIONS, point, 0),
        )
        self.assertEqual(report.decision, 'reuse')

    def test_eligibility_disagreement_witness(self):
        left_id, right_id = self.prepare_recipe_pair(
            right_c_override=self.recipe['right_C_with_zero_rate'],
        )
        point = [({'C': 1}, 1), ({'C': -1}, -1)]
        report = retrieve(
            self.night, compare_recipe_publish(self.night, left_id, right_id, self.ACTIONS, point, 0),
        )
        self.assertEqual(report.decision, 'retest')
        self.assertEqual(report.retest['recipe'], [
            {'layer': 'A', 'weight': '0'},
            {'layer': 'B', 'weight': '0'},
            {'layer': 'C', 'weight': '1'},
        ])
        self.assertEqual(report.retest['left'], {'eligible': False, 'conditional_rate': None})
        self.assertEqual(report.retest['right'], {'eligible': True, 'conditional_rate': '0'})

    def test_witness_is_independently_recomputable_from_receipts(self):
        left_id, right_id = self.prepare_recipe_pair()
        report_id = compare_recipe_publish(
            self.night, left_id, right_id, self.ACTIONS, [], Fraction(1, 4),
        )
        report = retrieve(self.night, report_id)
        weights = {entry['layer']: Fraction(entry['weight']) for entry in report.retest['recipe']}
        for receipt_id, side_key in ((left_id, 'left'), (right_id, 'right')):
            body = get_receipt(self.night, receipt_id).body
            passed = sum(
                weights[name] * body.replay_layer(name, self.ACTIONS).passed for name in weights
            )
            decided = sum(
                weights[name] * body.replay_layer(name, self.ACTIONS).decided_mass for name in weights
            )
            rate = None if decided == 0 else passed / decided
            self.assertEqual(
                report.retest[side_key],
                {'eligible': decided > 0, 'conditional_rate': None if rate is None else str(rate)},
            )


class TestRecipeRequests(RecipeBench):
    def test_empty_domain_and_bad_constraints(self):
        left_id, right_id = self.prepare_recipe_pair()
        with self.assertRaises(ValueError):
            compare_recipe_publish(
                self.night, left_id, right_id, ('X',), [({'A': 1}, -1)], 0,
            )
        with self.assertRaises(ValueError):
            compare_recipe_publish(
                self.night, left_id, right_id, ('X',), [({'Z': 1}, 0)], 0,
            )
        with self.assertRaises(ValueError):
            compare_recipe_publish(
                self.night, left_id, right_id, ('X',), [({'A': 1}, '1/2')], Fraction(-1),
            )
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_unknown_action_and_bad_procedure(self):
        left_id, right_id = self.prepare_recipe_pair()
        with self.assertRaises(ValueError):
            compare_recipe_publish(self.night, left_id, right_id, ('Z',), [], 0)
        with self.assertRaises(ValueError):
            compare_recipe_publish(self.night, left_id, right_id, 'X', [], 0)
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_machine_model_layer_set_and_version_mismatch(self):
        left_id, right_id = self.prepare_recipe_pair()
        self.reopen_station()
        # V1 items cannot drive a recipe comparison.
        plain = json.loads((SAMPLES / 'left.json').read_text(encoding='utf-8'))
        revision = self.record_version(plain)
        from models.approval import approve_model
        model_id = approve_model(
            self.store, revision, plain['state_ids'], plain['initial'],
            plain['transitions'], plain['classification'],
        )
        v1_id = receive(self.night, issue(self.store, model_id).to_json(), plain['machine_model'])
        with self.assertRaises(ValueError):
            compare_recipe_publish(self.night, v1_id, right_id, ('X',), [], 0)
        with self.assertRaises(ValueError):
            compare_publish(self.night, left_id, right_id)

    def test_unknown_receipt_is_lookup_error(self):
        left_id, right_id = self.prepare_recipe_pair()
        with self.assertRaises(LookupError):
            compare_recipe_publish(self.night, left_id, max(left_id, right_id) + 9, ('X',), [], 0)
        self.assertEqual(self.archive_counts(), (0, 0, 0))

    def test_layer_sets_must_match(self):
        data = self.recipe
        left_revision, left_model = self.seed_layered('left')
        side = data['right']
        layers = {name: value for name, value in side['layers'].items() if name != 'C'}
        revision = self.record_version(data, left_revision)
        model_id = approve_layered_model(
            self.store, revision, side['state_ids'], layers,
            side['transitions'], side['classification'],
        )
        left_id = receive(self.night, issue(self.store, left_model).to_json(), data['machine_model'])
        right_id = receive(self.night, issue(self.store, model_id).to_json(), data['machine_model'])
        self.disconnect_station()
        with self.assertRaises(ValueError):
            compare_recipe_publish(self.night, left_id, right_id, ('X',), [], 0)


class TestRecipeArchive(RecipeBench):
    def test_request_snapshot_and_ordered_parents(self):
        left_id, right_id = self.prepare_recipe_pair()
        constraints = [({'C': 1}, '1/2'), ({'C': -1}, '-1/2')]
        report_id = compare_recipe_publish(
            self.night, left_id, right_id, ('X', 'X'), constraints, Fraction(1, 4),
        )
        report = retrieve(self.night, report_id)
        self.assertEqual(report.request, (left_id, right_id))
        request = report.as_dict()['request']
        self.assertEqual(request['actions'], ['X', 'X'])
        self.assertEqual(request['constraints'], [[{'C': 1}, '1/2'], [{'C': -1}, '-1/2']])
        self.assertEqual(request['tolerance'], '1/4')
        parents = [parent.receipt_id for parent in report.parents]
        self.assertEqual(parents, [left_id, right_id])
        self.assertEqual([parent.position for parent in report.parents], [0, 1])
        self.assertEqual(export_report(self.night, report_id), export_report(self.night, report_id))

    def test_publish_failure_is_atomic(self):
        left_id, right_id = self.prepare_recipe_pair()
        before = self.night.execute(
            'SELECT count(*) FROM recipe_reports'
        ).fetchone()[0]
        self.night.executescript(
            '''CREATE TRIGGER test_recipe_fail BEFORE INSERT ON recipe_publication_receipts
               BEGIN
                   SELECT RAISE(ABORT, 'recipe commit refused');
               END'''
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'recipe commit refused'):
            compare_recipe_publish(self.night, left_id, right_id, ('X',), [], Fraction(1, 4))
        self.reopen_night()
        self.assertEqual(
            self.night.execute('SELECT count(*) FROM recipe_reports').fetchone()[0], before,
        )
        self.assertEqual(
            self.night.execute('SELECT count(*) FROM recipe_report_parents').fetchone()[0], 0,
        )

    def test_reopen_and_reinitialize_keep_recipe_reports(self):
        left_id, right_id = self.prepare_recipe_pair()
        report_id = compare_recipe_publish(
            self.night, left_id, right_id, ('X',), [], Fraction(1, 4),
        )
        frozen = export_report(self.night, report_id)
        self.reopen_night()
        from archive.publish import initialize_archive
        from exchange.receipt import initialize_receipts
        initialize_receipts(self.night)
        initialize_archive(self.night)
        self.assertEqual(export_report(self.night, report_id), frozen)
        with self.assertRaises(LookupError):
            retrieve(self.night, report_id + 100)

    def test_v1_and_recipe_report_identifiers_do_not_collide(self):
        left_id, right_id = self.prepare_recipe_pair()
        # Reopen station and also publish a classic V1 report on fresh receipts.
        self.reopen_station()
        plain_left = json.loads((SAMPLES / 'left.json').read_text(encoding='utf-8'))
        plain_right = json.loads((SAMPLES / 'right.json').read_text(encoding='utf-8'))
        from models.approval import approve_model
        rev_l = self.record_version(plain_left)
        model_l = approve_model(
            self.store, rev_l, plain_left['state_ids'], plain_left['initial'],
            plain_left['transitions'], plain_left['classification'],
        )
        rev_r = self.record_version(plain_right, rev_l)
        model_r = approve_model(
            self.store, rev_r, plain_right['state_ids'], plain_right['initial'],
            plain_right['transitions'], plain_right['classification'],
        )
        v1_left = receive(self.night, issue(self.store, model_l).to_json(), plain_left['machine_model'])
        v1_right = receive(self.night, issue(self.store, model_r).to_json(), plain_right['machine_model'])
        recipe_id = compare_recipe_publish(
            self.night, left_id, right_id, ('X',), [], Fraction(1, 4),
        )
        v1_report = compare_publish(self.night, v1_left, v1_right)
        self.assertNotEqual(recipe_id, v1_report)
        self.assertEqual(retrieve(self.night, recipe_id).decision, 'retest')
        self.assertIn(retrieve(self.night, v1_report).decision, ('reuse', 'retest'))


class TestRecipeDomain(BenchCase):
    def test_vertices_and_feasibility(self):
        names = ('A', 'B', 'C')
        domain = RecipeDomain(names, parse_constraints(names, []))
        self.assertEqual(
            set(domain.vertices),
            {
                (Fraction(1), Fraction(0), Fraction(0)),
                (Fraction(0), Fraction(1), Fraction(0)),
                (Fraction(0), Fraction(0), Fraction(1)),
            },
        )
        half = RecipeDomain(
            names, parse_constraints(names, [({'C': 1}, '1/2'), ({'C': -1}, '-1/2')]),
        )
        for point in half.vertices:
            self.assertEqual(point[2], Fraction(1, 2))
        single = RecipeDomain(
            names, parse_constraints(names, [({'C': 1}, 1), ({'C': -1}, -1)]),
        )
        self.assertEqual(single.vertices, ((Fraction(0), Fraction(0), Fraction(1)),))

    def test_one_layer_simplex(self):
        domain = RecipeDomain(('A',), parse_constraints(('A',), [({'A': 1}, 1), ({'A': -1}, -1)]))
        self.assertEqual(domain.vertices, ((Fraction(1),),))
