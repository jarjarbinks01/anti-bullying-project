"""Synthetic compatibility checks for the single portable presentation boundary."""
import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from test_descriptives import inputs
from study2 import analysis_eligibility as native_eligibility
from study2 import descriptives as native
from study2 import static_assets
from study2.bd_pairing import POLICY, selected_parent_pairs, selected_parent_rows
from study2.common import PipelineError
from study2.presentation import analysis_eligibility as presentation_eligibility
from study2.presentation import descriptives as presentation


def test_reviewed_client_bytes_preserved():
    # HTML/CSS retain the accepted pre-consolidation export. APP_JS also includes
    # the reviewed Back/Forward fix, covered by the navigation browser tests.
    expected = {
        'HTML': '1b0fa232560909db86a615134681507ccfbaca6cc7458fe9ffbaf928dedd30fa',
        'APP_JS': 'f0e63b82cf51adecb52ea6a05e7d7cde3b646049fb543332c544ad4407f3791f',
        'STYLES': 'ccb63b546f534f2d83cddee52970296080c284e0271d4f94940a0bf3c1bc8264',
    }
    for name, digest in expected.items():
        assert hashlib.sha256(getattr(static_assets, name).encode()).hexdigest() == digest


def test_selected_child_is_not_same_adult_and_science_is_reused(inputs):
    frame, historical, measurements, _ = inputs
    pairs = selected_parent_pairs(frame)
    assert pairs.adult_status.eq('unconfirmed').all()
    selected = selected_parent_rows(frame, pairs)
    rows = presentation.cohort(frame, selected, measurements, 'acbd', 'parent')
    assert len(rows) == 4 and not rows.adult_continuity_confirmed.any()
    assert not presentation.paired_changes(rows, 'parent').variable_id.str.startswith('PHQ_').any()
    # Historical confirmed-adult artifacts keep native meaning.
    old = native.cohort(frame, historical, measurements, 'acbd', 'parent')
    compatible = presentation.cohort(frame, historical, measurements, 'acbd', 'parent')
    pd.testing.assert_frame_equal(old, compatible)
    assert presentation.cohort is native.cohort
    assert presentation.statistics is native.statistics
    assert presentation.paired_changes is native.paired_changes


def test_exact_adult_evidence_and_exclusions_do_not_reselect(inputs):
    frame, _, measurements, _ = inputs
    tracking = pd.DataFrame([
        dict(child_id='one', parent_t0_id='one-parent-T0', parent_t1_id='one-parent-T1',
             adult_status='same', adult_rule='synthetic-confirmation'),
        dict(child_id='two', parent_t0_id='stale-parent-T0', parent_t1_id='two-parent-T1',
             adult_status='same', adult_rule='synthetic-stale'),
    ])
    pairs = selected_parent_pairs(frame, tracking=tracking)
    assert dict(zip(pairs.child_id, pairs.adult_status)) == {'one': 'same', 'two': 'unconfirmed'}
    rows = presentation.cohort(frame, selected_parent_rows(frame, pairs), measurements, 'acbd', 'parent')
    phq = presentation.paired_changes(rows, 'parent').query("variable_id == 'PHQ_total'")
    # Native paired inference refuses a mixed continuity cohort rather than
    # silently treating all selected-child pairs as the same adult.
    assert phq.empty
    confirmed = rows.loc[rows.adult_continuity_confirmed].copy()
    phq = presentation.paired_changes(confirmed, 'parent').query("variable_id == 'PHQ_total'")
    assert len(phq) == 1 and phq.iloc[0]['paired_valid_n'] == 1
    excluded = selected_parent_pairs(frame, tracking=tracking, excluded=['one-parent-T1'])
    assert excluded.child_id.tolist() == ['two']


def test_inconsistent_adult_evidence_rejected(inputs):
    frame, _, measurements, _ = inputs
    selected = selected_parent_rows(frame, selected_parent_pairs(frame))
    selected['adult_continuity_confirmed'] = True
    with pytest.raises(PipelineError, match='adult-continuity'):
        presentation.cohort(frame, selected, measurements, 'acbd', 'parent')


def test_candidate_scope_does_not_relax_native_validation():
    manifest = dict(format='study2_candidate_exclusion_manifest_v1', release_id='SYNfixture',
                    inventory_revision=native_eligibility.inventory_revision([]),
                    status='draft_unapplied', copy_policy=native_eligibility.COPY_POLICY,
                    entries=[], source_manifest_revision='a' * 64)
    manifest['revision'] = native_eligibility.manifest_revision(manifest)
    with pytest.raises(native_eligibility.EligibilityError):
        presentation_eligibility.validate_manifest(manifest, [], 'SYNfixture')
    with presentation_eligibility.candidate_exclusion_scope(manifest['revision']):
        assert presentation_eligibility.validate_manifest(manifest, [], 'SYNfixture') == frozenset()
        with pytest.raises(native_eligibility.EligibilityError):
            native_eligibility.validate_manifest(manifest, [], 'SYNfixture')
    with pytest.raises(native_eligibility.EligibilityError):
        presentation_eligibility.validate_manifest(manifest, [], 'SYNfixture')


def test_controls_pin_and_environment_restoration(tmp_path, monkeypatch):
    from study2.controls_capture import read_pin, selected_environment, capture, code_revision
    path = tmp_path / 'request.json'
    path.write_text('{"synthetic": true}')
    pin = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    assert read_pin(pin) == {'synthetic': True}
    path.write_text('{}')
    with pytest.raises(ValueError, match='source_changed'):
        read_pin(pin)
    monkeypatch.setenv('STUDY2_REVIEW_STATE_DIR', 'original-synthetic')
    with pytest.raises(RuntimeError):
        with selected_environment({'environment': {'STUDY2_REVIEW_STATE_DIR': 'temporary-synthetic'}},
                                  {'STUDY2_REVIEW_STATE_DIR'}):
            assert os.environ['STUDY2_REVIEW_STATE_DIR'] == 'temporary-synthetic'
            raise RuntimeError('synthetic failure')
    assert os.environ['STUDY2_REVIEW_STATE_DIR'] == 'original-synthetic'
    assert len(code_revision()) == 64
    with pytest.raises(ValueError, match='backend_code_changed'):
        capture(dict(config=None, selection=None, context=None, candidate=None, code_revision='0' * 64))


def test_canonical_cli_defaults_are_explicit(monkeypatch, tmp_path, capsys):
    from study2 import static_export
    called = {}
    monkeypatch.setattr(static_export, 'load_config', lambda path: {'synthetic': True})
    monkeypatch.setattr(static_export, 'export_static', lambda cfg, output, **kw: called.update(kw))
    static_export.main(['--output', str(tmp_path / 'not-written')])
    assert called['default_eligibility'] == 'on' and called['project_selected_bd'] is True


def test_mask_projection_retains_selected_adult_evidence(inputs):
    frame, _, measurements, _ = inputs
    records = [dict(submission_id=row.submission_id, child_id=row.child_id,
                    role=row.role, selected_wave=row.wave, status='eligible',
                    version_id=hashlib.sha256(row.submission_id.encode()).hexdigest(),
                    raw_hash=hashlib.sha256(row.submission_id.encode()).hexdigest())
               for row in frame.itertuples()]
    parents = selected_parent_rows(frame, selected_parent_pairs(frame))
    projection = presentation_eligibility.project_eligibility(
        records, frame, parents, None, 'SYNfixture', enabled=False)
    cohorts = presentation_eligibility.projected_cohorts(records, frame, parents, measurements, projection)
    bd = next(rows for mode, role, rows in cohorts if mode == 'acbd' and role == 'parent')
    assert len(bd) == 4 and not bd.adult_continuity_confirmed.any()


def test_formal_site_rejects_stale_context_and_path_escape(tmp_path):
    from study2.formal_dashboard import pin, verify_site
    from study2.static_release_context import FIELDS, HASH_FIELDS, FLAG_FIELDS, WORK_FIELDS, FORMAT
    from study2.analysis_eligibility import sha
    context = {key: 'a' * 64 for key in HASH_FIELDS}
    context.update(format=FORMAT, release_id='SYNfixture', run_id='SYNrun',
                   flags={key: ('b' * 64 if key.endswith('revision') else 0) for key in FLAG_FIELDS},
                   workload={key: 0 for key in WORK_FIELDS})
    context['revision'] = sha({k: v for k, v in context.items() if k != 'revision'})
    public = dict(context, default_eligibility='on', workload_scope='release_wide_applied_controls',
                  export_program_hash='c' * 64)
    site = tmp_path / 'formal'
    site.mkdir()
    for name in ('index.html', 'preview.mjs'):
        (site / name).write_text('synthetic fixture')
    manifest = dict(release_id=context['release_id'], release_context=public,
                    bd_projection=dict(policy=POLICY, source_release_id=context['release_id']),
                    files={name: pin(site / name)['sha256'] for name in ('index.html', 'preview.mjs')})
    path = site / 'snapshot-manifest.json'
    path.write_text(json.dumps(manifest))
    config = dict(site=str(site), manifest_sha256=pin(path)['sha256'])
    assert verify_site(config, context, tmp_path) == site
    stale = dict(context, review_control_revision='d' * 64)
    stale['revision'] = sha({k: v for k, v in stale.items() if k != 'revision'})
    with pytest.raises(ValueError, match='current published controls'):
        verify_site(config, stale, tmp_path)
    manifest['files']['../outside.txt'] = 'f' * 64
    path.write_text(json.dumps(manifest))
    config['manifest_sha256'] = pin(path)['sha256']
    with pytest.raises(ValueError, match='Unsafe'):
        verify_site(config, context, tmp_path)
