"""One pinned synthetic preview; separate administrative units and no writes."""
import ast
from copy import deepcopy
from pathlib import Path
import json

import pytest

from study2 import group_intent_review as review, group_cleaning_operator as operator
from study2.analysis_eligibility import sha
from test_group_decision_intents import original, project
from test_group_intent_review import UI, save


@pytest.fixture
def candidate(original):
    records,cases,groups,_,_,collection=deepcopy(original)
    records['SYN_A']['version_id']='SYNTHETIC_CHANGED'
    proposal=project(records,cases,groups,collection)
    # A synthetic inventory exercises the presentation boundary only; it does
    # not claim that self-sealed artifacts authenticate native policy evidence.
    proposal['burst_holds']=[{
        'group_id':f'SYNTHETIC_SCOPE_{i:02d}', 'outcome':'hold',
        'reasons':['source_proof_shape_or_membership'],
        'member_pins':[{'submission_id':'SYNTHETIC_SHARED' if i<2 else f'SYNTHETIC_MEMBER_{i}',
                        'version_id':'SYNTHETIC_VERSION'}],
    } for i in range(12)]
    proposal['flag_entries']=[{'submission_id':f'SYNTHETIC_EXISTING_FLAG_{i}',
                               'version_id':'SYNTHETIC_EXISTING_VERSION'} for i in range(127)]
    proposal['revision']=sha({k:v for k,v in proposal.items() if k!='revision'})
    return proposal


def test_single_loader_panel_keeps_intents_scopes_and_records_separate(candidate,tmp_path,monkeypatch):
    before=deepcopy(candidate);path,pin=save(tmp_path,candidate)
    real_loader=review.load_preview;calls=[]
    def load_once(*args,**kwargs):
        calls.append(args);return real_loader(*args,**kwargs)
    monkeypatch.setattr(review,'load_preview',load_once)
    ui=UI();assert review.render_candidate_preview(ui,path=path,expected_sha256=pin)
    assert len(calls)==1
    metrics={args[0]:args[1] for name,args,_ in ui.calls if name=='metric'}
    assert metrics=={'Earlier decisions requiring review':1,
                    'Burst-rule scopes awaiting evidence':12,'Submission records in burst holds':11}
    tables=[args[0] for name,args,_ in ui.calls if name=='dataframe']
    assert [len(table) for table in tables]==[1,12]
    assert tables[1][0]['Scope']=='Scope 1' and tables[1][-1]['Scope']=='Scope 12'
    assert 'SYNTHETIC_' not in json.dumps(tables)
    model=review.review_model(candidate)
    assert model['burst_review']['proposal_revision']==model['proposal_revision']==candidate['revision']
    assert model['burst_review']['reason_scope_counts']=={'source_proof_shape_or_membership':12}
    assert candidate==before and len(candidate['flag_entries'])==127
    assert candidate['projection']==before['projection']
    assert candidate['decision_application']==before['decision_application']
    tree=ast.parse((Path(__file__).parents[1]/'dashboard.py').read_text())
    assert sum(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and
               n.func.id=='render_candidate_preview' for n in ast.walk(tree))==1


def test_html_and_native_console_use_the_same_separate_review_counts(candidate,monkeypatch,capsys):
    before=deepcopy(candidate)
    page=review.review_html(candidate)
    assert '1 earlier decisions require package or evidence review' in page
    assert '12 scopes awaiting evidence; 11 submission records' in page
    assert 'Burst-rule evidence holds' in page and 'These holds do not add exclusions' in page
    assert 'SYNTHETIC_SCOPE_' not in page and 'SYNTHETIC_MEMBER_' not in page
    monkeypatch.setattr(operator,'preview',lambda path:candidate)
    monkeypatch.setattr('sys.argv',['group_cleaning_operator','dry-run','--bundle','SYNTHETIC_ONLY.json'])
    assert operator.main()==0
    result=json.loads(capsys.readouterr().out)
    assert result['pending_decision_intents']==1 and len(result['candidate_group_decisions'])==1
    assert result['burst_hold_review']['scope_count']==12
    assert result['burst_hold_review']['distinct_submission_count']==11
    assert len(result['burst_hold_review']['rows'])==12
    assert candidate==before


def test_explicit_empty_burst_inventory_is_zero_and_does_not_hide_intents(candidate,tmp_path):
    candidate['burst_holds']=[]
    candidate['revision']=sha({k:v for k,v in candidate.items() if k!='revision'})
    path,pin=save(tmp_path,candidate);ui=UI()
    assert review.render_candidate_preview(ui,path=path,expected_sha256=pin)
    metrics={args[0]:args[1] for name,args,_ in ui.calls if name=='metric'}
    assert metrics['Earlier decisions requiring review']==1
    assert metrics['Burst-rule scopes awaiting evidence']==0
    assert metrics['Submission records in burst holds']==0
    assert len([args for name,args,_ in ui.calls if name=='dataframe'])==1


@pytest.mark.parametrize('change',['missing','array_member','wrong_outcome','unknown_reason',
                                  'duplicate_scope','malformed_pin','conflicting_version'])
def test_unavailable_burst_inventory_does_not_display_zero_or_partial_metrics(candidate,tmp_path,change):
    holds=candidate['burst_holds']
    if change=='missing':candidate.pop('burst_holds')
    elif change=='array_member':holds[0]=[]
    elif change=='wrong_outcome':holds[0]['outcome']='excluded'
    elif change=='unknown_reason':holds[0]['reasons']=['UNRECOGNISED_SYNTHETIC_REASON']
    elif change=='duplicate_scope':holds[1]['group_id']=holds[0]['group_id']
    elif change=='malformed_pin':holds[0]['member_pins'][0]=[]
    elif change=='conflicting_version':holds[1]['member_pins'][0]['version_id']='DIFFERENT_SYNTHETIC_VERSION'
    candidate['revision']=sha({k:v for k,v in candidate.items() if k!='revision'})
    before=deepcopy(candidate);path,pin=save(tmp_path,candidate);ui=UI()
    assert review.render_candidate_preview(ui,path=path,expected_sha256=pin) is False
    assert [name for name,_,_ in ui.calls]==['subheader','warning']
    assert candidate==before
