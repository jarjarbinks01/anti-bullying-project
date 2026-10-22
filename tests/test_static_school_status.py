"""Synthetic school-status audit, overlap and exact scope-signature tests."""
from copy import deepcopy
from itertools import product
import json
import random

import pytest

from study2.static_school_status import (EVIDENCE_FORMAT, LABEL_STATES, RECORD_PRIORITY, SchoolEvidenceError,
    build_scope_attachment, canonical_json, fingerprint, local_record_projection, normalize_school_key,
    project_school_status, query_school_scope, reconcile_school_status, validate_public_projection, validate_scope_attachment)


def fixture():
    bundle=dict(format=EVIDENCE_FORMAT,release_id="synthetic-release",dictionary_sha256="a"*64,review_state="recorded_review",
                decision_revision="review-v1",criteria_revision="criteria-v1",historical_queue=[],current_queue=[],
                records=[],dictionary=[],decisions=[],criteria=[])
    for cid in ("current-use","background-use","absent-from-release"):
        bundle["criteria"].append(dict(criterion_id=cid,release_id="synthetic-release",revision="criteria-v1",
            accepted_by="Synthetic coordinator",evidence_ref="synthetic accepted criterion",description="Explicit synthetic operational criterion: "+cid))

    def queue(name, historical=True, current=False):
        row=dict(raw_name=name,normalized_key=name.strip().lower())
        if historical: bundle["historical_queue"].append(row)
        if current: bundle["current_queue"].append(dict(row))

    def decision(name, action, canonical=None, criterion=None):
        bundle["decisions"].append(dict(decision_id="synthetic-decision-"+str(len(bundle["decisions"])),normalized_key=name,
            action=action,canonical_school_name=canonical,release_id="synthetic-release",dictionary_sha256="a"*64,revision="review-v1",
            reviewer="Synthetic reviewer",reason="Synthetic documented decision",evidence_ref="Synthetic decision row",
            criterion_id=criterion))
        if action in {"map","delete"}:
            bundle["dictionary"].append(dict(normalized_key=name,action=action,canonical_school_name=canonical))

    for name in ("map alpha","map beta","invalid a","invalid b","historical secondary","old excluded","removed",
                 "pending one","unknown no evidence","ambiguous use","absent no proof"):
        queue(name,current=name in {"pending one","unknown no evidence","ambiguous use"})
    queue("new pending",historical=False,current=True)
    bundle["historical_queue"].append(dict(raw_name=" MAP ALPHA ",normalized_key="map alpha"))
    for name in ("map alpha","map beta"):decision(name,"map","Synthetic Canonical School")
    for name in ("invalid a","invalid b"):decision(name,"delete")
    for name in ("historical secondary","old excluded"):decision(name,"historical",criterion="background-use")
    decision("removed","historical",criterion="absent-from-release")
    for name in ("pending one","new pending","ambiguous use"):decision(name,"pending")

    def field(name="", action="missing", canonical=None, *, use="cleaning_and_identity", actionable=True, criterion="current-use", caused=False):
        if not name:
            return dict(raw_name="",use="none",actionable=False,criterion_id=None,published_action="missing",published_canonical=None,caused_exclusion=False)
        return dict(raw_name=name,use=use,actionable=actionable,criterion_id=criterion,published_action=action,published_canonical=canonical,caused_exclusion=caused)

    def record(sid,role,primary,secondary=None,status="eligible"):
        primary_key="school_from_student" if role=="student" else "school_from_parent"
        secondary_key="school_from_parent" if role=="student" else "school_from_student"
        bundle["records"].append(dict(submission_id=sid,role=role,status=status,
            school_fields={primary_key:primary,secondary_key:secondary or field()}))

    canon="Synthetic Canonical School"
    record("s0","student",field("Map Alpha","map",canon),field(" MAP ALPHA ","map",canon,use="cleaning"))
    record("p0","parent",field("map alpha","map",canon))
    record("s1","student",field("map beta","map",canon))
    record("p1","parent",field("invalid a","delete",caused=True),field("invalid b","delete",use="cleaning",caused=True),status="excluded_school")
    record("s2","student",field("pending one","unmapped"))
    record("p2","parent",field("pending one","unmapped"))
    record("s3","student",field(),field("historical secondary","not_used",use="background",actionable=False,criterion="background-use"))
    record("p3","parent",field("old excluded","unmapped",use="cleaning",actionable=False,criterion="background-use"),status="incomplete")
    record("s4","student",field("unknown no evidence","unmapped"))
    record("p4","parent",field("ambiguous use","unmapped",use="unknown",actionable=None,criterion=None))
    record("s5","student",field("not in review","delete",caused=True),status="excluded_school")
    record("p5","parent",field("known school","map","Other Synthetic School"))
    record("s6","student",field("new pending","unmapped"),field("pending one","unmapped",use="cleaning"))
    return bundle


def pins(bundle):
    return {k:bundle[k] for k in ("release_id","dictionary_sha256","review_state","decision_revision","criteria_revision")}|dict(bundle_sha256=fingerprint(bundle))


def audit(bundle=None):
    bundle=fixture() if bundle is None else bundle
    return reconcile_school_status(bundle,pins(bundle))


def label(report,key):
    return next(l for l in report["labels"] if l["normalized_key"]==key)


def test_all_resolution_states_and_units_are_evidence_based():
    report=audit(); public=project_school_status(report)
    assert public["availability"]=="available" and public["reconciliation_status"]=="not_reconciled"
    wide=public["release_wide"]
    assert wide["labels"]["historical_queue"]==11 and wide["labels"]["current_queue"]==4
    assert wide["labels"]["review_universe"]==12
    assert wide["labels"]["states"]==dict(mapped=2,invalid=2,historical_only=3,pending=2,unreviewed=0,not_reconciled=3)
    assert wide["labels"]["historical_accounted"]==8 and wide["labels"]["historical_resolved"]==7
    assert not wide["labels"]["all_historical_accounted"] and not wide["labels"]["all_historical_resolved"]
    assert wide["schools"]==dict(unit="canonical_school_names",verified_reviewed_canonical_schools=1)
    assert label(report,"map alpha")["raw_names"]==[" MAP ALPHA ","map alpha"]
    assert len(label(report,"map alpha")["occurrences"])==3
    assert label(report,"removed")["status"]=="historical_only"
    assert label(report,"absent no proof")["status"]=="not_reconciled"


def test_distinct_records_multiple_labels_fields_and_school_exclusion_attribution():
    scope=project_school_status(audit())["current_scope"]
    assert scope["raw"]==dict(student=7,parent=6)
    assert scope["affected"]==dict(student=6,parent=5)
    assert scope["excluded_school"]==dict(student=1,parent=1)
    assert scope["verified_queue_attributed_exclusion"]==dict(student=0,parent=1)
    assert scope["actionable_pending"]==dict(student=2,parent=1)
    assert scope["label_record_links"]==13 and scope["school_field_occurrences"]==14
    assert scope["records_with_multiple_labels"]==2
    assert scope["labels"]==dict(unit="normalized_labels",affected=10,actionable_pending=2,unreviewed=0,not_reconciled=2)
    for role in ("student","parent"):
        assert sum(v[role] for v in scope["status_partition"].values())==scope["raw"][role]
    # Two invalid labels on p1 are one excluded parent record, not two.
    assert project_school_status(audit(),["p1"])["current_scope"]["verified_queue_attributed_exclusion"]==dict(student=0,parent=1)


@pytest.mark.parametrize("key",["historical secondary","old excluded"])
def test_secondary_and_excluded_only_labels_need_accepted_criteria(key):
    b=fixture()
    for r in b["records"]:
        for c in r["school_fields"].values():
            if c["raw_name"]==key:c["criterion_id"]=None
    report=audit(b)
    assert label(report,key)["status"]=="not_reconciled"
    assert "field_actionability_evidence_missing" in label(report,key)["problems"]
    assert any(o["record_status"]=="incomplete" for o in label(audit(),"old excluded")["occurrences"])
    assert not any(o["primary_field"] for o in label(audit(),"historical secondary")["occurrences"])


def test_secondary_delete_is_not_dismissed_as_background():
    b=fixture();r=next(r for r in b["records"] if r["submission_id"]=="p1")
    r["school_fields"]["school_from_parent"]=deepcopy(next(r for r in b["records"] if r["submission_id"]=="p5")["school_fields"]["school_from_parent"])
    report=audit(b)
    assert label(report,"invalid b")["status"]=="invalid"
    assert project_school_status(report,["p1"])["current_scope"]["verified_queue_attributed_exclusion"]["parent"]==1


def test_absence_from_dictionary_or_current_release_is_not_completion():
    b=fixture();b["dictionary"]=[]; b["decisions"]=[]
    report=audit(b)
    assert all(l["status"]=="not_reconciled" for l in report["labels"])
    assert not project_school_status(report)["release_wide"]["labels"]["all_historical_resolved"]
    b=fixture();b["decisions"]=[d for d in b["decisions"] if d["normalized_key"]!="removed"]
    assert label(audit(b),"removed")["status"]=="not_reconciled"


def test_pending_can_be_reconciled_without_claiming_review_complete():
    b=fixture();unknown={"unknown no evidence","ambiguous use","absent no proof"}
    for queue in ("historical_queue","current_queue"):
        b[queue]=[q for q in b[queue] if q["normalized_key"] not in unknown]
    report=audit(b); output=project_school_status(report)
    assert output["reconciliation_status"]=="reconciled"
    assert output["release_wide"]["labels"]["all_historical_accounted"]
    assert not output["release_wide"]["labels"]["all_historical_resolved"]
    assert output["release_wide"]["labels"]["states"]["pending"]==2


@pytest.mark.parametrize("artifact",["dictionary","decisions"])
def test_missing_artifact_is_unavailable_not_zero_or_completed(artifact):
    b=fixture();b[artifact]=None
    result=project_school_status(audit(b))
    assert result["availability"]=="unavailable" and result["reconciliation_status"]=="not_reconciled"
    assert result["release_wide"] is None and result["current_scope"] is None
    assert local_record_projection(audit(b)) is None


def test_no_real_bundle_never_invents_the_historical_count():
    result=project_school_status(reconcile_school_status(None,pins(fixture())))
    assert result["problems"]==["evidence_bundle_missing"]
    assert result["release_wide"] is None and result["revision"] is None


@pytest.mark.parametrize("field,value",[("release_id","stale-release"),("dictionary_sha256","b"*64),
    ("decision_revision","review-v0"),("criteria_revision","criteria-v0")])
def test_stale_bundle_or_changed_input_fingerprint_is_unavailable(field,value):
    b=fixture(); expected=pins(b);b[field]=value
    result=project_school_status(reconcile_school_status(b,expected))
    assert result["availability"]=="unavailable"
    assert field+"_mismatch" in result["problems"] and "input_fingerprint_changed" in result["problems"]


def test_fingerprint_change_without_revision_change_also_stops_reconciliation():
    b=fixture();expected=pins(b);b["decisions"][0]["reason"]="Changed private review evidence"
    result=project_school_status(reconcile_school_status(b,expected))
    assert result["problems"]==["input_fingerprint_changed"]
    assert result["current_scope"] is None


@pytest.mark.parametrize("field,value,reason",[("release_id","old-release","stale_decision_release"),
    ("dictionary_sha256","b"*64,"stale_decision_dictionary"),("revision","review-v0","stale_decision_revision"),
    ("reviewer","","decision_provenance_missing"),("reason","","decision_provenance_missing"),
    ("evidence_ref","","decision_provenance_missing")])
def test_stale_or_missing_per_decision_provenance_does_not_resolve_label(field,value,reason):
    b=fixture();b["decisions"][0][field]=value
    l=label(audit(b),"map alpha")
    assert l["status"]=="not_reconciled" and reason in l["problems"]


def test_conflicting_decisions_and_dictionary_entries_are_audited_not_overwritten():
    b=fixture();conflict=deepcopy(b["decisions"][0]);conflict.update(decision_id="synthetic-conflict",action="delete",canonical_school_name=None)
    b["decisions"].append(conflict)
    assert "conflicting_decisions" in label(audit(b),"map alpha")["problems"]
    b=fixture();b["dictionary"].append(dict(normalized_key="map alpha",action="delete",canonical_school_name=None))
    assert "conflicting_dictionary_entries" in label(audit(b),"map alpha")["problems"]


def test_decision_not_applied_requires_existing_correction_rerun_publication_workflow():
    b=fixture();cell=b["records"][0]["school_fields"]["school_from_student"]
    cell.update(published_action="unmapped",published_canonical=None)
    assert "mapping_not_reflected_in_publication" in label(audit(b),"map alpha")["problems"]
    b=fixture();record=next(r for r in b["records"] if r["submission_id"]=="p1")
    record["status"]="eligible"
    for c in record["school_fields"].values():c.update(published_action="unmapped",caused_exclusion=False)
    result=audit(b)
    assert label(result,"invalid a")["status"]=="not_reconciled"
    assert project_school_status(result)["current_scope"]["excluded_school"]["parent"]==0


def test_explicit_empty_scope_zeroes_current_counts_but_preserves_historical_evidence():
    report=audit(); all_scope=project_school_status(report); empty=project_school_status(report,[])
    assert empty["release_wide"]==all_scope["release_wide"]
    assert empty["current_scope"]["raw"]==dict(student=0,parent=0)
    assert empty["current_scope"]["labels"]["actionable_pending"]==0
    assert project_school_status(report,["s2","s2"])["current_scope"]["raw"]["student"]==1
    with pytest.raises(SchoolEvidenceError,match="scope_record_not_in_pinned_release"):
        project_school_status(report,["record-outside-release"])


def profile_fixture(report):
    # R01 owns actual profiles/predicates. Synthetic profiles mix roles and
    # distinct source/version/day combinations; this test supplies its mask.
    mapping={r["submission_id"]:(0 if r["role"]=="student" else 1)+(2 if r["submission_id"] in {"s2","s4","s6","p2","p4"} else 0)
             for r in report["records"]}
    return mapping,["student","parent","student","parent"]


def direct_scope_oracle(report,selected):
    # Direct distinct unions over PRIVATE labels/records, not aggregate cells.
    records=[r for r in report["records"] if r["submission_id"] in selected]
    affected_labels={l["normalized_key"] for l in report["labels"] if any(o["submission_id"] in selected for o in l["occurrences"])}
    pending_labels={l["normalized_key"] for l in report["labels"] if l["status"]=="pending" and any(
        o["submission_id"] in selected and o["actionable"] is True for o in l["occurrences"])}
    unknown_labels={l["normalized_key"] for l in report["labels"] if l["status"]=="not_reconciled" and l["normalized_key"] in affected_labels}
    return dict(raw={role:sum(r["role"]==role for r in records) for role in ("student","parent")},
        affected={role:sum(r["role"]==role and bool(r["label_keys"]) for r in records) for role in ("student","parent")},
        labels=dict(unit="normalized_labels",affected=len(affected_labels),actionable_pending=len(pending_labels),
                    unreviewed=sum(l["status"]=="unreviewed" and l["normalized_key"] in affected_labels for l in report["labels"]),
                    not_reconciled=len(unknown_labels)))


def test_scope_profile_attachment_exhaustively_matches_direct_distinct_label_unions():
    report=audit();mapping,roles=profile_fixture(report)
    index=build_scope_attachment(report,mapping,roles)
    for bits in product([False,True],repeat=len(roles)):
        mask=list(bits);selected={sid for sid,p in mapping.items() if mask[p]}
        actual=query_school_scope(index,mask)
        direct=project_school_status(report,selected)
        assert actual==direct
        oracle=direct_scope_oracle(report,selected)
        for name in ("raw","affected","labels"):
            assert actual["current_scope"][name]==oracle[name]
    assert query_school_scope(index,[True]*4)["current_scope"]["labels"]["actionable_pending"]==2
    # Three records sharing one pending label do not create three labels.
    assert project_school_status(report,["s2","p2","s6"])["current_scope"]["labels"]["actionable_pending"]==2
    assert project_school_status(report,["s2","p2"])["current_scope"]["labels"]["actionable_pending"]==1


def test_source_version_date_mask_examples_use_the_same_fixed_membership_predicate():
    report=audit()
    # IDs are private and used only in this synthetic test's direct oracle.
    metadata={r["submission_id"]:dict(source="alpha" if i%2 else "beta",version="form-a" if i%3 else "form-b",
        day=None if i%4==0 else "2025-02-01" if i%2 else "2025-06-01") for i,r in enumerate(report["records"])}
    signatures=sorted({(r["role"],metadata[r["submission_id"]]["source"],metadata[r["submission_id"]]["version"],metadata[r["submission_id"]]["day"] or "unknown") for r in report["records"]})
    mapping={r["submission_id"]:signatures.index((r["role"],metadata[r["submission_id"]]["source"],metadata[r["submission_id"]]["version"],metadata[r["submission_id"]]["day"] or "unknown")) for r in report["records"]}
    index=build_scope_attachment(report,mapping,[s[0] for s in signatures])
    for sources,versions,start,end,include_unknown in product([[],["alpha"],["beta"],["alpha","beta"]],[[],["form-a"],["form-b"],["form-a","form-b"]],
        [None,"2025-02-01"],[None,"2025-06-01"],[False,True]):
        mask=[source in sources and version in versions and (include_unknown if day=="unknown" else (start is None or day>=start) and (end is None or day<=end))
              for _,source,version,day in signatures]
        selected={sid for sid,p in mapping.items() if mask[p]}
        assert query_school_scope(index,mask)==project_school_status(report,selected)


def test_background_record_does_not_keep_pending_label_in_current_actionable_count():
    b=fixture();pending=next(r for r in b["records"] if r["submission_id"]=="p2")
    pending["school_fields"]["school_from_parent"].update(actionable=False,criterion_id="background-use")
    report=audit(b)
    assert label(report,"pending one")["status"]=="pending"
    selected=project_school_status(report,["p2"])
    assert selected["current_scope"]["labels"]["affected"]==1
    assert selected["current_scope"]["labels"]["actionable_pending"]==0


def test_record_attachment_is_explicitly_local_and_covers_every_raw_record_once():
    report=audit();rows=local_record_projection(report)
    assert set(rows)=={"revision","statuses","rows"} and rows["statuses"]==list(RECORD_PRIORITY)
    assert len(rows["rows"])==13 and len({r["submission_id"] for r in rows["rows"]})==13
    assert "submission_id" in canonical_json(rows)
    mapping,roles=profile_fixture(report); index=build_scope_attachment(report,mapping,roles)
    assert "submission_id" not in canonical_json(index)


def test_private_school_names_provenance_and_ids_never_enter_online_objects():
    report=audit();mapping,roles=profile_fixture(report)
    public=canonical_json(project_school_status(report));index=canonical_json(build_scope_attachment(report,mapping,roles))
    for value in ("map alpha","Synthetic Canonical School","Synthetic reviewer","Synthetic decision row","normalized_key","submission_id","school_from_student","raw_name","evidence_ref"):
        assert value not in public and value not in index
    assert "Synthetic Canonical School" in canonical_json(report)
    poisoned=deepcopy(project_school_status(report));poisoned["raw_name"]="PRIVATE"
    with pytest.raises(SchoolEvidenceError):validate_public_projection(poisoned)
    poisoned=deepcopy(build_scope_attachment(report,mapping,roles));poisoned["label_cells"][0]["label_id"]="PRIVATE"
    with pytest.raises(SchoolEvidenceError):validate_scope_attachment(poisoned)


def test_report_and_outputs_do_not_mutate_inputs_or_alias_each_other():
    b=fixture();before=canonical_json(b);report=audit(b)
    assert canonical_json(b)==before
    snapshot=canonical_json(report);out=project_school_status(report)
    out["release_wide"]["labels"]["states"].clear()
    assert canonical_json(report)==snapshot
    corrupted=deepcopy(report);corrupted["labels"][0]["status"]="mapped"
    with pytest.raises(SchoolEvidenceError,match="private_report_changed"):project_school_status(corrupted)


@pytest.mark.parametrize("bad",[float("nan"),float("inf"),-1,True,1.5])
def test_counts_require_finite_safe_integers(bad):
    output=project_school_status(audit());output["current_scope"]["raw"]["student"]=bad
    with pytest.raises(SchoolEvidenceError):validate_public_projection(output)


@pytest.mark.parametrize("mutate",[
    lambda b:b["records"].append(deepcopy(b["records"][0])),
    lambda b:b["records"][0]["school_fields"].pop("school_from_parent"),
    lambda b:b["decisions"].append(deepcopy(b["decisions"][0])),
    lambda b:b["records"][0].update(status="unknown-new-status"),
    lambda b:b["historical_queue"][0].update(normalized_key="wrong-key"),
    lambda b:b["dictionary"][0].update(action="guess-map"),
])
def test_malformed_or_incomplete_evidence_fails_explicitly(mutate):
    b=fixture();mutate(b)
    with pytest.raises(SchoolEvidenceError):audit(b)


def test_wrong_scope_profiles_roles_ids_and_masks_are_not_approximated():
    report=audit();mapping,roles=profile_fixture(report)
    missing=dict(mapping);missing.pop("s0")
    with pytest.raises(SchoolEvidenceError):build_scope_attachment(report,missing,roles)
    wrong=dict(mapping);wrong["s0"]=1
    with pytest.raises(SchoolEvidenceError):build_scope_attachment(report,wrong,roles)
    index=build_scope_attachment(report,mapping,roles)
    for mask in ([True], [1]*4, [], [True]*5):
        with pytest.raises(SchoolEvidenceError):query_school_scope(index,mask)


def test_input_reordering_preserves_classification_but_new_inventory_has_new_hash():
    b=fixture();original=audit(b);rng=random.Random(630121)
    for name in ("historical_queue","current_queue","records","dictionary","decisions","criteria"):rng.shuffle(b[name])
    changed=audit(b)
    assert original["labels"]==changed["labels"] and original["records"]==changed["records"]
    assert original["context"]["bundle_sha256"]!=changed["context"]["bundle_sha256"]
    for key in ("release_wide","current_scope"):
        assert project_school_status(original)[key]==project_school_status(changed)[key]


def test_safe_public_metadata_and_closed_shapes_do_not_allow_free_text_leakage():
    b=fixture();expected=pins(b);expected["decision_revision"]="reviewer@example.com"
    with pytest.raises(SchoolEvidenceError):reconcile_school_status(b,expected)
    out=project_school_status(audit());out["problems"]=["PRIVATE raw reason"]
    with pytest.raises(SchoolEvidenceError):validate_public_projection(out)
    with pytest.raises(SchoolEvidenceError):canonical_json({"bad":float("nan")})


@pytest.mark.parametrize("change",["state","historical","current"])
def test_scope_signatures_cannot_rewrite_release_wide_label_evidence(change):
    report=audit();mapping,roles=profile_fixture(report)
    index=build_scope_attachment(report,mapping,roles)
    row=next(r for r in index["label_cells"] if r["status"]=="historical_only" and not r["profiles"])
    if change=="state":row["status"]="mapped"
    elif change=="historical":row.update(historical=False,current=True)
    else:row["current"]=True
    with pytest.raises(SchoolEvidenceError):validate_scope_attachment(index)


@pytest.mark.parametrize("change",["links","fields","overlap","partition","pending","unknown","schools"])
def test_public_projection_rejects_impossible_count_relationships(change):
    output=project_school_status(audit());scope=output["current_scope"]
    if change=="links":scope["label_record_links"]=0
    elif change=="fields":scope["school_field_occurrences"]=100
    elif change=="overlap":scope["records_with_multiple_labels"]=0
    elif change=="partition":scope["affected"]["student"]-=1
    elif change=="pending":scope["labels"]["actionable_pending"]=3
    elif change=="unknown":scope["labels"]["not_reconciled"]=4
    else:output["release_wide"]["schools"]["verified_reviewed_canonical_schools"]=3
    with pytest.raises(SchoolEvidenceError):validate_public_projection(output)


@pytest.mark.parametrize("action",["historical","pending"])
def test_non_mapping_decision_with_canonical_school_is_not_reconciled(action):
    b=fixture();d=next(d for d in b["decisions"] if d["action"]==action)
    d["canonical_school_name"]="Unapproved Synthetic School"
    assert label(audit(b),d["normalized_key"])["status"]=="not_reconciled"


def test_missing_both_artifacts_reports_both_evidence_gaps():
    b=fixture();b["dictionary"]=None;b["decisions"]=None
    assert project_school_status(audit(b))["problems"]==["decision_artifact_missing","dictionary_evidence_missing"]


@pytest.mark.parametrize("key,value",[("criterion_id","background-use"),("published_canonical","Synthetic School")])
def test_missing_school_field_cannot_carry_a_decision_or_canonical_value(key,value):
    b=fixture()
    # Explicitly choose a genuinely empty field, independent of fixture ordering.
    cell=next(c for r in b["records"] for c in r["school_fields"].values() if not c["raw_name"])
    cell[key]=value
    with pytest.raises(SchoolEvidenceError):audit(b)


def test_explicit_no_recorded_review_is_unreviewed_not_missing_or_completed():
    b=fixture();b.update(review_state="no_recorded_review",decision_revision=None,criteria_revision=None,decisions=[],criteria=[])
    report=audit(b);public=project_school_status(report)
    assert public["availability"]=="available" and public["reconciliation_status"]=="not_reconciled"
    assert public["evidence"]["review_state"]=="no_recorded_review" and public["evidence"]["decision_revision"] is None
    assert all(l["status"]=="unreviewed" for l in report["labels"])
    assert public["release_wide"]["labels"]["states"]["unreviewed"]==12
    assert public["release_wide"]["labels"]["historical_resolved"]==0
    assert not public["release_wide"]["labels"]["all_historical_resolved"]
    assert public["current_scope"]["labels"]["unreviewed"]==10
    mapping,roles=profile_fixture(report);index=build_scope_attachment(report,mapping,roles)
    for bits in product([False,True],repeat=4):
        mask=list(bits);selected={sid for sid,p in mapping.items() if mask[p]}
        assert query_school_scope(index,mask)==project_school_status(report,selected)


@pytest.mark.parametrize("change",["null_recorded_revision","invented_unrecorded_revision","unrecorded_with_decisions"])
def test_review_absence_cannot_be_disguised_by_a_snapshot_revision(change):
    b=fixture()
    if change=="null_recorded_revision":b["decision_revision"]=None
    else:
        b.update(review_state="no_recorded_review",decision_revision=None)
        if change=="invented_unrecorded_revision":b["decision_revision"]="evidence-snapshot-v1"
    with pytest.raises(SchoolEvidenceError):audit(b)


def test_malicious_school_label_stays_private_and_never_becomes_public_text():
    b=fixture();raw='<script>synthetic_bad_label()</script>'
    key=raw.lower()
    b["historical_queue"].append(dict(raw_name=raw,normalized_key=key))
    b["records"][0]["school_fields"]["school_from_student"].update(raw_name=raw)
    report=audit(b);mapping,roles=profile_fixture(report)
    assert raw in canonical_json(report)
    for output in (project_school_status(report),build_scope_attachment(report,mapping,roles)):
        assert "synthetic_bad_label" not in canonical_json(output)
        assert "<script>" not in canonical_json(output)


def individual_profiles(report):
    return ({r["submission_id"]: i for i, r in enumerate(report["records"])},
            [r["role"] for r in report["records"]])


@pytest.mark.parametrize("unreviewed", [False, True])
@pytest.mark.parametrize("destination", ["s5", "s1"])
def test_scope_signatures_cannot_move_to_unaffected_or_incompatible_same_role_profile(unreviewed, destination):
    b = fixture()
    if unreviewed:
        b.update(review_state="no_recorded_review", decision_revision=None, criteria_revision=None, decisions=[], criteria=[])
    report = audit(b)
    mapping, roles = individual_profiles(report)
    index = build_scope_attachment(report, mapping, roles)
    # Same student role on both sides; all-scope totals and label states stay fixed.
    for cell in index["label_cells"]:
        if mapping["s2"] in cell["profiles"]:
            cell["profiles"] = sorted(set(cell["profiles"]) - {mapping["s2"]} | {mapping[destination]})
            cell["actionable_profiles"] = sorted(set(cell["actionable_profiles"]) - {mapping["s2"]} | {mapping[destination]})
    with pytest.raises(SchoolEvidenceError):
        validate_scope_attachment(index)


def test_actionability_cannot_move_to_an_incompatible_record_within_one_profile():
    report = audit()
    mapping = {r["submission_id"]: int(r["role"] == "parent") for r in report["records"]}
    index = build_scope_attachment(report, mapping, ["student", "parent"])
    pending = next(c for c in index["record_cells"] if c["profile"] == 0 and c["status"] == "pending" and c["label_links"] == 1)
    mapped = next(c for c in index["record_cells"] if c["profile"] == 0 and c["status"] == "mapped" and c["field_occurrences"] == 1)
    assert pending["count"] == mapped["count"] == 1
    pending["actionable_pending"], mapped["actionable_pending"] = False, True
    # All profile and full-scope totals match, but a mapped partition cannot hide pending.
    with pytest.raises(SchoolEvidenceError, match="profile_record_state_or_flag"):
        validate_scope_attachment(index)


def test_attribution_cannot_move_to_historical_partition_within_one_profile():
    report = audit()
    mapping = {r["submission_id"]: int(r["role"] == "parent") for r in report["records"]}
    index = build_scope_attachment(report, mapping, ["student", "parent"])
    invalid = next(c for c in index["record_cells"] if c["profile"] == 1 and c["status"] == "invalid")
    historical = next(c for c in index["record_cells"] if c["profile"] == 1 and c["status"] == "historical_only")
    assert invalid["count"] == historical["count"] == 1
    for key in ("school_excluded", "attributed_exclusion"):
        invalid[key], historical[key] = historical[key], invalid[key]
    with pytest.raises(SchoolEvidenceError, match="profile_record_state_or_flag"):
        validate_scope_attachment(index)


def test_profile_cannot_require_two_distinct_labels_with_only_one_incident_label():
    b = fixture()
    extra = deepcopy(next(r for r in b["records"] if r["submission_id"] == "p1"))
    extra["submission_id"] = "synthetic-extra-parent"
    b["records"].append(extra)
    report = audit(b)
    mapping, roles = individual_profiles(report)
    index = build_scope_attachment(report, mapping, roles)
    # Both labels remain present globally, and p1 still has one affected label.
    # Its record cell nevertheless requires TWO distinct labels.
    cell = next(c for c in index["label_cells"] if c["status"] == "invalid")
    assert cell["count"] == 2
    cell["count"] = 1
    other = deepcopy(cell)
    other["profiles"].remove(mapping["p1"])
    other["actionable_profiles"].remove(mapping["p1"])
    index["label_cells"].append(other)
    with pytest.raises(SchoolEvidenceError, match="profile_record_needs_more_distinct_labels"):
        validate_scope_attachment(index)


@pytest.mark.parametrize("state", [s for s in RECORD_PRIORITY if s not in {"unreviewed", "no_queue_label"}])
def test_no_recorded_review_rejects_every_other_affected_partition(state):
    b = fixture()
    b.update(review_state="no_recorded_review", decision_revision=None, criteria_revision=None, decisions=[], criteria=[])
    output = project_school_status(audit(b))
    partition = output["current_scope"]["status_partition"]
    partition["unreviewed"]["student"] -= 1
    partition[state]["student"] += 1
    with pytest.raises(SchoolEvidenceError):
        validate_public_projection(output)


@pytest.mark.parametrize("state", ["not_reconciled", "unreviewed", "actionable_pending"])
def test_public_label_evidence_cannot_exceed_two_field_record_capacity(state):
    b = fixture()
    if state == "unreviewed":
        b.update(review_state="no_recorded_review", decision_revision=None, criteria_revision=None, decisions=[], criteria=[])
    output = project_school_status(audit(b), ["s4" if state != "actionable_pending" else "s2"])
    output["current_scope"]["labels"].update(affected=3, **{state: 3})
    with pytest.raises(SchoolEvidenceError):
        validate_public_projection(output)


def test_valid_mixed_states_flags_and_duplicate_occurrences_preserve_every_scope():
    b = fixture()
    by_id = {r["submission_id"]: r for r in b["records"]}
    pending_field = deepcopy(by_id["s2"]["school_fields"]["school_from_student"])
    # A higher-priority unresolved label can coexist with actionable pending.
    by_id["s4"]["school_fields"]["school_from_parent"] = deepcopy(pending_field)
    # Pending + invalid on one parent can support BOTH flags with two links.
    by_id["p1"]["school_fields"]["school_from_parent"] = deepcopy(pending_field)
    report = audit(b)
    records = {r["submission_id"]: r for r in report["records"]}
    assert records["s4"]["status"] == "not_reconciled" and records["s4"]["actionable_pending"]
    assert records["p1"]["status"] == "pending" and records["p1"]["actionable_pending"] and records["p1"]["attributed_exclusion"]
    for seed in range(12):
        rng = random.Random(seed)
        roles = ["student", "parent", "student", "parent"]
        mapping = {r["submission_id"]: rng.choice([0, 2] if r["role"] == "student" else [1, 3]) for r in report["records"]}
        index = build_scope_attachment(report, mapping, roles)
        for bits in product([False, True], repeat=4):
            selected = [sid for sid, p in mapping.items() if bits[p]]
            assert query_school_scope(index, list(bits)) == project_school_status(report, selected)


def test_empty_review_universe_with_no_recorded_review_keeps_outside_queue_records():
    b = fixture()
    b.update(review_state="no_recorded_review", decision_revision=None, criteria_revision=None, decisions=[], criteria=[],
             historical_queue=[], current_queue=[])
    report = audit(b)
    mapping, roles = individual_profiles(report)
    index = build_scope_attachment(report, mapping, roles)
    scope = query_school_scope(index, [True] * len(roles))["current_scope"]
    assert scope["raw"] == scope["status_partition"]["no_queue_label"]
    assert sum(scope["affected"].values()) == scope["labels"]["affected"] == 0


def test_public_two_distinct_links_cannot_be_supplied_by_one_label():
    output = project_school_status(audit(), ["p1"])
    assert output["current_scope"]["label_record_links"] == 2
    output["current_scope"]["labels"]["affected"] = 1
    with pytest.raises(SchoolEvidenceError, match="scope_record_label_evidence_disagreement"):
        validate_public_projection(output)


def test_historical_summary_matches_independent_subset_oracle():
    # Enumerate actual small label sets, independently of the validator's bounds.
    from itertools import combinations
    template = project_school_status(audit(), [])
    for resolved_state in ("mapped", "invalid", "historical_only"):
        for resolved, pending, unknown in product(range(4), repeat=3):
            total = resolved + pending + unknown
            if total > 4:
                continue
            population = ["resolved"] * resolved + ["pending"] * pending + ["unknown"] * unknown
            for historical in range(total + 1):
                possible = {(chosen.count("resolved"), sum(s != "unknown" for s in chosen))
                            for chosen in combinations(population, historical)}
                for reported_resolved in range(historical + 1):
                    for reported_accounted in range(reported_resolved, historical + 1):
                        output = deepcopy(template)
                        labels = output["release_wide"]["labels"]
                        labels.update(historical_queue=historical, current_queue=total, review_universe=total,
                                      historical_resolved=reported_resolved, historical_accounted=reported_accounted,
                                      all_historical_resolved=reported_resolved == historical,
                                      all_historical_accounted=reported_accounted == historical)
                        labels["states"] = {s: 0 for s in LABEL_STATES}
                        labels["states"].update({resolved_state: resolved, "pending": pending, "not_reconciled": unknown})
                        output["release_wide"]["schools"]["verified_reviewed_canonical_schools"] = int(resolved_state == "mapped" and resolved > 0)
                        output["reconciliation_status"] = "not_reconciled" if unknown else "reconciled"
                        if (reported_resolved, reported_accounted) in possible:
                            validate_public_projection(output)
                        else:
                            with pytest.raises(SchoolEvidenceError, match="historical_state_count_reconciliation"):
                                validate_public_projection(output)


@pytest.mark.parametrize("empty_history", [False, True])
def test_no_review_history_has_zero_resolved_and_preserves_empty_completion(empty_history):
    b = fixture()
    b.update(review_state="no_recorded_review", decision_revision=None, criteria_revision=None, decisions=[], criteria=[])
    if empty_history:
        b["current_queue"] = b["historical_queue"] + b["current_queue"]
        b["historical_queue"] = []
    labels = project_school_status(audit(b))["release_wide"]["labels"]
    assert labels["historical_resolved"] == 0
    assert labels["all_historical_resolved"] is empty_history
    assert labels["historical_accounted"] == labels["historical_queue"]
    assert labels["all_historical_accounted"]


@pytest.mark.parametrize("missing", ["school_excluded", "attributed_exclusion", "both"])
def test_invalid_partition_cannot_lose_either_persisted_exclusion_flag(missing):
    report = audit()
    mapping, roles = individual_profiles(report)
    index = build_scope_attachment(report, mapping, roles)
    cell = next(c for c in index["record_cells"] if c["profile"] == mapping["p1"])
    assert cell["status"] == "invalid"
    scope = index["header"]["current_scope"]
    if missing in {"school_excluded", "both"}:
        cell["school_excluded"] = False
        scope["excluded_school"]["parent"] -= 1
    if missing in {"attributed_exclusion", "both"}:
        cell["attributed_exclusion"] = False
        scope["verified_queue_attributed_exclusion"]["parent"] -= 1
    with pytest.raises(SchoolEvidenceError):
        validate_scope_attachment(index)
    with pytest.raises(SchoolEvidenceError):
        query_school_scope(index, [True] * len(roles))


@pytest.mark.parametrize("dominant", ["pending", "not_reconciled"])
@pytest.mark.parametrize("same_profile", [False, True])
def test_hidden_invalid_cannot_use_unflagged_capacity_even_when_another_record_is_flagged(dominant, same_profile):
    b = fixture()
    by_id = {r["submission_id"]: r for r in b["records"]}
    source = "s2" if dominant == "pending" else "s4"
    by_id["p1"]["school_fields"]["school_from_parent"] = deepcopy(by_id[source]["school_fields"]["school_from_student"])
    extra = deepcopy(by_id["p1"])
    extra["submission_id"] = "synthetic-extra-excluded"
    b["records"].append(extra)
    report = audit(b)
    mapping, roles = individual_profiles(report)
    if same_profile:
        mapping[extra["submission_id"]] = mapping["p1"]
    index = build_scope_attachment(report, mapping, roles)
    cell = next(c for c in index["record_cells"] if c["profile"] == mapping["p1"])
    assert cell["status"] == dominant and cell["school_excluded"] and cell["attributed_exclusion"]
    unflagged = deepcopy(cell)
    unflagged.update(count=1, school_excluded=False, attributed_exclusion=False)
    index["record_cells"].append(unflagged)
    cell["count"] -= 1
    if not cell["count"]:
        index["record_cells"].remove(cell)
    scope = index["header"]["current_scope"]
    scope["excluded_school"]["parent"] -= 1
    scope["verified_queue_attributed_exclusion"]["parent"] -= 1
    # Public totals still have valid exclusion evidence and zero invalid partition.
    validate_public_projection(index["header"])
    with pytest.raises(SchoolEvidenceError):
        validate_scope_attachment(index)


def test_public_invalid_partition_requires_attribution_within_each_role():
    output = project_school_status(audit())
    output["current_scope"]["verified_queue_attributed_exclusion"].update(student=1, parent=0)
    with pytest.raises(SchoolEvidenceError, match="record_count_reconciliation"):
        validate_public_projection(output)
