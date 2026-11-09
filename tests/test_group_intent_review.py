"""Candidate workflow contract with synthetic records and an injected UI only."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from study2 import group_cleaning as policy, group_intent_review as review
from study2 import continuity_integration as integration
from study2.analysis_eligibility import sha
from study2 import group_cleaning_operator as operator, group_decision_intents as intents
from test_group_decision_intents import original, project
from test_intent_continuity_compat import build_fixture, TARGET


class UI:
    def __init__(self):self.calls=[]
    def __getattr__(self,name):
        def call(*args,**kwargs):self.calls.append((name,args,kwargs))
        return call


def save(tmp_path,proposal):
    p=tmp_path/'proposal.json';raw=json.dumps(proposal).encode();p.write_bytes(raw)
    return p,hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('current_scope',[True,False])
def test_held_intent_is_visible_without_fabricating_a_comparison(original,tmp_path,current_scope):
    records,cases,groups,_,_,collection=deepcopy(original)
    records['SYN_A']['version_id']='changed'
    records['SYN_B']['child_id']=records['SYN_A']['child_id']
    if not current_scope:groups={}
    before=deepcopy((records,cases,collection))
    proposal=project(records,cases,groups,collection)
    model=review.review_model(proposal)
    assert model['pending_intents']==1
    assert model['rows'][0]['Recorded answer']=='Keep existing subgroups'
    assert model['rows'][0]['Current scopes']==int(current_scope)
    assert model['rows'][0]['Evidence']=='Continuity evidence not verified in this preview'
    assert proposal['projection']['holds']==[]
    path,pin=save(tmp_path,proposal);ui=UI()
    assert review.render_candidate_preview(ui,path=path,expected_sha256=pin)
    assert next(args[0] for name,args,_ in ui.calls if name=='dataframe')==model['rows']
    assert before==(records,cases,collection)


def test_six_time_changes_cover_two_intents_without_carrying_either(monkeypatch,tmp_path):
    data,opts,profile,_,_,target,collection=build_fixture(monkeypatch,retained_change=True)
    before=deepcopy((data,opts))
    proposal=integration.bound_proposal(data,opts)
    lineage=integration.check_intent_lineage(proposal)
    assert sorted(row['changed_subjects'] for row in lineage.values() if row['changed_subjects'])==[2,4]
    assert sum(row['changed_subjects'] for row in lineage.values())==6
    model=review.review_model(proposal)
    assert model['pending_intents']==2
    assert sorted(row['Changed submissions'] for row in model['rows'])==[2,4]
    assert all(row['Evidence']=='Creation-time lineage recorded in candidate' for row in model['rows'])
    assert all(row['Next step']=='Verify recorded lineage and review the candidate package using the earlier answer' for row in model['rows'])
    pending={e['decision_id'] for e in proposal['decision_application']['entries'] if e['status'] in review.PENDING}
    assert len(pending)==2
    assert not any(e['status']=='carried' and e['decision_id'] in pending for e in proposal['decision_application']['entries'])
    assert proposal['projection']['counts']['pending_decision_intents']==2
    assert proposal['group_dispositions']['intent_review_required']==2
    assert proposal['projection']['scopes'][profile['target_group_id']]==policy.classify_scope(data['records'],target,data['cases'])
    assert proposal['decision_intents']==collection
    assert (data,opts)==before
    path,pin=save(tmp_path,proposal);ui=UI()
    assert review.render_candidate_preview(ui,path=path,expected_sha256=pin)
    html=review.review_html(proposal)
    assert html.count('Creation-time lineage recorded in candidate')==2
    assert 'No new identity answer is requested' in html
    control={'policy_active':True,'release_id':TARGET,'proposal_revision':proposal['revision'],
        'historical_continuity_revision':proposal['historical_continuity']['revision'],
        'partitions':proposal['partitions'],'inventory_revision':profile['target_inventory_revision'],
        'main_revision':opts['main_revision']}
    receipt={'review':{'accepted':True,'proposal_revision':proposal['revision']}}
    integration.check_generation(control,proposal,receipt)
    integration.check_intent_inventory(proposal,data['records'])
    bad_records=deepcopy(data['records'])
    changed_sid=next(r['current_subject_pins'][0]['submission_id'] for r in lineage.values() if r['changed_subjects']==4)
    bad_records[changed_sid]['raw_hash']='0'*64
    with pytest.raises(Exception,match='intent_lineage_inventory_changed'):
        integration.check_intent_inventory(proposal,bad_records)
    bad=deepcopy(proposal)
    row=next(r for r in bad['historical_continuity']['intent_lineage']['entries'] if r['changed_subjects']==4)
    row['current_subject_pins'][0]['version_id']='forged'
    with pytest.raises(Exception,match='intent_lineage_binding_changed'):
        integration.check_intent_lineage(bad)


def test_retained_intent_cannot_borrow_lineage_with_a_different_original_pin(monkeypatch):
    data,opts,*_=build_fixture(monkeypatch,retained_change=True)
    collection=opts['decision_intents']
    item=next(i for i in collection['intents'] if len(i['subjects'])==4)
    item['subjects'][0]['raw_hash']='0'*64
    item['revision']=sha({k:v for k,v in item.items() if k!='revision'})
    collection['revision']=sha({k:v for k,v in collection.items() if k!='revision'})
    with pytest.raises(Exception,match='intent_lineage_historical_decision_changed'):
        integration.bound_proposal(data,opts)


def test_self_consistent_untrusted_candidate_cannot_display_verified_proof(monkeypatch,tmp_path):
    data,opts,*_=build_fixture(monkeypatch,retained_change=True)
    proposal=integration.bound_proposal(data,opts)
    binding=proposal['historical_continuity'];proof=binding['proof']
    proof['source_time_export_sha256']='0'*64
    proof['revision']=sha({k:v for k,v in proof.items() if k!='revision'})
    lineage=binding['intent_lineage'];lineage['proof_revision']=proof['revision']
    lineage['revision']=sha({k:v for k,v in lineage.items() if k!='revision'})
    binding['revision']=sha({k:v for k,v in binding.items() if k!='revision'})
    proposal['revision']=sha({k:v for k,v in proposal.items() if k!='revision'})
    path,pin=save(tmp_path,proposal);ui=UI()
    assert review.render_candidate_preview(ui,path=path,expected_sha256=pin)
    rows=next(args[0] for name,args,_ in ui.calls if name=='dataframe')
    assert all(row['Evidence']=='Creation-time lineage recorded in candidate' for row in rows)
    assert not any('verified' in row['Evidence'].lower() for row in rows)
    assert any('independent verification before action' in str(args) for name,args,_ in ui.calls if name=='caption')
    assert 'SYN_' not in json.dumps(rows)


@pytest.mark.parametrize('tamper',['missing_pin','file_change','application_change','missing_lineage'])
def test_preview_rejects_stale_or_incomplete_evidence(original,tmp_path,tamper,monkeypatch):
    records,cases,groups,_,_,collection=deepcopy(original)
    records['SYN_A']['version_id']='changed'
    proposal=project(records,cases,groups,collection)
    if tamper=='missing_lineage':
        data,opts,*_=build_fixture(monkeypatch,retained_change=True)
        proposal=integration.bound_proposal(data,opts)
        proposal['historical_continuity'].pop('intent_lineage')
        binding=proposal['historical_continuity'];binding['revision']=sha({k:v for k,v in binding.items() if k!='revision'})
        proposal['revision']=sha({k:v for k,v in proposal.items() if k!='revision'})
    if tamper=='application_change':
        proposal['decision_application']['entries'][0]['status']='carried'
        proposal['revision']=sha({k:v for k,v in proposal.items() if k!='revision'})
    path,pin=save(tmp_path,proposal)
    if tamper=='file_change':path.write_text('{}')
    ui=UI()
    assert not review.render_candidate_preview(ui,path=path,expected_sha256='' if tamper=='missing_pin' else pin)
    assert any(name=='warning' for name,_,_ in ui.calls)
    assert not any(name in {'metric','dataframe'} for name,_,_ in ui.calls)


def test_dashboard_calls_preview_outside_legacy_diagnostics():
    root=Path(__file__).parents[1]
    tree=ast.parse((root/'dashboard.py').read_text())
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)]
    hook=next(n for n in calls if isinstance(n.value.func,ast.Name) and n.value.func.id=='render_candidate_preview')
    summary=next(n for n in calls if isinstance(n.value.func,ast.Name) and n.value.func.id=='render_current_review_workload')
    assert hook.lineno==summary.end_lineno+1


def test_native_dry_run_lists_visible_pending_decisions(original,monkeypatch,capsys):
    records,cases,groups,_,_,collection=deepcopy(original)
    records['SYN_A']['version_id']='changed'
    proposal=project(records,cases,groups,collection)
    monkeypatch.setattr(operator,'preview',lambda path:proposal)
    monkeypatch.setattr('sys.argv',['group_cleaning_operator','dry-run','--bundle','SYNTHETIC_ONLY.json'])
    assert operator.main()==0
    result=json.loads(capsys.readouterr().out)
    assert result['pending_decision_intents']==1
    assert result['candidate_group_decisions'][0]['Recorded answer']=='Keep existing subgroups'


def test_unknown_earlier_semantics_are_not_shown_as_a_new_subgroup_answer(original):
    records,cases,groups,_,_,collection=deepcopy(original)
    item=collection['intents'][0];item['kind']='ambiguous_legacy_negative'
    item['revision']=sha({k:v for k,v in item.items() if k!='revision'})
    collection['revision']=sha({k:v for k,v in collection.items() if k!='revision'})
    rows=review.review_model(project(records,cases,groups,collection))['rows']
    assert rows[0]['Recorded answer']=='Earlier decision needs interpretation'


def test_unconfigured_preview_does_not_change_the_published_workflow(monkeypatch):
    monkeypatch.delenv(review.PATH_ENV,raising=False);monkeypatch.delenv(review.SHA_ENV,raising=False)
    ui=UI();assert not review.render_candidate_preview(ui)
    assert ui.calls==[]


@pytest.mark.parametrize('shape',['proposal','application','base','collection','application_entry',
    'continuity','proof','lineage','lineage_entry','original_pin','current_pin','release_id'])
def test_hash_pinned_array_is_unavailable_instead_of_crashing(original,tmp_path,shape,monkeypatch):
    records,cases,groups,_,_,collection=deepcopy(original)
    proposal=project(records,cases,groups,collection)
    if shape in {'continuity','proof','lineage','lineage_entry','original_pin','current_pin'}:
        data,opts,*_=build_fixture(monkeypatch,retained_change=True)
        proposal=integration.bound_proposal(data,opts)
    if shape=='proposal':proposal=[]
    else:
        if shape=='application':proposal['decision_application']=[]
        elif shape=='base':proposal['base']=[]
        elif shape=='collection':proposal['decision_intents']=[]
        elif shape=='application_entry':proposal['decision_application']['entries'][0]=[]
        elif shape=='continuity':proposal['historical_continuity']=[]
        elif shape=='proof':proposal['historical_continuity']['proof']=[]
        elif shape=='lineage':proposal['historical_continuity']['intent_lineage']=[]
        elif shape=='lineage_entry':proposal['historical_continuity']['intent_lineage']['entries'][0]=[]
        elif shape in {'original_pin','current_pin'}:
            field='original_subject_pins' if shape=='original_pin' else 'current_subject_pins'
            proposal['historical_continuity']['intent_lineage']['entries'][0][field][0]=[]
        elif shape=='release_id':proposal['base']['release_id']=[]
        application=proposal['decision_application']
        if isinstance(application,dict):
            application['revision']=sha({k:v for k,v in application.items() if k!='revision'})
        binding=proposal.get('historical_continuity')
        if isinstance(binding,dict):
            lineage=binding['intent_lineage']
            if isinstance(lineage,dict):lineage['revision']=sha({k:v for k,v in lineage.items() if k!='revision'})
            binding['revision']=sha({k:v for k,v in binding.items() if k!='revision'})
        proposal['revision']=sha({k:v for k,v in proposal.items() if k!='revision'})
    path,pin=save(tmp_path,proposal)
    ui=UI()
    assert review.render_candidate_preview(ui,path=path,expected_sha256=pin) is False
    assert [name for name,_,_ in ui.calls]==['subheader','warning']
    assert 'unavailable' in ui.calls[-1][1][0].lower()
    with pytest.raises(ValueError,match='preview_.*_shape'):
        review.review_model(proposal)
