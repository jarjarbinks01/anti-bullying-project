"""Reviewable BD projection, using invented release and exclusion evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from study2.bd_pairing import POLICY, project_published_selection
from study2.common import PipelineError, file_hash
from study2.analysis_eligibility import manifest_revision
from study2.static_export import export_static, validate_snapshot
from test_static_quality_integration import load_script, tree_bytes
from test_static_release_context import context, publication


def setup_projection(root):
    value, manifest, _ = publication(root)
    folder, summary, frame = value['folder'], value['summary'], value['frame']
    summary['bd_requires_same_adult'] = True
    (folder / 'summary.json').write_text(json.dumps(summary))
    with sqlite3.connect(Path(value['cfg']['state_dir']) / 'study2.sqlite') as db:
        db.execute('UPDATE runs SET stats_json=?', (json.dumps(summary),))
        db.execute('UPDATE releases SET stats_json=?', (json.dumps(summary),))
    parents = frame.loc[frame.role.eq('parent')]
    by_child = {child: dict(zip(group.wave, group.submission_id)) for child, group in parents.groupby('child_id')}
    rows = []
    for child, slots in sorted(by_child.items()):
        if not {'T0', 'T1'} <= set(slots):
            continue
        i = len(rows)
        rows.append(dict(child_id=child, parent_t0_id=slots['T0'], parent_t1_id=slots['T1'],
            adult_status=('same', 'different', 'unconfirmed')[i % 3],
            adult_rule=('reviewer_confirmed_same_adult', 'reviewer_rejected_same_adult', '')[i % 3],
            registration_state='active', followup_status='both_complete'))
    pd.DataFrame(rows).to_parquet(folder / 'dyad_tracking.parquet', index=False)
    names = ('summary.json', 'analysis.parquet', 'parent_longitudinal.parquet', 'dyad_tracking.parquet')
    (folder / 'checksums.json').write_text(json.dumps({name: file_hash(folder / name) for name in names}))
    record = next(r for r in value['records'] if r['submission_id'] == 'toy-record-kp0')
    manifest['entries'] = [dict(submission_id=record['submission_id'], version_id=record['version_id'])]
    manifest['revision'] = manifest_revision(manifest)
    return value, manifest, context(summary['release_id'], 'synthetic-run', manifest)


def test_projection_is_pure_and_retains_exact_pair_evidence(tmp_path):
    value, _, _ = setup_projection(tmp_path / 'inputs')
    tracking = pd.read_parquet(value['folder'] / 'dyad_tracking.parquet')
    before = value['frame'].copy(deep=True); old_summary = deepcopy(value['summary'])
    frame, parents, summary = project_published_selection(before, tracking, old_summary)
    pd.testing.assert_frame_equal(before, value['frame'])
    assert old_summary == value['summary']
    assert summary['bd_pairing_policy'] == POLICY and summary['BD'] == 3
    assert parents.groupby('child_id').bd_adult_status.first().tolist() == ['same', 'different', 'unconfirmed']
    assert len(parents) == 6 and frame.loc[frame.role.eq('parent'), 'longitudinal'].all()
    with pytest.raises(PipelineError, match='legacy_source_policy_required'):
        project_published_selection(frame, tracking, summary)


def test_full_projected_export_binds_off_on_and_source_without_mutation(tmp_path, monkeypatch):
    import study2.static_export as module
    monkeypatch.setattr(module, 'GROUPS', {'all': 'All'})
    value, manifest, ctx = setup_projection(tmp_path / 'inputs')
    original = tree_bytes(value['folder'])
    site = tmp_path / 'review-site'
    export_static(value['cfg'], site, manual_manifest=manifest, release_context=ctx,
                  default_eligibility='on', project_selected_bd=True)
    assert tree_bytes(value['folder']) == original
    off = load_script(site / 'snapshot.js', 'window.STUDY2_SNAPSHOT=')
    raw = (site / 'manual-exclusion.js').read_text().split('window.STUDY2_MANUAL_EXCLUSION=', 1)[1]
    wrapper = json.loads(raw.removesuffix(';\n'))
    on = wrapper['on']['snapshot']
    published = json.loads((site / 'snapshot-manifest.json').read_text())
    assert off['counts']['BD'] == 3 and on['counts']['BD'] == 2
    assert off['bd_pairing_policy'] == POLICY and on['bd_pairing_policy'] == POLICY
    assert off['bd_projection'] == on['bd_projection'] == published['bd_projection']
    assert off['bd_projection']['source_release_id'] == value['summary']['release_id']
    assert wrapper['revision'] == manifest['revision']
    label = next(item['label'] for item in off['samples'] if item['sample'] == 'BD')
    assert 'same child' in label and 'may differ' in label
    assert 'bd_projection_revision' in (site / 'app.js').read_text()
    bad = deepcopy(off); bad['bd_projection']['policy'] = 'changed'
    with pytest.raises(PipelineError, match='provenance'):
        validate_snapshot(bad)


def test_projection_rejects_changed_source_checksum(tmp_path):
    value, manifest, ctx = setup_projection(tmp_path / 'inputs')
    checksums = value['folder'] / 'checksums.json'
    body = json.loads(checksums.read_text()); body['analysis.parquet'] = '0' * 64
    checksums.write_text(json.dumps(body))
    with pytest.raises(PipelineError, match='published checksums'):
        export_static(value['cfg'], tmp_path / 'rejected', manual_manifest=manifest,
                      release_context=ctx, project_selected_bd=True)
    assert not (tmp_path / 'rejected').exists()
