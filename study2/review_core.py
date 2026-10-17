"""Shared review service. Reviewer submissions are isolated from published state.

Excel and future web adapters exchange simple verdicts, never pipeline commands.
Only apply_batch acquires the main pipeline writer lock.
"""
from __future__ import annotations

import json
import copy
import sqlite3
import uuid
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from .common import PipelineError, atomic_json, digest, dumps, secure_directory, text, utcnow, file_hash
from .matching import hard_conflict, identity_evidence, identity_evidence_matches, validate_manual_links
from .respondents import adult_evidence, adult_evidence_matches
from .review import active_decisions, commit_review_rows, release_records, validate_review_rows
from .store import backup, connect, current, writer_lock

VERDICTS = {"確認相同": "MATCH", "確認不同": "NONMATCH", "資料不足": "UNRESOLVED"}
EVIDENCE_SOURCES = ["問卷資料比較", "原始紙本", "既有收集紀錄", "其他已核實來源", "沒有足夠證據"]
VERIFICATION_SOURCES = {'原始紙本', '既有收集紀錄', '其他已核實來源'}
KINDS = {"identity": "孩子身份", "family": "親子孩子身份", "respondent": "同一成人身份"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS packages(id TEXT PRIMARY KEY, created_at TEXT, reviewer TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, package_id TEXT, case_id TEXT, reviewer TEXT,
 revision INTEGER, state TEXT, payload TEXT, FOREIGN KEY(package_id) REFERENCES packages(id));
CREATE INDEX IF NOT EXISTS tasks_case ON tasks(case_id,state);
CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY, task_id TEXT, revision INTEGER, submitted_at TEXT,
 payload TEXT, UNIQUE(task_id,revision), FOREIGN KEY(task_id) REFERENCES tasks(id));
CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, state TEXT, created_at TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at TEXT, kind TEXT, target TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS carries(task_id TEXT, release_id TEXT, at TEXT, payload TEXT,
 PRIMARY KEY(task_id,release_id));
CREATE TABLE IF NOT EXISTS followups(case_id TEXT PRIMARY KEY, task_id TEXT, state TEXT, payload TEXT);
"""


def workspace(cfg):
    state = Path(cfg["state_dir"])
    from .maintenance import recover_activation
    recover_activation(state)
    secure_directory(state)
    path = state / "review.sqlite"
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    from .review_storage import prepare_workspace
    prepare_workspace(db,SCHEMA)
    db.execute('CREATE TABLE IF NOT EXISTS review_evidence_leads('
               'lead_id TEXT PRIMARY KEY,case_id TEXT NOT NULL,signature TEXT NOT NULL,'
               'created_at TEXT NOT NULL,payload TEXT NOT NULL)')
    path.chmod(0o600)
    return db


def backup_workspace(cfg, reason="manual"):
    if not (Path(cfg["state_dir"]) / "review.sqlite").exists():
        return None
    folder = Path(cfg["state_dir"]) / "review_backups"
    secure_directory(folder)
    path = folder / ("review_" + reason.replace("/", "_") + "_" + uuid.uuid4().hex + ".sqlite")
    db = workspace(cfg)
    try:
        backup(db, path)
    finally:
        db.close()
    # Keep legacy logical paths, sharing only verified immutable snapshots.
    from .artifacts import publish_object, copy_object
    h, obj = publish_object(Path(cfg['state_dir']) / 'artifact_objects', path)
    copy_object(obj, path)
    atomic_json(path.with_suffix('.sha256.json'), {'snapshot_sha256': h})
    return str(path)


def event(db, kind, target, payload):
    db.execute("INSERT INTO events(at,kind,target,payload) VALUES(?,?,?,?)",
               (utcnow(), kind, target, dumps(payload)))


def rules_hash(cfg):
    hashes = {
        name: file_hash(Path(__file__).parent / name) for name in (
            'matching.py', 'respondents.py', 'review_core.py', 'review_hints.py', 'grades.py', 'common.py',
        )
    }
    compatibility = Path(cfg['state_dir']) / 'review_rule_compatibility.json'
    if compatibility.exists():
        proof = json.loads(compatibility.read_text())
        if (proof.get('format_version') == 1 and proof.get('verified') is True
                and proof.get('current_code') == hashes):
            hashes = proof['original_code']
    if cfg.get('parent_wave_policy'):
        hashes = {**hashes, 'parent_waves.py': file_hash(Path(__file__).parent/'parent_waves.py')}
    config = {k: cfg.get(k) for k in ("matching_policy", "date_policy", "duplicate_days",
                                    "minimum_followup_days", "bd_requires_same_adult")}
    if cfg.get('parent_wave_policy'):
        config['parent_wave_policy'] = cfg['parent_wave_policy']
    return digest({"review_rules": 1, "code": hashes,
                  "config": config})


def record_snapshot(record):
    # Only identity evidence and provenance are distributed, never survey answers.
    fields = {k: v for k, v in record.get("answer", {}).items()
              if k.startswith("contact_") or k in {"student_demographics_02", "adult_demographics_02",
              "adult_demographics_05", "adult_demographics_06", "adult_demographics_06.1", "建立時間"}}
    result = {k: record.get(k) for k in ("submission_id", "version_id", "role", "source_id", "source_label",
              "location", "school", "dob", "gender", "grade", "grade_raw", "child_id", "claimed_wave", "selected_wave",
              "observed_at", "time_confidence", "date_basis", "status", "wave_reason", "school_type")}
    result.update(answer=fields, child_evidence=identity_evidence(record), adult_evidence=adult_evidence(record))
    return result


class Context:
    """Read one published release and construct versioned review evidence.

    Scientific groups are built before any dispatch overlay. Registered
    evidence can make a group actionable, but never changes its membership.
    """

    def __init__(self, db, cfg):
        self.release = current(db)
        if not self.release:
            raise PipelineError("尚未有發布版本，不能派發身份審核")
        self.records = self._load_records(db)
        self.cases = {
            row[0]: json.loads(row[1]) for row in db.execute(
                "SELECT case_id,payload_json FROM release_candidates WHERE release_id=?",
                (self.release["release_id"],),
            )
        }
        self._index_related_records()
        self.decisions = active_decisions(db)
        self.rules = rules_hash(cfg)
        # A new canonical decision invalidates a preview before pipeline rerun.
        self.main_revision = digest({
            "decisions": [dict(decision) for decision in self.decisions],
            "labels": [dict(row) for row in db.execute("SELECT * FROM labels ORDER BY case_id")],
        })
        self._component_cache = {}
        from .review_groups import build_groups
        self.group_cases = build_groups(self.records, self.cases, self.decisions, cfg.get('matching_policy'))
        self.cases.update(self.group_cases)
        self._dispatch_baselines = {}
        self.review_evidence = {}
        self.expired_review_evidence = []
        self._load_review_evidence(Path(cfg['state_dir']) / 'review.sqlite')
        self._apply_dispatch_overlay()

    def _load_records(self, db):
        """Read identity fields and provenance, excluding survey-scale answers."""
        from .storage import read_records

        keys = {
            "submission_id", "version_id", "role", "answer", "source_id", "source_label", "location",
            "school", "dob", "gender", "grade", "grade_raw", "child_id", "claimed_wave", "selected_wave",
            "observed_at", "time_confidence", "date_basis", "status", "wave_reason", "school_type",
        }
        answer_keys = {
            'Survey', 'student_demographics_02', 'adult_demographics_02', 'adult_demographics_05',
            'adult_demographics_06', 'adult_demographics_06.1', '建立時間',
        }
        records = {}
        for record in read_records(db, self.release['run_id'], include_raw=False):
            record['school_type'] = record.get('school_type') or record['answer'].get('school_type')
            record['answer'] = {
                key: value for key, value in record['answer'].items()
                if key.startswith('contact_') or key in answer_keys
            }
            records[record['submission_id']] = {
                key: value for key, value in record.items() if key in keys
            }
        return records

    def _index_related_records(self):
        """Index raw comparisons before synthesized group cases are added."""
        self.by_sid, self.by_child = defaultdict(list), defaultdict(set)
        for case in self.cases.values():
            for sid in (case["record_a"], case["record_b"]):
                if sid:
                    self.by_sid[sid].append(case)
        for sid, record in self.records.items():
            if record.get("child_id"):
                self.by_child[record["child_id"]].add(sid)

    def _load_review_evidence(self, path):
        """Carry only the newest registered source whose complete evidence matches."""
        if not path.exists():
            return
        evidence_db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        try:
            exists = evidence_db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='review_evidence_leads'"
            ).fetchone()
            latest = {}
            if exists:
                for case_id, signature, payload in evidence_db.execute("""
                    SELECT case_id, signature, payload FROM review_evidence_leads
                    ORDER BY created_at, lead_id
                """):
                    latest[case_id] = (signature, json.loads(payload))
            for case_id, (signature, payload) in latest.items():
                if case_id in self.cases and self.dispatch_signature(case_id) == signature:
                    self.review_evidence[case_id] = payload
                else:
                    self.expired_review_evidence.append(case_id)
        finally:
            evidence_db.close()

    def _apply_dispatch_overlay(self):
        """Annotate work routing without changing scientific group evidence."""
        from .review_dispatch import Router

        router = Router(self.records, self.decisions, self.review_evidence)
        for case_id, case in self.group_cases.items():
            group = case['group_review']
            route = router.classify(case)['route']
            if route != group['route'] or case_id in self.review_evidence:
                group['eligibility_route'] = group['route']
                group['route'] = route
            if case_id in self.review_evidence:
                group['verification_source'] = self.review_evidence[case_id]

    def dispatch_signature(self, case_id):
        """Evidence-lead validity excludes the lead itself and dispatch overlay."""
        if case_id not in self._dispatch_baselines:
            if case_id in self.group_cases:
                from .review_groups import snapshot
                case = copy.deepcopy(self.group_cases[case_id])
                group = case['group_review']
                group['route'] = group.pop('eligibility_route', group['route'])
                group.pop('verification_source', None)
                self._dispatch_baselines[case_id] = snapshot(self, case, record_snapshot)['signature']
            else:
                self._dispatch_baselines[case_id] = self._component(case_id)[1]['signature']
        return self._dispatch_baselines[case_id]

    def snapshot(self, case_id):
        if case_id in self.group_cases:
            from .review_groups import snapshot
            case = self.group_cases[case_id]
            return {'case': copy.deepcopy(case), **snapshot(self, case, record_snapshot)}
        case, component = self._component(case_id)
        # Copy the shared component; preserve the historical case-reference contract.
        result = {'case': case, **copy.deepcopy(component)}
        if case_id in self.review_evidence:
            lead = self.review_evidence[case_id]
            result['verification_source'] = copy.deepcopy(lead)
            result['signature'] = digest([result['signature'], lead])
        return result

    def signature(self, case_id):
        return self.snapshot(case_id)['signature']

    def _related_submission_ids(self, ids, case_id):
        """Include competing candidates and existing child members in a snapshot.

        Evidence outside the two displayed endpoints can change their meaning;
        a stale endpoint or neighbor therefore blocks carry-forward.
        """
        related = set(ids)
        pending = list(ids)
        while pending:
            sid = pending.pop()
            nearby = set(self.by_child.get(self.records[sid].get("child_id"), set()))
            for other in self.by_sid[sid]:
                if other["kind"] in KINDS:
                    nearby.update(x for x in (other["record_a"], other["record_b"]) if x)
            if not nearby <= self.records.keys():
                raise PipelineError("相關候選提交已失效，請重新發布及派發：" + case_id)
            added = nearby - related
            related.update(added)
            pending.extend(added)
        return related

    def _component(self, case_id):
        case = self.cases.get(case_id)
        if not case or case["kind"] not in KINDS or not case.get("record_b"):
            raise PipelineError("個案已失效或不是兩份提交的身份比較：" + case_id)
        ids = {case["record_a"], case["record_b"]}
        if not ids <= self.records.keys():
            raise PipelineError("提交已失效，請重新派發：" + case_id)
        cached = self._component_cache.get(case['record_a'])
        if cached is not None:
            return case, cached
        related = self._related_submission_ids(ids, case_id)
        neighbors = {c["case_id"]: c for sid in related for c in self.by_sid[sid]
                     if c["record_a"] in related and (not c["record_b"] or c["record_b"] in related)}
        records = {sid: record_snapshot(self.records[sid]) for sid in sorted(related)}
        # File hashes/row positions and non-identity source updates do not change identity.
        # The old provenance remains in the immutable original evidence snapshot.
        evidence = {sid: {k: v for k, v in r.items() if k not in
                    {"version_id","location","answer","source_id","source_label"}} for sid, r in records.items()}
        candidates = [{k: v for k, v in c.items() if k not in {"version_a", "version_b"}}
                      for _, c in sorted(neighbors.items())]
        constraints = [d["payload"] for d in self.decisions
                       if {d["payload"].get("record_a"), d["payload"].get("record_b")} & related]
        signature = digest({"evidence": evidence, "candidates": candidates, "rules": self.rules})
        component = {
            "records": records, "candidates": candidates,
            "release_id": self.release["release_id"], "rules_hash": self.rules, "signature": signature,
            "original_manual_constraints": constraints,
        }
        for sid in related:
            self._component_cache[sid] = component
        return case, component


def stratified_cases(cases, reviewer, limit):
    """Sample reproducibly, rotating through status, kind and rule buckets."""
    buckets = defaultdict(list)
    for case in sorted(cases, key=lambda item: digest([reviewer, item['case_id']])):
        buckets[(case['kind'], case['status'], case['rule'])].append(case)
    selected, offsets = [], Counter()
    statuses = ['confirmed', 'pending', 'rejected', 'unmatched']
    statuses += sorted({case['status'] for case in cases} - set(statuses))
    while any(buckets.values()) and len(selected) < limit:
        for status in statuses:
            for kind in KINDS:
                keys = sorted(key for key, values in buckets.items() if values and key[:2] == (kind, status))
                if keys and len(selected) < limit:
                    key = keys[offsets[(kind, status)] % len(keys)]
                    offsets[(kind, status)] += 1
                    selected.append(buckets[key].pop())
    return selected


def register_review_evidence(cfg, case_id, source, reference, question, reviewer='Jarvis'):
    """Register an operator-attested available source, never an identity verdict.

    The source is bound to the full scientific evidence signature. Changing
    that evidence expires the registration rather than silently carrying it.
    """
    if reviewer != 'Jarvis' or source not in VERIFICATION_SOURCES:
        raise PipelineError('只可由 Jarvis 登記原始紙本、既有收集紀錄或其他已核實來源')
    reference, question = text(reference), text(question)
    if not reference or not question:
        raise PipelineError('必須填寫實際核實來源的位置及具體要核對的問題')
    main = connect(Path(cfg['state_dir']), readonly=True)
    work = workspace(cfg)
    try:
        ctx = Context(main, cfg)
        case = ctx.cases.get(case_id)
        from .review_dispatch import Router
        if (not case or case.get('status') != 'pending'
                or not Router(ctx.records, ctx.decisions).group_candidate(case)):
            raise PipelineError('個案失效、已有結論或存在身份／人工限制；須先處理更正或裁定')
        if case['kind'] in {'identity', 'family'} and case_id not in ctx.group_cases:
            raise PipelineError('孩子身份來源須登記至完整 GROUP 個案，不能繞過群組限制')
        signature = ctx.dispatch_signature(case_id)
        with work:
            old = work.execute("""
                SELECT payload FROM review_evidence_leads WHERE case_id=?
                ORDER BY created_at DESC, lead_id DESC LIMIT 1
            """, (case_id,)).fetchone()
            if old:
                previous = json.loads(old[0])
                expected = {'source': source, 'reference': reference, 'question': question, 'signature': signature}
                if all(previous.get(key) == value for key, value in expected.items()):
                    return {**previous, 'unchanged': True}
            lead = {
                'lead_id': 'EVID_' + uuid.uuid4().hex, 'case_id': case_id, 'signature': signature,
                'source': source, 'reference': reference, 'question': question,
                'reviewer': reviewer, 'created_at': utcnow(),
            }
            work.execute(
                'INSERT INTO review_evidence_leads VALUES(?,?,?,?,?)',
                (lead['lead_id'], case_id, signature, lead['created_at'], dumps(lead)),
            )
            event(work, 'verification_source_registered', case_id, lead)
        return lead
    finally:
        main.close()
        work.close()


def _allowed_package_cases(cases, router, purpose):
    """General work uses child groups/adult pairs; QA uses original comparisons."""
    return {
        case['case_id']: case for case in cases
        if router.eligible(case, purpose)
        and (purpose != 'review' or case.get('group_review') or case['kind'] == 'respondent')
        and (purpose == 'review' or not case.get('group_review'))
    }


def create_package(cfg, reviewer, output=None, limit=20, kinds=None, case_ids=None,
                   independent=False, replaces=None, purpose='review'):
    """Assign fixed evidence snapshots without writing formal matching decisions.

    Revalidate existing work, preserve task ownership, select eligible cases,
    then persist tasks and an optional sealed workbook in one workspace change.
    """
    reviewer = text(reviewer)
    if not reviewer or limit < 1:
        raise PipelineError("必須指定審核者及正整數宗數")
    from .review_dispatch import PURPOSES, REASONS, Router
    if purpose not in PURPOSES:
        raise PipelineError('未知審核用途')
    if purpose == 'adjudication' and reviewer != 'Jarvis':
        raise PipelineError('裁定工作包只可指派給指定執行者 Jarvis')
    if output and Path(output).exists():
        raise PipelineError("輸出檔案已存在；請使用新檔名，不覆寫原工作包")
    kinds = set(kinds or KINDS)
    if not kinds <= KINDS.keys():
        raise PipelineError("未知案例類型")
    main = connect(Path(cfg["state_dir"]), readonly=True)
    work = workspace(cfg)
    try:
        ctx = Context(main, cfg)
        valid = [c for c in ctx.cases.values() if c.get('record_b') and (c['kind'] in kinds or
                 (c.get('group_review') and 'family' in kinds and
                  set(c['group_review']['member_roles']) == {'student','parent'}))]
        router = Router(ctx.records, ctx.decisions,ctx.review_evidence)
        allowed = _allowed_package_cases(valid, router, purpose)
        work.execute("BEGIN IMMEDIATE")
        from .review_storage import task_heads
        for old_task in task_heads(work):
            try:
                changed = ctx.signature(old_task["case_id"]) != old_task['signature']
            except PipelineError:
                changed = True
            if changed:
                work.execute("UPDATE tasks SET state='stale' WHERE id=?", (old_task["id"],))
                event(work, "task_reopened_evidence_changed", old_task["id"], {"release_id":ctx.release["release_id"]})
        if replaces:
            old = work.execute("SELECT * FROM packages WHERE id=?", (replaces,)).fetchone()
            if not old:
                raise PipelineError("找不到原工作包")
            # Reassignment retains the original review/QA purpose and scope.
            purpose = json.loads(old['payload']).get('purpose', purpose)
            if purpose == 'adjudication' and reviewer != 'Jarvis':
                raise PipelineError('裁定工作包只可指派給指定執行者 Jarvis')
            allowed = _allowed_package_cases(valid, router, purpose)
            if work.execute("SELECT 1 FROM reviews WHERE task_id IN (SELECT id FROM tasks WHERE package_id=?)", (replaces,)).fetchone():
                raise PipelineError("已交回答案的工作包不能重新指派；請另行安排獨立重審")
            case_ids = [r[0] for r in work.execute("SELECT case_id FROM tasks WHERE package_id=?", (replaces,))]
            work.execute("UPDATE tasks SET state='cancelled' WHERE package_id=?", (replaces,))
            event(work, "reassign", replaces, {"reviewer": reviewer})
        assigned = {r[0] for r in work.execute("SELECT case_id FROM tasks WHERE state NOT IN ('cancelled','stale')")}
        # An unfinished legacy pair task still owns its group. Preserve its
        # answers and prevent a new helper receiving overlapping work.
        assigned_members = set()
        unfinished_pairs = {r[0] for r in work.execute("SELECT case_id FROM tasks WHERE state IN ('assigned','submitted')")}
        for cid in unfinished_pairs:
            existing = ctx.cases.get(cid)
            if (existing and not existing.get('group_review') and existing['kind'] in {'identity','family'}
                    and router.eligible(existing)):
                assigned_members.update((existing['record_a'], existing['record_b']))
        group_assigned = {cid for cid, c in ctx.group_cases.items()
                          if set(c['group_review']['members']) & assigned_members}
        assigned |= group_assigned
        if independent and case_ids:
            for old_task in work.execute("SELECT reviewer,payload FROM tasks WHERE state NOT IN ('cancelled','stale')"):
                if old_task['reviewer'] != reviewer:
                    continue
                old_case = json.loads(old_task['payload'])['snapshot']['case']
                old_ids = set(old_case.get('group_review', {}).get('members', [old_case['record_a'], old_case['record_b']]))
                if any(cid in ctx.group_cases and old_ids & set(ctx.group_cases[cid]['group_review']['members']) for cid in case_ids):
                    raise PipelineError('獨立重審需由另一位審核者進行；此審核者已獲派相關群組比較')
        if independent and not case_ids:
            raise PipelineError("獨立重審必須明確指定個案")
        if case_ids:
            case_ids = list(dict.fromkeys(case_ids))
            available = {c["case_id"]: c for c in valid}
            if any(cid not in available for cid in case_ids):
                raise PipelineError("指定個案已失效或類型不符")
            if not independent and any(cid in assigned for cid in case_ids):
                raise PipelineError("個案已有有效任務；重審請明確指定 independent")
            if independent and any(work.execute("SELECT 1 FROM tasks WHERE case_id=? AND reviewer=? AND state NOT IN ('cancelled','stale')",
                                               (cid, reviewer)).fetchone() for cid in case_ids):
                raise PipelineError("獨立重審需由另一位審核者進行")
            blocked = [cid for cid in case_ids if cid not in allowed]
            if blocked:
                messages = [cid + '：' + ('孩子比較已改為整組派審，請使用對應 GROUP ID' if
                            purpose == 'review' and available[cid]['kind'] != 'respondent' and not available[cid].get('group_review')
                            and router.eligible(available[cid], purpose)
                            else '、'.join(REASONS[x] for x in router.classify(available[cid])['reasons'])) for cid in blocked]
                raise PipelineError('以下比較不屬此用途的可派審個案；保留作參考或交指定執行者處理：\n' + '\n'.join(messages))
            selected = [allowed[cid] for cid in case_ids[:limit]]
        else:
            selected = stratified_cases([c for c in allowed.values() if c['case_id'] not in assigned],reviewer,limit)
        if not selected:
            raise PipelineError("沒有可派發的兩份提交個案")
        pid = "PKG_" + uuid.uuid4().hex
        tasks = []
        package = {"format_version": "study2-review-cards-1", "package_id": pid, "reviewer": reviewer,
                   "created_at": utcnow(), "release_id": ctx.release["release_id"], "tasks": tasks,
                   "sampling": "kind_status_rule_round_robin" if not case_ids else "explicit_case_ids",
                   'purpose': purpose}
        work.execute("INSERT INTO packages VALUES(?,?,?,?)", (pid, package["created_at"], reviewer, dumps(package)))
        for case in selected:
            tid = "TASK_" + uuid.uuid4().hex
            snapshot = ctx.snapshot(case["case_id"])
            revision = work.execute('SELECT COALESCE(MAX(revision),0)+1 FROM tasks WHERE case_id=? AND reviewer=?',
                                    (case['case_id'],reviewer)).fetchone()[0]
            task = {"task_id": tid, "revision": revision, "reviewer": reviewer,
                    "independent": independent and case["case_id"] in assigned, "snapshot": snapshot}
            tasks.append(task)
            work.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?)",
                         (tid, pid, case["case_id"], reviewer, revision, "assigned", dumps(task)))
        if output:
            from .review_excel import write_package
            contract = write_package(package, Path(output))
            package["contract"] = contract
        work.execute("UPDATE packages SET payload=? WHERE id=?", (dumps(package), pid))
        event(work, "package_created", pid, {"independent": independent, "count": len(tasks)})
        work.commit()
        return package
    except Exception:
        work.rollback()
        if output:
            Path(output).unlink(missing_ok=True)
        raise
    finally:
        main.close()
        work.close()


def check_task(work, ctx, task):
    stored = task["snapshot"]
    now = ctx.snapshot(stored["case"]["case_id"])
    if stored["signature"] != now["signature"]:
        raise PipelineError("身份證據、候選群組或規則已改變，須重新審核：" + task["task_id"])
    if stored["release_id"] != now["release_id"]:
        work.execute("INSERT OR IGNORE INTO carries VALUES(?,?,?,?)",
                     (task["task_id"], now["release_id"], utcnow(), dumps({"from": stored["release_id"], "signature": now["signature"]})))
    return now


def submit_reviews(cfg, package_id, answers, source="api"):
    """Stage atomic, fully validated answers. An entirely blank card is skipped."""
    work = workspace(cfg)
    main = connect(Path(cfg["state_dir"]), readonly=True)
    try:
        ctx = Context(main, cfg)
        work.execute("BEGIN IMMEDIATE")
        package = work.execute("SELECT * FROM packages WHERE id=?", (package_id,)).fetchone()
        if not package:
            raise PipelineError("未登記的工作包")
        errors, valid, seen = [], [], set()
        for answer in answers:
            tid = text(answer.get("task_id"))
            if tid in seen:
                errors.append(tid + "：重複個案答案")
                continue
            seen.add(tid)
            row = work.execute("SELECT * FROM tasks WHERE id=? AND package_id=?", (tid, package_id)).fetchone()
            if not row or row["state"] in {"cancelled", "stale"}:
                errors.append(tid + "：失效或不屬於此工作包")
                continue
            verdict, evidence, reason = (text(answer.get(k)) for k in ("verdict", "evidence_source", "reason"))
            if not any((verdict, evidence, reason)):
                continue
            missing = [name for name, v in (("審核結論", verdict), ("主要證據來源", evidence), ("補充理由", reason)) if not v]
            if missing:
                errors.append(tid + "：缺少 " + "、".join(missing))
            elif verdict not in VERDICTS or evidence not in EVIDENCE_SOURCES:
                errors.append(tid + "：下拉選項不合法")
            elif verdict != "資料不足" and evidence == "沒有足夠證據":
                errors.append(tid + "：確認相同／不同不能使用沒有足夠證據")
            else:
                try:
                    check_task(work, ctx, json.loads(row["payload"]))
                except PipelineError as error:
                    errors.append(str(error))
                valid.append((row, {"verdict": verdict, "label": VERDICTS[verdict], "evidence_source": evidence,
                                    "reason": reason, "reviewer": row["reviewer"]}))
        if errors:
            raise PipelineError("工作包退回補填或重新派發：\n" + "\n".join(errors))
        saved, unchanged = [], 0
        for row, answer in valid:
            previous = work.execute("SELECT * FROM reviews WHERE task_id=? ORDER BY revision DESC LIMIT 1", (row["id"],)).fetchone()
            if previous and all(json.loads(previous["payload"]).get(k) == v for k, v in answer.items()):
                unchanged += 1
                continue
            revision = previous["revision"] + 1 if previous else 1
            answer.update(source=source, package_id=package_id, task_revision=row["revision"])
            rid = "REV_" + uuid.uuid4().hex
            work.execute("INSERT INTO reviews VALUES(?,?,?,?,?)", (rid, row["id"], revision, utcnow(), dumps(answer)))
            work.execute("UPDATE tasks SET state='submitted' WHERE id=?", (row["id"],))
            event(work, "review_submitted", row["id"], {"review_id": rid, "supersedes": previous["id"] if previous else None})
            saved.append(rid)
        work.commit()
        return {"package_id": package_id, "saved": len(saved), "unchanged": unchanged,
                "review_ids": saved, "message": "答案已保存，尚未批准，正式配對及 Dashboard 未改動"}
    except Exception:
        work.rollback()
        raise
    finally:
        main.close()
        work.close()


def latest_reviews(work, include_stale=False):
    state_filter = "t.state<>'cancelled'" if include_stale else "t.state NOT IN ('cancelled','stale')"
    return work.execute("SELECT r.*,t.case_id,t.state,t.payload AS task_payload FROM reviews r JOIN tasks t ON r.task_id=t.id "
                        "WHERE r.revision=(SELECT MAX(revision) FROM reviews WHERE task_id=r.task_id) "
                        "AND "+state_filter+" ORDER BY t.case_id,r.id").fetchall()


def _adult_conflicts(a, b):
    return {k for k in ("birth_year",)
            if a[k] and b[k] and a[k] != b[k]}


def _adult_exception(ctx, case, request):
    """Operator-only, evidence-bound identity adjudication; never a field correction."""
    a, b = (ctx.records[case[k]] for k in ("record_a", "record_b"))
    ea, eb = adult_evidence(a), adult_evidence(b)
    fields = _adult_conflicts(ea, eb)
    if isinstance(request, dict) and request.get('type') == 'equivalent_relationship_wording':
        fields = {k for k in ('birth_year','relationship','other_relationship') if ea[k] and eb[k] and ea[k] != eb[k]}
    types = {"accepted_typo_unknown_year": {"birth_year"},
             "equivalent_relationship_wording": {"other_relationship"}}
    if not isinstance(request, dict) or fields != types.get(request.get("type")):
        raise PipelineError("人工成人例外只處理已裁定的出生年份錯字或親屬稱呼同義；其他矛盾仍須核實")
    if fields == {"other_relationship"} and not ea["relationship"] == eb["relationship"] == "2":
        raise PipelineError("稱呼同義例外須用於兩份均填其他關係的回應")
    if not text(request.get("reason")) or not text(request.get("authority")):
        raise PipelineError("人工成人例外須保存裁定理由及確認來源")
    return {"type": request["type"], "fields": sorted(fields), "reason": text(request["reason"]),
            "authority": text(request["authority"]), "adjudicator": "Jarvis",
            "correct_birth_year": None if fields == {"birth_year"} else "not_applicable",
            "record_a": case["record_a"], "record_b": case["record_b"],
            "child_id": a.get("child_id"), "evidence_a": ea, "evidence_b": eb}


def _valid_adult_exception(ctx, row):
    exception = row.get("adult_identity_exception")
    if not isinstance(exception, dict) or exception.get("adjudicator") != "Jarvis":
        return False
    if any(exception.get(k) != row.get(k) for k in ("record_a", "record_b")):
        return False
    if not {row["record_a"], row["record_b"]} <= ctx.records.keys():
        return False
    a, b = (ctx.records[row[k]] for k in ("record_a", "record_b"))
    if not (a["role"] == b["role"] == "parent" and a.get("child_id") and
            a["child_id"] == b.get("child_id") == exception.get("child_id")):
        return False
    try:
        expected = _adult_exception(ctx, row, exception)
    except PipelineError:
        return False
    return (expected.keys() == exception.keys()
            and all(expected[k] == exception.get(k) for k in expected if k not in {'evidence_a','evidence_b'})
            and all(adult_evidence_matches(record, exception.get('evidence_' + side), row.get('version_' + side))
                    for side, record in (('a', a), ('b', b))))


def _commands(ctx, task, answer, resolution=None):
    case = ctx.cases[task["snapshot"]["case"]["case_id"]]
    a, b = (ctx.records[case[k]] for k in ("record_a", "record_b"))
    label = answer["label"]
    adult = case["kind"] == "respondent"
    exception = None
    if adult and not (a["role"] == b["role"] == "parent" and a.get("child_id") and a["child_id"] == b.get("child_id")):
        raise PipelineError("成人決定要求兩份家長回應指向同一個已確認孩子")
    if label == "MATCH":
        if adult:
            ea, eb = adult_evidence(a), adult_evidence(b)
            request = (resolution or {}).get("adult_identity_exception")
            if request:
                exception = _adult_exception(ctx, case, request)
            elif _adult_conflicts(ea, eb):
                raise PipelineError("成人出生年份矛盾；先更正並重新取證，或由 Jarvis 明確裁定可用的逐宗出生年份例外")
        elif hard_conflict(a, b):
            raise PipelineError("孩子身份資料矛盾；先用既有修正流程更正資料、重跑及重新取證")
        action = "" if case["status"] == "confirmed" else ("LINK_ADULT" if adult else "LINK")
    elif label == "NONMATCH":
        action = "UNLINK_ADULT" if adult else "UNLINK"
    else:
        action = ""
    result = {**case, "release_id": ctx.release["release_id"], "version_a": a["version_id"], "version_b": b["version_id"],
            "action": action, "label": label, "value": "", "reviewer": answer["reviewer"],
            "reason": answer["reason"], "evidence_source": answer["evidence_source"],
            "pre_review": task["snapshot"]["case"], "pre_review_release_id":task['snapshot']['release_id'],
            "review_task_id": task["task_id"]}
    if exception:
        result["adult_identity_exception"] = exception
    return result


def preview_batch(cfg, package_ids=None, adjudications=None):
    """Freeze a review revision and a main-state revision, excluding conflicts."""
    work = workspace(cfg)
    main = connect(Path(cfg["state_dir"]), readonly=True)
    try:
        ctx = Context(main, cfg)
        work.execute("BEGIN IMMEDIATE")
        groups = defaultdict(list)
        for row in latest_reviews(work):
            answer = json.loads(row["payload"])
            # Include independent reviews outside selected packages for conflict detection.
            groups[row["case_id"]].append((row, json.loads(row["task_payload"]), answer))
        rows, conflicts, unresolved, selected_ids, carry = [], [], [], [], []
        adjudications = adjudications or {}
        current_labels = {r["case_id"]: dict(r) for r in main.execute("SELECT * FROM labels")}
        for cid, reviews in sorted(groups.items()):
            if package_ids and not any(a["package_id"] in package_ids for _, _, a in reviews):
                continue
            if all(r["state"] == "applied" for r, _, _ in reviews):
                continue
            selected_ids.extend(r["id"] for r, _, _ in reviews)
            resolution = adjudications.get(cid)
            try:
                for _, task, _ in reviews:
                    fresh = check_task(work, ctx, task)
                    if fresh["release_id"] != task["snapshot"]["release_id"]:
                        carry.append(task["task_id"])
                distinct = {a["label"] for _, _, a in reviews}
                if len(distinct) > 1 and not resolution:
                    raise PipelineError("不同審核者或獨立重審的答案不一致")
                chosen = reviews[0]
                if resolution:
                    if not text(resolution.get("reason")):
                        raise PipelineError("Jarvis 裁定必須填寫理由")
                    chosen = next((v for v in reviews if v[0]["id"] == resolution.get("review_id")), None)
                    if not chosen:
                        raise PipelineError("裁定必須採納現有審核結果")
                row, task, answer = chosen
                if task['snapshot']['case'].get('group_review'):
                    from .review_groups import commands
                    proposed = commands(ctx, task, answer, resolution, _commands)
                else:
                    proposed = [_commands(ctx, task, answer, resolution)]
                for command in proposed:
                    old_label = current_labels.get(command['case_id'])
                    prefix = "adult_pair:" if command["kind"] == "respondent" else "pair:"
                    target = prefix + digest(sorted([command["record_a"], command["record_b"]]))
                    old = next((d for d in ctx.decisions if d["payload"]["target_key"] == target), None)
                    opposite = (old and command["action"] and old["payload"]["action"] != command["action"]) or (
                        old_label and old_label["label"] in {"MATCH", "NONMATCH"} and command['label'] in {"MATCH", "NONMATCH"}
                        and old_label["label"] != command['label'])
                    if opposite and not resolution:
                        raise PipelineError("與既有人工決定相反，需要 Jarvis 裁定")
                    command["review_ids"] = [r["id"] for r, _, _ in reviews]
                    if resolution:
                        command["adjudication"] = {**resolution, "adjudicator": "Jarvis", "replaced_label": old_label,
                                                   "replaced_decision": old, "alternatives": [dict(r) for r, _, _ in reviews]}
                rows.extend(proposed)
                if answer["label"] == "UNRESOLVED":
                    unresolved.append(cid)
            except PipelineError as error:
                conflicts.append({"case_id": cid, "message": str(error),
                                  "reviews": [{"review_id": r["id"], **a} for r, _, a in reviews]})
        # Isolate conflicting connected components; unrelated valid cases remain approvable.
        accepted = []
        for component in _decision_components(ctx, rows):
            try:
                validate_review_rows(main, cfg, component, context=(ctx.release,ctx.records,ctx.cases))
                _check_group_conflicts(ctx, component)
                accepted.extend(component)
            except PipelineError as error:
                conflicts.extend({"case_id": r["case_id"], "message": "批次連鎖矛盾：" + str(error),
                                  "reviews": [{"review_id": rid} for rid in r["review_ids"]]} for r in component)
        rows = accepted
        unresolved = [r["case_id"] for r in rows if r["label"] == "UNRESOLVED"]
        batch = {"batch_id": "RB_" + uuid.uuid4().hex, "release_id": ctx.release["release_id"],
                 "main_revision": ctx.main_revision, "rules_hash": ctx.rules, "review_ids": sorted(selected_ids),
                 "rows": rows, "conflicts": conflicts, "unresolved": unresolved, "carried_tasks": carry,
                 "package_ids": package_ids, "created_at": utcnow()}
        batch["preview_hash"] = digest(batch)
        work.execute("INSERT INTO batches VALUES(?,?,?,?)", (batch["batch_id"], "previewed", batch["created_at"], dumps(batch)))
        event(work, "batch_previewed", batch["batch_id"], {"valid": len(rows), "conflicts": len(conflicts)})
        work.commit()
        return batch
    except Exception:
        work.rollback()
        raise
    finally:
        main.close()
        work.close()


def _decision_components(ctx, rows):
    """Partition by identity domain and all potentially interacting constraints."""
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    def union(adult,a,b):
        parent[find((adult,a))] = find((adult,b))
    for d in ctx.decisions:
        p=d['payload']
        if p['action'] in {'LINK','UNLINK','LINK_ADULT','UNLINK_ADULT'}:
            union(p['action'].endswith('_ADULT'),p['record_a'],p['record_b'])
    for group in ctx.by_child.values():
        ids=sorted(group)
        for sid in ids[1:]:
            union(False,ids[0],sid)
    for r in rows:
        union(r['kind']=='respondent',r['record_a'],r['record_b'])
    groups = defaultdict(list)
    for r in rows:
        groups[find((r['kind']=='respondent',r['record_a']))].append(r)
    return list(groups.values())


def _check_group_conflicts(ctx, rows):
    for adult,action in ((False,'LINK'),(True,'LINK_ADULT')):
        new_links=[r for r in rows if r['action']==action]
        if not new_links:
            continue
        proposed={d['payload']['target_key']:d['payload'] for d in ctx.decisions}
        for r in rows:
            if r['action'] in {'LINK','UNLINK','LINK_ADULT','UNLINK_ADULT'}:
                key=('adult_pair:' if r['kind']=='respondent' else 'pair:')+digest(sorted([r['record_a'],r['record_b']]))
                proposed[key]=r
        adjacency=defaultdict(set)
        for p in proposed.values():
            if p['action']!=action or not {p['record_a'],p['record_b']}<=ctx.records.keys():
                continue
            if p.get('evidence_a') is not None:
                def unchanged(side):
                    record = ctx.records[p['record_' + side]]
                    saved = p.get('evidence_' + side)
                    return adult_evidence_matches(record, saved, p.get('version_' + side)) if adult else identity_evidence_matches(record, saved)
                if not all(unchanged(s) for s in ('a','b')):
                    continue
            adjacency[p['record_a']].add(p['record_b'])
            adjacency[p['record_b']].add(p['record_a'])
        for r in new_links:
            queue=[r['record_a'],r['record_b']]
            members=set()
            while queue:
                sid=queue.pop()
                if sid in members:
                    continue
                members.add(sid)
                queue.extend(adjacency[sid]-members)
                if not adult:
                    queue.extend(ctx.by_child.get(ctx.records[sid].get('child_id'),set())-members)
            for a,b in combinations(members,2):
                if adult:
                    ea,eb=adult_evidence(ctx.records[a]),adult_evidence(ctx.records[b])
                    conflict=not ctx.records[a].get('child_id') or ctx.records[a].get('child_id')!=ctx.records[b].get('child_id')
                    fields = _adult_conflicts(ea, eb)
                    key = 'adult_pair:' + digest(sorted([a,b]))
                    explicit = proposed.get(key, {})
                    waived = bool(explicit.get('action') == 'LINK_ADULT' and _valid_adult_exception(ctx, explicit))
                    conflict |= bool(fields and not waived)
                else:
                    conflict=hard_conflict(ctx.records[a],ctx.records[b])
                if conflict:
                    raise PipelineError('連鎖連結或現有群組包含矛盾的身份資料')


def _check_batch(work, ctx, batch):
    if ctx.release["release_id"] != batch["release_id"] or ctx.main_revision != batch["main_revision"] or ctx.rules != batch["rules_hash"]:
        raise PipelineError("預覽已失效：發布版本、人工決定或規則已改變，請重新預覽及批准")
    heads = {r["id"]: r for r in latest_reviews(work)}
    if any(rid not in heads for rid in batch["review_ids"]):
        raise PipelineError("預覽已失效：審核者更正了答案，請重新預覽及批准")
    # A newly arrived second review can introduce a disagreement after preview.
    cases = {row["case_id"] for row in batch["rows"]}
    if any(r["id"] not in batch["review_ids"] and r["case_id"] in cases for r in heads.values()):
        raise PipelineError("預覽已失效：收到新的独立審核答案，請重新預覽及批准")
    valid_ids = {rid for row in batch["rows"] for rid in row["review_ids"]}
    for rid in valid_ids:
        check_task(work, ctx, json.loads(heads[rid]["task_payload"]))
    for row in batch["rows"]:
        if row.get("adult_identity_exception") and not _valid_adult_exception(ctx, row):
            raise PipelineError("人工成人例外已失效，須重新裁定")
    _check_group_conflicts(ctx, batch["rows"])


def approve_batch(cfg, batch_id, approver="Jarvis", reason=""):
    if approver != "Jarvis" or not text(reason):
        raise PipelineError("批次批准須由 Jarvis 執行並填寫批准理由")
    work, main = workspace(cfg), connect(Path(cfg["state_dir"]), readonly=True)
    try:
        ctx = Context(main, cfg)
        work.execute("BEGIN IMMEDIATE")
        row = work.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not row:
            raise PipelineError("找不到預覽批次")
        batch = json.loads(row["payload"])
        if row["state"] == "applied":
            return {"batch_id": batch_id, "state": "applied"}
        _check_batch(work, ctx, batch)
        if not batch["rows"]:
            raise PipelineError("批次沒有可批准的無衝突結果")
        batch["approval"] = {"approver": approver, "reason": reason, "at": utcnow()}
        work.execute("UPDATE batches SET state='approved',payload=? WHERE id=?", (dumps(batch), batch_id))
        event(work, "batch_approved", batch_id, batch["approval"])
        work.commit()
        return {"batch_id": batch_id, "state": "approved", "valid": len(batch["rows"]),
                "conflicts_not_approved": len(batch["conflicts"])}
    finally:
        main.close()
        work.close()


def _finish_apply(work, batch, result):
    with work:
        previous = work.execute("SELECT state FROM batches WHERE id=?", (batch["batch_id"],)).fetchone()
        if previous and previous["state"] == "applied":
            return
        work.execute("UPDATE batches SET state='applied' WHERE id=?", (batch["batch_id"],))
        for row in batch["rows"]:
            for rid in row["review_ids"]:
                work.execute("UPDATE tasks SET state='applied' WHERE id=(SELECT task_id FROM reviews WHERE id=?) "
                             "AND ?=(SELECT id FROM reviews WHERE task_id=tasks.id ORDER BY revision DESC LIMIT 1)", (rid,rid))
            if row["label"] == "UNRESOLVED":
                work.execute("INSERT OR REPLACE INTO followups VALUES(?,?,?,?)",
                             (row["case_id"], row["review_task_id"], "pending", dumps(row)))
            else:
                work.execute("UPDATE followups SET state='resolved' WHERE case_id=?", (row["case_id"],))
        event(work, "batch_applied", batch["batch_id"], result)


def apply_batch(cfg, batch_id):
    work = workspace(cfg)
    try:
        row = work.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not row or row["state"] not in {"approved", "applied"}:
            raise PipelineError("批次尚未批准")
        batch = json.loads(row["payload"])
        try:
            with writer_lock(Path(cfg["state_dir"])):
                main = connect(Path(cfg["state_dir"]))
                try:
                    marker = main.execute("SELECT payload_json FROM review_applications WHERE batch_id=?", (batch_id,)).fetchone()
                    if marker:
                        result = json.loads(marker[0])["result"]
                        _finish_apply(work, batch, result)
                        return {"batch_id": batch_id, "state": "applied", "recovered_or_repeated": True, **result}
                    ctx = Context(main, cfg)
                    saved = backup_workspace(cfg, "before_apply")
                    batch["workspace_backup"] = saved
                    work.execute("BEGIN IMMEDIATE")
                    _check_batch(work, ctx, batch)
                    canonical_rows=[{**r,'approved_batch_id':batch_id,'approval':batch['approval']} for r in batch['rows']]
                    validated = validate_review_rows(main, cfg, canonical_rows, context=(ctx.release,ctx.records,ctx.cases))
                    counts = {"corrections": len(validated["actions"]), "validation_labels": len(validated["labels"]), "school_changes": 0}
                    result = commit_review_rows(main, validated, {**batch, "result": counts})
                    # Main commit and marker above are atomic. A crash here is recoverable.
                    _finish_apply(work, batch, result)
                    return {"batch_id": batch_id, "state": "applied", "workspace_backup": saved,
                            "message": "已套用。請重跑及發布後，Dashboard 才會使用新結果", **result}
                finally:
                    main.close()
        except PipelineError as error:
            work.rollback()
            if "Another pipeline" in str(error):
                return {"batch_id": batch_id, "state": "approved", "message": "Pipeline 正在執行；結果已批准、待套用，請稍後重試"}
            raise
    finally:
        work.close()


def reopen_tasks(cfg, task_ids, reason):
    if not text(reason):
        raise PipelineError("重新派發須填寫理由")
    work = workspace(cfg)
    try:
        with work:
            for tid in task_ids:
                if not work.execute("SELECT 1 FROM tasks WHERE id=?", (tid,)).fetchone():
                    raise PipelineError("失效任務：" + tid)
                work.execute("UPDATE tasks SET state='stale' WHERE id=?", (tid,))
                event(work, "task_reopened", tid, {"reason": reason})
        return {"reopened": len(task_ids)}
    finally:
        work.close()


def review_report(cfg):
    work = workspace(cfg)
    try:
        rules, independent = defaultdict(Counter), Counter()
        groups = defaultdict(list)
        reviewed_active=set()
        for row in latest_reviews(work, include_stale=True):
            task, answer = json.loads(row["task_payload"]), json.loads(row["payload"])
            baseline = task["snapshot"]["case"]
            counts = rules[baseline["rule"]]
            counts["reviewed"] += 1
            category = ("資料不足" if answer["label"] == "UNRESOLVED" else "程式待審" if
                        baseline["status"] not in {"confirmed","rejected"} else "一致" if
                        (baseline["status"] == "confirmed") == (answer["label"] == "MATCH") else "不一致")
            counts[category] += 1
            groups[(row['case_id'],task['snapshot']['signature'])].append((task, answer))
            if row['state']!='stale':
                reviewed_active.add(row['case_id'])
        for group in groups.values():
            if len(group) > 1 and any(t["independent"] for t, _ in group):
                independent["cases"] += 1
                independent["agreement" if len({a["label"] for _, a in group}) == 1 else "disagreement"] += 1
                independent["unresolved_cases"] += any(a["label"] == "UNRESOLVED" for _, a in group)
        from .store import current
        main=connect(Path(cfg["state_dir"]),readonly=True)
        try:
            release=current(main)
            stats=json.loads(release['stats_json'])
            from .review_dispatch import summary as dispatch_summary
            dispatch = dispatch_summary(Context(main, cfg), work)
            candidates={r[0] for r in main.execute("SELECT case_id FROM release_candidates WHERE release_id=? "
                        "AND json_extract(payload_json,'$.kind') IN ('identity','family','respondent') "
                        "AND json_extract(payload_json,'$.record_b')<>''",(release['release_id'],))}
        finally:
            main.close()
        reviewed=reviewed_active&candidates
        assigned={r[0] for r in work.execute("SELECT DISTINCT case_id FROM tasks WHERE state NOT IN ('cancelled','stale')")}&candidates
        return {"original_algorithm_by_rule": dict(rules), "independent_review": dict(independent),
                'identity_review_queue': dispatch,
                "published_results": {'release_id':release['release_id'],'published_at':release['created_at'],
                    'samples':{k:stats.get(k) for k in ('A','B','C','D','AC','BD','E','F','EF')},
                    'validation_cases_labelled':stats.get('validation_cases_labelled',0)},
                "coverage": {"release_id":release['release_id'],"paired_candidate_cases":len(candidates),
                    "assigned_unique_cases":len(assigned),"reviewed_unique_cases":len(reviewed),
                    "historical_reviewed_unique_cases":len({cid for cid,_ in groups}),
                    "reviewed_case_coverage":len(reviewed)/len(candidates) if candidates else None},
                "tasks": dict(Counter(r[0] for r in work.execute("SELECT state FROM tasks"))),
                "batches": dict(Counter(r[0] for r in work.execute("SELECT state FROM batches"))),
                "followups_pending": work.execute("SELECT COUNT(*) FROM followups WHERE state='pending'").fetchone()[0],
                "note": "分層審核樣本，不能推定整體 precision/recall；程式結論採用審核前快照"}
    finally:
        work.close()


from .checkpoints import protect_mutation
create_package=protect_mutation(create_package)
register_review_evidence=protect_mutation(register_review_evidence)
submit_reviews=protect_mutation(submit_reviews)
preview_batch=protect_mutation(preview_batch)
approve_batch=protect_mutation(approve_batch)
apply_batch=protect_mutation(apply_batch)
reopen_tasks=protect_mutation(reopen_tasks)
