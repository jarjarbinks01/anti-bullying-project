from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from collections import Counter
from pathlib import Path

import pandas as pd

from . import __version__
from .adapters import check_manifest, input_records, modules, normalize_records, source_root
from .common import PipelineError, atomic_json, digest, dumps, file_hash, secure_directory, utcnow
from .matching import assign_children, link_records, select_waves
from .outputs import write_excel, write_outputs
from .review import active_decisions, apply_field_decisions, validation_report
from .store import backup, backup_path, connect, current, ingest, writer_lock
from .storage import read_records, store_record
from .artifacts import artifact_cache, freeze_file, logical_hash


def program_hash() -> str:
    return digest({p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob("*.py"))})


def fingerprint(cfg, manifest, db):
    from .legacy import legacy_files
    from .dyads import administrative_fingerprint
    inputs = sorted(manifest["sources"], key=lambda r: r["source_id"])
    return digest({"inputs": inputs, "code": program_hash(), "mappings": cfg["mapping_hashes"],
                   "dictionary": file_hash(Path(cfg["state_dir"]) / "school_dictionary.xlsx"),
                   "decisions": [d["payload"] for d in active_decisions(db)],
                   "labels": [dict(r) for r in db.execute("SELECT * FROM labels ORDER BY case_id")],
                   "rules": [cfg["duplicate_days"], cfg["minimum_followup_days"], cfg.get("matching_policy", {}), cfg.get("bd_requires_same_adult", False), cfg.get("date_policy"), cfg.get("parent_wave_policy")],
                   "source_folder": cfg.get("source_folder", "1.1_raw_file"), "source_registry": cfg["sources"],
                   "legacy_sources": {str(p.relative_to(cfg["project_root"])):file_hash(p) for p in legacy_files(cfg)},
                   "permanent_registration": administrative_fingerprint(db)})


def baseline_comparison(cfg, summary):
    if cfg.get("source_scope") in {"qualtrics_only", "merged_abcd"}:
        return []
    root = Path(cfg["project_root"])
    reconstruction = root / "3.1.1_ABCD_reconstruction/step_3.1.1_stats.json"
    pairing = root / "3.1.3_manual_pairing/step_3.1.3_stats.json"
    old = {}
    if reconstruction.exists():
        v = json.loads(reconstruction.read_text())
        old.update(A=v["student"]["n_final_T0_rows"], C=v["student"]["n_final_T1_rows"],
                   B=v["parent"]["n_final_T0_rows"], D=v["parent"]["n_final_T1_rows"],
                   AC=v["student"]["n_matched_wide_rows"], BD=v["parent"]["n_matched_wide_rows"])
    if pairing.exists():
        v = json.loads(pairing.read_text())
        old.update(E=v["E"]["n_paired"], F=v["F"]["n_paired"], EF=v["EF"]["n_EF_paired"])
    return [{"dataset": k, "legacy_n": n, "prototype_n": summary[k], "difference": summary[k] - n,
             "source_scope": cfg.get("source_scope", "registered_sources"),
             "interpretation": "Legacy outputs include other sources; this release uses only its registered sources. Counts are not a like-for-like test of pairing accuracy. See submission audit for decisions."} for k, n in old.items()]


def run(cfg: dict, manifest: dict, publish=True, force=False) -> dict:
    state = Path(cfg["state_dir"])
    with writer_lock(state):
        db = connect(state)
        recover_pointer(db, cfg)
        from . import dyads
        from .dyad_operator import backup_tracking, recovery_check
        recovery_check(db, cfg)
        dyads.migrate(db)
        run_id = "RUN_" + uuid.uuid4().hex
        start_code_hash = program_hash()
        folder = Path(cfg["release_dir"]) / run_id
        try:
            check_manifest(cfg, manifest)
            fp = fingerprint(cfg, manifest, db)
            release = current(db)
            if release and not force:
                old = db.execute("SELECT fingerprint FROM runs WHERE run_id=?", (release["run_id"],)).fetchone()
                if old[0] == fp:
                    return {"unchanged": True, "release_id": release["release_id"], **json.loads(release["stats_json"])}
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (run_id, fp, utcnow(), "running", dumps(manifest), None, None))
            db.commit()
            records = input_records(cfg, manifest, db)
            db.commit()
            check_source_conservation(db, records)
            for record in records:
                record["ingest_status"] = record["status"]
            dictionary_path = state / "school_dictionary.xlsx"
            dictionary = pd.read_excel(dictionary_path)
            decisions = [d for d in active_decisions(db) if not d["payload"]["target_key"].startswith("school:")]
            records = apply_field_decisions(records, decisions)
            records, school_queue = normalize_records(records, dictionary)
            school_stage_eligible = sum(r["status"] == "eligible" for r in records)
            from .merged import mark_exact_input_repeats
            records, input_repeat_cases = mark_exact_input_repeats(records)
            from .legacy import migrate_legacy
            migration = migrate_legacy(db, cfg, records)
            decisions = [d for d in active_decisions(db) if not d["payload"]["target_key"].startswith("school:")]
            fp = fingerprint(cfg, manifest, db)
            with db:
                db.execute("UPDATE runs SET fingerprint=? WHERE run_id=?", (fp,run_id))
            groups, cases, events = link_records(records, decisions, cfg.get("matching_policy", {}))
            cases += input_repeat_cases
            with db:
                ingest(db, run_id, records)
                children = assign_children(db, run_id, groups)
                from .parent_panel import build_parent_panel
                parent_panel = build_parent_panel(records, children, decisions,
                    matching_policy=cfg.get("matching_policy", {}),
                    duplicate_days=cfg["duplicate_days"], followup_days=cfg["minimum_followup_days"])
                records, time_cases = select_waves(records, children, cfg["duplicate_days"], cfg["minimum_followup_days"], cfg.get("bd_requires_same_adult", False), cfg.get("matching_policy", {}), adult_decisions=decisions, parent_wave_policy=cfg.get("parent_wave_policy"))
                check_unexpected_backfill(db, records)
                cases += time_cases
                adult_pairs = None
                if cfg.get("bd_requires_same_adult"):
                    from .respondents import adult_followups
                    adult_pairs, adult_cases, adult_events = adult_followups(records, decisions, cfg["minimum_followup_days"], cfg.get("matching_policy", {}), parent_wave_policy=cfg.get("parent_wave_policy"))
                    cases += adult_cases
                    events += adult_events
                from collections import defaultdict
                rules_by_id = defaultdict(set)
                for case in cases:
                    if case["status"] == "confirmed" and case["kind"] in {"identity", "family"}:
                        for sid in [case["record_a"], case["record_b"]]:
                            if sid:
                                rules_by_id[sid].add(case["rule"])
                    if case["status"] == "confirmed" and case["kind"] == "identity_group":
                        for sid in case["component_evidence"]["members"]:
                            rules_by_id[sid].add(case["rule"])
                for r in records:
                    r["identity_rules"] = sorted(rules_by_id[r["submission_id"]])
                    store_record(db, run_id, r["submission_id"], {k: v for k, v in r.items() if k != "contacts"})
                for event in events:
                    db.execute("INSERT INTO decision_events VALUES(?,?,?,?)", (run_id, event["decision_id"], event["status"], event["message"]))
            labels = validation_report(db, cases, records)
            validation_report(db, parent_panel.guard_cases, records)
            panel_labels = {r["case_id"]: dict(r) for r in db.execute("SELECT * FROM labels")}
            dyad_rows = dyads.stage(db, run_id, records, cases, cfg)
            # Persist reservations before output/publication so a retry reuses IDs.
            backup_tracking(db, cfg, "staged_" + run_id)
            fp = fingerprint(cfg, manifest, db)
            with db:
                db.execute("UPDATE runs SET fingerprint=? WHERE run_id=?", (fp, run_id))
            secure_directory(folder)
            online, _, _ = modules(cfg)
            print("Writing versioned outputs and audit tables", flush=True)
            with artifact_cache(state/'artifact_objects',folder):
                summary = write_outputs(folder, records, cases, school_queue, {"student": online.STUDENT_COLUMNS, "parent": online.PARENT_COLUMNS}, adult_pairs, dyad_rows,
                                        independent_parent_panel=parent_panel, panel_labels=panel_labels)
            summary["permanent_registration"] = dyads.validate_staging(db, run_id, records, cases, cfg)
            summary["manual_decisions_reopened"] = sum(e["status"] == "reopened" for e in events)
            summary["legacy_corrections_pending"] = sum(r["migration_status"].startswith("pending") for r in migration)
            summary["legacy_corrections_scope"] = "not_applied" if cfg.get("source_scope") in {"qualtrics_only", "merged_abcd"} else "migration_attempted"
            write_excel(folder / "legacy_correction_migration.xlsx", {"migration": migration})
            summary["identity_pending_submissions"] = sum(bool(r.get("identity_pending")) for r in records)
            summary["chronology_pending_submissions"] = sum(r.get("wave_reason") == "pending_chronology" for r in records)
            summary["analysis_rows_unverified_dates"] = sum(bool(r["selected_wave"]) and r["time_confidence"] not in {"observed", "manual_verified"} for r in records)
            summary["accepted_creation_time_submissions"] = sum(r["time_confidence"] == "accepted_creation_time" for r in records)
            summary["batch_creation_time_submissions"] = sum(r.get("date_basis") == "batch_assigned_creation" for r in records)
            summary["matching_policy"] = cfg.get("matching_policy", {})
            summary["date_policy"] = cfg.get("date_policy", "observed_dates_only")
            summary["parent_wave_policy"] = cfg.get("parent_wave_policy")
            summary["bd_requires_same_adult"] = cfg.get("bd_requires_same_adult", False)
            summary["t0_inferred_from_T1"] = sum(r["selected_wave"] == "T0" and r["claimed_wave"] == "T1" for r in records)
            summary["validation_cases_labelled"] = sum(r["reviewed"] for r in labels)
            summary["research_validation"] = "reviewed_sample" if labels else "not_yet_reviewed"
            summary["program_version"] = __version__
            summary["source_exported_at"] = manifest.get("exported_at")
            summary["source_scope"] = cfg.get("source_scope", "registered_sources")
            summary["source_submission_counts"] = dict(sorted(Counter(r["source_id"] for r in records).items()))
            summary["export_time_provenance"] = manifest.get("export_time_provenance", "unknown")
            summary["program_hash"] = program_hash()
            if summary["program_hash"] != start_code_hash:
                raise PipelineError("Program changed during run; rerun a consistent code version")
            summary["release_id"] = run_id
            summary["stage_counts"] = {
                "1.1": len(records), "1.3/2.1.1/2.1.2": len(records),
                "2.1.3": school_stage_eligible,
                "2.1.4": {"eligible_submissions": len(children), "child_groups": len(set(children.values()))},
                "2.1.5": sum(r["status"] in {"eligible", "short_interval_followup", "extra_followup"} for r in records),
                "2.1.6": sum(r["status"] not in {"manual_excluded", "excluded_school", "short_repeat", "exact_input_repeat", "sparse_response", "incomplete", "unrecognized_survey"} for r in records),
                "3.1.1": {k: summary[k] for k in "ABCD"}, "3.1.2/3.1.3": {k: summary[k] for k in ["E", "F", "EF"]}}
            write_excel(folder / "comparison.xlsx", {"legacy_comparison": baseline_comparison(cfg, summary), "validation": pd.DataFrame(labels)})
            atomic_json(folder / "summary.json", summary)
            atomic_json(folder / "run_manifest.json", {"inputs": manifest, "fingerprint": fp,
                "program_hash": summary["program_hash"], "mapping_hashes": cfg["mapping_hashes"],
                "dictionary_hash": file_hash(dictionary_path), "decision_ids": [d["decision_id"] for d in decisions]})
            reproducible = folder / "reproduce"
            secure_directory(reproducible)
            freeze_file(dictionary_path,reproducible/'school_dictionary.xlsx',state/'artifact_objects')
            atomic_json(reproducible / "config.json", cfg)
            for source_directory,target_directory in [(Path(cfg['mapping_dir']),reproducible/'mappings'),(Path(__file__).parent,reproducible/'study2')]:
                for p in source_directory.rglob('*'):
                    if p.is_file() and '__pycache__' not in p.parts and not p.is_symlink():
                        freeze_file(p,target_directory/p.relative_to(source_directory),state/'artifact_objects')
            freeze_file(Path(__file__).parent.parent/'dashboard.py',reproducible/'dashboard.py',state/'artifact_objects')
            from .legacy import legacy_files
            for source_path in legacy_files(cfg):
                target=reproducible/"legacy"/source_path.relative_to(cfg["project_root"])
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source_path,target)
            import importlib.metadata
            atomic_json(reproducible / "environment.json", {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()})
            source_folder = reproducible / "sources"
            secure_directory(source_folder)
            for source in manifest["sources"]:
                name = source["file"]
                if not (source_folder / name).exists():
                    freeze_file(source_root(cfg)/name,source_folder/name,state/'artifact_objects')
            # Verify every source is unchanged after reading, before publication.
            check_manifest(cfg, manifest)
            if fingerprint(cfg,manifest,db)!=fp:
                raise PipelineError("Inputs, dictionary, source registry or decisions changed during run")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise PipelineError("Database integrity check failed")
            if sum(summary["status_counts"].values()) != len(records):
                raise PipelineError("Submission accounting does not reconcile")
            files = {str(p.relative_to(folder)): file_hash(p) for p in sorted(folder.rglob("*")) if p.is_file()}
            atomic_json(folder / "checksums.json", files)
            with db:
                db.execute("UPDATE runs SET status='validated',stats_json=? WHERE run_id=?", (dumps(summary), run_id))
                db.execute("INSERT INTO releases VALUES(?,?,?,?,?)", (run_id, run_id, utcnow(), str(folder), dumps(summary)))
                db.executemany("INSERT INTO release_candidates VALUES(?,?,?)", [(run_id, c["case_id"], dumps(c)) for c in cases])
            backup(db, folder / "backup.sqlite")
            # The verified backup must restore the release it accompanies.
            snapshot = sqlite3.connect(folder / "backup.sqlite")
            with snapshot:
                snapshot.execute("INSERT OR REPLACE INTO publication VALUES(1,?)", (run_id,))
                snapshot.execute("UPDATE runs SET status='published' WHERE run_id=?", (run_id,))
                snapshot.execute("UPDATE dyad_registry SET lifecycle=(SELECT state FROM dyad_memberships WHERE run_id=? AND dyad_id=dyad_registry.dyad_id) WHERE lifecycle!='retired' AND dyad_id IN (SELECT dyad_id FROM dyad_memberships WHERE run_id=?)", (run_id, run_id))
                snapshot.execute('UPDATE dyad_registry SET first_published_run_id=? WHERE first_published_run_id IS NULL AND dyad_id IN (SELECT dyad_id FROM dyad_memberships WHERE run_id=?)', (run_id,run_id))
            snapshot.close()
            atomic_json(folder / "backup.sha256.json", {"backup.sqlite": file_hash(folder / "backup.sqlite")})
            from .publication_baseline import ensure_baseline
            ensure_baseline(folder,run_id)
            if publish:
                publish_release(db, cfg, run_id)
            print(f"{'Published' if publish else 'Validated'} {run_id}", flush=True)
            return summary
        except Exception as error:
            db.rollback()
            if db.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
                with db:
                    db.execute("UPDATE runs SET status='failed',error=? WHERE run_id=?", (str(error), run_id))
            atomic_json(state / "last_failure.json", {"failed_at": utcnow(), "run_id": run_id, "error": str(error)})
            raise
        finally:
            db.close()


def verify_release(db, release_id):
    row = db.execute("SELECT r.*,n.status FROM releases r JOIN runs n ON r.run_id=n.run_id WHERE release_id=?", (release_id,)).fetchone()
    if not row or row["status"] not in {"validated", "published"}:
        raise PipelineError("Release does not exist or failed validation")
    result = dict(row)
    locations = Path(db.execute('PRAGMA database_list').fetchone()[2]).parent/'release_locations.json'
    if locations.exists():
        result['path'] = json.loads(locations.read_text()).get(release_id,result['path'])
    path = Path(result["path"])
    hashes = json.loads((path / "checksums.json").read_text())
    for name, expected in hashes.items():
        if logical_hash(path/name) != expected:
            raise PipelineError("Published file checksum mismatch")
    descriptive = json.loads(row['stats_json']).get('descriptive')
    if descriptive:
        from .descriptive_reports import verify_reports
        verify_reports(path, descriptive)
    expected_backup = json.loads((path / "backup.sha256.json").read_text())["backup.sqlite"]
    if not (path/'backup.sqlite').exists() and not (path/'backup.sqlite.gz').exists():
        if not (path/'backup.retention.json').exists():
            raise PipelineError('Full recovery backup is unavailable without a retention record')
        return result
    with backup_path(path / 'backup.sqlite', expected_backup) as restored:
        snapshot = sqlite3.connect(restored.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise PipelineError("Release backup failed integrity check")
        finally:
            snapshot.close()
    return result


def check_unexpected_backfill(db, records):
    """Collector contract: newly arriving observations cannot precede T0."""
    release = current(db)
    if not release:
        return
    prior = list(read_records(db, release['run_id'], include_raw=False))
    seen = {r["submission_id"] for r in prior}
    baselines = {(r.get("child_id"), r["role"]): r for r in prior if r.get("selected_wave") == "T0"}
    from .common import timestamp
    for r in records:
        if r.get("selected_wave") != "T0" or r["submission_id"] in seen or r.get("manual_keep"):
            continue
        previous = baselines.get((r.get("child_id"), r["role"]))
        old_date = timestamp(previous.get("observed_at")) if previous else None
        new_date = timestamp(r.get("observed_at"))
        if old_date and new_date and new_date < old_date:
            raise PipelineError("Unexpected earlier new submission contradicts collection contract; publication requires explicit review")


def check_source_conservation(db, records):
    release = current(db)
    if not release:
        return
    present = {r["submission_id"] for r in records}
    excluded = {d["payload"]["record_a"] for d in active_decisions(db) if d["payload"]["action"] == "EXCLUDE"}
    previous = db.execute("SELECT submission_id FROM run_records WHERE run_id=?", (release["run_id"],)).fetchall()
    missing = {r[0] for r in previous} - present - excluded
    if missing:
        raise PipelineError(f"Full source snapshot lost {len(missing)} registered submissions; possible identity-key change or incomplete export. Review before publication")


def publish_release(db, cfg, release_id, rollback=False):
    row = verify_release(db, release_id)
    # Newly collected NONMATCH labels must also guard publication of older releases.
    cases = [json.loads(r[0]) for r in db.execute("SELECT payload_json FROM release_candidates WHERE release_id=?", (release_id,))]
    validation_report(db, cases)
    panel_guard = Path(row['path']) / 'independent_parent_guard.jsonl.gz'
    if panel_guard.exists():
        import gzip
        with gzip.open(panel_guard, 'rt', encoding='utf-8') as handle:
            validation_report(db, [json.loads(line) for line in handle])
    from .review_core import backup_workspace
    review_backup = backup_workspace(cfg, "publish_" + release_id)
    from .dyad_operator import backup_tracking, recovery_check
    from .dyads import publish_memberships
    recovery_check(db, cfg)
    if json.loads(row['stats_json']).get('permanent_registration') and not rollback:
        from . import dyads
        records = dyads.scientific_records(db, row['run_id'])
        dyads.validate_staging(db, row['run_id'], records, cases, cfg)
        manifest = json.loads((Path(row['path']) / 'run_manifest.json').read_text())
        if fingerprint(cfg, manifest['inputs'], db) != manifest['fingerprint']:
            raise PipelineError('Source, rules or permanent registration changed after validation; rerun before publication')
    tracking_backup = backup_tracking(db, cfg, "before_publish_" + release_id)
    pointer = Path(cfg["release_dir"]) / "CURRENT.json"
    previous = json.loads(pointer.read_text()) if pointer.exists() else None
    try:
        with db:
            db.execute("INSERT OR REPLACE INTO publication VALUES(1,?)", (release_id,))
            db.execute("UPDATE runs SET status='published' WHERE run_id=?", (row["run_id"],))
            if not rollback:
                publish_memberships(db, row["run_id"])
            tracking_after = backup_tracking(db, cfg, "after_publish_" + release_id, promote=False)
            atomic_json(pointer, {"release_id": release_id, "path": row["path"], "published_at": utcnow()})
    except Exception:
        if previous is not None:
            atomic_json(pointer, previous)
        else:
            pointer.unlink(missing_ok=True)
        raise
    failure = Path(cfg["state_dir"]) / "last_failure.json"
    failure.unlink(missing_ok=True)
    tracking_manifest = json.loads((Path(tracking_after) / 'manifest.json').read_text())
    # The complete backup was verified before switching the release. Updating
    # the derived recovery hint after commit must not mark a valid release failed.
    recovery_hint_warning = None
    try:
        atomic_json(Path(cfg['state_dir']) / 'DYAD_LEDGER.json',
                    {'bundle': tracking_after, 'hash': tracking_manifest['tracking_hash']})
    except OSError:
        recovery_hint_warning = 'Tracking backup is complete; recovery hint needs repair using tracking_after_backup'
    return {"release_id": release_id, "path": row["path"], "review_workspace_backup": review_backup,
            "tracking_before_backup": tracking_backup, "tracking_after_backup": tracking_after,
            "recovery_hint_warning": recovery_hint_warning}


def recover_pointer(db, cfg):
    """SQLite is authoritative. Repair the derived file after a process crash."""
    release = current(db)
    pointer = Path(cfg["release_dir"]) / "CURRENT.json"
    try:
        value = json.loads(pointer.read_text()) if pointer.exists() else None
    except (OSError, ValueError):
        value = None
    if release and (not value or value.get("release_id") != release["release_id"]):
        atomic_json(pointer, {"release_id": release["release_id"], "path": release["path"], "recovered_at": utcnow()})
    elif not release and pointer.exists():
        pointer.unlink()


from .checkpoints import protect_mutation
run=protect_mutation(run)
