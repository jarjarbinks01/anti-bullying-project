"""One-time migration of populated legacy pair decisions with explicit provenance.

Legacy IDs are never assumed to equal new IDs. Only a unique source observation
match is reusable. Missing/ambiguous mappings remain in the migration report.
"""
from collections import defaultdict
from pathlib import Path

import pandas as pd

from .common import PipelineError, digest, dumps, text, timestamp, utcnow
from .matching import identity_evidence
from .review import active_decisions


def legacy_files(cfg):
    if cfg.get("source_scope") in {"qualtrics_only", "merged_abcd"}:
        return []
    root=Path(cfg["project_root"])
    names=["2.1.5_same_person_dedup/student_same_person_long_dedup.xlsx", "2.1.5_same_person_dedup/parent_same_person_long_dedup.xlsx",
           "2.1.6_manual_swap/false-single.xlsx", "2.1.6_manual_swap/manual-substitution.xlsx",
           "2.1.6_manual_swap/false-matched_cases.xlsx", "2.1.6_manual_swap/false-duplication.xlsx",
           "3.1.3_manual_pairing/false-paired_cases.xlsx", "3.1.3_manual_pairing/false-single-pair.xlsx", "3.1.3_manual_pairing/manual-pair-substitution.xlsx"]
    return [root/n for n in names if (root/n).exists()]


def observation_key(row, role):
    date = timestamp(row.get("建立時間"))
    return role, text(row.get("Survey")), date.isoformat() if date else text(row.get("建立時間"))


def migrate_legacy(db, cfg, records):
    if cfg.get("source_scope") in {"qualtrics_only", "merged_abcd"}:
        return []
    root = Path(cfg["project_root"])
    for path in legacy_files(cfg):
        if path.name in {"false-matched_cases.xlsx", "false-duplication.xlsx", "false-paired_cases.xlsx", "false-single-pair.xlsx", "manual-pair-substitution.xlsx"}:
            if any(len(f.dropna(how="all")) for f in pd.read_excel(path,sheet_name=None).values()):
                raise PipelineError("Populated legacy split/rescue/dyad correction needs stable-ID review migration: "+path.name)
    jobs = []
    for name in ["false-single.xlsx", "manual-substitution.xlsx"]:
        path = root / "2.1.6_manual_swap" / name
        if path.exists():
            for sheet, frame in pd.read_excel(path, sheet_name=None, dtype=str).items():
                for i, row in frame.fillna("").iterrows():
                    a,b = text(row.get("entry_id_1")),text(row.get("entry_id_2"))
                    if a or b:
                        if not a or not b:
                            raise PipelineError("Incomplete legacy manual pair; migration needs review")
                        jobs.append({"legacy_a":a,"legacy_b":b,"file":str(path.relative_to(root)),"sheet":sheet,"row":i+2,"action":"LINK"})
    if not jobs:
        return []
    requested = {j[k] for j in jobs for k in ["legacy_a","legacy_b"]}
    legacy_rows = {}
    for role in ["student","parent"]:
        path = root / "2.1.5_same_person_dedup" / f"{role}_same_person_long_dedup.xlsx"
        if not path.exists():
            continue
        frame = pd.read_excel(path)
        for row in frame.to_dict("records"):
            old = text(row.get("same_person_entry_id"))
            if old in requested:
                legacy_rows[old] = (role,row)
    index = defaultdict(list)
    for r in records:
        index[observation_key(r["answer"],r["role"])].append(r)
    resolved = {}
    for old,(role,row) in legacy_rows.items():
        possible = index[observation_key(row,role)]
        # Source observation timestamps are unique for the current old-system
        # exports; paper batch timestamps are not unique and stay pending.
        if len(possible)==1 and possible[0]["source_kind"] in {"system","qualtrics"}:
            current = possible[0]
            demo = "student_demographics_" if role=="student" else "adult_demographics_"
            born=timestamp(row.get(demo+("06" if role=="student" else "03")))
            old_record={"role":role,"answer":row,"school":text(row.get("school_from_"+role)),
                        "dob":born.date().isoformat() if born else "", "gender":text(row.get(demo+("03" if role=="student" else "04"))),
                        "grade":current.get("grade"), "observed_at":current.get("observed_at")}
            if identity_evidence(current)==identity_evidence(old_record):
                resolved[old]=current
    active = {d["payload"]["target_key"] for d in active_decisions(db)}
    report=[]
    for job in jobs:
        a,b = resolved.get(job["legacy_a"]),resolved.get(job["legacy_b"])
        row={**job,"submission_a":a["submission_id"] if a else "","submission_b":b["submission_id"] if b else ""}
        if not a or not b:
            row["migration_status"]="pending_unresolved_observation"
        else:
            if a["submission_id"]==b["submission_id"]:
                raise PipelineError("Legacy correction endpoints resolve to the same submission")
            a,b=sorted([a,b],key=lambda r:r["submission_id"])
            target="pair:"+digest([a["submission_id"],b["submission_id"]])
            if target in active:
                row["migration_status"]="existing_decision_preserved"
            else:
                p={"action":"LINK","record_a":a["submission_id"],"record_b":b["submission_id"],
                   "version_a":a["version_id"],"version_b":b["version_id"],"target_key":target,
                   "evidence_a":identity_evidence(a),"evidence_b":identity_evidence(b),"legacy_provenance":job}
                reason="Existing legacy correction; original workbook records neither reviewer nor reason. Source: "+job["file"]+f" / {job['sheet']} / row {job['row']}"
                db.execute("INSERT OR IGNORE INTO decisions VALUES(?,?,?,?,?,?)",("DEC_"+digest(p)[:28],utcnow(),"legacy_unattributed",reason,dumps(p),None))
                active.add(target)
                row["migration_status"]="migrated_unique_source_observation"
        report.append(row)
    db.commit()
    return report
