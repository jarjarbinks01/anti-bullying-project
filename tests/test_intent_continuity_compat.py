"""Synthetic proof-aware bridge. Real native continuity verifier, no RUN41 data."""
import base64
from copy import deepcopy
import gzip
import json

import pytest

from study2 import group_cleaning as policy, group_decision_intents as intents
from study2 import continuity_integration as integration, pair_continuity as native
from study2.group_cleaning_operator import _intent_partition_inputs
from study2.analysis_eligibility import sha,inventory_revision
from study2.common import digest

HISTORY='RUN_SYNTHETIC_HISTORY'
OLD='RUN_SYNTHETIC_OLD'
TARGET='RUN_SYNTHETIC_TARGET'
AT='2026-01-01T00:00:00+00:00'


def blob(value):return json.dumps(value,sort_keys=True).encode()
def checksum(value):
    import hashlib
    return hashlib.sha256(value).hexdigest()


def record(sid,contact,*,role='student',child=None,when=AT):
    raw={'synthetic':sid,'建立時間':when,'contact_01':contact}
    raw_hash=digest(raw)
    return dict(submission_id=sid,version_id=digest([sid,raw_hash]),raw_hash=raw_hash,
                role=role,raw=raw,answer={'contact_01':contact},source_id='SYNTHETIC_SOURCE',
                child_id=child or 'SYNTHETIC_CHILD_'+sid,selected_wave='T0',status='eligible',
                dob='2010-01-01',gender='0',school='SYNTHETIC SCHOOL')


def group(members,ids,*,passed=()):
    gid='GROUP_'+digest(['child_review_v1',sorted(members)])[:28]
    return gid,{'case_id':gid,'group_review':{'members':sorted(members),'comparison_ids':list(ids),
                'passed_pairs':list(passed),'conflicts':[],'manual_restrictions':[]}}


def manifest(rows,rid):
    return policy.exclusion_manifest(list(rows.values()),rid,[],operator='SYNTHETIC ONLY',at=AT)


def options(rows,rid,parts,auth,*,prior=None):
    result=dict(release_id=rid,main_revision='a'*64,rules_hash='b'*64,
                eric_manifest=manifest(rows,rid),source_evidence={},partitions=parts,
                user_exclusions={},authorization=auth)
    if prior is not None:result['prior_policy_manifest']=prior
    return result


def build_fixture(monkeypatch, *, retained_change=False):
    old={'SYN_A':record('SYN_A','91230001'),'SYN_B':record('SYN_B','93456789')}
    cases={'AB':{'case_id':'AB','kind':'identity','status':'pending','rule':'fuzzy_contact_child_demo',
                 'record_a':'SYN_A','record_b':'SYN_B'}}
    gid,g=group(['SYN_A','SYN_B'],['AB']);groups={gid:g};parts={gid:[['SYN_A'],['SYN_B']]}
    retained_changed=[]
    for i in range(7):
        members=['SYN_RETAINED_'+str(i)]
        if i==0 and retained_change:members=['SYN_RETAINED_0_'+str(j) for j in range(4)]
        ids=[]
        for j,sid in enumerate(members):
            old[sid]=record(sid,'9567'+str(i)+str(j)+'00')
            if j:
                cid='RETAINED_'+str(j);ids.append(cid)
                cases[cid]={'case_id':cid,'kind':'identity','status':'pending','rule':'fuzzy_contact_child_demo',
                            'record_a':members[0],'record_b':sid}
        other,v=group(members,ids);groups[other]=v;parts[other]=[[sid] for sid in members]
        if i==0 and retained_change:retained_changed=members
    auth=dict(workbook_sha256='c'*64,request_sha256='d'*64,
              partition_groups=sorted(parts),user_exclusion_groups=[])
    historical=policy.make_proposal(old,cases,groups,[],**options(old,HISTORY,parts,auth))
    receipt={'release_id':HISTORY,'proposal_revision':historical['revision'],
        'reason':'SYNTHETIC original scoped student answer',
        'review':{'format':'study2_group_cleaning_acceptance_v1','proposal_revision':historical['revision'],
                  'accepted':True,'reviewer':'SYNTHETIC INDEPENDENT REVIEWER','reason':'SYNTHETIC ONLY',
                  'review_manifest_sha256':'e'*64}}
    control={'format':'study2_group_policy_control_v1','policy_active':True,'release_id':HISTORY,
             'proposal_revision':historical['revision'],'partitions':parts}
    history_files={'authorization':blob(auth),'partitions':blob(parts),'groups':blob(groups),
                   'records':gzip.compress(b''.join(blob(r)+b'\n' for r in old.values()),mtime=0)}
    bundle={'format':'study2_group_cleaning_inputs_v1','release_id':HISTORY,
            'files':{k:{'path':'/SYNTHETIC_ONLY/'+k,'sha256':checksum(v)} for k,v in history_files.items()}}
    bundle['revision']=sha(bundle)
    generation={'proposal.json':blob(historical),'policy.json':blob(control),'receipt.json':blob(receipt)}
    generation_manifest=blob({'format':'study2_group_cleaning_generation_v1',
                              'files':{k:checksum(v) for k,v in generation.items()}})
    history={'bundle':blob(bundle),'files':history_files,'generation':generation,'manifest':generation_manifest}
    current=deepcopy(old)
    for sid in ['SYN_A','SYN_B']+retained_changed:
        current[sid]=record(sid,old[sid]['answer']['contact_01'],when='2026-01-02T00:00:00+00:00')
    current['SYN_P']=record('SYN_P','91230001',role='parent',child=current['SYN_A']['child_id'])
    current_cases={**cases,'PB':{'case_id':'PB','kind':'family','status':'pending','rule':'fuzzy_contact_child_demo',
                                'record_a':'SYN_P','record_b':'SYN_B'}}
    target_gid,target_group=group(['SYN_A','SYN_B','SYN_P'],['AB','PB'],
        passed=[{'a':'SYN_A','b':'SYN_P','rule':'exact_school_contact_child_demo'}])
    target_groups={k:deepcopy(v) for k,v in groups.items() if k!=gid};target_groups[target_gid]=target_group
    retained={k:v for k,v in parts.items() if k!=gid}
    target_auth={**auth,'partition_groups':sorted(retained)}
    prior_manifest={'inputs':{'sources':[{'source_id':'SYNTHETIC_SOURCE','sha256':'f'*64}]}}
    transitions={'format':'verified_source_time_export_v1','prior_release_id':OLD,'rows':[]}
    for i,sid in enumerate(['SYN_A','SYN_B']+retained_changed,1):
        transitions['rows'].append(dict(sequence=i,submission_id=sid,source_id='SYNTHETIC_SOURCE',
            input_sha256='f'*64,old_version=old[sid]['version_id'],new_version=current[sid]['version_id'],
            old_raw_hash=old[sid]['raw_hash'],new_raw_hash=current[sid]['raw_hash'],
            old_observed_at=AT,new_observed_at='2026-01-02T00:00:00+00:00',slot=i,
            operation_id='SYNTHETIC_TIME_'+str(i),authorizer='SYNTHETIC ONLY',
            reason='SYNTHETIC approved time-only transition',approved_at=AT))
    prior_manual=manifest(current,OLD);prior_policy=manifest(current,OLD)
    profile={'historical_bundle_sha256':checksum(history['bundle']),
        'historical_authorization_sha256':checksum(history_files['authorization']),
        'historical_partitions_sha256':checksum(history_files['partitions']),
        'historical_policy_head_sha256':checksum(generation_manifest),
        'historical_workbook_sha256':auth['workbook_sha256'],'historical_request_sha256':auth['request_sha256'],
        'historical_group_id':gid,'prior_release_id':OLD,'target_release_id':TARGET,'target_group_id':target_gid,
        'target_inventory_revision':inventory_revision(current.values()),
        'transition_export_sha256':checksum(blob(transitions)),'prior_run_manifest_sha256':checksum(blob(prior_manifest)),
        'prior_manual_revision':prior_manual['revision'],'prior_policy_revision':prior_policy['revision'],
        'prior_scope_sha256':native.scope_fingerprint(OLD,current,target_group,current_cases),
        'target_scope_sha256':native.scope_fingerprint(TARGET,current,target_group,current_cases)}
    monkeypatch.setitem(integration.PROFILES,TARGET,profile)
    encoded={'bundle':base64.b64encode(history['bundle']).decode(),
             'manifest':base64.b64encode(history['manifest']).decode(),
             'files':{k:base64.b64encode(v).decode() for k,v in history_files.items()},
             'generation':{k:base64.b64encode(v).decode() for k,v in generation.items()}}
    payload={'format':integration.PAYLOAD_FORMAT,'history':encoded,
             'transition_export':base64.b64encode(blob(transitions)).decode(),
             'prior_run_manifest':base64.b64encode(blob(prior_manifest)).decode(),
             'prior_records':deepcopy(current),'prior_cases':deepcopy(current_cases),'prior_group':deepcopy(target_group),
             'prior_manual_manifest':prior_manual,'prior_policy_manifest':prior_policy}
    collection=intents.migrate(historical,old,cases,groups,receipt)
    opts=options(current,TARGET,retained,target_auth,prior=manifest(current,TARGET))
    opts['decision_intents']=collection
    data={'records':current,'cases':current_cases,'groups':target_groups,'decisions':[],'continuity':payload}
    return data,opts,profile,history,current,target_group,collection


@pytest.fixture
def fixture(monkeypatch):
    return build_fixture(monkeypatch)


def test_existing_proof_accepts_original_scope_and_seven_partitions(fixture):
    data,opts,profile,history,current,target_group,collection=fixture
    before=deepcopy(data['records'])
    parts,auth=_intent_partition_inputs(TARGET,{**data,'partitions':opts['partitions'],'authorization':opts['authorization']})
    assert parts==opts['partitions'] and auth==opts['authorization']
    opts['partitions']=parts;opts['authorization']=auth
    proposal=integration.bound_proposal(data,opts)
    native_scope=policy.classify_scope(data['records'],target_group,data['cases'])
    assert proposal['projection']['scopes'][profile['target_group_id']]==native_scope
    assert len(proposal['partitions'])==7 and proposal['partitions']==opts['partitions']
    deferred=[e for e in proposal['decision_application']['entries'] if e['status']=='requires_existing_continuity_proof']
    assert len(deferred)==1 and deferred[0]['subjects']==['SYN_A','SYN_B']
    assert all('decision_ids' not in row for row in native_scope['closures'])
    assert proposal['decision_intents']==collection and data['records']==before
    proof=proposal['historical_continuity']['proof']
    assert proof['target']['existing_parent_atom']=={'parent':'SYN_P','student':'SYN_A','rule':'exact_school_contact_child_demo'}
    control={'policy_active':True,'release_id':TARGET,'proposal_revision':proposal['revision'],
             'historical_continuity_revision':proposal['historical_continuity']['revision'],
             'partitions':proposal['partitions'],'inventory_revision':profile['target_inventory_revision'],
             'main_revision':opts['main_revision']}
    receipt={'review':{'accepted':True,'proposal_revision':proposal['revision']}}
    integration.check_generation(control,proposal,receipt)
    unbound=policy.make_proposal(data['records'],data['cases'],data['groups'],[],**opts)
    with pytest.raises(Exception,match='continuity_generation_missing'):
        integration.check_generation(control,unbound,receipt)


def test_empty_partitions_still_fail_the_unchanged_native_guard(fixture):
    data,opts,*_=deepcopy(fixture)
    opts['partitions']={};opts['authorization']['partition_groups']=[]
    with pytest.raises(ValueError,match='retained_partitions_changed'):
        integration.bound_proposal(data,opts)


def test_proof_preserves_parent_only_native_edge_without_inventing_a_student_edge(fixture):
    data,opts,profile,*_=fixture
    target=profile['target_group_id']
    data['cases'].pop('AB');data['groups'][target]['group_review']['comparison_ids']=['PB']
    data['continuity']['prior_cases']=deepcopy(data['cases'])
    data['continuity']['prior_group']=deepcopy(data['groups'][target])
    profile['prior_scope_sha256']=native.scope_fingerprint(OLD,data['records'],data['groups'][target],data['cases'])
    profile['target_scope_sha256']=native.scope_fingerprint(TARGET,data['records'],data['groups'][target],data['cases'])
    proposal=integration.bound_proposal(data,opts)
    scope=proposal['projection']['scopes'][target]
    assert scope==policy.classify_scope(data['records'],data['groups'][target],data['cases'])
    assert {cid for row in scope['closures'] for cid in row['comparison_ids']}=={'PB'}
    entry=next(e for e in proposal['decision_application']['entries'] if e['group_id']==target)
    assert entry['subjects']==['SYN_A','SYN_B'] and entry['comparison_ids']==[]
    assert entry['status']=='requires_existing_continuity_proof'


def test_parent_relationship_change_is_not_inherited_from_student_decision(fixture):
    data,opts,*_=deepcopy(fixture)
    data['records']['SYN_P']['child_id']=data['records']['SYN_B']['child_id']
    with pytest.raises(ValueError,match='continuity_evidence_invalid'):
        integration.bound_proposal(data,opts)


def test_wrong_original_subject_pin_cannot_borrow_the_proof(fixture):
    data,opts,*_=deepcopy(fixture)
    collection=opts['decision_intents']
    for i,item in enumerate(collection['intents']):
        if len(item['subjects'])==2:
            changed={k:v for k,v in item.items() if k!='revision'}
            changed['subjects'][0]['raw_hash']='0'*64
            collection['intents'][i]=intents.sealed(changed)
    opts['decision_intents']=intents.sealed({k:v for k,v in collection.items() if k!='revision'})
    with pytest.raises(Exception,match='intent_continuity_subjects_or_authorization_changed'):
        integration.bound_proposal(data,opts)


def test_even_a_pinned_transition_cannot_change_non_time_raw_fields(fixture):
    data,opts,profile,history,*_=deepcopy(fixture)
    _,_,_,_,old_records,_=native._history(history,profile)
    current=data['records'];row=current['SYN_A'];row['raw']['not_a_time_field']='CHANGED SYNTHETIC VALUE'
    row['raw_hash']=digest(row['raw']);row['version_id']=digest(['SYN_A',row['raw_hash']])
    exported=json.loads(base64.b64decode(data['continuity']['transition_export']))
    for transition in exported['rows']:
        if transition['submission_id']=='SYN_A':
            transition['new_raw_hash']=row['raw_hash'];transition['new_version']=row['version_id']
    raw=blob(exported);profile['transition_export_sha256']=checksum(raw)
    prior=base64.b64decode(data['continuity']['prior_run_manifest'])
    with pytest.raises(native.ContinuityError,match='source_time_non_time_change'):
        native._lineage(old_records,current,raw,prior,profile)
