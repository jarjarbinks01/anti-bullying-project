from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from .adapters import discover, make_manifest, mapping_module, modules
from .common import PipelineError, atomic_json, dumps, file_hash, load_config, secure_directory, utcnow
from .store import backup_path, connect, current, writer_lock

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PACKAGE_ROOT / "config.local.json"
STEPS = ["1.1", "1.3", "2.1.1", "2.1.2", "2.1.3", "2.1.4", "2.1.5", "2.1.6", "3.1.1", "3.1.2", "3.1.3"]


def initialize(project: Path, config_path: Path, state: Path | None = None, source_scope="qualtrics_only"):
    if config_path.exists():
        raise PipelineError("Config already exists; do not overwrite an initialized source registry")
    state = state or Path.home() / ("Library/Application Support/HKU-Study2-Merged-Prototype" if source_scope == "merged_abcd" else "Library/Application Support/HKU-Study2-Qualtrics-Prototype")
    if (state / "study2.sqlite").exists():
        raise PipelineError("State directory already contains a database; choose another --state")
    source_scripts = project / "scripts"
    frozen = PACKAGE_ROOT / "mappings"
    frozen.mkdir(exist_ok=True)
    names = ["2.1.1_produce_ABCD.py", "1.3.1_standardise_paperform_data.py", "1.3.2_standardise_separate_school_data.py"]
    for name in names:
        shutil.copy2(source_scripts / name, frozen / name)
    cfg = {"config_version": 1, "project_root": str(project.resolve()), "state_dir": str(state.resolve()),
           "checkpoint_policy": {"latest_complete_only": True},
           "release_dir": str(PACKAGE_ROOT / "releases"), "inbox_dir": str(PACKAGE_ROOT / "inbox"),
           "mapping_dir": str(frozen), "mapping_hashes": {n: file_hash(frozen / n) for n in names},
           "duplicate_days": 30, "minimum_followup_days": 90, "stale_after_days": 8,
           "source_scope": "qualtrics_only",
           "sources": []}
    if source_scope == "merged_abcd":
        cfg.update(config_version=2, source_scope=source_scope,
                   source_folder="2.1.2_T0T1-student-parent(A,B,C,D)_merged_paperform",
                   release_dir=str(PACKAGE_ROOT / "releases/merged"), inbox_dir=str(PACKAGE_ROOT / "inbox/merged"),
                   date_policy="current_creation_time_user_accepted_20261006",
                   matching_policy={"allow_one_digit_phone": True, "allow_school_transfer": True,
                                    "allow_contact_bridge_components": True,
                                    "allow_contact_subgroups": True,
                                    "adult_contact_scope": "any_exact"},
                   parent_wave_policy="student_anchored_hk_nearest_v2",
                   bd_requires_same_adult=True)
    for role in ["student", "parent"]:
        for wave in ["T0", "T1"]:
            time = {("student", "T0"): "19.08", ("student", "T1"): "19.09",
                    ("parent", "T0"): "19.09", ("parent", "T1"): "19.10"}[(role, wave)]
            if source_scope == "merged_abcd":
                letter = {("student", "T0"): "A", ("parent", "T0"): "B", ("student", "T1"): "C", ("parent", "T1"): "D"}[(role, wave)]
                cfg["sources"].append({"source_id": f"merged_{role}_{wave}", "kind": "merged", "role": role,
                                       "wave": wave, "pattern": f"{letter}_{wave}-{role}_merged.xlsx"})
                continue
            cfg["sources"].append({"source_id": f"qualtrics_{role}_{wave}", "survey_namespace": f"study2_{role}_{wave}",
                                   "kind": "qualtrics", "role": role, "wave": wave,
                                   "pattern": f"Study 2 {role.title()} Survey {wave}_September 20, 2026_{time}.csv"})
    online, _, _ = modules(cfg)
    from .adapters import read_source, source_root
    for entry in discover(cfg):
        frame = read_source(source_root(cfg) / entry["file"], entry, online)
        next(s for s in cfg["sources"] if s["source_id"] == entry["source_id"])["columns"] = list(map(str, frame.columns))
    secure_directory(state)
    dictionary = project / "2.1.3_T0T1-student-parent(A,B,C,D)_cleaned_schoolname/school_dictionary.xlsx"
    shutil.copy2(dictionary, state / "school_dictionary.xlsx")
    (state / "school_dictionary.xlsx").chmod(0o600)
    secure_directory(Path(cfg["inbox_dir"]))
    secure_directory(Path(cfg["release_dir"]))
    atomic_json(config_path, cfg)
    connect(state).close()
    return {"config": str(config_path), "state": str(state), "registered_sources": len(cfg["sources"])}


def watch_once(cfg):
    from .runner import run
    inbox = Path(cfg["inbox_dir"])
    secure_directory(inbox / "processed")
    secure_directory(inbox / "failed")
    reports = []
    for path in sorted(inbox.glob("*.ready.json")):
        try:
            manifest = json.loads(path.read_text())
            result = run(cfg, manifest)
            path.replace(inbox / "processed" / path.name)
            reports.append({"batch": path.name, "release_id": result["release_id"]})
        except Exception as error:
            # Ready-file parsing/reading can fail before the runner starts.
            # Publish the failure status even in that case, so the dashboard
            # cannot imply that a failed collector handoff was processed.
            atomic_json(Path(cfg["state_dir"]) / "last_failure.json",
                        {"failed_at": utcnow(), "batch": path.name, "error": str(error)})
            atomic_json(inbox / "failed" / (path.name + ".error.json"), {"error": str(error), "at": utcnow()})
            path.replace(inbox / "failed" / path.name)
            reports.append({"batch": path.name, "error": str(error)})
    return reports


def schedule(config_path: Path, install: bool):
    if sys.platform != "darwin":
        raise PipelineError("Prototype scheduler supports macOS; use cron/Task Scheduler with watch on other systems")
    cfg = load_config(config_path)
    state = Path(cfg["state_dir"])
    launch_agents = Path.home() / "Library/LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)
    path = launch_agents / "org.hku.study2.prototype.plist"
    payload = {"Label": "org.hku.study2.prototype", "ProgramArguments": [sys.executable, "-m", "study2", "--config", str(config_path.resolve()), "watch"],
               "StartInterval": 900, "RunAtLoad": True, "WorkingDirectory": str(PACKAGE_ROOT),
               "EnvironmentVariables": {"PYTHONPYCACHEPREFIX": str(Path(sys.prefix).resolve().parent / "pycache")},
               "StandardOutPath": str(state / "scheduler.stdout.log"), "StandardErrorPath": str(state / "scheduler.stderr.log")}
    path.write_bytes(plistlib.dumps(payload))
    if install:
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", domain, str(path)], capture_output=True)
        result = subprocess.run(["launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True)
        if result.returncode:
            raise PipelineError("launchd did not accept schedule: " + result.stderr.strip())
    return {"schedule": str(path), "interval_seconds": 900, "installed": install}


def main():
    parser = argparse.ArgumentParser(description="Study 2 auditable local prototype")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--project", required=True, type=Path)
    init.add_argument("--state", type=Path)
    init.add_argument("--source-scope", choices=["qualtrics_only", "merged_abcd"], default="qualtrics_only")
    manifest = sub.add_parser("manifest")
    manifest.add_argument("--output", type=Path)
    manifest.add_argument("--exported-at")
    runp = sub.add_parser("run")
    runp.add_argument("--manifest", required=True, type=Path)
    runp.add_argument("--no-publish", action="store_true")
    runp.add_argument("--force", action="store_true")
    validate = sub.add_parser("validate")
    validate.add_argument("--step", choices=STEPS)
    validate.add_argument("--manifest", type=Path)
    export = sub.add_parser("review-export")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--limit", type=int, default=500)
    imp = sub.add_parser("review-import")
    imp.add_argument("workbook", type=Path)
    cards = sub.add_parser("review-cards", help="匯出逐宗審核卡")
    cards.add_argument("--reviewer", required=True)
    cards.add_argument("--output", type=Path, required=True)
    cards.add_argument("--limit", type=int, default=20)
    cards.add_argument("--kind", choices=["identity", "family", "respondent"], action="append")
    cards.add_argument("--case-id", action="append")
    cards.add_argument("--independent", action="store_true")
    cards.add_argument("--replaces", help="只重新指派尚未交回答案的工作包")
    cards.add_argument('--purpose', choices=['review', 'validation', 'adjudication'], default='review',
                       help='review：一般待審；validation：另行品質抽查；adjudication：Jarvis 成人裁定')
    evidence = sub.add_parser('review-evidence-add',help='Jarvis 登記可核實來源及具體問題，不寫入配對裁定')
    evidence.add_argument('--case-id',required=True)
    evidence.add_argument('--source',choices=['原始紙本','既有收集紀錄','其他已核實來源'],required=True)
    evidence.add_argument('--reference',required=True)
    evidence.add_argument('--question',required=True)
    waiting = sub.add_parser('review-waiting-export',help='唯讀匯出證據不足的固定版本 SQLite 資料集')
    waiting.add_argument('--output',required=True,type=Path)
    receive = sub.add_parser("review-receive", help="保存答案，不改正式配對")
    receive.add_argument("workbook", type=Path)
    preview = sub.add_parser("review-preview")
    preview.add_argument("--package", action="append")
    preview.add_argument("--output", type=Path)
    approve = sub.add_parser("review-approve")
    approve.add_argument("batch_id")
    approve.add_argument("--reason", required=True)
    apply = sub.add_parser("review-apply")
    apply.add_argument("batch_id")
    resolve = sub.add_parser("review-resolve")
    resolve.add_argument("batch_id")
    resolve.add_argument("--case-id", required=True)
    resolve.add_argument("--review-id", required=True)
    resolve.add_argument("--reason", required=True)
    resolve.add_argument("--output", type=Path)
    resolve.add_argument('--group-partition', type=Path, help='Jarvis 裁定的完整提交分組 JSON')
    reopen = sub.add_parser("review-reopen")
    reopen.add_argument("task_id", nargs="+")
    reopen.add_argument("--reason", required=True)
    sub.add_parser("review-report")
    sub.add_parser('review-queue', help='查閱已過濾的一般身份審核工作量')
    sub.add_parser("review-console", help="中文執行者操作選單")
    sub.add_parser("dyad-console", help="永久親子追蹤中心，不發送訊息")
    dyad_preview = sub.add_parser("dyad-preview", help="唯讀預覽登記及衝突")
    dyad_preview.add_argument("--output", type=Path)
    sub.add_parser("dyad-report")
    invite_export = sub.add_parser("dyad-invitations")
    invite_export.add_argument("--output", type=Path, required=True)
    for name in ("dyad-record-invitation", "dyad-adjudicate"):
        p = sub.add_parser(name)
        p.add_argument("request", type=Path)
    sub.add_parser("dyad-backup")
    dyad_restore = sub.add_parser("dyad-restore")
    dyad_restore.add_argument("bundle", type=Path)
    dyad_restore.add_argument("--main-backup", required=True, type=Path)
    dyad_restore.add_argument("--destination", required=True, type=Path)
    for name in ["publish", "rollback"]:
        p = sub.add_parser(name)
        p.add_argument("release_id")
    restore = sub.add_parser("restore")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--destination", required=True, type=Path)
    sub.add_parser("status")
    sub.add_parser("watch")
    sub.add_parser('storage-report')
    migrate=sub.add_parser('storage-migrate')
    migrate.add_argument('--destination',required=True,type=Path)
    gc=sub.add_parser('storage-gc')
    gc.add_argument('--apply',action='store_true')
    sub.add_parser('checkpoint')
    checkpoint_restore=sub.add_parser('checkpoint-restore')
    checkpoint_restore.add_argument('checkpoint',type=Path)
    checkpoint_restore.add_argument('--destination',required=True,type=Path)
    sched = sub.add_parser("schedule")
    sched.add_argument("--install", action="store_true")
    sub.add_parser("dashboard")
    static = sub.add_parser('static-export', help='匯出可部署的唯讀彙總 HTML，不發布到網絡')
    static.add_argument('--output', type=Path, default=PACKAGE_ROOT / 'static_dashboard')
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize(args.project, args.config, args.state, args.source_scope)
        else:
            cfg = load_config(args.config)
            state = Path(cfg["state_dir"])
            if args.command == 'static-export':
                from .static_export import export_static
                result = export_static(cfg, args.output,
                    progress=lambda text: print('建立彙總：' + text, file=sys.stderr, flush=True))
            elif args.command == "manifest":
                result = make_manifest(cfg, args.exported_at)
                path = args.output or Path(cfg["inbox_dir"]) / "current.ready.json"
                atomic_json(path, result)
                result = {"manifest": str(path), "sources": len(result["sources"])}
            elif args.command=='storage-report':
                from .maintenance import storage_report
                result=storage_report(cfg)
            elif args.command=='storage-migrate':
                from .maintenance import migrate_copy
                result=migrate_copy(cfg,args.destination)
            elif args.command=='storage-gc':
                from .maintenance import storage_gc
                result=storage_gc(cfg,args.apply)
            elif args.command=='checkpoint':
                from .checkpoints import save_checkpoint
                result=save_checkpoint(cfg,'operator',force=True)
            elif args.command=='checkpoint-restore':
                from .checkpoints import restore_checkpoint
                result=restore_checkpoint(args.checkpoint,args.destination)
            elif args.command == "run":
                from .runner import run
                result = run(cfg, json.loads(args.manifest.read_text()), not args.no_publish, args.force)
            elif args.command == "watch":
                result = watch_once(cfg)
            elif args.command == "schedule":
                result = schedule(args.config, args.install)
            elif args.command.startswith("dyad-"):
                from . import dyad_operator as operator
                if args.command == "dyad-console":
                    result = operator.console(cfg)
                elif args.command == "dyad-preview":
                    result = operator.preview(cfg)
                    if args.output:
                        from .dyads import safe_tracking_rows
                        from .outputs import write_excel
                        write_excel(args.output, {"登記預覽": safe_tracking_rows(result['rows']),
                                    "待裁定": safe_tracking_rows([r for r in result['rows'] if r['registration_state'] not in {'active','new'}])}, tracking=True)
                        result = {k:v for k,v in result.items() if k != 'rows'} | {'output':str(args.output.resolve())}
                elif args.command == "dyad-report":
                    result = operator.report(cfg)
                elif args.command == "dyad-invitations":
                    result = operator.export_invitations(cfg, args.output)
                elif args.command == "dyad-adjudicate":
                    result = operator.adjudicate(cfg, json.loads(args.request.read_text()))
                elif args.command == "dyad-record-invitation":
                    result = operator.record_invitation(cfg, json.loads(args.request.read_text()))
                elif args.command == "dyad-restore":
                    result = operator.restore_bundle(args.bundle, args.main_backup, args.destination)
                elif args.command == "dyad-backup":
                    if cfg.get('checkpoint_policy',{}).get('latest_complete_only'):
                        from .checkpoints import save_checkpoint
                        result=save_checkpoint(cfg,'dyad_operator',force=True)
                    else:
                        with writer_lock(state):
                            db = connect(state)
                            try:
                                operator.recovery_check(db, cfg)
                                result = {'bundle':operator.backup_tracking(db, cfg, 'operator')}
                            finally:
                                db.close()
            elif args.command in {"review-cards", "review-receive", "review-preview", "review-approve", "review-apply", "review-resolve", "review-report", "review-queue", "review-reopen", "review-console", 'review-evidence-add', 'review-waiting-export'}:
                from . import review_core as core
                from . import review_operator as operator
                if args.command == "review-cards":
                    package = core.create_package(cfg, args.reviewer, args.output, args.limit, args.kind,
                                                  args.case_id, args.independent, args.replaces, purpose=args.purpose)
                    result = {"package_id": package["package_id"], "reviewer": package["reviewer"],
                              "cases": len(package["tasks"]), "output": str(args.output.resolve())}
                elif args.command == 'review-queue':
                    from .review_dispatch import queue_snapshot
                    result = queue_snapshot(cfg)
                elif args.command == 'review-evidence-add':
                    result = core.register_review_evidence(cfg,args.case_id,args.source,args.reference,args.question)
                elif args.command == 'review-waiting-export':
                    from .review_dispatch import export_waiting_dataset
                    result = export_waiting_dataset(cfg,args.output)
                elif args.command == "review-receive":
                    from .review_excel import import_package
                    result = import_package(cfg, args.workbook)
                elif args.command == "review-preview":
                    result = core.preview_batch(cfg, args.package)
                    if args.output:
                        operator.write_preview(result, args.output)
                elif args.command == "review-approve":
                    result = core.approve_batch(cfg, args.batch_id, reason=args.reason)
                elif args.command == "review-apply":
                    result = core.apply_batch(cfg, args.batch_id)
                elif args.command == "review-resolve":
                    partition = json.loads(args.group_partition.read_text()) if args.group_partition else None
                    result = operator.resolve(cfg, args.batch_id, args.case_id, args.review_id, args.reason, group_partition=partition)
                    if args.output:
                        operator.write_preview(result, args.output)
                elif args.command == "review-reopen":
                    result = core.reopen_tasks(cfg, args.task_id, args.reason)
                elif args.command == "review-console":
                    result = operator.console(cfg)
                else:
                    result = core.review_report(cfg)
            elif args.command == "dashboard":
                os.environ["STUDY2_CONFIG"] = str(args.config.resolve())
                app = PACKAGE_ROOT / "dashboard.py"
                raise SystemExit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(app), "--server.address", "127.0.0.1", "--server.port", "8501", "--server.showEmailPrompt", "false", "--browser.gatherUsageStats", "false"]))
            elif args.command == "restore":
                import sqlite3
                if args.destination.exists():
                    raise PipelineError("Restore destination must be new; never overwrite a live database")
                with backup_path(args.backup) as restored:
                    origin = sqlite3.connect(restored.resolve().as_uri() + '?mode=ro', uri=True)
                    try:
                        if origin.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise PipelineError("Backup is not valid")
                        target = sqlite3.connect(args.destination)
                        try:
                            origin.backup(target)
                        finally:
                            target.close()
                        args.destination.chmod(0o600)
                    finally:
                        origin.close()
                result = {"restored_copy": str(args.destination)}
            elif args.command == "validate" and args.manifest:
                from .adapters import check_manifest, input_records
                data = json.loads(args.manifest.read_text())
                check_manifest(cfg, data)
                result = {"valid_manifest": True, "step": args.step or "1.1"}
                if args.step in {"1.3", "2.1.1", "2.1.2"}:
                    result["adapter_records"] = len(input_records(cfg, data))
                elif args.step and args.step != "1.1":
                    raise PipelineError("For matching/corrections/output checks, run --no-publish then validate the version; manifest validation alone cannot confirm these stages")
            else:
                with writer_lock(state):
                    db = connect(state)
                    try:
                        from .runner import recover_pointer
                        recover_pointer(db, cfg)
                        if args.command == "status":
                            result = {"current": current(db), "submission_count": db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0],
                                      "latest_run": dict(db.execute("SELECT run_id,status,created_at,error FROM runs ORDER BY created_at DESC LIMIT 1").fetchone() or {}),
                                      "schedule_note": "Runs while this Mac is awake and logged in; no remote access in prototype"}
                        elif args.command in {"publish", "rollback", "validate"}:
                            from .runner import publish_release, verify_release
                            if args.command == "validate":
                                latest = current(db)
                                if not latest:
                                    raise PipelineError("No published release to check")
                                r = verify_release(db, latest["release_id"])
                                result = {"checks_passed": True, "release_id": latest["release_id"], "step": args.step or "all", "counts": json.loads(r["stats_json"])["stage_counts"]}
                            else:
                                result = publish_release(db, cfg, args.release_id, rollback=args.command == 'rollback')
                        elif args.command == "review-export":
                            from .review import export_review
                            result = export_review(db, cfg, args.output, args.limit)
                        elif args.command == "review-import":
                            from .review import import_review
                            result = import_review(db, cfg, args.workbook)
                    finally:
                        db.close()
                if args.command in {'publish','rollback','review-import'}:
                    from .checkpoints import checkpoint_committed_result
                    result=checkpoint_committed_result(cfg,result,args.command)
        print(dumps(result))
    except (PipelineError, ValueError, OSError) as error:
        print("Pipeline stopped: " + str(error), file=sys.stderr)
        raise SystemExit(1)
