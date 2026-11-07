"""Synthetic accepted snapshots; no live data, DB connection or state APIs."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from study2 import administrative_carry_preview as carry, group_intent_review as review
from study2 import group_cleaning as policy, review_dispositions as dispositions
from study2.analysis_eligibility import sha
from study2.common import digest
from test_group_intent_review import UI, save


def raw(value):return (json.dumps(value,sort_keys=True,ensure_ascii=False)+'\n').encode()
def h(value):return hashlib.sha256(value).hexdigest()


@pytest.fixture
def snapshots(monkeypatch):
    cases=[{'case_id':f'SYN_CASE_{i:02d}','route':'correction','record_a':f'SYN_A_{i}','record_b':f'SYN_B_{i}',
            'version_a':'SYN_VA','version_b':'SYN_VB','evidence_hash':'a'*64,'reasons':['SYN_MISSING_FIELD']} for i in range(65)]
    source_rules,target_rules='1'*64,'2'*64
    source={'release_id':'RUN_SYN_OLD','rules_hash':source_rules,'decision_revision':'d'*64,
            'source_bindings':{'original_authority':'b'*64},'output_bindings':{'source_inventory':'c'*64}}
    target={**deepcopy(source),'release_id':'RUN_SYN_TARGET','rules_hash':target_rules,
            'output_bindings':{'correction_inventory':digest(cases),'native_case_file':'e'*64,'run_manifest':'f'*64}}
    base={'release_id':target['release_id'],'rules_hash':target_rules,'main_revision':'9'*64,'view_revision':'8'*64}
    proposal={'format':policy.PROPOSAL_FORMAT,'base':base,'burst_holds':[],
              'flag_entries':[{'submission_id':f'SYN_FLAG_{i}','version_id':'SYN_V'} for i in range(127)]}
    proposal['revision']=sha(proposal)
    closed=[c['case_id'] for c in cases[:4]]
    projection={'projection_ready':True,'bindings':source,'admin_revision':'7'*64,'closed_case_ids':closed,
                'stale_case_ids':[],'expired_binding_case_ids':[],'absent_current_case_ids':[]}
    work={'decision_revision':'d'*64,'administrative_disposition':{'bindings':source,'admin_revision':'7'*64,
          'projection':projection,'case_inventory':deepcopy(cases[:42])}}
    inventory={'target_context':base,'source_bindings':source,'source_admin_revision':'7'*64,
        'recorded_target_bindings':target,'decision_revision':'d'*64,
        'target_controls_decision_and_main_revisions_recomputed':True,'target_run_manifest_body_verified_this_capture':True,
        'target_run_manifest_sha256':'f'*64,'state_written':False,'case_inventory':cases,
        'preserved_source_closure_case_ids':closed}
    code={'review_dispositions.py':'3'*64,'review_core.py':'4'*64}
    compat={'source_rules_hash':source_rules,'target_rules_hash':target_rules,'semantic_config_equal':True,
        'review_module_rest_ast_equal':True,'only_changed_definitions':['backup_workspace','workspace'],
        'global_rule_equivalence_claimed':False,'operational_rebind_permitted':False,'target_code_sha256':code}
    assessment={'target_closures_exactly_matching':4,'case_equality_counterfactual_closed':4,
        'case_equality_counterfactual_active':61,'actual_target_bound_closed':0,'actual_target_bound_active':65,
        'actual_target_expired_bindings':4,'formal_rebind_performed':False}
    data={'proposal':proposal,'source_workload':work,'inventory':inventory,'compatibility':compat,
          'assessment':assessment,'evidence_manifest':{},'acceptance_report':b'SYNTHETIC independent scope acceptance'}
    def seal():
        data['evidence_manifest']={'files':{filename:h(raw(data[name])) for name,filename in
            [('inventory','TARGET_CASE_INVENTORY.private.json'),('compatibility','RULE_COMPATIBILITY_EVIDENCE.json'),('assessment','ASSESSMENT.json')]}}
        blobs={name:(value if isinstance(value,bytes) else raw(value)) for name,value in data.items()}
        profile={'id':'SYNTHETIC_ONLY','inputs':{name:h(value) for name,value in blobs.items()},
            'source_rules_hash':source_rules,'target_rules_hash':target_rules,'target_release_id':'RUN_SYN_TARGET',
            'closed_comparisons':4,'target_comparisons':65}
        monkeypatch.setattr(carry,'PROFILE',profile)
        return blobs
    monkeypatch.setattr(carry,'_current_code_pins',lambda names:code)
    return data,seal


def test_plan_preserves_four_original_closures_without_formal_rebinding(snapshots,monkeypatch):
    data,seal=snapshots;blobs=seal();before=deepcopy((data,blobs))
    def forbidden(*args,**kwargs):raise AssertionError('A state API must not run')
    monkeypatch.setattr('sqlite3.connect',forbidden)
    monkeypatch.setattr(dispositions,'apply_closed_unresolvable',forbidden)
    monkeypatch.setattr(dispositions,'reopen_closed_unresolvable',forbidden)
    envelope=carry.build_preview(blobs);proposal,view=carry.validate_preview(envelope)
    plan=envelope['transition']
    assert plan['source_bindings']==data['source_workload']['administrative_disposition']['bindings']
    assert plan['target_bindings']==data['inventory']['recorded_target_bindings']
    assert plan['preserve_case_ids']==data['inventory']['preserved_source_closure_case_ids']
    assert (view['proposed_preserved_comparisons'],view['projected_active_comparisons'])==(4,61)
    assert (view['native_target_closed'],view['native_target_active'],view['native_target_expired'])==(0,65,4)
    assert not plan['formal_rebind_performed'] and not plan['activation_permitted']
    assert proposal['flag_entries']==data['proposal']['flag_entries']
    assert (data,blobs)==before
    with pytest.raises(policy.PolicyError,match='proposal_format'):
        policy.validate_proposal(plan,{}, {}, {}, [])


def test_single_loader_displays_plan_and_native_expiry_without_zeroing_missing_intents(snapshots,tmp_path,monkeypatch):
    data,seal=snapshots;envelope=carry.build_preview(seal());p,pin=save(tmp_path,envelope)
    calls=[];loader=review.load_preview
    def counted(*args,**kwargs):calls.append(args);return loader(*args,**kwargs)
    monkeypatch.setattr(review,'load_preview',counted)
    ui=UI();assert review.render_candidate_preview(ui,path=p,expected_sha256=pin)
    assert len(calls)==1
    metrics={args[0]:args[1] for name,args,_ in ui.calls if name=='metric'}
    assert metrics['Recorded closures proposed for preservation']==4
    assert metrics['Projected active correction comparisons']==61
    assert 'Earlier decisions requiring review' not in metrics
    assert any('unavailable in this native snapshot' in str(args) for name,args,_ in ui.calls if name=='warning')
    assert any('0 closed, 65 active, 4 expired' in str(args) for name,args,_ in ui.calls if name=='caption')
    table=next(args[0] for name,args,_ in ui.calls if name=='dataframe')
    assert len(table)==4 and 'SYN_' not in json.dumps(table)
    html=review.review_html(envelope)
    assert '4 recorded closures proposed for preservation; 61 projected active' in html
    assert '0 closed, 65 active and 4 expired' in html
    assert 'no rebind applied' in html and 'SYN_CASE_' not in html
    assert review.review_model(envelope)['pending_intents'] is None


@pytest.mark.parametrize('change',['reasons','evidence_hash','record_a','version_a','route','rules','release',
    'unverified_controls','unverified_manifest','closure_scope','case_inventory','authority','projection'])
def test_even_resealed_synthetic_evidence_cannot_expand_scope_or_hide_drift(snapshots,change):
    data,seal=snapshots
    if change in {'reasons','evidence_hash','record_a','version_a','route'}:
        data['inventory']['case_inventory'][0][change]=['CHANGED'] if change=='reasons' else ('0'*64 if change=='evidence_hash' else 'CHANGED')
        data['inventory']['recorded_target_bindings']['output_bindings']['correction_inventory']=digest(data['inventory']['case_inventory'])
    elif change=='rules':data['proposal']['base']['rules_hash']='0'*64
    elif change=='release':data['proposal']['base']['release_id']='RUN_UNAPPROVED'
    elif change=='unverified_controls':data['inventory']['target_controls_decision_and_main_revisions_recomputed']=False
    elif change=='unverified_manifest':data['inventory']['target_run_manifest_body_verified_this_capture']=False
    elif change=='closure_scope':data['source_workload']['administrative_disposition']['projection']['closed_case_ids'].append('SYN_CASE_04')
    elif change=='case_inventory':data['inventory']['case_inventory'].pop()
    elif change=='authority':data['source_workload']['administrative_disposition']['bindings']['source_bindings']={}
    elif change=='projection':data['assessment']['actual_target_bound_closed']=4
    data['proposal']['revision']=sha({k:v for k,v in data['proposal'].items() if k!='revision'})
    with pytest.raises(ValueError):carry.build_preview(seal())


@pytest.mark.parametrize('change',['untrusted_report','transition','missing_input','malformed_input','code'])
def test_self_consistent_untrusted_or_tampered_plan_is_unavailable(snapshots,tmp_path,monkeypatch,change):
    data,seal=snapshots;envelope=carry.build_preview(seal())
    if change=='untrusted_report':envelope['inputs']['acceptance_report']=base64.b64encode(b'UNTRUSTED').decode()
    elif change=='transition':envelope['transition']['formal_rebind_performed']=True
    elif change=='missing_input':envelope['inputs'].pop('inventory')
    elif change=='malformed_input':envelope['inputs']['inventory']=[]
    elif change=='code':monkeypatch.setattr(carry,'_current_code_pins',lambda names:{})
    envelope['revision']=sha({k:v for k,v in envelope.items() if k!='revision'})
    p,pin=save(tmp_path,envelope);ui=UI()
    assert review.render_candidate_preview(ui,path=p,expected_sha256=pin) is False
    assert [name for name,_,_ in ui.calls]==['subheader','warning']


def test_candidate_only_preparation_is_write_new_and_uses_existing_html_renderer(snapshots,tmp_path,monkeypatch):
    _,seal=snapshots;blobs=seal();evidence=tmp_path/'accepted-evidence';evidence.mkdir()
    names={'inventory':'TARGET_CASE_INVENTORY.private.json','compatibility':'RULE_COMPATIBILITY_EVIDENCE.json',
           'assessment':'ASSESSMENT.json','evidence_manifest':'EVIDENCE_MANIFEST.json'}
    for key,name in names.items():(evidence/name).write_bytes(blobs[key])
    proposal=tmp_path/'native-proposal.json';proposal.write_bytes(blobs['proposal'])
    source=tmp_path/'source-workload.json';source.write_bytes(blobs['source_workload'])
    report=tmp_path/'acceptance.md';report.write_bytes(blobs['acceptance_report'])
    monkeypatch.setattr(carry,'OUTPUT_ROOT',tmp_path)
    out=tmp_path/'admin-carry-preview-synthetic'
    result=carry.prepare_preview(proposal,source,evidence,report,out)
    assert result['proposed_preserved_comparisons']==4 and result['projected_active_comparisons']==61
    assert not result['formal_rebind_performed']
    assert 'Provisional administrative carry' in Path(result['html']).read_text()
    assert review.load_preview(result['preview'],result['preview_sha256'])['administrative_carry']['native_target_active']==65
    before={p.name:p.read_bytes() for p in out.iterdir()}
    with pytest.raises(ValueError,match='new_regular_output_required'):
        carry.prepare_preview(proposal,source,evidence,report,out)
    assert before=={p.name:p.read_bytes() for p in out.iterdir()}
    with pytest.raises(ValueError,match='candidate_output_required'):
        carry.prepare_preview(proposal,source,evidence,report,tmp_path/'formal-state'/'admin-carry-preview-bad')
