"""Synthetic checks; never opens research data or a control store."""

import copy
import json
import unittest

from study2.burst_hold_view import burst_hold_view
from study2.analysis_eligibility import sha


def hold(i, reason='source_proof_shape_or_membership'):
    return {'group_id': f'synthetic-scope-{i}', 'outcome': 'hold', 'reasons': [reason],
            'member_pins': [{'submission_id': f'synthetic-subject-{i}', 'version_id': 'v1'}]}


def proposal(holds):
    value = {'format': 'study2_group_cleaning_proposal_v1', 'burst_holds': holds,
             'projection': {'counts': {'held_scopes': 0, 'pending_decision_intents': 2}},
             'flag_entries': [{'submission_id': 'synthetic-preserved', 'version_id': 'v1'}]}
    value['revision'] = sha(value)
    return value


class BurstHoldViewTest(unittest.TestCase):
    def test_separate_counts_no_flag_or_input_changes(self):
        value = proposal([hold(i) for i in range(12)])
        before = copy.deepcopy(value)
        model = burst_hold_view(value, validated_revision=value['revision'])
        self.assertEqual(model['scope_count'], 12)
        self.assertEqual(model['distinct_submission_count'], 12)
        self.assertEqual(model['reason_scope_counts'], {'source_proof_shape_or_membership': 12})
        self.assertEqual(value, before)
        self.assertEqual(value['projection']['counts']['held_scopes'], 0)
        self.assertEqual(value['projection']['counts']['pending_decision_intents'], 2)
        self.assertNotIn('synthetic-subject-', json.dumps(model))
        self.assertNotIn('synthetic-preserved', json.dumps(model))

    def test_empty_is_distinct_from_missing(self):
        value = proposal([])
        self.assertEqual(burst_hold_view(value, validated_revision=value['revision'])['scope_count'], 0)
        value = proposal([])
        del value['burst_holds']
        value['revision'] = sha({key: item for key, item in value.items() if key != 'revision'})
        with self.assertRaisesRegex(ValueError, 'burst_hold_inventory_unavailable'):
            burst_hold_view(value, validated_revision=value['revision'])

    def test_rejects_wrong_revision_or_unexpected_reason(self):
        with self.assertRaises(ValueError):
            burst_hold_view(proposal([hold(1)]), validated_revision='b' * 64)
        value = proposal([hold(1)])
        value['burst_holds'].append(hold(2))
        with self.assertRaises(ValueError):
            burst_hold_view(value, validated_revision=value['revision'])
        value = proposal([hold(1, 'unknown')])
        with self.assertRaises(ValueError):
            burst_hold_view(value, validated_revision=value['revision'])

    def test_rejects_duplicate_scope_and_member(self):
        value = proposal([hold(1), hold(1)])
        with self.assertRaises(ValueError):
            burst_hold_view(value, validated_revision=value['revision'])
        x = hold(2)
        x['member_pins'].append(copy.deepcopy(x['member_pins'][0]))
        value = proposal([x])
        with self.assertRaises(ValueError):
            burst_hold_view(value, validated_revision=value['revision'])

    def test_rejects_conflicting_versions_across_scopes(self):
        x, y = hold(1), hold(2)
        y['member_pins'] = [{'submission_id': x['member_pins'][0]['submission_id'], 'version_id': 'v2'}]
        value = proposal([x, y])
        with self.assertRaises(ValueError):
            burst_hold_view(value, validated_revision=value['revision'])


if __name__ == '__main__':
    unittest.main()
