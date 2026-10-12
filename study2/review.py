from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

import pandas as pd

from .common import PipelineError, contacts, digest, dumps, file_hash, text, timestamp, utcnow
from .outputs import write_excel
from .store import current
from .matching import identity_evidence, validate_manual_links

ACTION_COLUMNS = ["release_id", "case_id", "kind", "rule", "status", "reason_for_review",
                  "record_a", "record_b", "version_a", "version_b", "role_a", "role_b",
                  "school_a", "school_b", "dob_a", "dob_b", "gender_a", "gender_b",
                  "contacts_a", "contacts_b", "observed_at_a", "observed_at_b",
                  "adult_birth_year_a", "adult_birth_year_b", "adult_relationship_a", "adult_relationship_b",
                  "adult_personal_contacts_a", "adult_personal_contacts_b", "review_warnings",
                  "action", "value", "label", "reviewer", "reason"]
SCHOOL_COLUMNS = ["release_id", "dictionary_hash", "normalized_key", "raw_name",
                  "action", "canonical_school_name", "school_type", "school_sex",
                  "school_district", "school_religion", "reviewer", "reason"]


def release_records(db) -> tuple[dict, dict]:
    release = current(db)
    if not release:
        raise PipelineError("No published release")
    records = {r["submission_id"]: r for r in db.execute(
        "SELECT n.submission_id,n.payload_json FROM normalized_records n WHERE run_id=?", (release["run_id"],))}
    return release, {k: json.loads(v["payload_json"]) for k, v in records.items()}


def export_review(db, cfg: dict, path: Path, limit=500):
    release, records = release_records(db)
    cases = [json.loads(r[0]) for r in db.execute("SELECT payload_json FROM release_candidates WHERE release_id=? ORDER BY case_id", (release["release_id"],))]
    rng = random.Random(20261005)
    rng.shuffle(cases)
    # Include all cases with --limit 0. Default stratified sample distributes
    # capacity across confirmed, pending and unmatched cases for validation.
    if limit:
        keys = sorted({(c["status"], c["rule"]) for c in cases})
        buckets = {key: [c for c in cases if (c["status"], c["rule"]) == key] for key in keys}
        chosen = []
        while len(chosen) < limit and any(buckets.values()):
            for status in buckets:
                if buckets[status] and len(chosen) < limit:
                    chosen.append(buckets[status].pop())
        cases = chosen
    rows = []
    for c in cases:
        row = {"release_id": release["release_id"], **c, "reason_for_review": c["reason"], "reason": "", "action": "", "value": "", "label": "", "reviewer": ""}
        row["review_warnings"] = "；".join(c.get("review_warnings", []))
        for suffix in ["a", "b"]:
            r = records.get(c["record_" + suffix], {})
            for k in ["role", "school", "dob", "gender", "observed_at"]:
                row[k + "_" + suffix] = r.get(k)
            from .common import contacts
            row["contacts_" + suffix] = ";".join(sorted(contacts(r.get("answer", {}))))
            from .respondents import adult_evidence
            ae = adult_evidence(r)
            row["adult_birth_year_" + suffix] = ae["birth_year"]
            row["adult_relationship_" + suffix] = ae["relationship"]
            row["adult_personal_contacts_" + suffix] = ";".join(ae["personal_contacts"])
        rows.append(row)
    dictionary_path = Path(cfg["state_dir"]) / "school_dictionary.xlsx"
    dictionary = pd.read_excel(dictionary_path).fillna("").to_dict("records")
    known = {text(r.get("normalized_key") or r.get("raw_name")).lower(): r for r in dictionary}
    for r in records.values():
        if "school_unmapped" in r["issues"]:
            for name in ["school_from_student", "school_from_parent"]:
                raw_name = text(r["answer"].get(name))
                if raw_name:
                    known.setdefault(raw_name.lower(), {"normalized_key": raw_name.lower(), "raw_name": raw_name})
    schools = []
    for key, r in sorted(known.items()):
        schools.append({"release_id": release["release_id"], "dictionary_hash": file_hash(dictionary_path),
                        **{k: r.get(k, "") for k in SCHOOL_COLUMNS}, "normalized_key": key,
                        "action": "", "reviewer": "", "reason": ""})
        schools[-1]["release_id"] = release["release_id"]
        schools[-1]["dictionary_hash"] = file_hash(dictionary_path)
    index = [{"submission_id": r["submission_id"], "version_id": r["version_id"],
              "role": r["role"], "child_id": r.get("child_id"), "status": r["status"],
              "school": r.get("school"), "dob": r.get("dob"), "gender": r.get("gender"),
              "contacts": ";".join(sorted(contacts(r["answer"]))),
              "observed_at": r.get("observed_at"), "time_confidence": r.get("time_confidence"),
              "source_id": r["source_id"], "original_row": r.get("location", {}).get("row")}
             for r in records.values()]
    write_excel(path, {"cases": pd.DataFrame(rows, columns=ACTION_COLUMNS), "submissions": index,
                       "schools": pd.DataFrame(schools, columns=SCHOOL_COLUMNS),
                       "instructions": [{"instruction": s} for s in [
                           "Edit action/value/label/reviewer/reason only; blank action does nothing.",
                           "Actions: LINK, UNLINK, LINK_ADULT, UNLINK_ADULT, KEEP, EXCLUDE, SET_DATE, SET_FIELD. SET_DATE value must be ISO timestamp.",
                           "LINK_ADULT/UNLINK_ADULT apply only to parent responses already assigned to the same confirmed child; LINK means child identity only.",
                           'SET_FIELD value: {"field":"student_PHQ_01","value":2}. It changes the standardized field, never the raw source.',
                           "Use NEW_RECORD for a single-record correction copied from submissions. Pair corrections use NEW.",
                           "Labels: MATCH, NONMATCH, UNRESOLVED. Label alone records validation, not an override.",
                           "Use case_id NEW and kind identity/family for a missed pair; copy IDs/version IDs from submissions.",
                           "School actions: MAP or DELETE. Add reason and reviewer for every decision.",
                           "This workbook contains identifiers. Keep it within the research team's controlled storage.",
                       ]]})
    return {"release_id": release["release_id"], "cases_exported": len(rows), "school_rows": len(schools)}


def active_decisions(db) -> list[dict]:
    active = {}
    for row in db.execute("SELECT * FROM decisions ORDER BY imported_at,decision_id"):
        payload = json.loads(row["payload_json"])
        active[payload["target_key"]] = {**dict(row), "payload": payload}
    return list(active.values())


def validate_review_rows(db, cfg: dict, case_rows: list[dict], school_rows: list[dict] | None = None, context=None) -> dict:
    """Interface-independent, all-or-nothing validation. Does not write state."""
    release, records = context[:2] if context else release_records(db)
    actions, labels, school_changes = [], [], []
    package_targets = set()
    expected_cases = context[2] if context else {r[0]: json.loads(r[1]) for r in db.execute("SELECT case_id,payload_json FROM release_candidates WHERE release_id=?", (release["release_id"],))}
    for row in case_rows:
        action, label = text(row.get("action")).upper(), text(row.get("label")).upper()
        if not action and not label:
            continue
        if text(row.get("release_id")) != release["release_id"]:
            raise PipelineError("Stale review release; export a new package")
        if not text(row.get("reviewer")) or not text(row.get("reason")):
            raise PipelineError("Every action or validation label needs reviewer and reason")
        sid_a, sid_b = text(row.get("record_a")), text(row.get("record_b"))
        for suffix, sid in [("a", sid_a), ("b", sid_b)]:
            if sid and (sid not in records or records[sid]["version_id"] != text(row.get("version_" + suffix))):
                raise PipelineError("Missing record or source version mismatch")
        case_id = text(row.get("case_id"))
        if case_id == "NEW_RECORD":
            if not sid_a or sid_b or label or action in {"LINK", "UNLINK", "LINK_ADULT", "UNLINK_ADULT"}:
                raise PipelineError("NEW_RECORD needs one record and a single-record correction")
            case_id = "CASE_" + digest(["correction", [sid_a]])[:28]
        elif case_id != "NEW":
            expected = expected_cases.get(case_id)
            if not expected or expected["record_a"] != sid_a or expected["record_b"] != sid_b:
                raise PipelineError("Case identifiers were changed")
        else:
            if not sid_a or not sid_b or sid_a == sid_b:
                raise PipelineError("NEW pair needs two different current records")
            case_id = "CASE_" + digest([text(row.get("kind")), sorted([sid_a, sid_b])])[:28]
        if label:
            kind = expected_cases.get(case_id, row).get("kind")
            if kind not in {"identity", "family", "respondent"}:
                raise PipelineError("Identity validation labels apply only to identity/family/respondent cases")
            if label not in {"MATCH", "NONMATCH", "UNRESOLVED"}:
                raise PipelineError("Unknown validation label")
            if label in {"MATCH", "NONMATCH"} and not sid_b:
                raise PipelineError("MATCH/NONMATCH validation needs a pair, not a single submission")
            labels.append({**row, "case_id": case_id, "label": label})
        if not action:
            continue
        if action not in {"LINK", "UNLINK", "LINK_ADULT", "UNLINK_ADULT", "KEEP", "EXCLUDE", "SET_DATE", "SET_FIELD"}:
            raise PipelineError("Unknown correction action")
        if action in {"LINK", "UNLINK", "LINK_ADULT", "UNLINK_ADULT"}:
            if not sid_b or sid_a == sid_b:
                raise PipelineError("Link correction needs two different submissions")
            is_adult = action.endswith("_ADULT")
            if is_adult and not (records[sid_a]["role"] == records[sid_b]["role"] == "parent" and
                                 records[sid_a].get("child_id") and records[sid_a]["child_id"] == records[sid_b].get("child_id")):
                raise PipelineError("Adult correction needs two parent responses for the same confirmed child")
            target_key = ("adult_pair:" if is_adult else "pair:") + digest(sorted([sid_a, sid_b]))
        elif action == "SET_FIELD":
            try:
                value = json.loads(row.get("value", ""))
            except ValueError:
                raise PipelineError("SET_FIELD value must be a JSON field/value object") from None
            if not isinstance(value, dict) or set(value) != {"field", "value"} or value["field"] not in records[sid_a]["answer"] or value["field"] in {"Survey", "建立時間", "更新時間", "student_answer", "parent_answer"} or isinstance(value["value"], (dict, list)):
                raise PipelineError("SET_FIELD needs a registered, editable scalar answer field")
            import re
            match = re.fullmatch(r"(?:student|parent)_(PHQ|SEC|FQOL|TBV|TBP|CBV|CBP)_\d{2}", value["field"])
            if match and value["value"] is not None:
                lo, hi = {"PHQ": (0,3), "SEC": (0,3), "FQOL": (1,5)}.get(match[1],(0,4))
                try:
                    number = float(value["value"])
                    valid = number.is_integer() and lo <= number <= hi
                except (ValueError, TypeError):
                    valid = False
                if not valid:
                    raise PipelineError("SET_FIELD scale value is outside questionnaire coding")
            target_key = "field:" + sid_a + ":" + value["field"]
        else:
            target_key = ("date:" if action == "SET_DATE" else "selection:") + sid_a
        if not sid_a or target_key in package_targets:
            raise PipelineError("Conflicting/duplicate commands in the same review package")
        package_targets.add(target_key)
        if action == "SET_DATE" and not timestamp(row.get("value")):
            raise PipelineError("SET_DATE requires a reliable ISO timestamp")
        from .respondents import adult_evidence
        evidence = adult_evidence if action.endswith("_ADULT") else identity_evidence
        actions.append({**row, "case_id": case_id, "action": action, "target_key": target_key,
                        "evidence_a": evidence(records[sid_a]),
                        "evidence_b": evidence(records[sid_b]) if sid_b else None})
    proposed = {d["payload"]["target_key"]: d["payload"] for d in active_decisions(db)}
    corrected_ids = {a["record_a"] for a in actions if a["action"] == "SET_FIELD"}
    if any(corrected_ids & {a["record_a"], a.get("record_b")} for a in actions if a["action"] in {"LINK", "UNLINK", "LINK_ADULT", "UNLINK_ADULT"}):
        raise PipelineError("Correct fields, rerun and export current evidence before submitting identity decisions for those records")
    proposed.update({a["target_key"]: a for a in actions})
    current_pairs = [p for p in proposed.values() if p["action"] in {"LINK", "UNLINK"}
                     and all(sid in records and records[sid]["version_id"] == p.get("version_" + suffix)
                             for suffix, sid in [("a", p["record_a"]), ("b", p["record_b"])])]
    validate_manual_links([(p["record_a"], p["record_b"]) for p in current_pairs if p["action"] == "LINK"],
                          [(p["record_a"], p["record_b"]) for p in current_pairs if p["action"] == "UNLINK"])
    current_adults = [p for p in proposed.values() if p["action"] in {"LINK_ADULT", "UNLINK_ADULT"}
                      and all(sid in records and records[sid]["version_id"] == p.get("version_"+suffix)
                              for suffix, sid in [("a", p["record_a"]), ("b", p["record_b"])])]
    validate_manual_links([(p["record_a"], p["record_b"]) for p in current_adults if p["action"] == "LINK_ADULT"],
                          [(p["record_a"], p["record_b"]) for p in current_adults if p["action"] == "UNLINK_ADULT"])
    dictionary_path = Path(cfg["state_dir"]) / "school_dictionary.xlsx"
    expected_hash = file_hash(dictionary_path) if school_rows else None
    dictionary = pd.read_excel(dictionary_path).fillna("") if school_rows else pd.DataFrame()
    if school_rows:
        dictionary["normalized_key"] = dictionary.apply(lambda r: text(r.get("normalized_key") or r.get("raw_name")).lower(), axis=1)
    school_keys = set()
    for row in school_rows or []:
        action = text(row.get("action")).upper()
        if not action:
            continue
        if text(row.get("release_id")) != release["release_id"] or text(row.get("dictionary_hash")) != expected_hash:
            raise PipelineError("School dictionary version conflict")
        key = text(row.get("normalized_key")).lower()
        if action not in {"MAP", "DELETE"} or not key or not text(row.get("reviewer")) or not text(row.get("reason")):
            raise PipelineError("School decision requires valid action, key, reviewer and reason")
        if key in school_keys:
            raise PipelineError("Duplicate school decisions")
        school_keys.add(key)
        if action == "MAP" and not text(row.get("canonical_school_name")):
            raise PipelineError("School MAP requires official canonical name")
        school_changes.append({**row, "action": action.lower(), "normalized_key": key})
    return {"actions": actions, "labels": labels, "school_changes": school_changes,
            "dictionary": dictionary, "dictionary_path": dictionary_path}


def commit_review_rows(db, validated: dict, application: dict | None = None) -> dict:
    """Commit already validated changes; application marker shares this transaction."""
    actions, labels, school_changes = (validated[k] for k in ("actions", "labels", "school_changes"))
    dictionary, dictionary_path = validated["dictionary"], validated["dictionary_path"]
    # Validation above is all-or-nothing. Dictionary is replaced inside the same
    # protected writer operation; preserve its previous file for failure recovery.
    if school_changes:
        for row in school_changes:
            update = {k: row.get(k, "") for k in ["raw_name", "normalized_key", "canonical_school_name", "action", "school_type", "school_sex", "school_district", "school_religion"]}
            mask = dictionary["normalized_key"] == row["normalized_key"]
            if mask.any():
                for k, value in update.items():
                    dictionary.loc[mask, k] = value
            else:
                dictionary = pd.concat([dictionary, pd.DataFrame([update])], ignore_index=True)
        tmp = dictionary_path.with_name("school_dictionary.next.xlsx")
        write_excel(tmp, {"Sheet1": dictionary})
    else:
        tmp = None
    old_decisions = {d["payload"]["target_key"]: d["decision_id"] for d in active_decisions(db)}
    try:
        with db:
            for row in actions:
                did = "DEC_" + digest(row)[:28]
                db.execute("INSERT OR IGNORE INTO decisions VALUES(?,?,?,?,?,?)", (did, utcnow(), row["reviewer"], row["reason"], dumps(row), old_decisions.get(row["target_key"])))
            for row in labels:
                db.execute("INSERT OR REPLACE INTO labels VALUES(?,?,?,?,?,?)", (row["case_id"], row["label"], row["reviewer"], row["reason"], utcnow(), dumps(row)))
            for row in school_changes:
                payload = {**row, "target_key": "school:" + row["normalized_key"]}
                db.execute("INSERT OR IGNORE INTO decisions VALUES(?,?,?,?,?,?)", ("DEC_" + digest(payload)[:28], utcnow(), row["reviewer"], row["reason"], dumps(payload), None))
            if application:
                db.execute("INSERT INTO review_applications VALUES(?,?,?)",
                           (application["batch_id"], utcnow(), dumps(application)))
            if tmp:
                import shutil
                previous = dictionary_path.with_name("school_dictionary.previous.xlsx")
                shutil.copy2(dictionary_path, previous)
                tmp.replace(dictionary_path)
    except Exception:
        if tmp and dictionary_path.with_name("school_dictionary.previous.xlsx").exists():
            import shutil
            shutil.copy2(dictionary_path.with_name("school_dictionary.previous.xlsx"), dictionary_path)
        raise
    return {"corrections": len(actions), "validation_labels": len(labels), "school_changes": len(school_changes)}


def import_review(db, cfg: dict, path: Path) -> dict:
    sheets = pd.read_excel(path, sheet_name=None, dtype=str)
    if not {"cases", "schools"} <= set(sheets):
        raise PipelineError("Review workbook needs cases and schools worksheets")
    validated = validate_review_rows(db, cfg, sheets["cases"].fillna("").to_dict("records"),
                                     sheets["schools"].fillna("").to_dict("records"))
    return commit_review_rows(db, validated)


def apply_field_decisions(records, decisions):
    by_id = {r["submission_id"]: r for r in records}
    for d in decisions:
        p = d["payload"]
        if p["action"] != "SET_FIELD":
            continue
        r = by_id.get(p["record_a"])
        if r and r["version_id"] == p["version_a"]:
            value = json.loads(p["value"])
            if value["field"] not in r["answer"]:
                raise PipelineError("Correction field removed from current questionnaire schema")
            r["answer"][value["field"]] = value["value"]
    return records


def validation_report(db, cases: list[dict], records: list[dict] | None = None) -> list[dict]:
    indexed = {c["case_id"]: c for c in cases}
    records_by_id = {r["submission_id"]: r for r in records or []}
    buckets = {}
    for row in db.execute("SELECT * FROM labels"):
        c = indexed.get(row["case_id"])
        p = json.loads(row["payload_json"])
        if not c and records_by_id and p.get("record_a") in records_by_id and p.get("record_b") in records_by_id:
            c = {**p, "status": "unmatched", "rule": "outside_candidate_search",
                 "version_a": records_by_id[p["record_a"]]["version_id"],
                 "version_b": records_by_id[p["record_b"]]["version_id"]}
        if not c or c["version_a"] != p.get("version_a") or c["version_b"] != p.get("version_b"):
            continue
        baseline = p.get("pre_review", c)
        rule = baseline["rule"]
        counts = buckets.setdefault((rule,p.get('pre_review_release_id','')), Counter())
        counts["reviewed"] += 1
        counts["unresolved" if row["label"] == "UNRESOLVED" else "true_positive" if baseline["status"] == "confirmed" and row["label"] == "MATCH" else "false_positive" if baseline["status"] == "confirmed" else "missed_match" if row["label"] == "MATCH" else "nonmatch"] += 1
        if c["status"] == "confirmed" and row["label"] == "NONMATCH":
            raise PipelineError("A reviewer-labelled NONMATCH was automatically confirmed; publication blocked")
    totals = Counter(c["rule"] for c in cases if c["kind"] in {"identity", "family", "respondent"})
    for rule, baseline_release in buckets:
        if baseline_release:
            totals[(rule,baseline_release)] = db.execute("SELECT COUNT(*) FROM release_candidates WHERE release_id=? "
                    "AND json_extract(payload_json,'$.rule')=? AND json_extract(payload_json,'$.kind') IN ('identity','family','respondent')",
                    (baseline_release,rule)).fetchone()[0]
    return [{"rule": rule, "baseline_release_id":baseline_release or None, **counts,
             "generated_candidates": totals[(rule,baseline_release)] if baseline_release else totals[rule],
             "precision_on_reviewed_confirmed": counts["true_positive"] / (counts["true_positive"] + counts["false_positive"]) if counts["true_positive"] + counts["false_positive"] else None,
             "coverage_note": "Stratified reviewed cases only; not a population accuracy estimate"} for (rule,baseline_release), counts in sorted(buckets.items())]
