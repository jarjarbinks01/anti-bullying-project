"""Selected B/D policy through the existing scope and eligibility contracts."""
import json
import subprocess
from copy import deepcopy

import pandas as pd
import pytest

from static_scope_cases import synthetic_inputs
from study2.analysis_eligibility import (COPY_POLICY, MANIFEST_FORMAT, inventory_revision,
    manifest_revision, project_eligibility, scope_overlay, sha)
from study2.bd_pairing import POLICY, selected_parent_pairs, selected_parent_rows
from study2.static_scope import ScopeError, build_scope_index, query_scope
from study2.static_scope_client import JS_SOURCE


def inputs():
    records, rows, _, summary = synthetic_inputs()
    for r in records: r['raw_hash'] = sha(r['submission_id'])
    frame = pd.DataFrame(rows)
    pairs = selected_parent_pairs(frame)
    parents = selected_parent_rows(frame, pairs)
    summary.update(BD=3, bd_requires_same_adult=False, bd_pairing_policy=POLICY)
    return records, frame, parents, summary


def manifest(records, excluded):
    by_id={r['submission_id']:r for r in records}
    value=dict(format=MANIFEST_FORMAT, release_id='synthetic-mm-r02', inventory_revision=inventory_revision(records),
               status='accepted', approved_by='Synthetic reviewer', approved_at='2026-10-23T10:00:00+08:00',
               copy_policy=COPY_POLICY, entries=[dict(submission_id=s,version_id=by_id[s]['version_id']) for s in excluded])
    value['revision']=manifest_revision(value)
    return value


def sample(result,code):
    return next(r['count'] for r in result['samples'] if r['code']==code)


def test_child_linked_bd_reconciles_and_exclusion_never_reselects():
    records,frame,parents,summary=inputs();before=frame.copy(deep=True);original=deepcopy(records)
    index=build_scope_index(records,frame,parents,summary)
    assert index['meta']['adult']['policy']==POLICY
    assert index['meta']['adult']['evidence']=='selected_parent_longitudinal_artifact'
    assert sample(query_scope(index),'BD')==3
    accepted=manifest(records,['toy-record-kp0'])
    projection=project_eligibility(records,frame,parents,accepted,summary['release_id'])
    assert len(projection.canonical_members['BD'])==3 and len(projection.members['BD'])==2
    assert not any('toy-record-kp0' in pair for pair in projection.members['BD'])
    assert not any('toy-record-kb1' in pair for pair in projection.members['BD'])
    on=scope_overlay(index,records,projection,accepted['revision'],inventory_revision(records))
    assert sample(query_scope(on),'BD')==2
    node=subprocess.run(['node','-e',JS_SOURCE+"\nlet x=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(Study2Scope.query(x)));"],
                        input=json.dumps(on),text=True,capture_output=True,check=True,timeout=30)
    assert sample(json.loads(node.stdout),'BD')==2
    pd.testing.assert_frame_equal(frame,before);assert records==original


def test_policy_rejects_an_alternative_or_inconsistent_adult_evidence():
    records,frame,parents,summary=inputs()
    bad=parents.copy();index=bad.index[bad.submission_id.eq('toy-record-kp1')][0]
    bad.loc[index,'submission_id']='toy-record-kb1'
    with pytest.raises(ScopeError,match='child_bd_evidence_or_slot_mismatch'):
        build_scope_index(records,frame,bad,summary)
    bad=parents.copy();bad.loc[bad.index[0],'adult_continuity_confirmed']=True
    with pytest.raises(ScopeError,match='child_bd_evidence_or_slot_mismatch'):
        build_scope_index(records,frame,bad,summary)
