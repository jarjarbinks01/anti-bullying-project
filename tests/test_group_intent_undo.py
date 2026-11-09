"""Synthetic immutable generations: undo retains original migration authority."""
import json
from copy import deepcopy

import pytest

from study2 import group_cleaning_operator as op
from study2.group_cleaning import PolicyError
from study2.analysis_eligibility import sha
from study2.common import file_hash
from test_group_cleaning import fixture_bundle, proposal_review


def accepted_then_undone(tmp_path):
    bundle,_=fixture_bundle(tmp_path)
    b=op._json(bundle)
    for name,value in [('partitions',{'group':[[str(i)] for i in range(6)]}),
                       ('authorization',dict(workbook_sha256='c'*64,request_sha256='d'*64,
                                             partition_groups=['group'],user_exclusion_groups=[]))]:
        path=tmp_path/(name+'.json');path.write_text(json.dumps(value))
        b['files'][name]['sha256']=file_hash(path)
    b['revision']=sha({k:v for k,v in b.items() if k!='revision'});bundle.write_text(json.dumps(b))
    p,q=proposal_review(tmp_path,bundle);root=tmp_path/'control'
    op.apply(root,bundle,p,q,operator='synthetic',reason='original accepted boundary')
    accepted=op.read_active(root)
    second=op.undo(root,bundle,expected_head=accepted['pointer']['manifest_sha256'],
                   operator='synthetic',reason='turn policy off')
    op.undo(root,bundle,expected_head=second['pointer']['manifest_sha256'],operator='synthetic',reason='restore original')
    return root,bundle,accepted


def test_undo_migrates_original_acceptance_and_preserves_history(tmp_path):
    root,bundle,accepted=accepted_then_undone(tmp_path)
    active=op.read_active(root);before=deepcopy(active['receipt'])
    assert active['receipt']['operation']=='undo' and 'review' not in active['receipt']
    _,source,_=op.load_bundle(bundle)
    migrated=op._migrate_active_intents(active,source)
    assert len(migrated['intents'])==1
    assert migrated['intents'][0]['origin']['receipt']==accepted['receipt']
    assert migrated['intents'][0]['reason']=='original accepted boundary'
    assert op.read_active(root)['receipt']==before
    assert len(list(root.glob('gen_*')))==3


@pytest.mark.parametrize('damage',['missing','tampered'])
def test_undo_rejects_missing_or_tampered_original_acceptance(tmp_path,damage):
    root,bundle,accepted=accepted_then_undone(tmp_path)
    target=accepted['folder']/'receipt.json'
    if damage=='missing':target.unlink()
    else:target.write_text('{}')
    active=op.read_active(root);_,source,_=op.load_bundle(bundle)
    with pytest.raises(PolicyError,match='generation_file_changed'):
        op._migrate_active_intents(active,source)


def test_repeated_undo_follows_restoration_not_previous_head(tmp_path):
    root,bundle,accepted=accepted_then_undone(tmp_path)
    for reason in ['restore off state','restore prior undo']:
        active=op.read_active(root)
        op.undo(root,bundle,expected_head=active['pointer']['manifest_sha256'],operator='synthetic',reason=reason)
    active=op.read_active(root);_,source,_=op.load_bundle(bundle)
    assert op._migrate_active_intents(active,source)['intents'][0]['origin']['receipt']==accepted['receipt']
    assert len(list(root.glob('gen_*')))==5


def test_missing_restoration_link_cannot_borrow_other_acceptance(tmp_path):
    root,bundle,_=accepted_then_undone(tmp_path)
    active=op.read_active(root);_,source,_=op.load_bundle(bundle)
    del active['receipt']['restored_pointer']
    with pytest.raises(PolicyError,match='intent_origin_restoration_missing'):
        op._migrate_active_intents(active,source)
