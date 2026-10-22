"""Actual JavaScript runtime parity, not a Python imitation of the client."""
from copy import deepcopy
import json
import shutil
import subprocess

import pytest

from study2.static_scope import build_scope_index, query_scope, default_selection
from study2.static_scope_client import JS_SOURCE
from test_static_scope import fixture, seeded_fixture, exhaustive_selections, random_selections
from test_static_scope import REVIEW_PRIVATE_LABELS, REQUIRED_REVIEW_CHECKS, fully_reconciled_fixture


def node_batch(index, selections, *, operation="query"):
    node=shutil.which("node")
    assert node, "Node is required for frozen browser parity acceptance"
    script=JS_SOURCE + r'''
let input="";
process.stdin.setEncoding("utf8");
process.stdin.on("data",v=>input+=v);
process.stdin.on("end",()=>{
  const data=JSON.parse(input);
  const result=data.selections.map(selection=>{
    try { return {ok:true,result:Study2Scope[data.operation](data.index,selection)}; }
    catch(e) { return {ok:false,error:e.message}; }
  });
  process.stdout.write(JSON.stringify(result));
});
'''
    run=subprocess.run([node,"-e",script],input=json.dumps(dict(index=index,selections=selections,operation=operation),allow_nan=False),
                       capture_output=True,text=True,timeout=120)
    assert run.returncode==0,run.stderr
    return json.loads(run.stdout)


def test_every_small_filter_combination_python_javascript_parity():
    index=build_scope_index(*fixture()); selections=list(exhaustive_selections(index))
    actual=node_batch(index,selections)
    assert len(actual)==len(selections)
    for selection,row in zip(selections,actual):
        assert row["ok"],row
        assert row["result"]==query_scope(index,selection)


def test_seeded_large_randomized_python_javascript_parity():
    index=build_scope_index(*seeded_fixture())
    selections=list(random_selections(index,100,seed=610124))
    for selection,row in zip(selections,node_batch(index,selections)):
        assert row["ok"],row
        assert row["result"]==query_scope(index,selection)


def test_javascript_transition_search_defaults_and_side_effect_free_vm():
    node=shutil.which("node"); assert node
    script=r'''
const vm=require("node:vm");
let input="";process.stdin.on("data",c=>input+=c);
process.stdin.on("end",()=>{
  const {source,index}=JSON.parse(input);
  const context={module:{exports:{}}};
  for(const name of ["document","window","fetch","localStorage","sessionStorage","XMLHttpRequest"])
    Object.defineProperty(context,name,{get(){throw new Error("side effect: "+name);}});
  vm.createContext(context);vm.runInContext(source,context);
  const s=context.module.exports;
  const before=JSON.stringify(index), initial=s.defaultSelection(index);
  const activated=s.transitionSelection(index,initial,{start:"2025-02-01"});
  const override=s.transitionSelection(index,activated,{include_unknown:true});
  const changed=s.transitionSelection(index,override,{end:"2025-07-01"});
  const visible=s.catalogueOptions(index,"surveys","absent search");
  s.query(index,changed);
  process.stdout.write(JSON.stringify({initial,activated,changed,visible,unchanged:before===JSON.stringify(index)}));
});
'''
    index=build_scope_index(*fixture())
    run=subprocess.run([node,"-e",script],input=json.dumps(dict(source=JS_SOURCE,index=index)),capture_output=True,text=True,timeout=15)
    assert run.returncode==0,run.stderr
    value=json.loads(run.stdout)
    assert value["initial"]==default_selection(index)
    assert not value["activated"]["include_unknown"] and value["changed"]["include_unknown"]
    assert value["visible"]==[] and value["unchanged"]


@pytest.mark.parametrize("selection",[dict(sources=[]),dict(surveys=[]),dict(start="2025-02-01"),dict(end="2025-07-01"),
    dict(start="2025-07-01",end="2025-02-01"),dict(start="2025-02-30"),dict(start="0000-01-01"),
    dict(include_unknown=1),dict(sources=["unknown-key"]),dict(arbitrary="PRIVATE")])
def test_selection_validation_parity(selection):
    from study2.static_scope import ScopeError
    index=build_scope_index(*fixture())
    row=node_batch(index,[selection])[0]
    try: expected=query_scope(index,selection)
    except ScopeError:
        assert not row["ok"]
    else:
        assert row==dict(ok=True,result=expected)


@pytest.mark.parametrize("mutate",[
    lambda i:i.update(submission_id="PRIVATE"),
    lambda i:i["profiles"][0].update(answer="PRIVATE"),
    lambda i:i["surveys"][0].update(label="<img src=x onerror=alert(1)>"),
    lambda i:i["sources"][0].update(label="https://example.test"),
    lambda i:i["records"][0].update(count=-1),
    lambda i:i["records"][0].update(count=True),
    lambda i:i["records"][0].update(count=1.5),
    lambda i:i["samples"][0].update(profiles=[]),
    lambda i:next(r for r in i["samples"] if r["code"]=="AC").update(count=3),
    lambda i:i["meta"]["adult"].update(policy="same_child_only"),
    lambda i:i["records"][0].update(exit_stage="new_status"),
])
def test_browser_rejects_malformed_or_leaking_payloads(mutate):
    index=deepcopy(build_scope_index(*fixture())); mutate(index)
    assert not node_batch(index,[None])[0]["ok"]


def test_browser_unavailable_old_format_and_missing_evidence():
    assert not node_batch(dict(format="study2_static_v1"),[None])[0]["ok"]
    data=fixture(); data[0][-1]["manual_keep"]=True
    index=build_scope_index(data[0],data[1],None,data[3])
    row=node_batch(index,[None])[0]
    assert row["ok"] and row["result"]==query_scope(index)
    assert row["result"]["flow"]["lanes"] is None


def test_browser_approved_school_projection_and_result_alias_isolation():
    data=fixture()
    school=dict(revision="synthetic-school-v1",statuses=["mapped","unresolved"],rows=[
        dict(submission_id=r["submission_id"],status="mapped" if i%2 else "unresolved") for i,r in enumerate(data[0])])
    index=build_scope_index(*data,school_projection=school)
    selections=list(random_selections(index,20,seed=610126))
    for selection,row in zip(selections,node_batch(index,selections)):
        assert row["ok"] and row["result"]==query_scope(index,selection)
    # This checks returned metadata is detached from the validated index.
    node=shutil.which("node"); assert node
    script=JS_SOURCE+'''
let input="";process.stdin.on("data",x=>input+=x);process.stdin.on("end",()=>{
 const index=JSON.parse(input),before=JSON.stringify(index),result=Study2Scope.query(index);
 result.school.statuses.length=0;result.reconciliation.checked.length=0;
 process.stdout.write(JSON.stringify({unchanged:before===JSON.stringify(index)}));
});
'''
    run=subprocess.run([node,"-e",script],input=json.dumps(index),text=True,capture_output=True,timeout=15)
    assert run.returncode==0,run.stderr
    assert json.loads(run.stdout)==dict(unchanged=True)


def test_browser_legitimate_year_and_calendar_labels_supported():
    data=fixture(); data[0][0]["answer"]["Survey"]="2025-2026 questionnaire from 2025-09-03"
    index=build_scope_index(*data)
    assert node_batch(index,[None])[0]==dict(ok=True,result=query_scope(index))


def test_browser_rejects_nonfinite_counts_before_json_serialization():
    node=shutil.which("node"); assert node
    script=JS_SOURCE+'''
let input="";process.stdin.on("data",x=>input+=x);process.stdin.on("end",()=>{
 const index=JSON.parse(input),rejected=[];
 for(const n of [NaN,Infinity,-Infinity]) {
  index.records[0].count=n;
  try{Study2Scope.query(index);rejected.push(false);}catch(e){rejected.push(e.message==="invalid_count");}
 }
 process.stdout.write(JSON.stringify(rejected));
});
'''
    run=subprocess.run([node,"-e",script],input=json.dumps(build_scope_index(*fixture())),capture_output=True,text=True,timeout=15)
    assert run.returncode==0,run.stderr
    assert json.loads(run.stdout)==[True,True,True]


@pytest.mark.parametrize("field",["survey_label","source_label","form_id","form_version"])
def test_review_r2_browser_rejects_private_catalogue_payload_without_builder(field):
    # Build only safe input, then poison the already serialized browser payload.
    # This avoids depending on the Python builder accepting the vulnerable value.
    for label in REVIEW_PRIVATE_LABELS:
        index=build_scope_index(*fixture())
        if field=="source_label": index["sources"][0]["label"]=label
        elif field=="survey_label": index["surveys"][0]["label"]=label
        else: index["surveys"][0][field]=label
        result=node_batch(index,[None])[0]
        assert not result["ok"],(field,label)
        assert result["error"]=="unsafe_or_missing_label"


def test_review_r2_browser_complete_partial_and_false_checked_validation():
    for missing in [None,*sorted(REQUIRED_REVIEW_CHECKS)]:
        data=fully_reconciled_fixture()
        if missing is not None:
            if missing.startswith("2."):data[3]["stage_counts"].pop(missing)
            else:data[3].pop(missing)
        index=build_scope_index(*data)
        result=node_batch(index,[None])[0]
        assert result==dict(ok=True,result=query_scope(index))
        assert result["result"]["reconciliation"]["status"]==("checked" if missing is None else "partial")
        if missing is not None:
            index["meta"]["reconciliation"]["status"]="checked"
            row=node_batch(index,[None])[0]
            assert not row["ok"] and row["error"]=="invalid_reconciliation"
    data=fully_reconciled_fixture(); data[3]["stage_counts"]["2.1.3"]=9999
    index=build_scope_index(*data)
    assert node_batch(index,[None])[0]==dict(ok=True,result=query_scope(index))
    index["meta"]["reconciliation"]["status"]="checked"
    index["meta"]["reconciliation"]["checked"]=sorted(REQUIRED_REVIEW_CHECKS)
    assert node_batch(index,[None])[0]["error"]=="invalid_reconciliation"


def test_review_r2_browser_keeps_public_release_id_and_valid_calendar_names():
    for label in ["Student questionnaire 2025-2026 launched 2025-09-03", "Survey 2025/2026 from 2024-02-29"]:
        data=fixture(); data[0][0]["answer"]["Survey"]=label; data[3]["release_id"]="RUN_"+"b"*32
        index=build_scope_index(*data)
        assert node_batch(index,[None])[0]==dict(ok=True,result=query_scope(index))
