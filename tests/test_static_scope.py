"""Independent direct-membership oracle and synthetic scope acceptance suite."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import combinations, product
import json
import random
from zoneinfo import ZoneInfo

import pytest

from study2.static_scope import (ADULT_POLICY, FORMAT, REASONS, ROLES, SLOTS, STAGES,
    ScopeError, build_scope_index, canonical_json, catalogue_options, creation_day,
    default_selection, normalize_selection, query_scope, transition_selection, validate_index)


def fixture():
    """Two children, an alternate BD follow-up and all documented exit types."""
    records, analysis, adults = [], [], []

    def add(sid, child, role, source, at, wave=None, status="eligible", reason=None, survey="Shared survey"):
        r = dict(submission_id=sid, child_id=child, role=role, source_type=source,
                 source_label=source, observed_at=at, time_confidence="observed",
                 date_basis="system_creation", claimed_wave="T1" if "late" in sid else "T0",
                 selected_wave=wave, status=status, wave_reason=reason,
                 answer={"Survey": survey}, version_id="PRIVATE-content-revision-" + sid)
        records.append(r)
        if wave:
            analysis.append(dict(submission_id=sid, child_id=child, role=role, wave=wave))
        return r

    for child in ("child-one", "child-two"):
        for role, wave, source, at in (
            ("student", "T0", "alpha", "2025-01-31T16:00:00Z"),
            ("parent", "T0", "alpha", "2025-02-01T00:00:00+08:00"),
            ("student", "T1", "beta", "2025-06-01T00:00:00Z"),
            ("parent", "T1", "beta", "2025-07-01T00:00:00Z"),
        ):
            add(child+role+wave, child, role, source, at, wave)
        add(child+"alternate", child, "parent", "alpha", "2025-06-01T00:00:00Z",
            status="extra_followup", reason="parent_other_same_phase_response")
        for wave, sid in (("T0", child+"parentT0"), ("T1", child+"alternate")):
            adults.append(dict(submission_id=sid, child_id=child, role="parent", wave=wave))
    for i, (status, role, reason) in enumerate([
        ("excluded_school", "student", None), ("sparse_response", "parent", None),
        ("incomplete", "student", None), ("unrecognized_survey", "parent", None),
        ("exact_input_repeat", "student", None), ("short_repeat", "parent", None),
        ("short_interval_followup", "student", None), ("extra_followup", "student", None),
        ("eligible", "student", "pending_chronology"),
        ("eligible", "parent", "parent_no_reliable_student_baseline"),
        ("eligible", "parent", "pending_chronology"),
    ]):
        r=add("exit-"+str(i), "exit-child-"+str(i), role, "alpha" if i%2 else "beta",
              "2025-04-01T00:00:00Z", status=status, reason=reason)
        if i%4 == 0:
            r["observed_at"] = None
        elif i%4 == 1:
            r["observed_at"] = "2025-04-01T00:00:00"  # No inferred timezone.
        elif i%4 == 2:
            r.update(date_basis="batch_assigned_creation", time_confidence="accepted_creation_time")
    summary=dict(release_id="synthetic-release", adult_identity_policy=ADULT_POLICY,
                 submissions=len(records), status_counts=dict(Counter(r["status"] for r in records)))
    # Explicit expectations come from fixture construction, not the engine.
    summary.update({code: 2 for code in SLOTS})
    return records, analysis, adults, summary


def direct_oracle(records, analysis, adults, selection, index):
    """Read ORIGINAL records and links; never inspect cells or grouped profiles.

    Catalogue keys are opaque in the public contract. Resolve them using raw
    source/role/form/name identity rather than the builder's hashing helper.
    Date parsing and sample joins below are independently implemented.
    """
    source_keys={s["label"]: s["key"] for s in index["sources"]}
    survey_keys={(s["source_key"], s["role"], None if s["missing_name"] else s["label"],
                  s["form_id"], s["form_version"]): s["key"] for s in index["surveys"]}
    selected_sources=set(selection["sources"]); selected_surveys=set(selection["surveys"])

    def day(r):
        if r.get("time_confidence") not in ("observed", "manual_verified", "accepted_creation_time"):
            return None
        try:
            dt=datetime.fromisoformat((r.get("observed_at") or "").replace("Z", "+00:00"))
            return dt.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d") if dt.tzinfo else None
        except ValueError:
            return None

    def keys(r):
        sk=source_keys[r["source_type"]]
        name=r["answer"].get("Survey") or None
        return sk,survey_keys[sk,r["role"],name,r.get("survey_form_id"),r.get("survey_form_version")]

    # Cache per ORIGINAL record only, never joint cells. This removes repeated
    # timestamp parsing from the oracle without sharing production helpers.
    record_keys={r["submission_id"]:keys(r) for r in records}
    record_days={r["submission_id"]:day(r) for r in records}

    def accepts(r, ignore=None):
        sk,vk=record_keys[r["submission_id"]]
        if ignore != "sources" and sk not in selected_sources:
            return False
        if ignore != "surveys" and vk not in selected_surveys:
            return False
        d=record_days[r["submission_id"]]
        if d is None:
            return selection["include_unknown"]
        return (selection["start"] is None or d>=selection["start"]) and (selection["end"] is None or d<=selection["end"])

    by_id={r["submission_id"]:r for r in records}
    inside={r["submission_id"] for r in records if accepts(r)}
    raw={role:sum(r["role"]==role and r["submission_id"] in inside for r in records) for role in ROLES}
    outside={role:sum(r["role"]==role and r["submission_id"] not in inside for r in records) for role in ROLES}
    sources=[dict(source_key=s["key"],label=s["label"],**{role:sum(r["source_type"]==s["label"] and r["role"]==role and
                r["submission_id"] in inside for r in records) for role in ROLES}) for s in index["sources"]]
    facet_counts={name:dict.fromkeys([option["key"] for option in index[name]],0) for name in ("sources","surveys")}
    for r in records:
        for name,i in (("sources",0),("surveys",1)):
            if accepts(r,name): facet_counts[name][record_keys[r["submission_id"]][i]]+=1
    facets={name:[dict(key=k,available=n) for k,n in counts.items()] for name,counts in facet_counts.items()}
    # This oracle filters link rows first, then performs set intersections by
    # child and slot. Index implementation instead tests whole profile tuples.
    expected_slots={
        "A": [("student","T0")], "B": [("parent","T0")], "C": [("student","T1")], "D": [("parent","T1")],
        "AC": [("student","T0"),("student","T1")], "BD": [("parent","T0"),("parent","T1")],
        "E": [("student","T0"),("parent","T0")], "F": [("student","T1"),("parent","T1")],
        "EF": [("student","T0"),("parent","T0"),("student","T1"),("parent","T1")],
    }
    samples={}
    for code, requirements in expected_slots.items():
        rows=adults if code=="BD" else analysis
        if rows is None or (code=="BD" and index["meta"]["adult"]["status"]!="available"):
            samples[code]=None; continue
        sets=[{r["child_id"] for r in rows if (r["role"],r["wave"])==slot and r["submission_id"] in inside} for slot in requirements]
        samples[code]=len(set.intersection(*sets))
    # Independent stage predicates over terminal facts, rather than incremental
    # traversal over grouped cells. Hardcoded lists deliberately independent.
    screen={"excluded_school","sparse_response","incomplete","unrecognized_survey"}
    copy=screen|{"exact_input_repeat"}; repeat=copy|{"manual_excluded","short_repeat"}
    lanes={}
    for role in ROLES:
        rows=[r for r in records if r["role"]==role and r["submission_id"] in inside]
        counts=[len(rows),sum(r["status"] not in screen for r in rows),sum(r["status"] not in copy for r in rows),
                sum(r["status"] not in repeat for r in rows),sum(bool(r.get("selected_wave")) for r in rows)]
        lanes[role]={}
        for i,stage in enumerate(STAGES):
            reasons={reason:0 for reason in REASONS[stage]}
            for r in rows:
                if r.get("selected_wave"):
                    continue
                status=r["status"]
                reason=status if status in screen|{"exact_input_repeat","short_repeat","manual_excluded","short_interval_followup"} else r.get("wave_reason") or status
                if reason in reasons:
                    reasons[reason]+=1
            lanes[role][stage]=dict(entering=counts[i],remaining=counts[i+1],exits=reasons)
    return dict(raw=raw,out_of_scope=outside,sources=sources,facets=facets,samples=samples,lanes=lanes)


def assert_oracle(data,index,selection):
    result=query_scope(index,selection)
    expected=direct_oracle(*data[:3],result["scope"],index)
    for name in ("raw","out_of_scope","sources","facets"):
        assert result[name]==expected[name]
    assert {s["code"]:s["count"] for s in result["samples"]}==expected["samples"]
    if result["flow"]["status"]=="available":
        assert result["flow"]["lanes"]==expected["lanes"]
        for lanes in result["flow"]["lanes"].values():
            for stage in STAGES:
                lane=lanes[stage]
                assert lane["entering"]==lane["remaining"]+sum(lane["exits"].values())
    return result


def subsets(values):
    return [list(v) for n in range(len(values)+1) for v in combinations(values,n)]


def exhaustive_selections(index):
    dates=[None,"2025-02-01","2025-06-01","2025-07-01"]
    for sources,surveys,start,end,unknown in product(subsets([s["key"] for s in index["sources"]]),
            subsets([s["key"] for s in index["surveys"]]),dates,dates,(True,False)):
        if start and end and start>end:
            continue
        yield dict(sources=sources,surveys=surveys,start=start,end=end,include_unknown=unknown)


def seeded_fixture(size=32000, seed=610121):
    rng=random.Random(seed)
    records,analysis,adults=[],[],[]
    sources=["alpha","beta","gamma","delta"]
    names=["Baseline study","Followup study","Shared survey",None]
    nfamilies=size//10
    for child in range(nfamilies):
        for role,wave,alternate in (("student","T0",False),("parent","T0",False),("student","T1",False),
                                    ("parent","T1",False),("parent","T1",True)):
            sid=f"private-{child}-{role}-{wave}-{alternate}"
            dt=datetime(2024,1,1,tzinfo=timezone.utc)+timedelta(days=rng.randrange(370)+(400 if wave=="T1" else 0))
            r=dict(submission_id=sid,child_id=f"child-{child}",role=role,source_type=rng.choice(sources),
                   answer={"Survey":rng.choice(names)},observed_at=dt.isoformat(),time_confidence="observed",date_basis="system_creation",
                   status="extra_followup" if alternate else "eligible",selected_wave=None if alternate else wave,
                   claimed_wave=rng.choice(["T0","T1"]),wave_reason="parent_other_same_phase_response" if alternate else None)
            records.append(r)
            if not alternate:
                analysis.append({k:r[k] for k in ("submission_id","child_id","role")}|dict(wave=wave))
            if role=="parent" and (wave=="T0" or alternate):
                adults.append({k:r[k] for k in ("submission_id","child_id","role")}|dict(wave=wave))
    patterns=[("excluded_school",None),("incomplete",None),("unrecognized_survey",None),("sparse_response",None),
              ("exact_input_repeat",None),("short_repeat",None),("short_interval_followup",None),("extra_followup",None),
              ("eligible","pending_chronology"),("eligible","parent_no_reliable_student_baseline")]
    for i in range(size-len(records)):
        status,reason=rng.choice(patterns)
        role="parent" if reason=="parent_no_reliable_student_baseline" else rng.choice(ROLES)
        r=dict(submission_id=f"private-exit-{i}",child_id=f"exit-child-{i}",role=role,source_type=rng.choice(sources),
               answer={"Survey":rng.choice(names)},observed_at="2025-03-01T00:00:00Z",time_confidence="observed",date_basis="system_creation",
               status=status,selected_wave=None,claimed_wave=rng.choice(["T0","T1"]),wave_reason=reason)
        mode=i%7
        if mode==0: r["observed_at"]=None
        elif mode==1: r["observed_at"]="2025-03-01T00:00:00"
        elif mode==2: r["observed_at"]="not-a-time"
        elif mode==3: r.update(time_confidence="accepted_creation_time",date_basis="batch_assigned_creation")
        elif mode==4: r["time_confidence"]="unknown"
        records.append(r)
    summary=dict(release_id="synthetic-large",adult_identity_policy=ADULT_POLICY,submissions=size,
                 status_counts=dict(Counter(r["status"] for r in records)),**{c:nfamilies for c in SLOTS})
    return records,analysis,adults,summary


def random_selections(index,n=100,seed=610122):
    rng=random.Random(seed)
    for _ in range(n):
        s={name:[r["key"] for r in index[name] if rng.random()<.6] for name in ("sources","surveys")}
        a,b=sorted(rng.sample(["2024-01-01","2024-06-01","2025-01-01","2025-07-01","2026-01-01"],2))
        s.update(start=a if rng.random()<.7 else None,end=b if rng.random()<.7 else None,include_unknown=rng.choice([True,False]))
        yield s


def test_all_small_combinations_against_independent_raw_oracle():
    data=fixture(); index=build_scope_index(*data)
    for selection in exhaustive_selections(index):
        assert_oracle(data,index,selection)


def test_seeded_32000_raw_records_and_randomized_queries():
    data=seeded_fixture(); index=build_scope_index(*data)
    assert len(data[0])==32000
    for selection in random_selections(index,40):
        assert_oracle(data,index,selection)


def test_all_fixed_slots_and_alternate_bd_followup():
    data=fixture(); index=build_scope_index(*data)
    result=assert_oracle(data,index,None)
    assert all(s["count"]==2 for s in result["samples"])
    alpha=next(s["key"] for s in index["sources"] if s["label"]=="alpha")
    counts={r["code"]:r["count"] for r in query_scope(index,{"sources":[alpha]})["samples"]}
    assert counts==dict(A=2,B=2,C=0,D=0,AC=0,BD=2,E=2,F=0,EF=0)
    # Exclude every EF slot separately. Others survive without replacement.
    keys={(s["source_key"],s["role"]):s["key"] for s in index["surveys"]}
    assert len(keys)==4
    for excluded in keys.values():
        r=query_scope(index,{"surveys":[s["key"] for s in index["surveys"] if s["key"]!=excluded]})
        assert next(s["count"] for s in r["samples"] if s["code"]=="EF")==0
        assert any(s["count"] for s in r["samples"] if s["code"] in "ABCD")


def test_missing_adult_artifact_policy_and_genuinely_empty_sample_are_distinct():
    records,analysis,adults,summary=fixture()
    for rows,policy in ((None,ADULT_POLICY),(adults,None),(adults,"legacy_same_child")):
        index=build_scope_index(records,analysis,rows,{**summary,"adult_identity_policy":policy})
        bd=next(s for s in query_scope(index)["samples"] if s["code"]=="BD")
        assert bd["status"]=="unavailable" and bd["count"] is None
        assert bd["continuity_evidence"] is None
    index=build_scope_index(records,analysis,[],{**summary,"BD":0})
    bd=next(s for s in query_scope(index)["samples"] if s["code"]=="BD")
    assert bd["count"]==0 and bd["continuity_evidence"]=="formal_parent_longitudinal_artifact"


def test_empty_selection_zero_catalogue_options_never_disappear_and_search_not_selection():
    index=build_scope_index(*fixture())
    for selection in ({"sources":[]},{"surveys":[]}):
        result=query_scope(index,selection)
        assert result["raw"]==dict(student=0,parent=0)
        assert all(s["count"]==0 for s in result["samples"])
        assert len(result["sources"])==len(index["sources"])
        assert len(result["facets"]["surveys"])==len(index["surveys"])
    before=canonical_json(index)
    assert catalogue_options(index,"surveys","no-match")==[]
    assert len(default_selection(index)["surveys"])==len(index["surveys"])
    assert canonical_json(index)==before


@pytest.mark.parametrize("raw,confidence,basis,expected,state",[
    ("2025-01-31T15:59:59Z","observed","system_creation","2025-01-31","usable"),
    ("2025-01-31T16:00:00Z","observed","system_creation","2025-02-01","usable"),
    ("2025-02-01T23:59:59-05:00","manual_verified","system_creation","2025-02-02","usable"),
    ("2025-02-01T00:00:00","observed","system_creation",None,"naive"),
    ("2025-02-30T00:00:00Z","observed","system_creation",None,"invalid"),
    (None,"observed","system_creation",None,"missing"),
    ("2025-01-31T16:00:00Z","accepted_creation_time","batch_assigned_creation","2025-02-01","usable"),
    ("2025-01-31T16:00:00Z","batch_only",None,None,"untrusted"),
])
def test_creation_dates_only_trusted_aware_hk(raw,confidence,basis,expected,state):
    record=dict(observed_at=raw,time_confidence=confidence,date_basis=basis,
                imported_at="2025-01-01T00:00:00Z",batch_at="2025-01-01T00:00:00Z",dob="2000-01-01")
    result=creation_day(record)
    assert (result[0],result[2])==(expected,state)


def test_first_date_activation_unknown_default_inclusion_reset_and_inclusive_bounds():
    data=fixture(); index=build_scope_index(*data)
    defaults=default_selection(index)
    assert defaults["include_unknown"]
    state=transition_selection(index,defaults,{"start":"2025-02-01"})
    assert not state["include_unknown"]
    assert not normalize_selection(index,{"end":"2025-06-01"})["include_unknown"]
    state=transition_selection(index,state,{"include_unknown":True})
    assert transition_selection(index,state,{"end":"2025-07-01"})["include_unknown"]
    assert default_selection(index)==defaults
    result=query_scope(index,{"start":"2025-02-01","end":"2025-02-01"})
    assert {s["code"]:s["count"] for s in result["samples"]}["A"]==2
    result=query_scope(index,{"start":"2025-02-01","include_unknown":True})
    assert result["date_policy"]["included_unknown_interval_unverified"]
    assert sum(result["dates"]["date_state"].values())==sum(result["raw"].values())
    for selection in ({"start":"2026-01-01","end":"2025-01-01"},{"start":"2025-02-30"},{"start":"2025-2-1"},{"start":"0000-01-01"}):
        with pytest.raises(ScopeError): query_scope(index,selection)


def test_missing_names_duplicate_labels_real_form_metadata_not_content_revision():
    records,analysis,adults,summary=fixture()
    records[0]["answer"]["Survey"]=None
    records[1]["survey_form_id"]="form-a"
    records[1]["survey_form_version"]="revision-b"
    records[4]["answer"]["Survey"]=None
    index=build_scope_index(records,analysis,adults,summary)
    assert sum(s["missing_name"] for s in index["surveys"])>=1
    assert any(s["identity_basis"]=="form_metadata" for s in index["surveys"])
    original=canonical_json(index)
    for r in records: r["version_id"]="OTHER-private-revision"
    assert canonical_json(build_scope_index(records,analysis,adults,summary))==original
    shared=[s for s in index["surveys"] if s["label"]=="Shared survey"]
    assert len(shared)>1 and len({s["key"] for s in shared})==len(shared)


@pytest.mark.parametrize("label",["<img src=x onerror=alert(1)>","<script>alert(1)</script>","https://example.test/form", "call 91234567", "person@example.com", "/"+"Users/"+"example/"+"private", "C:\\Users\\example", "GROUP_privateidentity"])
def test_suspect_catalogue_label_fails_explicitly_not_silently_dropped(label):
    data=fixture(); data[0][0]["answer"]["Survey"]=label
    with pytest.raises(ScopeError,match="unsafe_or_missing_label"):
        build_scope_index(*data)


def test_payload_closed_projection_has_no_private_ids_answers_paths_or_nonfinite_values():
    data=fixture()
    for r in data[0]: r.update(raw={"secret":"private answer"},phone="91234567",school="Private school",dob="2010-01-01")
    index=build_scope_index(*data); raw=canonical_json(index)
    for forbidden in ("PRIVATE-content","child-one","child-two","exit-child","private answer","91234567","submission_id","child_id","Private school","dob"):
        assert forbidden not in raw
    for field in ("submission_id","answer","phone","school","dob","raw"):
        corrupt=deepcopy(index); corrupt["profiles"][0][field]="PRIVATE"
        with pytest.raises(ScopeError): validate_index(corrupt)
    for value in (float("nan"),float("inf"),True,-1,0,1.5):
        corrupt=deepcopy(index); corrupt["records"][0]["count"]=value
        with pytest.raises(ScopeError): validate_index(corrupt)


def test_input_reordering_canonical_serialization_and_integer_outputs():
    data=fixture(); original=build_scope_index(*data)
    shuffled=deepcopy(data); rng=random.Random(610123)
    for rows in shuffled[:3]: rng.shuffle(rows)
    assert canonical_json(build_scope_index(*shuffled))==canonical_json(original)
    result=query_scope(original)
    def walk(v):
        if isinstance(v,dict):
            for x in v.values(): walk(x)
        elif isinstance(v,list):
            for x in v: walk(x)
        elif isinstance(v,(int,float)) and not isinstance(v,bool): assert type(v) is int
    walk(result)


def test_identical_slot_profiles_preserve_multiplicity():
    data=fixture()
    for r in data[0]: r["observed_at"]=None
    # Give both waves the same source, survey and timing; no rerun of selection.
    for r in data[0]: r["source_type"]="alpha"
    index=build_scope_index(*data)
    ac=next(r for r in index["samples"] if r["code"]=="AC")
    assert len(ac["profiles"])==2 and len(set(ac["profiles"]))==1
    assert ac["count"]==2 and next(r for r in query_scope(index)["samples"] if r["code"]=="AC")["count"]==2


def test_flow_manual_history_missing_ledger_not_guessed_and_unknown_status_errors():
    data=fixture(); data[0][-1]["manual_keep"]=True
    index=build_scope_index(*data)
    assert query_scope(index)["flow"]["lanes"] is None
    assert query_scope(index)["flow"]["reason"]=="persisted_checkpoint_ledger_required"
    data=fixture(); data[0][-1]["status"]="new-pipeline-status"
    with pytest.raises(ScopeError,match="unsupported_terminal_status"): build_scope_index(*data)
    data=fixture(); data[0][-1]["wave_reason"]="new-unselected-reason"
    with pytest.raises(ScopeError,match="unsupported_unselected_reason"): build_scope_index(*data)


def test_stage_summary_disagreement_stops_flow_branch_and_sample_disagreement_errors():
    data=fixture(); data[3]["stage_counts"]={"2.1.3":9999}
    result=query_scope(build_scope_index(*data))
    assert result["flow"]["status"]=="unavailable" and result["raw"]["student"]>0
    data=fixture(); data[3]["EF"]=9999
    with pytest.raises(ScopeError,match="summary_sample_mismatch:EF"): build_scope_index(*data)


def test_approved_checkpoint_ledger_and_school_extension_without_fake_defaults():
    data=fixture(); base=build_scope_index(*data)
    data[0][-1]["manual_keep"]=True
    # Construct persisted fixture facts independently of the builder.
    ledger=[]
    for r in data[0]:
        status=r["status"]
        if r["selected_wave"]: stage,reason="selected","selected"
        elif status in {"excluded_school","incomplete","unrecognized_survey","sparse_response"}: stage,reason="screening",status
        elif status=="exact_input_repeat": stage,reason="exact_copies",status
        elif status=="short_repeat": stage,reason="repeat_handling",status
        else: stage,reason="selection",r.get("wave_reason") or status
        ledger.append(dict(submission_id=r["submission_id"],exit_stage=stage,reason=reason))
    evidence=dict(revision="synthetic-ledger-v1",rows=ledger)
    school=dict(revision="synthetic-school-r1",statuses=["reviewed","unresolved"],rows=[
        dict(submission_id=r["submission_id"],status="reviewed" if i%2 else "unresolved") for i,r in enumerate(data[0])])
    result=query_scope(build_scope_index(*data,flow_evidence=evidence,school_projection=school))
    assert result["flow"]["status"]=="available"
    assert result["school"]["status"]=="available"
    for role in ROLES: assert sum(s[role] for s in result["school"]["counts"].values())==result["raw"][role]
    absent=query_scope(base)
    assert absent["school"]["counts"] is None and absent["identity_groups"]["count"] is None
    evidence["rows"].pop()
    with pytest.raises(ScopeError,match="incomplete_checkpoint_ledger"):
        build_scope_index(*data,flow_evidence=evidence)


@pytest.mark.parametrize("defect",["duplicate_slot","missing_analysis","unknown_member","adult_duplicate","adult_missing","adult_wrong_baseline"])
def test_bad_formal_membership_fails_instead_of_replacing(defect):
    data=fixture()
    if defect=="duplicate_slot": data[1].append(dict(data[1][0]))
    if defect=="missing_analysis": data[1].pop()
    if defect=="unknown_member": data[1][0]["submission_id"]="not-in-release"
    if defect=="adult_duplicate": data[2].append(dict(data[2][0]))
    if defect=="adult_missing": data[2].pop()
    if defect=="adult_wrong_baseline": data[2][0]["submission_id"]="child-oneparentT1"
    with pytest.raises(ScopeError): build_scope_index(*data)


def test_old_snapshots_fail_closed_do_not_approximate_filters():
    with pytest.raises(ScopeError,match="compatible_scope_export_required"):
        query_scope({"format":"study2_static_v1","views":[]})


def test_local_release_source_mapping_dataframe_input_and_metadata_validation():
    import pandas as pd
    data=fixture()
    for r in data[0]:
        r.pop("source_type")
        r["source_label"]="qualtrics-wave" if r["source_label"]=="beta" else "paperform-wave"
    index=build_scope_index(data[0],pd.DataFrame(data[1]),pd.DataFrame(data[2]),data[3])
    assert {s["label"] for s in index["sources"]}=={"paperform","qualtrics"}
    for mutate in (lambda d:d[0][0].pop("source_label"),lambda d:d[3].update(release_id="/Users/private"),
                   lambda d:d[0][0].update(time_confidence="new_date_policy")):
        corrupt=deepcopy(data); mutate(corrupt)
        with pytest.raises(ScopeError): build_scope_index(*corrupt)


def test_query_result_cannot_mutate_index_through_nested_metadata_aliases():
    index=build_scope_index(*fixture())
    before=canonical_json(index)
    query_scope(index)["reconciliation"]["checked"].clear()
    assert canonical_json(index)==before


def test_legitimate_survey_year_ranges_and_iso_dates_are_not_phone_numbers():
    data=fixture()
    data[0][0]["answer"]["Survey"]="Student questionnaire 2025-2026, launched 2025-09-03"
    index=build_scope_index(*data)
    assert any(s["label"]==data[0][0]["answer"]["Survey"] for s in index["surveys"])


def test_corrupt_aggregate_joint_samples_cannot_exceed_published_single_slot_margins():
    index=build_scope_index(*fixture())
    next(r for r in index["samples"] if r["code"]=="AC")["count"]=3
    with pytest.raises(ScopeError,match="sample_marginal"):
        validate_index(index)


def test_missing_source_label_keeps_existing_static_intake_unknown_category():
    data=fixture(); data[0][0].pop("source_type"); data[0][0]["source_label"]=""
    assert any(s["label"]=="unknown" for s in build_scope_index(*data)["sources"])


REVIEW_PRIVATE_LABELS = ["Contact 9123-4567", "Contact 6123-4567", "Contact 9123/4567",
    "Contact 2025-2026", "Questionnaire contact 2025-2026", "Contact 2025-09-03",
    "Survey 9123-4567", "Contact 9123 4567", "Contact 9123.4567", "Contact 9123—4567",
    "Survey 2025-2027", "Survey 2025/2027", "Survey 2025-02-30", "Survey 1900-02-29", "Survey 2101-01-01", "2025-2026",
    *[prefix+"_"+"a"*24 for prefix in ("SUB","GROUP","RESP","CHILD","CASE","REV","PKG","RB","DEC","DYAD","DRES","DEVENT","INV","RUN")],
    "R_"+"x"*12]


@pytest.mark.parametrize("label", REVIEW_PRIVATE_LABELS)
def test_review_r2_rejects_private_label_in_every_catalogue_field(label):
    # Same rejected value at each externally supplied catalogue boundary.
    for field in ("Survey", "source_type", "survey_form_id", "survey_form_version"):
        data=fixture()
        if field=="Survey": data[0][0]["answer"][field]=label
        else: data[0][0][field]=label
        with pytest.raises(ScopeError,match="unsafe_or_missing_label"):
            build_scope_index(*data)


@pytest.mark.parametrize("label", [
    "Student questionnaire 2025-2026 launched 2025-09-03",
    "Survey 2025/2026 from 2024-02-29", "學年 2025-2026 問卷", "Academic year 1999-2000",
])
def test_review_r2_preserves_valid_academic_year_and_calendar_names(label):
    data=fixture(); data[0][0]["answer"]["Survey"]=label
    index=build_scope_index(*data)
    assert any(s["label"]==label for s in index["surveys"])


def fully_reconciled_fixture():
    data=fixture(); records=data[0]
    screened={"excluded_school","sparse_response","incomplete","unrecognized_survey"}
    before_repeat=screened|{"exact_input_repeat"}
    retained=before_repeat|{"short_repeat","manual_excluded"}
    data[3]["stage_counts"]={"2.1.3":sum(r["status"] not in screened for r in records),
        "2.1.4":{"eligible_submissions":sum(r["status"] not in before_repeat for r in records)},
        "2.1.6":sum(r["status"] not in retained for r in records)}
    return data


REQUIRED_REVIEW_CHECKS={"submissions","status_counts","2.1.3","2.1.4","2.1.6","A","B","C","D","AC","BD","E","F","EF"}


@pytest.mark.parametrize("missing",sorted(REQUIRED_REVIEW_CHECKS))
def test_review_r2_any_missing_required_check_is_partial(missing):
    data=fully_reconciled_fixture()
    if missing.startswith("2."): data[3]["stage_counts"].pop(missing)
    else: data[3].pop(missing)
    result=query_scope(build_scope_index(*data))
    assert result["reconciliation"]["status"]=="partial"
    assert missing not in result["reconciliation"]["checked"]
    assert "EF" in result["reconciliation"]["checked"] or missing=="EF"


@pytest.mark.parametrize("checkpoint",["2.1.3","2.1.4","2.1.6"])
def test_review_r2_checkpoint_disagreement_stays_partial(checkpoint):
    data=fully_reconciled_fixture()
    data[3]["stage_counts"][checkpoint]={"eligible_submissions":9999} if checkpoint=="2.1.4" else 9999
    result=query_scope(build_scope_index(*data))
    assert result["flow"]["status"]=="unavailable"
    assert result["reconciliation"]["status"]=="partial"
    assert checkpoint not in result["reconciliation"]["checked"]
    assert {"submissions","status_counts","EF"}<=set(result["reconciliation"]["checked"])


def test_review_r2_checked_requires_every_defined_check_and_available_flow():
    index=build_scope_index(*fully_reconciled_fixture())
    result=query_scope(index)
    assert result["reconciliation"]==dict(status="checked",checked=sorted(REQUIRED_REVIEW_CHECKS))
    assert result["flow"]["status"]=="available"
    assert query_scope(build_scope_index(*fixture()))["reconciliation"]["status"]=="partial"
    for feature in ("flow","adult"):
        broken=deepcopy(index)
        broken["meta"][feature].update(status="unavailable",reason="synthetic_missing_evidence")
        if feature=="flow": broken["meta"][feature]["revision"]=None
        else:
            broken["meta"][feature].update(policy=None,evidence=None)
            broken["samples"]=[s for s in broken["samples"] if s["code"]!="BD"]
        with pytest.raises(ScopeError,match="invalid_reconciliation"):
            validate_index(broken)


@pytest.mark.parametrize("field",["release_id","survey_form_id","survey_form_version"])
def test_review_r2_release_ids_are_public_only_in_release_metadata(field):
    data=fixture(); release="RUN_"+"b"*32
    if field=="release_id":
        data[3][field]=release
        assert query_scope(build_scope_index(*data))["release_id"]==release
    else:
        data[0][0][field]=release
        with pytest.raises(ScopeError,match="unsafe_or_missing_label"):
            build_scope_index(*data)
