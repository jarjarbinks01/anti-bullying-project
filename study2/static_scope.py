"""Exact first-tab scope prototype. No I/O, selection, matching or scoring.

Private release dictionaries enter only the local builder. Its closed projection
contains joint-profile multiplicities, never submission or child identifiers.
Real export integration and disclosure acceptance are deliberately separate.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import re
from zoneinfo import ZoneInfo

FORMAT = "study2_scope_v1"
RESULT_FORMAT = "study2_scope_result_v1"
ROLES = ("student", "parent")
SLOTS = {
    "A": (("student", "T0"),), "B": (("parent", "T0"),),
    "C": (("student", "T1"),), "D": (("parent", "T1"),),
    "AC": (("student", "T0"), ("student", "T1")),
    "BD": (("parent", "T0"), ("parent", "T1")),
    "E": (("student", "T0"), ("parent", "T0")),
    "F": (("student", "T1"), ("parent", "T1")),
    "EF": (("student", "T0"), ("parent", "T0"), ("student", "T1"), ("parent", "T1")),
}
STAGES = ("screening", "exact_copies", "repeat_handling", "selection")
REQUIRED_RECONCILIATION_CHECKS = frozenset({"submissions", "status_counts", "2.1.3", "2.1.4", "2.1.6", *SLOTS})
REASONS = {
    "screening": ("excluded_school", "sparse_response", "incomplete", "unrecognized_survey"),
    "exact_copies": ("exact_input_repeat",),
    "repeat_handling": ("short_repeat", "manual_excluded"),
    "selection": ("parent_no_reliable_student_baseline", "parent_other_same_phase_response",
                  "extra_followup", "short_interval_followup", "pending_chronology",
                  "parent_before_student_baseline"),
    "selected": ("selected",),
}
STATUSES = {"eligible", "short_interval_followup", "extra_followup", *sum(
    (list(REASONS[s]) for s in STAGES[:3]), [])}
ADULT_POLICY = "same_child_valid_equal_birth_year_any_exact_contact_relationship_informational"
BD_CHILD_POLICY = "selected_parent_waves_same_child_v1"
BD_CHILD_EVIDENCE = "selected_parent_longitudinal_artifact"
MAX_COUNT = 2**53 - 1
_KEY = re.compile(r"[a-z][a-z0-9_]*_[0-9a-f]{24}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_UNSAFE = re.compile(
    r"[<>\x00-\x08\x0a-\x1f\x7f]|(?:https?://|www\.|mailto:)|[\w.+-]+@[\w.-]+\.\w+|"
    r"(?:[/\\][\w.-]+[/\\])|"
    r"(?:SUB|GROUP|RESP|DYAD)_[A-Za-z0-9_-]+|"
    r"(?:CHILD|CASE|REV|PKG|RB|DEC|DRES|DEVENT|INV)_[0-9a-f]{20,}|"
    r"\bR_[A-Za-z0-9]{10,}\b", re.I)
_PRIVATE_RELEASE_LABEL = re.compile(r"\bRUN_[A-Za-z0-9_-]+", re.I)
_PHONE = re.compile(r"\+?[0-9][0-9 \t.()/\-\u2010-\u2015\u2212]{6,}[0-9]")
_CALENDAR_TOKEN = re.compile(r"(?<![0-9])[0-9]{4}-[0-9]{2}-[0-9]{2}(?![0-9])")
_ACADEMIC_TOKEN = re.compile(r"(?<![0-9])([0-9]{4})[-/]([0-9]{4})(?![0-9])")
_ACADEMIC_CONTEXT = re.compile(r"\b(?:academic|school|study|survey|questionnaire)\b|學年|問卷|研究", re.I)
_CONTACT_CONTEXT = re.compile(r"\b(?:contact|call|phone|telephone|mobile|whatsapp|tel)\b|電話|聯絡", re.I)


def _suspect_label(value):
    if _UNSAFE.search(value) or _PRIVATE_RELEASE_LABEL.search(value):
        return True
    # Contact-labelled numbers never acquire a calendar/year exemption.
    if _CONTACT_CONTEXT.search(value) and _PHONE.search(value):
        return True

    def calendar_token(match):
        try:
            parsed = date.fromisoformat(match.group())
        except ValueError:
            return match.group()
        return "" if 1900 <= parsed.year <= 2100 else match.group()

    def academic_token(match):
        first, second = map(int, match.groups())
        plausible = 1900 <= first < 2100 and second == first + 1
        return "" if plausible and _ACADEMIC_CONTEXT.search(value) else match.group()

    without_dates = _CALENDAR_TOKEN.sub(calendar_token, value)
    without_years = _ACADEMIC_TOKEN.sub(academic_token, without_dates)
    return bool(_PHONE.search(without_years))


class ScopeError(ValueError):
    """A precise contract failure; no private offending value is echoed."""


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _need(condition, message):
    if not condition:
        raise ScopeError(message)


def _text(value, field, *, nullable=False):
    if nullable and (value is None or value == ""):
        return None
    _need(isinstance(value, str) and bool(value.strip()) and len(value) <= 500
          and not _suspect_label(value), "unsafe_or_missing_label:" + field)
    return value


def _token(value, field):
    _need(isinstance(value, str) and bool(_TOKEN.fullmatch(value))
          and not _UNSAFE.search(value) and not re.fullmatch(r"\d{8,}", value), "invalid_metadata:" + field)
    return value


def _key(prefix, identity):
    return prefix + "_" + hashlib.sha256(canonical_json(identity).encode()).hexdigest()[:24]


def _count(value):
    _need(type(value) is int and 0 <= value <= MAX_COUNT, "invalid_count")
    return value


def _iso(value):
    _need(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None,
          "invalid_iso_date")
    try:
        _need(date.fromisoformat(value).year >= 1, "invalid_iso_date")
    except ValueError as exc:
        raise ScopeError("invalid_iso_date") from exc
    return value


def creation_day(record):
    """Use only persisted, explicitly trusted, aware entry timestamps."""
    confidence, basis = record.get("time_confidence"), record.get("date_basis")
    _need(confidence in {"observed", "manual_verified", "accepted_creation_time", "unknown", "batch_only", None},
          "unsupported_time_confidence")
    _need(basis in {"system_creation", "batch_assigned_creation", None, ""}, "unsupported_date_basis")
    timing = {"observed": "observed", "manual_verified": "manual_verified",
              "accepted_creation_time": "accepted_batch"}.get(confidence, "unknown")
    if confidence == "accepted_creation_time":
        _need(basis == "batch_assigned_creation", "accepted_batch_marker_required")
    if basis == "batch_assigned_creation" and confidence == "observed":
        raise ScopeError("batch_date_mislabeled_observed")
    raw = record.get("observed_at")
    if raw is None or raw == "":
        return None, timing, "missing"
    if confidence not in {"observed", "manual_verified", "accepted_creation_time"}:
        return None, timing, "untrusted"
    if not isinstance(raw, str):
        return None, timing, "invalid"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None, timing, "naive"
        return parsed.astimezone(ZoneInfo("Asia/Hong_Kong")).date().isoformat(), timing, "usable"
    except (ValueError, OverflowError):
        return None, timing, "invalid"


def _rows(value):
    # Pandas is optional at the adapter boundary, not a browser dependency.
    return value.to_dict("records") if hasattr(value, "to_dict") else list(value)


def _source(record):
    if record.get("source_type"):
        return _text(record["source_type"], "source")
    # Use the current static export's intake classification and missing-source
    # category, only with the published source-label provenance.
    _need("source_label" in record, "source_type_or_release_source_label_required")
    from .outputs import source_category
    label = _text(record["source_label"], "source_label", nullable=True)
    return source_category(label) if label else "unknown"


def _catalogue_profile(record):
    source = _source(record)
    role = record.get("role")
    _need(role in ROLES, "unsupported_role")
    answer = record.get("answer", {})
    _need(isinstance(answer, dict), "invalid_answer_container")
    name = _text(answer.get("Survey"), "survey_name", nullable=True)
    # These explicit metadata fields are an extension, not source-content version_id.
    form = _text(record.get("survey_form_id"), "survey_form_id", nullable=True)
    version = _text(record.get("survey_form_version"), "survey_form_version", nullable=True)
    source_key = _key("src", source)
    survey_key = _key("svy", [source, role, name, form, version])
    survey = dict(key=survey_key, label=name or "Missing survey name", missing_name=name is None,
                  source_key=source_key, role=role, form_id=form, form_version=version,
                  identity_basis="form_metadata" if form else "source_role_name_only",
                  provenance="answer.Survey")
    day, timing, state = creation_day(record)
    profile = dict(source_key=source_key, survey_key=survey_key, role=role, day=day,
                   timing_basis=timing, date_state=state)
    return dict(key=source_key, label=source), survey, profile


def _terminal_fact(record):
    status = record.get("status")
    _need(status in STATUSES, "unsupported_terminal_status")
    wave = record.get("selected_wave")
    _need(wave in {None, "", "T0", "T1"}, "unsupported_selected_wave")
    if wave:
        _need(status == "eligible", "selected_terminal_status_conflict")
        return "selected", "selected"
    for stage in STAGES[:3]:
        if status in REASONS[stage]:
            return stage, status
    if status == "short_interval_followup":
        return "selection", status
    reason = record.get("wave_reason")
    if status == "extra_followup" and not reason:
        return "selection", "extra_followup"
    _need(reason in REASONS["selection"], "unsupported_unselected_reason")
    if reason.startswith("parent_"):
        _need(record["role"] == "parent", "parent_reason_on_student")
    return "selection", reason


def _prepare(records, analysis, parent_longitudinal, summary, flow_evidence, school_projection):
    records, analysis = _rows(records), _rows(analysis)
    _need(isinstance(summary, dict), "invalid_summary")
    by_id, profiles, sources, surveys, facts = {}, {}, {}, {}, {}
    for record in records:
        sid = record.get("submission_id")
        _need(isinstance(sid, str) and bool(sid) and sid not in by_id, "duplicate_or_missing_local_record_id")
        by_id[sid] = record
        source, survey, profile = _catalogue_profile(record)
        sources[source["key"]] = source
        surveys[survey["key"]] = survey
        profiles[sid] = profile
        facts[sid] = _terminal_fact(record)
        _need(record.get("claimed_wave") in {"T0", "T1", None, ""}, "unsupported_original_wave")
    slots, used = {}, set()
    for row in analysis:
        sid, child, role, wave = (row.get(k) for k in ("submission_id", "child_id", "role", "wave"))
        _need(sid in by_id and isinstance(child, str) and bool(child), "unknown_selected_record_or_child")
        record = by_id[sid]
        _need(record.get("child_id") == child and record["role"] == role
              and record.get("selected_wave") == wave and wave in {"T0", "T1"}, "selected_slot_mismatch")
        slot = child, role, wave
        _need(slot not in slots and sid not in used, "duplicate_selected_slot")
        slots[slot] = sid
        used.add(sid)
    _need(used == {sid for sid, r in by_id.items() if r.get("selected_wave")}, "incomplete_analysis_membership")

    adult = {"status": "unavailable", "policy": None, "evidence": None,
             "reason": "formal_adult_artifact_or_policy_missing"}
    adult_slots = {}
    child_bd = summary.get("bd_pairing_policy") == BD_CHILD_POLICY
    _need(summary.get("bd_pairing_policy") in {None, BD_CHILD_POLICY}, "unsupported_bd_pairing_policy")
    if child_bd:
        _need(summary.get("bd_requires_same_adult") is False and parent_longitudinal is not None,
              "child_bd_policy_or_artifact_missing")
    if parent_longitudinal is not None and (child_bd or summary.get("adult_identity_policy") == ADULT_POLICY):
        adult = {"status": "available", "policy": BD_CHILD_POLICY if child_bd else ADULT_POLICY,
                 "evidence": BD_CHILD_EVIDENCE if child_bd else "formal_parent_longitudinal_artifact", "reason": None}
        seen = set()
        continuity = {}
        for row in _rows(parent_longitudinal):
            sid, child, role, wave = (row.get(k) for k in ("submission_id", "child_id", "role", "wave"))
            _need(sid in by_id and role == "parent" and wave in {"T0", "T1"}
                  and isinstance(child, str) and bool(child), "invalid_formal_adult_slot")
            record = by_id[sid]
            _need(record.get("child_id") == child and record["role"] == "parent"
                  and (record["status"] in {"eligible", "extra_followup", "short_interval_followup"}),
                  "formal_adult_record_mismatch")
            _need((child, role, wave) not in adult_slots and sid not in seen, "duplicate_formal_adult_slot")
            if child_bd:
                status, rule, confirmed = (row.get(k) for k in
                    ("bd_adult_status", "bd_adult_rule", "adult_continuity_confirmed"))
                _need(row.get("bd_pairing_policy") == BD_CHILD_POLICY and
                      sid == slots.get((child, "parent", wave)) and
                      status in {"same", "different", "unconfirmed"} and isinstance(rule, str) and
                      (status == "unconfirmed" or bool(rule.strip())) and type(confirmed) is bool and
                      confirmed == (status == "same"), "child_bd_evidence_or_slot_mismatch")
                _need(child not in continuity or continuity[child] == (status, rule),
                      "child_bd_evidence_inconsistent")
                continuity[child] = (status, rule)
            adult_slots[child, role, wave] = sid
            seen.add(sid)
        for child in {k[0] for k in adult_slots}:
            _need((child, "parent", "T0") in adult_slots and (child, "parent", "T1") in adult_slots,
                  "incomplete_formal_adult_pair")
            _need(adult_slots[child, "parent", "T0"] == slots.get((child, "parent", "T0")),
                  "formal_adult_baseline_mismatch")
        if child_bd:
            selected_pairs = {child for child, role, wave in slots if role == "parent" and wave == "T0"
                              and (child, "parent", "T1") in slots}
            _need({key[0] for key in adult_slots} == selected_pairs, "child_bd_incomplete_membership")

    flow = dict(status="available", revision="terminal_projection_v1", reason=None)
    # A KEEP can overwrite an earlier exclusion. Terminal status cannot prove
    # the earlier checkpoints in that situation; require a persisted ledger.
    if any(r.get("manual_keep") or r["status"] == "manual_excluded" for r in records):
        flow = dict(status="unavailable", revision=None, reason="persisted_checkpoint_ledger_required")
    if flow_evidence is not None:
        _need(set(flow_evidence) == {"revision", "rows"}, "invalid_checkpoint_ledger")
        revision = _token(flow_evidence["revision"], "flow_revision")
        ledger = {}
        for row in flow_evidence["rows"]:
            _need(set(row) == {"submission_id", "exit_stage", "reason"}, "invalid_checkpoint_row")
            sid, stage, reason = row["submission_id"], row["exit_stage"], row["reason"]
            _need(sid in by_id and sid not in ledger and stage in REASONS and reason in REASONS[stage],
                  "unknown_or_duplicate_checkpoint_fact")
            _need((stage == "selected") == bool(by_id[sid].get("selected_wave")), "checkpoint_selection_mismatch")
            # Ledger is a minimal projection of the *published* history, never
            # an opportunity to change its terminal outcome.
            _need((stage, reason) == facts[sid], "checkpoint_terminal_mismatch")
            ledger[sid] = (stage, reason)
        _need(set(ledger) == set(by_id), "incomplete_checkpoint_ledger")
        facts, flow = ledger, dict(status="available", revision=revision, reason=None)

    children = sorted({k[0] for k in slots})
    members = {code: [] for code in SLOTS}
    for code, requirements in SLOTS.items():
        lookup = adult_slots if code == "BD" else slots
        for child in children:
            keys = [(child, role, wave) for role, wave in requirements]
            if all(k in lookup for k in keys):
                members[code].append([lookup[k] for k in keys])

    checks = ["submissions"]
    if "submissions" in summary:
        _need(_count(summary["submissions"]) == len(records), "summary_raw_mismatch")
    else:
        checks = []
    if "status_counts" in summary:
        _need(summary["status_counts"] == dict(Counter(r["status"] for r in records)), "summary_status_mismatch")
        checks.append("status_counts")
    for code in SLOTS:
        if code in summary and (code != "BD" or adult["status"] == "available"):
            _need(_count(summary[code]) == len(members[code]), "summary_sample_mismatch:" + code)
            checks.append(code)
    stages = summary.get("stage_counts", {})
    if flow["status"] == "available":
        expected = {"2.1.3": sum(s != "screening" for s, _ in facts.values()),
                    "2.1.4": sum(s not in STAGES[:2] for s, _ in facts.values()),
                    "2.1.6": sum(s in {"selection", "selected"} for s, _ in facts.values())}
        for key, count in expected.items():
            if key in stages:
                value = stages[key]["eligible_submissions"] if key == "2.1.4" else stages[key]
                if value != count:
                    flow = dict(status="unavailable", revision=None, reason="checkpoint_summary_not_reconstructible")
                    break
                checks.append(key)
    school = dict(status="unavailable", revision=None, reason="approved_school_projection_missing")
    school_rows = []
    if school_projection is not None:
        _need(set(school_projection) == {"revision", "statuses", "rows"}, "invalid_school_projection")
        revision = _token(school_projection["revision"], "school_revision")
        statuses = school_projection["statuses"]
        _need(isinstance(statuses, list) and len(set(statuses)) == len(statuses), "invalid_school_statuses")
        for status in statuses:
            _token(status, "school_status")
        school = dict(status="available", revision=revision, reason=None, statuses=sorted(statuses))
        seen = set()
        for row in school_projection["rows"]:
            _need(set(row) == {"submission_id", "status"}, "invalid_school_row")
            sid = row["submission_id"]
            _need(sid in by_id and sid not in seen and row["status"] in statuses, "invalid_school_assignment")
            seen.add(sid)
            school_rows.append(row)
        _need(seen == set(by_id), "incomplete_school_projection")
    meta = dict(release_id=_token(summary.get("release_id"), "release_id"),
                schema=FORMAT, adult=adult, flow=flow, school=school,
                reconciliation=dict(status="checked" if REQUIRED_RECONCILIATION_CHECKS <= set(checks)
                                    and flow["status"] == "available" and adult["status"] == "available" else "partial",
                                    checked=sorted(checks)))
    return records, by_id, profiles, sources, surveys, facts, members, school_rows, meta


def build_scope_index(records, analysis, parent_longitudinal, summary, *, flow_evidence=None, school_projection=None):
    """Build a closed aggregate index from one pinned release, entirely locally."""
    records, by_id, profiles, sources, surveys, facts, members, school_rows, meta = _prepare(
        records, analysis, parent_longitudinal, summary, flow_evidence, school_projection)
    signatures = sorted({canonical_json(p) for p in profiles.values()})
    positions = {s: i for i, s in enumerate(signatures)}
    refs = {sid: positions[canonical_json(p)] for sid, p in profiles.items()}
    cells = Counter((refs[r["submission_id"]], *facts[r["submission_id"]], r.get("claimed_wave") or "unknown")
                    for r in records)
    samples = Counter((code, tuple(refs[sid] for sid in slots)) for code in SLOTS for slots in members[code])
    schools = Counter((refs[row["submission_id"]], row["status"]) for row in school_rows)
    index = dict(format=FORMAT, meta=meta, sources=sorted(sources.values(), key=lambda x: x["key"]),
                 surveys=sorted(surveys.values(), key=lambda x: x["key"]),
                 profiles=[json.loads(s) for s in signatures],
                 records=[dict(profile=p, exit_stage=s, reason=r, original_wave=w, count=n)
                          for (p, s, r, w), n in sorted(cells.items())],
                 samples=[dict(code=c, profiles=list(ps), count=n) for (c, ps), n in sorted(samples.items())],
                 schools=[dict(profile=p, status=s, count=n) for (p, s), n in sorted(schools.items())])
    validate_index(index)
    return index


def validate_index(index):
    """Strict public-payload allowlist. Also used before every query."""
    _need(isinstance(index, dict) and index.get("format") == FORMAT, "compatible_scope_export_required")
    _need(set(index) == {"format", "meta", "sources", "surveys", "profiles", "records", "samples", "schools"}
          | ({"eligibility"} if "eligibility" in index else set()),
          "unexpected_index_field")
    _need(all(isinstance(index[k], list) for k in ("sources", "surveys", "profiles", "records", "samples", "schools")),
          "invalid_index_array")
    meta = index["meta"]
    _need(set(meta) == {"release_id", "schema", "adult", "flow", "school", "reconciliation"}
          and meta["schema"] == FORMAT, "invalid_index_metadata")
    _token(meta["release_id"], "release_id")
    for feature in ("adult", "flow", "school"):
        item = meta[feature]
        base = {"status", "policy" if feature == "adult" else "revision", "reason"}
        if feature == "adult":
            base.add("evidence")
        _need(set(item) == base | ({"statuses"} if feature == "school" and item.get("status") == "available" else set()),
              "invalid_feature_metadata")
        _need(item["status"] in {"available", "unavailable"}, "invalid_feature_status")
        for key in base - {"status"}:
            if item[key] is not None:
                _token(item[key], key)
        if item["status"] == "available":
            _need(item["reason"] is None and item["policy" if feature == "adult" else "revision"] is not None,
                  "missing_feature_provenance")
        if feature == "adult" and item["status"] == "available":
            _need((item["policy"], item["evidence"]) in {
                    (ADULT_POLICY, "formal_parent_longitudinal_artifact"),
                    (BD_CHILD_POLICY, BD_CHILD_EVIDENCE)},
                  "unsupported_adult_policy_or_evidence")
        if feature == "adult" and item["status"] == "unavailable":
            _need(item["evidence"] is None, "unavailable_adult_claims_evidence")
    rec = meta["reconciliation"]
    _need(set(rec) == {"status", "checked"} and rec["status"] in {"checked", "partial"}
          and isinstance(rec["checked"], list) and len(set(rec["checked"])) == len(rec["checked"])
          and set(rec["checked"]) <= REQUIRED_RECONCILIATION_CHECKS,
          "invalid_reconciliation")
    if rec["status"] == "checked":
        _need(REQUIRED_RECONCILIATION_CHECKS <= set(rec["checked"])
              and meta["flow"]["status"] == "available" and meta["adult"]["status"] == "available",
              "invalid_reconciliation")
    source_keys, survey_keys = set(), set()
    for row in index["sources"]:
        _need(set(row) == {"key", "label"} and row["key"] not in source_keys, "invalid_source_catalogue")
        _text(row["label"], "source")
        _need(row["key"] == _key("src", row["label"]), "source_key_mismatch")
        source_keys.add(row["key"])
    source_by_key = {s["key"]: s["label"] for s in index["sources"]}
    survey_by_key = {}
    for row in index["surveys"]:
        _need(set(row) == {"key", "label", "missing_name", "source_key", "role", "form_id", "form_version",
                           "identity_basis", "provenance"}, "unexpected_survey_field")
        _need(row["key"] not in survey_keys and row["source_key"] in source_keys and row["role"] in ROLES
              and type(row["missing_name"]) is bool, "invalid_survey_catalogue")
        _text(row["label"], "survey_name")
        for k in ("form_id", "form_version"):
            _text(row[k], k, nullable=True)
        _need(row["identity_basis"] == ("form_metadata" if row["form_id"] else "source_role_name_only")
              and row["provenance"] == "answer.Survey", "invalid_survey_provenance")
        _need(not row["missing_name"] or row["label"] == "Missing survey name", "invalid_missing_name")
        identity = [source_by_key[row["source_key"]], row["role"], None if row["missing_name"] else row["label"],
                    row["form_id"], row["form_version"]]
        _need(row["key"] == _key("svy", identity), "survey_key_mismatch")
        survey_keys.add(row["key"])
        survey_by_key[row["key"]] = row
    profiles = index["profiles"]
    for p in profiles:
        _need(set(p) == {"source_key", "survey_key", "role", "day", "timing_basis", "date_state"},
              "unexpected_profile_field")
        _need(p["source_key"] in source_keys and p["survey_key"] in survey_keys and p["role"] in ROLES,
              "invalid_profile_reference")
        survey = survey_by_key[p["survey_key"]]
        _need((survey["source_key"], survey["role"]) == (p["source_key"], p["role"]), "profile_catalogue_mismatch")
        _need(p["timing_basis"] in {"observed", "manual_verified", "accepted_batch", "unknown"}
              and p["date_state"] in {"usable", "missing", "naive", "invalid", "untrusted"}, "invalid_timing_profile")
        if p["day"] is not None:
            _iso(p["day"])
        _need((p["day"] is not None) == (p["date_state"] == "usable"), "day_state_mismatch")
        _need(p["day"] is None or p["timing_basis"] != "unknown", "untrusted_usable_day")
    _need(len({canonical_json(p) for p in profiles}) == len(profiles), "duplicate_profile")

    def ref(p):
        _need(type(p) is int and 0 <= p < len(profiles), "invalid_profile_position")
    for row in index["records"]:
        _need(set(row) == {"profile", "exit_stage", "reason", "original_wave", "count"}, "unexpected_record_cell_field")
        ref(row["profile"])
        _need(row["exit_stage"] in REASONS and row["reason"] in REASONS[row["exit_stage"]]
              and row["original_wave"] in {"T0", "T1", "unknown"}, "invalid_record_fact")
        _need(_count(row["count"]) > 0, "zero_record_cell")
    for row in index["samples"]:
        _need(set(row) == {"code", "profiles", "count"} and row["code"] in SLOTS, "invalid_sample_cell")
        _need(len(row["profiles"]) == len(SLOTS[row["code"]]), "invalid_slot_multiplicity")
        for p, (role, _) in zip(row["profiles"], SLOTS[row["code"]]):
            ref(p)
            _need(profiles[p]["role"] == role, "sample_slot_role_mismatch")
        _need(_count(row["count"]) > 0, "zero_sample_cell")
        _need(row["code"] != "BD" or meta["adult"]["status"] == "available", "unavailable_adult_has_cells")
    statuses = meta["school"].get("statuses", [])
    _need(isinstance(statuses, list) and len(set(statuses)) == len(statuses), "invalid_school_statuses")
    for s in statuses:
        _token(s, "school_status")
    for row in index["schools"]:
        _need(set(row) == {"profile", "status", "count"} and row["status"] in statuses, "invalid_school_cell")
        ref(row["profile"])
        _need(_count(row["count"]) > 0, "zero_school_cell")
    for name, fields in (("records", ("profile", "exit_stage", "reason", "original_wave")),
                         ("samples", ("code", "profiles")), ("schools", ("profile", "status"))):
        _need(len({canonical_json([r[k] for k in fields]) for r in index[name]}) == len(index[name]), "duplicate_aggregate_cell")
    totals = Counter()
    for r in index["records"]:
        totals[r["profile"]] += r["count"]
    raw_total = _count(sum(totals.values()))
    _need(set(totals) == set(range(len(profiles))), "orphan_profile")
    if meta["school"]["status"] == "available":
        school_totals = Counter()
        for r in index["schools"]:
            school_totals[r["profile"]] += r["count"]
        _need(school_totals == totals, "school_record_reconciliation")
    selected = Counter()
    for r in index["records"]:
        if r["exit_stage"] == "selected":
            selected[r["profile"]] += r["count"]
    singles = Counter()
    for r in index["samples"]:
        _count(r["count"])
        if len(r["profiles"]) == 1:
            singles[r["profiles"][0]] += r["count"]
        _need(r["count"] <= raw_total, "sample_exceeds_raw")
    if 'eligibility' in index:
        from .analysis_eligibility import validate_scope_eligibility
        excluded = validate_scope_eligibility(index)
        selected.subtract(excluded)
        selected = +selected
    _need(singles == selected, "selected_sample_reconciliation")
    # Whole-index slot margins also detect corrupted aggregate multiplicities.
    # BD's second slot may be an unselected retained record, so its first slot
    # uses B's published baseline margin and its second uses the raw margin.
    margins = {c: Counter() for c in "ABCD"}
    for r in index["samples"]:
        if r["code"] in margins:
            margins[r["code"]][r["profiles"][0]] += r["count"]
    requirements = {"AC": "AC", "BD": "B?", "E": "AB", "F": "CD", "EF": "ABCD"}
    for code, singles_codes in requirements.items():
        demands = [Counter() for _ in singles_codes]
        raw_demands = Counter()
        for r in index["samples"]:
            if r["code"] == code:
                for i, p in enumerate(r["profiles"]):
                    demands[i][p] += r["count"]
                    raw_demands[p] += r["count"]
        for i, single in enumerate(singles_codes):
            limit = totals if single == "?" else margins[single]
            _need(all(n <= limit[p] for p, n in demands[i].items()), "sample_marginal_exceeded")
        _need(all(n <= totals[p] for p, n in raw_demands.items()), "sample_marginal_multiplicity_exceeded")
    canonical_json(index)  # Reject non-JSON values and NaN/Infinity.
    return index


def default_selection(index):
    return dict(sources=[s["key"] for s in index["sources"]],
                surveys=[s["key"] for s in index["surveys"]], start=None, end=None, include_unknown=True)


def normalize_selection(index, selection=None):
    if selection is None:
        return default_selection(index)
    _need(isinstance(selection, dict) and not (set(selection) - {"sources", "surveys", "start", "end", "include_unknown"}),
          "invalid_selection_fields")
    out = default_selection(index)
    out.update(selection)
    for name in ("sources", "surveys"):
        keys = {r["key"] for r in index[name]}
        _need(isinstance(out[name], list) and all(isinstance(k, str) and k in keys for k in out[name]),
              "unknown_selection_key:" + name)
        out[name] = sorted(set(out[name]))
    for name in ("start", "end"):
        if out[name] is not None:
            _iso(out[name])
    _need(not (out["start"] and out["end"] and out["start"] > out["end"]), "reversed_date_bounds")
    if "include_unknown" not in selection:
        out["include_unknown"] = not (out["start"] or out["end"])
    _need(type(out["include_unknown"]) is bool, "invalid_include_unknown")
    return out


def transition_selection(index, current, patch):
    """UI state helper: first activation of bounds resets unknown inclusion."""
    old = normalize_selection(index, current)
    _need(isinstance(patch, dict), "invalid_selection_patch")
    new = {**old, **patch}
    if not (old["start"] or old["end"]) and (new.get("start") or new.get("end")) and "include_unknown" not in patch:
        new["include_unknown"] = False
    return normalize_selection(index, new)


def catalogue_options(index, facet, search=""):
    """Search is display-only. Select-all always uses default_selection."""
    _need(facet in {"sources", "surveys"} and isinstance(search, str), "invalid_catalogue_search")
    return [dict(r) for r in index[facet] if search.lower() in r["label"].lower()]


def _matches(profile, selection, ignore=None):
    if ignore != "sources" and profile["source_key"] not in selection["sources"]:
        return False
    if ignore != "surveys" and profile["survey_key"] not in selection["surveys"]:
        return False
    day = profile["day"]
    if day is None:
        return selection["include_unknown"]
    return (selection["start"] is None or day >= selection["start"]) and (selection["end"] is None or day <= selection["end"])


def query_scope(index, selection=None):
    validate_index(index)
    scope = normalize_selection(index, selection)
    mask = [_matches(p, scope) for p in index["profiles"]]
    return _assemble(index, scope, mask)


def _assemble(index, scope, mask):
    # Aggregation only. No private membership or research logic lives here.
    raw, outside, unknown_excluded = ({r: 0 for r in ROLES} for _ in range(3))
    source_rows = {s["key"]: dict(source_key=s["key"], label=s["label"], student=0, parent=0) for s in index["sources"]}
    facets = {name: {r["key"]: 0 for r in index[name]} for name in ("sources", "surveys")}
    basis = {b: 0 for b in ("observed", "manual_verified", "accepted_batch", "unknown")}
    date_states = {s: 0 for s in ("usable", "missing", "naive", "invalid", "untrusted")}
    original = {role: {w: 0 for w in ("T0", "T1", "unknown")} for role in ROLES}
    lanes = {role: {stage: dict(entering=0, remaining=0, exits={r: 0 for r in REASONS[stage]}) for stage in STAGES} for role in ROLES}
    for row in index["records"]:
        p, n = index["profiles"][row["profile"]], row["count"]
        role = p["role"]
        for name, key in (("sources", "source_key"), ("surveys", "survey_key")):
            if _matches(p, scope, ignore=name):
                facets[name][p[key]] += n
        if p["day"] is None and p["source_key"] in scope["sources"] and p["survey_key"] in scope["surveys"] and not scope["include_unknown"]:
            unknown_excluded[role] += n
        if not mask[row["profile"]]:
            outside[role] += n
            continue
        raw[role] += n
        source_rows[p["source_key"]][role] += n
        basis[p["timing_basis"]] += n
        date_states[p["date_state"]] += n
        original[role][row["original_wave"]] += n
        for stage in STAGES:
            lane = lanes[role][stage]
            lane["entering"] += n
            if row["exit_stage"] == stage:
                lane["exits"][row["reason"]] += n
                break
            lane["remaining"] += n
    samples = []
    for code in SLOTS:
        available = code != "BD" or index["meta"]["adult"]["status"] == "available"
        n = sum(row["count"] for row in index["samples"] if row["code"] == code and all(mask[p] for p in row["profiles"]))
        samples.append(dict(code=code, status="available" if available else "unavailable", count=n if available else None,
                            unit="questionnaire_records" if len(SLOTS[code]) == 1 else "longitudinal_cases" if code in {"AC", "BD"} else "dyads",
                            policy=index["meta"]["adult"]["policy"] if code == "BD" else "fixed_published_slots",
                            continuity_evidence=index["meta"]["adult"]["evidence"] if code == "BD" else None,
                            reason=None if available else index["meta"]["adult"]["reason"]))
    flow = dict(index["meta"]["flow"], unit="questionnaire_records",
                lanes=lanes if index["meta"]["flow"]["status"] == "available" else None)
    school = dict(index["meta"]["school"], unit="questionnaire_records", counts=None)
    if school["status"] == "available":
        school["counts"] = {s: {r: 0 for r in ROLES} for s in school["statuses"]}
        for row in index["schools"]:
            if mask[row["profile"]]:
                school["counts"][row["status"]][index["profiles"][row["profile"]]["role"]] += row["count"]
    out = dict(format=RESULT_FORMAT, release_id=index["meta"]["release_id"], schema=FORMAT, scope=scope,
               date_policy=dict(timezone="Asia/Hong_Kong", inclusive=True, unknown_excluded=unknown_excluded,
                                included_unknown_interval_unverified=bool((scope["start"] or scope["end"]) and scope["include_unknown"] and sum(date_states.values()) > date_states["usable"])),
               raw=raw, out_of_scope=outside, sources=list(source_rows.values()), samples=samples, flow=flow,
               facets={name: [dict(key=k, available=n) for k, n in counts.items()] for name, counts in facets.items()},
               dates=dict(timing_basis=basis, date_state=date_states), original_waves=original,
               identity_groups=dict(status="unavailable", count=None, unit="identity_groups", reason="represented_group_signatures_not_provided"),
               school=school, reconciliation=deepcopy(index["meta"]["reconciliation"]),
               scope_notice="First-tab scope only; published matching and other tabs are unchanged.")
    if 'eligibility' in index:
        from .analysis_eligibility import query_scope_eligibility
        out['eligibility'] = query_scope_eligibility(index, mask)
        out['scope_notice'] = 'Fixed published members after manual analytical exclusions; raw and stages remain historical.'
    canonical_json(out)
    return deepcopy(out)
