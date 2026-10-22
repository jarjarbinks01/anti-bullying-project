"""Read-only school-review reconciliation from a pinned, minimal evidence bundle.

No file, database, dictionary, research-selection or network operations. Detailed
labels and record IDs stay in the private report. Only closed aggregate objects
leave project_school_status / build_scope_attachment. Scope predicates belong
to the separately accepted R01 engine, never to this module.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import re

EVIDENCE_FORMAT = "study2_school_evidence_v1"
PRIVATE_FORMAT = "study2_school_private_v1"
PUBLIC_FORMAT = "study2_school_status_v1"
SCOPE_FORMAT = "study2_school_scope_v1"
FIELDS = ("school_from_student", "school_from_parent")
ROLES = ("student", "parent")
LABEL_STATES = ("mapped", "invalid", "historical_only", "pending", "unreviewed", "not_reconciled")
# A record can be linked to several label states. This is only a documented
# mutually exclusive display partition, not a new eligibility/exclusion rule.
RECORD_PRIORITY = ("not_reconciled", "unreviewed", "pending", "invalid", "mapped", "historical_only", "no_queue_label")
RECORD_STATUSES = {"eligible", "excluded_school", "incomplete", "unrecognized_survey", "sparse_response",
                   "manual_excluded", "exact_input_repeat", "short_repeat", "extra_followup", "short_interval_followup"}
MAX_COUNT = 2**53 - 1
MISSING_EVIDENCE = ("pinned_historical_and_current_queues", "both_school_field_occurrences", "release_dictionary",
                    "completed_review_decisions", "accepted_actionability_criteria", "immutable_input_inventory")


class SchoolEvidenceError(ValueError):
    """Specific contract failure; private offending values are not echoed."""


def canonical_json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SchoolEvidenceError("finite_json_required") from exc


def fingerprint(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _need(condition, message):
    if not condition:
        raise SchoolEvidenceError(message)


def _fields(value, keys):
    _need(isinstance(value, dict) and set(value) == set(keys), "unexpected_or_missing_fields")


def _private_text(value, *, empty=False):
    _need(isinstance(value, str) and (empty or bool(value.strip())) and len(value) <= 4000, "invalid_private_text")
    return value


def normalize_school_key(value):
    """Same strip/lower key convention as adapters.normalize_records; no alias guessing."""
    return _private_text(value).strip().lower()


def _revision(value):
    _need(isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,79}", value) is not None,
          "unsafe_public_revision")
    return value


def _release(value):
    _need(isinstance(value, str) and (re.fullmatch(r"RUN_[0-9a-f]{20,64}", value) is not None
          or re.fullmatch(r"[a-z][a-z0-9-]{0,79}", value) is not None), "unsafe_public_release_id")
    return value


def _sha(value):
    _need(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "invalid_sha256")
    return value


def _count(value, *, positive=False):
    _need(type(value) is int and (value > 0 if positive else value >= 0) and value <= MAX_COUNT, "invalid_count")
    return value


def _expected(value):
    _fields(value, ("release_id", "dictionary_sha256", "review_state", "decision_revision", "criteria_revision", "bundle_sha256"))
    _release(value["release_id"])
    _sha(value["dictionary_sha256"])
    _sha(value["bundle_sha256"])
    _need(value["review_state"] in {"recorded_review", "no_recorded_review"}, "invalid_review_state")
    _need((value["decision_revision"] is None) == (value["review_state"] == "no_recorded_review"),
          "review_revision_state_disagreement")
    for name in ("decision_revision", "criteria_revision"):
        if value[name] is not None: _revision(value[name])
    return value


def _seal(report):
    result = deepcopy(report)
    result["report_sha256"] = fingerprint(report)
    return result


def _verify_report(report):
    _fields(report, ("format", "context", "availability", "reconciliation_status", "revision", "problems", "labels", "records", "report_sha256"))
    _need(report["format"] == PRIVATE_FORMAT, "compatible_private_report_required")
    _need(report["report_sha256"] == fingerprint({k: v for k, v in report.items() if k != "report_sha256"}),
          "private_report_changed")


def _unavailable(expected, problems):
    return _seal(dict(format=PRIVATE_FORMAT, context={**expected, "decision_source_sha256": None},
                      availability="unavailable", reconciliation_status="not_reconciled", revision=None,
                      problems=sorted(problems), labels=None, records=None))


def _validate_bundle(bundle):
    _fields(bundle, ("format", "release_id", "dictionary_sha256", "review_state", "decision_revision", "criteria_revision",
                     "historical_queue", "current_queue", "records", "dictionary", "decisions", "criteria"))
    _need(bundle["format"] == EVIDENCE_FORMAT, "compatible_school_evidence_required")
    for name in ("historical_queue", "current_queue", "records", "criteria"):
        _need(isinstance(bundle[name], list), "evidence_array_required")
    for name in ("dictionary", "decisions"):
        _need(bundle[name] is None or isinstance(bundle[name], list), "evidence_array_required")
    queues = defaultdict(lambda: dict(raw_names=set(), historical=False, current=False))
    for name, flag in (("historical_queue", "historical"), ("current_queue", "current")):
        for row in bundle[name]:
            _fields(row, ("raw_name", "normalized_key"))
            key = normalize_school_key(row["raw_name"])
            _need(row["normalized_key"] == key, "queue_key_disagrees_with_published_normalization")
            queues[key]["raw_names"].add(row["raw_name"])
            queues[key][flag] = True
    records = {}
    for record in bundle["records"]:
        _fields(record, ("submission_id", "role", "status", "school_fields"))
        sid = _private_text(record["submission_id"])
        _need(sid not in records and record["role"] in ROLES and record["status"] in RECORD_STATUSES,
              "duplicate_record_or_unsupported_published_status")
        _fields(record["school_fields"], FIELDS)
        for field in FIELDS:
            cell = record["school_fields"][field]
            _fields(cell, ("raw_name", "use", "actionable", "criterion_id", "published_action", "published_canonical", "caused_exclusion"))
            _private_text(cell["raw_name"], empty=True)
            _need(cell["use"] in {"cleaning", "identity", "cleaning_and_identity", "background", "unknown", "none"}, "unsupported_field_use")
            _need(cell["actionable"] is None or type(cell["actionable"]) is bool, "invalid_actionability")
            _need(cell["published_action"] in {"map", "delete", "unmapped", "not_used", "unknown", "missing"}, "unsupported_published_school_action")
            _need(cell["published_canonical"] is None or isinstance(cell["published_canonical"], str), "invalid_published_canonical")
            _need(cell["criterion_id"] is None or isinstance(cell["criterion_id"], str), "invalid_criterion_reference")
            _need(type(cell["caused_exclusion"]) is bool, "invalid_exclusion_flag")
            if not cell["raw_name"].strip():
                _need(cell["use"] == "none" and cell["published_action"] == "missing"
                      and not cell["caused_exclusion"] and not cell["actionable"]
                      and cell["criterion_id"] is None and cell["published_canonical"] is None,
                      "inconsistent_empty_school_field")
            else:
                _need(cell["use"] != "none" and cell["published_action"] != "missing", "nonempty_school_field_marked_missing")
            if cell["caused_exclusion"]:
                _need(record["status"] == "excluded_school" and cell["published_action"] == "delete", "unproved_published_school_exclusion")
        records[sid] = record
    criteria = {}
    for row in bundle["criteria"]:
        _fields(row, ("criterion_id", "release_id", "revision", "accepted_by", "evidence_ref", "description"))
        cid = _private_text(row["criterion_id"])
        _need(cid not in criteria, "duplicate_actionability_criterion")
        for name in ("release_id", "revision", "accepted_by", "evidence_ref", "description"):
            _private_text(row[name], empty=True)
        criteria[cid] = row
    dictionary = defaultdict(list)
    for row in bundle["dictionary"] or []:
        _fields(row, ("normalized_key", "action", "canonical_school_name"))
        key = normalize_school_key(row["normalized_key"])
        _need(key == row["normalized_key"] and row["action"] in {"map", "delete"}, "unsupported_dictionary_entry")
        _need(row["canonical_school_name"] is None or isinstance(row["canonical_school_name"], str), "invalid_canonical_school")
        dictionary[key].append(row)
    decisions = defaultdict(list)
    decision_ids = set()
    for row in bundle["decisions"] or []:
        _fields(row, ("decision_id", "normalized_key", "action", "canonical_school_name", "release_id", "dictionary_sha256",
                      "revision", "reviewer", "reason", "evidence_ref", "criterion_id"))
        did = _private_text(row["decision_id"])
        _need(did not in decision_ids, "duplicate_decision_id")
        decision_ids.add(did)
        key = normalize_school_key(row["normalized_key"])
        _need(key == row["normalized_key"] and row["action"] in {"map", "delete", "historical", "pending"}, "unsupported_review_action")
        for name in ("release_id", "dictionary_sha256", "revision", "reviewer", "reason", "evidence_ref"):
            _private_text(row[name], empty=True)
        for name in ("canonical_school_name", "criterion_id"):
            _need(row[name] is None or isinstance(row[name], str), "invalid_decision_value")
        decisions[key].append(row)
    return queues, records, criteria, dictionary, decisions


def _criterion_valid(cid, criteria, context):
    row = criteria.get(cid)
    return bool(row and row["release_id"] == context["release_id"] and row["revision"] == context["criteria_revision"]
                and row["accepted_by"].strip() and row["evidence_ref"].strip() and row["description"].strip())


def _classify(key, occurrences, rows, dictionary, criteria, context, in_current_queue):
    problems = set()
    if not rows:
        return "not_reconciled", ["review_evidence_missing"], None
    for row in rows:
        if row["release_id"] != context["release_id"]: problems.add("stale_decision_release")
        if row["dictionary_sha256"] != context["dictionary_sha256"]: problems.add("stale_decision_dictionary")
        if row["revision"] != context["decision_revision"]: problems.add("stale_decision_revision")
        if not all(row[k].strip() for k in ("reviewer", "reason", "evidence_ref")):
            problems.add("decision_provenance_missing")
    actions = {(r["action"], r["canonical_school_name"], r["criterion_id"]) for r in rows}
    if len(actions) != 1: problems.add("conflicting_decisions")
    entries = {(r["action"], r["canonical_school_name"]) for r in dictionary.get(key, [])}
    if len(entries) > 1: problems.add("conflicting_dictionary_entries")
    if problems:
        return "not_reconciled", sorted(problems), None
    action, canonical, cid = next(iter(actions))
    if action == "map":
        if not canonical or not canonical.strip(): problems.add("canonical_school_missing")
        if entries != {("map", canonical)}: problems.add("mapping_not_in_release_dictionary")
        if any(o["published_action"] != "map" or o["published_canonical"] != canonical for o in occurrences):
            problems.add("mapping_not_reflected_in_publication")
        state = "mapped"
    elif action == "delete":
        if canonical: problems.add("delete_has_canonical_school")
        if entries != {("delete", None)}: problems.add("delete_not_in_release_dictionary")
        if any(o["published_action"] != "delete" or not o["caused_exclusion"] for o in occurrences):
            problems.add("exclusion_not_reflected_in_publication")
        state = "invalid"
    elif action == "historical":
        if canonical is not None: problems.add("non_mapping_has_canonical_school")
        if not _criterion_valid(cid, criteria, context): problems.add("historical_criterion_not_accepted")
        if any(o["actionable"] is not False for o in occurrences): problems.add("historical_label_still_actionable_or_unknown")
        state = "historical_only"
    else:
        if canonical is not None: problems.add("non_mapping_has_canonical_school")
        if entries: problems.add("pending_conflicts_with_release_dictionary")
        if not in_current_queue: problems.add("pending_not_in_current_queue")
        if not any(o["actionable"] is True and o["use"] in {"cleaning", "identity", "cleaning_and_identity"} for o in occurrences):
            problems.add("pending_has_no_actionable_current_record")
        if any(o["published_action"] not in {"unmapped", "not_used"} for o in occurrences):
            problems.add("pending_conflicts_with_published_school_result")
        state = "pending"
    return ("not_reconciled", sorted(problems), None) if problems else (state, [], canonical if state == "mapped" else None)


def reconcile_school_status(bundle, expected):
    """Return a PRIVATE sealed audit report. Pins must come from the coordinator."""
    _expected(expected)
    if bundle is None:
        return _unavailable(expected, ["evidence_bundle_missing"])
    actual_hash = fingerprint(bundle)
    _need(isinstance(bundle, dict), "evidence_object_required")
    problems = []
    for name in ("release_id", "dictionary_sha256", "review_state", "decision_revision", "criteria_revision"):
        if bundle.get(name) != expected[name]: problems.append(name + "_mismatch")
    if actual_hash != expected["bundle_sha256"]: problems.append("input_fingerprint_changed")
    if problems:
        return _unavailable(expected, problems)
    queues, records, criteria, dictionary, decisions = _validate_bundle(bundle)
    if bundle["dictionary"] is None or bundle["decisions"] is None:
        missing = [reason for name, reason in (("dictionary", "dictionary_evidence_missing"),
                   ("decisions", "decision_artifact_missing")) if bundle[name] is None]
        return _unavailable(expected, missing)
    _need(bundle["review_state"] != "no_recorded_review" or not bundle["decisions"],
          "no_recorded_review_has_decisions")
    context = {**expected, "decision_source_sha256": fingerprint(bundle["decisions"])}
    occurrences = defaultdict(list)
    for sid, record in records.items():
        for field, cell in record["school_fields"].items():
            if not cell["raw_name"].strip(): continue
            key = normalize_school_key(cell["raw_name"])
            if key not in queues: continue
            o = dict(cell, submission_id=sid, role=record["role"], record_status=record["status"], field=field,
                     primary_field=field == ("school_from_student" if record["role"] == "student" else "school_from_parent"))
            if cell["use"] == "unknown" or not _criterion_valid(cell["criterion_id"], criteria, context):
                o["actionable"] = None
            occurrences[key].append(o)
    labels = []
    for key in sorted(queues):
        occ = sorted(occurrences[key], key=lambda x: (x["submission_id"], x["field"]))
        if context["review_state"] == "no_recorded_review":
            state, reasons, canonical = "unreviewed", ["no_recorded_review"], None
        else:
            state, reasons, canonical = _classify(key, occ, decisions[key], dictionary, criteria, context, queues[key]["current"])
        # Unknown actual use/actionability never becomes a completed task.
        if state != "unreviewed" and any(o["actionable"] is None for o in occ):
            state, canonical = "not_reconciled", None
            reasons = sorted(set(reasons) | {"field_actionability_evidence_missing"})
        labels.append(dict(normalized_key=key, raw_names=sorted(queues[key]["raw_names"]),
                           historical=queues[key]["historical"], current=queues[key]["current"], status=state,
                           problems=reasons, canonical_school=canonical, occurrences=occ,
                           decisions=sorted(deepcopy(decisions[key]), key=lambda x: x["decision_id"]),
                           dictionary_entries=sorted(deepcopy(dictionary.get(key, [])), key=canonical_json)))
    record_links = defaultdict(list)
    for label in labels:
        by_record = defaultdict(list)
        for o in label["occurrences"]:
            by_record[o["submission_id"]].append(o)
        for sid, local_occurrences in by_record.items():
            record_links[sid].append((label, local_occurrences))
    record_audit = []
    for sid, record in sorted(records.items()):
        links = record_links[sid]
        linked = [l for l, _ in links]
        states = {l["status"] for l in linked}
        associated = [o for _, local in links for o in local]
        record_audit.append(dict(submission_id=sid, role=record["role"], published_status=record["status"],
                                 label_keys=[l["normalized_key"] for l in linked],
                                 label_states=sorted(states), status=next(s for s in RECORD_PRIORITY if s in states or s == "no_queue_label"),
                                 school_excluded=record["status"] == "excluded_school",
                                 attributed_exclusion=any(l["status"] == "invalid" and any(o["caused_exclusion"] for o in local) for l, local in links),
                                 actionable_pending=any(l["status"] == "pending" and any(o["actionable"] is True for o in local) for l, local in links),
                                 label_links=len(linked), field_occurrences=len(associated)))
    return _seal(dict(format=PRIVATE_FORMAT, context=context, availability="available",
                      reconciliation_status="not_reconciled" if any(l["status"] in {"not_reconciled", "unreviewed"} for l in labels) else "reconciled",
                      revision="school-" + fingerprint(context)[:24], problems=[], labels=labels, records=record_audit))


def _release_wide(report):
    labels = report["labels"]
    states = Counter(l["status"] for l in labels)
    historical = [l for l in labels if l["historical"]]
    return dict(basis="release_wide", labels=dict(unit="normalized_labels", historical_queue=len(historical),
                current_queue=sum(l["current"] for l in labels), review_universe=len(labels),
                states={s: states[s] for s in LABEL_STATES},
                historical_accounted=sum(l["status"] != "not_reconciled" for l in historical),
                historical_resolved=sum(l["status"] in {"mapped", "invalid", "historical_only"} for l in historical),
                all_historical_accounted=all(l["status"] != "not_reconciled" for l in historical),
                all_historical_resolved=all(l["status"] in {"mapped", "invalid", "historical_only"} for l in historical)),
                schools=dict(unit="canonical_school_names", verified_reviewed_canonical_schools=len({l["canonical_school"] for l in labels if l["status"] == "mapped"})))


def _scope_counts(records, labels):
    roles = lambda: {r: 0 for r in ROLES}
    output = dict(unit="questionnaire_records", raw=roles(), affected=roles(), excluded_school=roles(),
                  verified_queue_attributed_exclusion=roles(), actionable_pending=roles(),
                  status_partition={s: roles() for s in RECORD_PRIORITY}, label_record_links=0, school_field_occurrences=0,
                  records_with_multiple_labels=0, labels=dict(unit="normalized_labels", affected=0, actionable_pending=0, unreviewed=0, not_reconciled=0),
                  schools=dict(status="unavailable", count=None, reason="filtered_canonical_school_signatures_not_provided"))
    for record, n in records:
        role = record["role"]
        output["raw"][role] += n
        for name, flag in (("affected", record["label_links"] > 0), ("excluded_school", record["school_excluded"]),
                           ("verified_queue_attributed_exclusion", record["attributed_exclusion"]), ("actionable_pending", record["actionable_pending"])):
            if flag: output[name][role] += n
        output["status_partition"][record["status"]][role] += n
        output["label_record_links"] += record["label_links"] * n
        output["school_field_occurrences"] += record["field_occurrences"] * n
        if record["label_links"] > 1: output["records_with_multiple_labels"] += n
    for label, n, affected, actionable in labels:
        if affected:
            output["labels"]["affected"] += n
            if label["status"] == "unreviewed": output["labels"]["unreviewed"] += n
            if label["status"] == "not_reconciled": output["labels"]["not_reconciled"] += n
        if label["status"] == "pending" and actionable: output["labels"]["actionable_pending"] += n
    return output


def _public_header(report):
    return dict(format=PUBLIC_FORMAT, release_id=report["context"]["release_id"], availability=report["availability"],
                reconciliation_status=report["reconciliation_status"], revision=report["revision"],
                evidence=dict(dictionary_sha256=report["context"]["dictionary_sha256"],
                              review_state=report["context"]["review_state"],
                              decision_revision=report["context"]["decision_revision"], criteria_revision=report["context"]["criteria_revision"],
                              bundle_sha256=report["context"]["bundle_sha256"], decision_source_sha256=report["context"]["decision_source_sha256"]),
                problems=list(report["problems"]), release_wide=None, current_scope=None)


def project_school_status(report, in_scope_submission_ids=None):
    """Aggregate LOCAL report/IDs. Empty selection means zero, never all."""
    _verify_report(report)
    output = _public_header(report)
    if report["availability"] == "unavailable":
        _need(in_scope_submission_ids is None, "scope_unavailable_without_evidence")
        validate_public_projection(output)
        return output
    all_ids = {r["submission_id"] for r in report["records"]}
    if in_scope_submission_ids is None:
        selected = all_ids
    else:
        _need(isinstance(in_scope_submission_ids, (list, set, tuple)), "scope_ids_required")
        selected = set(in_scope_submission_ids)
        _need(selected <= all_ids, "scope_record_not_in_pinned_release")
    records = [(r, 1) for r in report["records"] if r["submission_id"] in selected]
    labels = [(l, 1, any(o["submission_id"] in selected for o in l["occurrences"]),
               any(o["submission_id"] in selected and o["actionable"] is True for o in l["occurrences"])) for l in report["labels"]]
    output["release_wide"], output["current_scope"] = _release_wide(report), _scope_counts(records, labels)
    validate_public_projection(output)
    return output


def local_record_projection(report):
    """Proposed R01 LOCAL adapter. This contains IDs and MUST NOT be serialized online."""
    _verify_report(report)
    if report["availability"] == "unavailable": return None
    return dict(revision=report["revision"], statuses=list(RECORD_PRIORITY),
                rows=[dict(submission_id=r["submission_id"], status=r["status"]) for r in report["records"]])


def build_scope_attachment(report, profile_by_submission, profile_roles):
    """Build anonymous multiplicities and label-union signatures, no label IDs.

    The coordinator must bind profile positions to the accepted R01 export.
    Passing an R01 predicate mask supports exact distinct-label counts without
    treating overlapping per-record flags as distinct labels.
    """
    _verify_report(report)
    _need(report["availability"] == "available", "school_scope_evidence_unavailable")
    _need(isinstance(profile_roles, list) and all(r in ROLES for r in profile_roles), "invalid_scope_profile_roles")
    _need(isinstance(profile_by_submission, dict) and set(profile_by_submission) == {r["submission_id"] for r in report["records"]},
          "incomplete_scope_profile_attachment")
    for r in report["records"]:
        p = profile_by_submission[r["submission_id"]]
        _need(type(p) is int and 0 <= p < len(profile_roles) and profile_roles[p] == r["role"], "scope_profile_role_or_reference_mismatch")
    cell_fields = ("status", "school_excluded", "attributed_exclusion", "actionable_pending", "label_links", "field_occurrences")
    cells = Counter((profile_by_submission[r["submission_id"]], *(r[k] for k in cell_fields)) for r in report["records"])
    signatures = Counter()
    for label in report["labels"]:
        profiles = tuple(sorted({profile_by_submission[o["submission_id"]] for o in label["occurrences"]}))
        actionable = tuple(sorted({profile_by_submission[o["submission_id"]] for o in label["occurrences"] if o["actionable"] is True}))
        signatures[(label["status"], label["historical"], label["current"], profiles, actionable)] += 1
    index = dict(format=SCOPE_FORMAT, header=project_school_status(report), profile_roles=list(profile_roles),
                 record_cells=[dict(profile=signature[0], **dict(zip(cell_fields, signature[1:])), count=n) for signature, n in sorted(cells.items())],
                 label_cells=[dict(status=s, historical=h, current=c, profiles=list(ps), actionable_profiles=list(aps), count=n)
                              for (s, h, c, ps, aps), n in sorted(signatures.items())])
    validate_scope_attachment(index)
    return index


def query_school_scope(index, profile_mask):
    """Query using the exact shared predicate mask, not a new source/date policy."""
    validate_scope_attachment(index)
    _need(isinstance(profile_mask, list) and len(profile_mask) == len(index["profile_roles"])
          and all(type(v) is bool for v in profile_mask), "invalid_scope_profile_mask")
    records = [(dict(r, role=index["profile_roles"][r["profile"]]), r["count"]) for r in index["record_cells"] if profile_mask[r["profile"]]]
    labels = [(l, l["count"], any(profile_mask[p] for p in l["profiles"]), any(profile_mask[p] for p in l["actionable_profiles"])) for l in index["label_cells"]]
    output = deepcopy(index["header"])
    output["current_scope"] = _scope_counts(records, labels)
    validate_public_projection(output)
    return output


def validate_public_projection(output):
    """Closed aggregate allowlist, including text values and units."""
    _fields(output, ("format", "release_id", "availability", "reconciliation_status", "revision", "evidence", "problems", "release_wide", "current_scope"))
    _need(output["format"] == PUBLIC_FORMAT and output["availability"] in {"available", "unavailable"}
          and output["reconciliation_status"] in {"reconciled", "not_reconciled"}, "invalid_public_status")
    _release(output["release_id"])
    _fields(output["evidence"], ("dictionary_sha256", "review_state", "decision_revision", "criteria_revision", "bundle_sha256", "decision_source_sha256"))
    for key in ("dictionary_sha256", "bundle_sha256"): _sha(output["evidence"][key])
    _need(output["evidence"]["review_state"] in {"recorded_review", "no_recorded_review"}
          and (output["evidence"]["decision_revision"] is None) == (output["evidence"]["review_state"] == "no_recorded_review"),
          "review_revision_state_disagreement")
    for key in ("decision_revision", "criteria_revision"):
        if output["evidence"][key] is not None: _revision(output["evidence"][key])
    _need(isinstance(output["problems"], list) and set(output["problems"]) <= {
        "evidence_bundle_missing", "release_id_mismatch", "dictionary_sha256_mismatch", "decision_revision_mismatch",
        "criteria_revision_mismatch", "review_state_mismatch", "input_fingerprint_changed", "dictionary_evidence_missing", "decision_artifact_missing"}, "unsafe_public_problem")
    if output["availability"] == "unavailable":
        _need(output["reconciliation_status"] == "not_reconciled" and output["revision"] is None
              and output["release_wide"] is None and output["current_scope"] is None
              and output["evidence"]["decision_source_sha256"] is None and bool(output["problems"]), "unavailable_evidence_claims_counts")
        return output
    _need(isinstance(output["revision"], str) and re.fullmatch(r"school-[0-9a-f]{24}", output["revision"]) is not None
          and not output["problems"], "invalid_reconciliation_revision")
    _sha(output["evidence"]["decision_source_sha256"])
    wide, scope = output["release_wide"], output["current_scope"]
    _fields(wide, ("basis", "labels", "schools"))
    _need(wide["basis"] == "release_wide", "historical_basis_required")
    _fields(wide["labels"], ("unit", "historical_queue", "current_queue", "review_universe", "states", "historical_accounted",
                            "historical_resolved", "all_historical_accounted", "all_historical_resolved"))
    labels = wide["labels"]
    _need(labels["unit"] == "normalized_labels", "label_unit_required")
    _fields(labels["states"], LABEL_STATES)
    for n in labels["states"].values(): _count(n)
    for key in ("historical_queue", "current_queue", "review_universe", "historical_accounted", "historical_resolved"): _count(labels[key])
    _need(sum(labels["states"].values()) == labels["review_universe"] and labels["historical_resolved"] <= labels["historical_accounted"] <= labels["historical_queue"] <= labels["review_universe"]
          and labels["current_queue"] <= labels["review_universe"], "label_count_reconciliation")
    # Historical labels are a subset of the review universe. Each of its three
    # disjoint accounting classes must fit both the historical and outside sets.
    resolved = sum(labels["states"][s] for s in ("mapped", "invalid", "historical_only"))
    accounted_unresolved = labels["states"]["pending"] + labels["states"]["unreviewed"]
    outside = labels["review_universe"] - labels["historical_queue"]
    for historical, total in ((labels["historical_resolved"], resolved),
                              (labels["historical_accounted"] - labels["historical_resolved"], accounted_unresolved),
                              (labels["historical_queue"] - labels["historical_accounted"], labels["states"]["not_reconciled"])):
        _need(max(0, total - outside) <= historical <= min(labels["historical_queue"], total),
              "historical_state_count_reconciliation")
    for key, count_key in (("all_historical_accounted", "historical_accounted"), ("all_historical_resolved", "historical_resolved")):
        _need(type(labels[key]) is bool and labels[key] == (labels[count_key] == labels["historical_queue"]), "historical_completion_disagreement")
    _need((output["reconciliation_status"] == "reconciled") == (labels["states"]["not_reconciled"] + labels["states"]["unreviewed"] == 0), "reconciliation_overclaim")
    _need(output["evidence"]["review_state"] != "no_recorded_review"
          or labels["states"]["unreviewed"] == labels["review_universe"], "unrecorded_review_claims_decisions")
    _fields(wide["schools"], ("unit", "verified_reviewed_canonical_schools"))
    _need(wide["schools"]["unit"] == "canonical_school_names", "school_unit_required")
    _count(wide["schools"]["verified_reviewed_canonical_schools"])
    _need(wide["schools"]["verified_reviewed_canonical_schools"] <= labels["states"]["mapped"],
          "reviewed_school_count_exceeds_mapped_labels")
    _fields(scope, ("unit", "raw", "affected", "excluded_school", "verified_queue_attributed_exclusion", "actionable_pending",
                    "status_partition", "label_record_links", "school_field_occurrences", "records_with_multiple_labels", "labels", "schools"))
    _need(scope["unit"] == "questionnaire_records", "record_unit_required")
    for key in ("raw", "affected", "excluded_school", "verified_queue_attributed_exclusion", "actionable_pending"):
        _fields(scope[key], ROLES)
        for n in scope[key].values(): _count(n)
    _fields(scope["status_partition"], RECORD_PRIORITY)
    for counts in scope["status_partition"].values():
        _fields(counts, ROLES)
        for n in counts.values(): _count(n)
    for role in ROLES:
        _need(sum(v[role] for v in scope["status_partition"].values()) == scope["raw"][role]
              and scope["status_partition"]["no_queue_label"][role] == scope["raw"][role] - scope["affected"][role]
              and scope["verified_queue_attributed_exclusion"][role] <= min(scope["excluded_school"][role], scope["affected"][role])
              and scope["status_partition"]["invalid"][role] <= scope["verified_queue_attributed_exclusion"][role]
              and scope["actionable_pending"][role] <= scope["affected"][role] <= scope["raw"][role]
              and scope["excluded_school"][role] <= scope["raw"][role], "record_count_reconciliation")
    for key in ("label_record_links", "school_field_occurrences", "records_with_multiple_labels"): _count(scope[key])
    affected = sum(scope["affected"].values())
    _need(affected <= scope["label_record_links"] <= scope["school_field_occurrences"] <= 2 * affected
          and scope["records_with_multiple_labels"] == scope["label_record_links"] - affected,
          "school_overlap_count_reconciliation")
    _fields(scope["labels"], ("unit", "affected", "actionable_pending", "unreviewed", "not_reconciled"))
    _need(scope["labels"]["unit"] == "normalized_labels", "scope_label_unit_required")
    for key in ("affected", "actionable_pending", "unreviewed", "not_reconciled"): _count(scope["labels"][key])
    _need(scope["labels"]["actionable_pending"] <= scope["labels"]["affected"] <= labels["review_universe"]
          and scope["labels"]["affected"] <= scope["label_record_links"]
          and scope["labels"]["actionable_pending"] <= labels["states"]["pending"]
          and scope["labels"]["unreviewed"] <= min(scope["labels"]["affected"], labels["states"]["unreviewed"])
          and scope["labels"]["not_reconciled"] <= min(scope["labels"]["affected"], labels["states"]["not_reconciled"]),
          "scope_label_count_reconciliation")
    _validate_scope_evidence(scope, labels["states"], output["evidence"]["review_state"])
    _fields(scope["schools"], ("status", "count", "reason"))
    _need(scope["schools"] == dict(status="unavailable", count=None, reason="filtered_canonical_school_signatures_not_provided"), "filtered_schools_unavailable")
    canonical_json(output)
    return output


def _validate_scope_evidence(scope, states, review_state):
    """Necessary evidence bounds, without equating labels with questionnaires."""
    local = scope["labels"]
    partitions = {s: sum(counts.values()) for s, counts in scope["status_partition"].items()}
    affected = sum(scope["affected"].values())
    pending = sum(scope["actionable_pending"].values())
    attributed = sum(scope["verified_queue_attributed_exclusion"].values())
    _need((affected > 0) == (local["affected"] > 0)
          and scope["label_record_links"] <= affected * local["affected"]
          and (pending > 0) == (local["actionable_pending"] > 0)
          and local["actionable_pending"] <= 2 * pending
          and local["unreviewed"] + local["not_reconciled"] + local["actionable_pending"] <= local["affected"],
          "scope_record_label_evidence_disagreement")
    for state in LABEL_STATES:
        _need(not partitions[state] or states[state] > 0, "record_partition_without_label_evidence")
    # A higher-priority state may hide a lower one on a two-label record.
    _need((partitions["not_reconciled"] > 0) == (local["not_reconciled"] > 0)
          and local["not_reconciled"] <= 2 * partitions["not_reconciled"]
          and (not partitions["unreviewed"] or local["unreviewed"] > 0)
          and local["unreviewed"] <= 2 * (partitions["not_reconciled"] + partitions["unreviewed"])
          and (not attributed or states["invalid"] > 0), "record_partition_label_state_disagreement")
    if review_state == "no_recorded_review":
        _need(all(scope["status_partition"]["unreviewed"][r] == scope["affected"][r] for r in ROLES)
              and local["unreviewed"] == local["affected"] and pending == attributed == 0,
              "unrecorded_review_claims_record_decisions")


def _validate_profile_evidence(records, labels):
    """Check incidence, priority and flags within ONE shared scope profile.

    Signature counts are distinct labels, while record-cell counts are reusable
    questionnaire multiplicities. Bounds allow one label on many records and two
    labels on one record; they do not reconstruct private record/label links.
    """
    states = Counter()
    actionable = 0
    for label, n, _, active in labels:
        states[label["status"]] += n
        if label["status"] == "pending" and active: actionable += n
    distinct = sum(states.values())
    rank = {s: i for i, s in enumerate(RECORD_PRIORITY)}
    capacity = Counter()
    actionable_capacity = 0
    for record, n in records:
        links = record["label_links"]
        _need(links <= distinct, "profile_record_needs_more_distinct_labels")
        if not links: continue
        required = {record["status"]}
        if record["attributed_exclusion"]: required.add("invalid")
        if record["actionable_pending"]: required.add("pending")
        _need(len(required) <= links and all(states[s] > 0 and rank[s] >= rank[record["status"]] for s in required),
              "profile_record_state_or_flag_without_label_evidence")
        # Invalid means every published occurrence was actually deleted with
        # exclusion attribution, including occurrences hidden by another state.
        has_exclusion = record["school_excluded"] and record["attributed_exclusion"]
        compatible = {s for s in LABEL_STATES if rank[s] >= rank[record["status"]]
                      and (s != "invalid" or has_exclusion)}
        _need(links <= sum(states[s] for s in compatible), "profile_links_without_compatible_label_evidence")
        for state in LABEL_STATES:
            # Each other required state consumes a different label slot.
            if state in compatible:
                capacity[state] += n * (links - len(required - {state}))
        if record["actionable_pending"]:
            actionable_capacity += n * (links - len(required - {"pending"}))
    _need(all(states[s] <= capacity[s] for s in LABEL_STATES)
          and actionable <= actionable_capacity, "profile_label_incidence_exceeds_record_capacity")


def validate_scope_attachment(index):
    _fields(index, ("format", "header", "profile_roles", "record_cells", "label_cells"))
    _need(index["format"] == SCOPE_FORMAT, "compatible_school_scope_required")
    validate_public_projection(index["header"])
    _need(index["header"]["availability"] == "available", "scope_requires_available_evidence")
    roles = index["profile_roles"]
    _need(isinstance(roles, list) and all(r in ROLES for r in roles)
          and isinstance(index["record_cells"], list) and isinstance(index["label_cells"], list), "invalid_scope_arrays")
    def ref(p):
        _need(type(p) is int and 0 <= p < len(roles), "invalid_scope_profile_reference")
    records = []
    for row in index["record_cells"]:
        _fields(row, ("profile", "status", "school_excluded", "attributed_exclusion", "actionable_pending", "label_links", "field_occurrences", "count"))
        ref(row["profile"])
        _need(row["status"] in RECORD_PRIORITY, "invalid_record_partition")
        for key in ("school_excluded", "attributed_exclusion", "actionable_pending"):
            _need(type(row[key]) is bool, "invalid_record_flag")
        for key in ("label_links", "field_occurrences"): _count(row[key])
        _need(0 <= row["label_links"] <= row["field_occurrences"] <= 2
              and (row["label_links"] == 0) == (row["field_occurrences"] == 0)
              and (row["label_links"] == 0) == (row["status"] == "no_queue_label")
              and (not row["actionable_pending"] or row["label_links"] > 0)
              and (not row["attributed_exclusion"] or row["school_excluded"] and row["label_links"] > 0), "invalid_school_record_multiplicity")
        _need(row["status"] != "invalid" or row["school_excluded"] and row["attributed_exclusion"],
              "profile_record_state_or_flag_without_label_evidence")
        _count(row["count"], positive=True)
        records.append((dict(row, role=roles[row["profile"]]), row["count"]))
    labels = []
    for row in index["label_cells"]:
        _fields(row, ("status", "historical", "current", "profiles", "actionable_profiles", "count"))
        _need(row["status"] in LABEL_STATES and type(row["historical"]) is bool and type(row["current"]) is bool
              and (row["historical"] or row["current"]), "invalid_label_signature")
        for key in ("profiles", "actionable_profiles"):
            _need(isinstance(row[key], list), "invalid_label_profiles")
            for p in row[key]: ref(p)
            _need(row[key] == sorted(set(row[key])), "duplicate_label_profile")
        _need(set(row["actionable_profiles"]) <= set(row["profiles"]), "actionable_profile_outside_label")
        _need(row["status"] != "pending" or row["current"] and bool(row["actionable_profiles"]),
              "pending_signature_has_no_actionable_current_profile")
        _count(row["count"], positive=True)
        labels.append((row, row["count"], bool(row["profiles"]), bool(row["actionable_profiles"])))
    _need(_scope_counts(records, labels) == index["header"]["current_scope"], "school_scope_all_records_mismatch")
    for name in ("record_cells", "label_cells"):
        _need(len({canonical_json({k: v for k, v in row.items() if k != "count"}) for row in index[name]}) == len(index[name]), "duplicate_scope_cell")
    _need(sum(row["count"] for row in index["label_cells"]) == index["header"]["release_wide"]["labels"]["review_universe"], "school_scope_label_total_mismatch")
    wide = index["header"]["release_wide"]["labels"]
    for state in LABEL_STATES:
        _need(sum(r["count"] for r in index["label_cells"] if r["status"] == state) == wide["states"][state],
              "school_scope_label_state_mismatch")
    for flag, total in (("historical", "historical_queue"), ("current", "current_queue")):
        _need(sum(r["count"] for r in index["label_cells"] if r[flag]) == wide[total],
              "school_scope_queue_total_mismatch")
    for total, states in (("historical_accounted", set(LABEL_STATES) - {"not_reconciled"}),
                          ("historical_resolved", {"mapped", "invalid", "historical_only"})):
        _need(sum(r["count"] for r in index["label_cells"] if r["historical"] and r["status"] in states) == wide[total],
              "school_scope_historical_evidence_mismatch")
    records_by_profile, labels_by_profile = defaultdict(list), defaultdict(list)
    for record, n in records:
        records_by_profile[record["profile"]].append((record, n))
    for label, n, _, _ in labels:
        active = set(label["actionable_profiles"])
        for profile in label["profiles"]:
            labels_by_profile[profile].append((label, n, True, profile in active))
    # All-scope agreement cannot detect signatures moved between profiles.
    # Validate single-profile projections before accepting ANY query mask.
    for profile in records_by_profile.keys() | labels_by_profile.keys():
        local_records, local_labels = records_by_profile[profile], labels_by_profile[profile]
        _validate_profile_evidence(local_records, local_labels)
        local_output = dict(index["header"], current_scope=_scope_counts(local_records, local_labels))
        validate_public_projection(local_output)
    canonical_json(index)
    return index
