"""Synthetic-only checks. Never import or start the dashboard."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from study2.review_workload import (
    ENVIRONMENT_KEY, FORMAT, WorkloadUnavailable,
    render_current_review_workload, validate_summary)

ROOT = Path(__file__).resolve().parent


def synthetic():
    return dict(format=FORMAT, release_id='SYNTHETIC_RELEASE', decision_revision='SYNTHETIC_DECISION',
        exclusion_manifest_revision='SYNTHETIC_EXCLUSION',
        native_workload=dict(remaining_general_reviews=2, pending_routes=dict(correction=3, untraceable=4)),
        correction_bundles=5, source_groups_resolved=6, accepted_historical_policy_closures=7,
        original_answers=dict(total=3, same_child=1, different_children=2))


class UI:
    def __init__(self):
        self.metrics = []
        self.warnings = []
        self.tables = []
        self.captions = []
    def subheader(self, text):
        pass
    def warning(self, text):
        self.warnings.append(text)
    def caption(self, text):
        self.captions.append(text)
    def dataframe(self, rows, **kwargs):
        self.tables.append(rows)
    def columns(self, count):
        return [self] * count
    def metric(self, label, value):
        self.metrics.append((label, value))


class PresentationTests(unittest.TestCase):
    def render(self, value, **expected):
        ui = UI()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.json'
            path.write_text(json.dumps(value))
            with patch.dict('os.environ', {ENVIRONMENT_KEY: str(path)}):
                accepted = render_current_review_workload(ui,
                    release_id='SYNTHETIC_RELEASE', decision_revision='SYNTHETIC_DECISION',
                    exclusion_revision=expected.get('exclusion_revision', 'SYNTHETIC_EXCLUSION'))
        return accepted, ui

    def test_exact_bindings_render_supplied_counts_without_recalculation(self):
        value = synthetic()
        before = deepcopy(value)
        accepted, ui = self.render(value)
        self.assertTrue(accepted)
        self.assertFalse(ui.warnings)
        self.assertEqual([row['Count'] for row in ui.tables[0]], [2, 3, 4])
        self.assertEqual([v for _, v in ui.metrics], ['5', '6', '3', '7'])
        self.assertEqual(value, before)

    def test_zero_is_displayed_as_real_zero(self):
        value = synthetic()
        value['native_workload'] = dict(remaining_general_reviews=0, correction_comparisons=0)
        for key in ['correction_bundles', 'source_groups_resolved', 'accepted_historical_policy_closures']:
            value[key] = 0
        value['original_answers'] = dict(total=0, same_child=0, different_children=0)
        accepted, ui = self.render(value)
        self.assertTrue(accepted)
        self.assertEqual([row['Count'] for row in ui.tables[0]], [0, 0])
        self.assertEqual([v for _, v in ui.metrics], ['0'] * 4)

    def test_missing_unreadable_or_bad_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            invalid = Path(folder) / 'invalid.json'
            invalid.write_text('{')
            for supplied in ['', str(Path(folder) / 'absent.json'), str(invalid)]:
                with self.subTest(supplied_category='missing' if not supplied else 'unreadable'):
                    ui = UI()
                    with patch.dict('os.environ', {ENVIRONMENT_KEY: supplied}):
                        accepted = render_current_review_workload(ui,
                            release_id='SYNTHETIC_RELEASE', decision_revision='SYNTHETIC_DECISION')
                    self.assertFalse(accepted)
                    self.assertEqual(len(ui.warnings), 1)
                    self.assertFalse(ui.metrics or ui.tables)

    def test_each_stale_binding_fails_closed(self):
        for field in ['release_id', 'decision_revision', 'exclusion_manifest_revision']:
            with self.subTest(field=field):
                value = synthetic()
                value[field] = 'STALE_SYNTHETIC_REVISION'
                accepted, ui = self.render(value)
                self.assertFalse(accepted)
                self.assertTrue(ui.warnings)
                self.assertFalse(ui.metrics or ui.tables)
        value = synthetic()
        value['exclusion_manifest_revision'] = None
        self.assertTrue(self.render(value, exclusion_revision=None)[0])
        self.assertFalse(self.render(synthetic(), exclusion_revision=None)[0])

    def test_missing_invalid_or_inconsistent_counts_are_not_zero(self):
        variants = []
        for key in ['native_workload', 'correction_bundles', 'source_groups_resolved',
                    'accepted_historical_policy_closures', 'original_answers', 'exclusion_manifest_revision']:
            value = synthetic()
            del value[key]
            variants.append(value)
        for bad in [True, -1, 0.5, '0', None]:
            value = synthetic()
            value['correction_bundles'] = bad
            variants.append(value)
        value = synthetic()
        value['native_workload']['remaining_general_reviews'] = False
        variants.append(value)
        value = synthetic()
        value['original_answers']['total'] = 99
        variants.append(value)
        for index, value in enumerate(variants):
            with self.subTest(variant=index):
                accepted, ui = self.render(value)
                self.assertFalse(accepted)
                self.assertTrue(ui.warnings)
                self.assertFalse(ui.metrics or ui.tables)
