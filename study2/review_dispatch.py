"""Read-only routing of candidate comparisons into useful review work.

Candidate discovery and scientific identity decisions are unchanged. Background
comparisons stay available as evidence, but are not ordinary review assignments.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from .common import contacts, text, timestamp, utcnow, fuzzy_phone, dumps, atomic_json, file_hash
from .matching import identity_evidence_matches
from .respondents import adult_evidence, adult_evidence_matches

PURPOSES = {'review', 'validation', 'adjudication'}
DISPATCH_POLICY = 'actionable_evidence_v1'
ROUTES = {'review': '一般身份審核', 'background': '按現有資料不配對／背景參考',
          'awaiting_evidence': '證據不足，待新資料（暫不合併）',
          'group_reference': '已納入群組審核，兩份比較不重複派發',
          'untraceable': '無可用聯絡，不派審', 'correction': '資料更正（有可用聯絡）',
          'operator': '指定執行者處理', 'settled': '已有結論，毋須一般派審'}
REASONS = {
    'not_an_identity_pair': '不是兩份提交的身份比較', 'missing_record': '提交已失效',
    'invalid_roles': '問卷類別與比較類型不符', 'excluded_submission': '包含已排除或不合資格提交',
    'child_birthdate_conflict': '完整孩子生日不同', 'child_gender_conflict': '有效孩子性別不同',
    'no_usable_contact': '至少一方沒有有效電話或電郵',
    'child_birthdate_missing_or_invalid': '孩子完整生日缺失或無效',
    'child_gender_missing_or_invalid': '孩子有效性別缺失或無效',
    'child_school_missing': '孩子學校資料缺失', 'manual_nonmatch': '存在有效人工不配對限制',
    'child_identity_not_confirmed': '成人比較尚未確認指向同一孩子',
    'adult_birth_year_conflict': '有效成人出生年份不同',
    'adult_birth_year_missing_or_invalid': '成人出生年份缺失或無效',
    'group_contact_bridge': '群組有聯絡連結，但部分提交沒有直接共同聯絡',
    'group_contact_gap': '群組有未連起的子群，需要判斷缺少證據的連結',
    'group_identity_conflict': '群組內存在生日或性別矛盾，交指定執行者處理',
    'group_manual_nonmatch': '群組內存在有效人工不配對限制',
    'group_incomplete_members': '已連結群組有不合資格或身份／聯絡資料不足的提交',
    'covered_by_group_review': '已改為整組核實，不重複派發兩份比較',
    'group_no_verifiable_bridge': '子群之間沒有已登記的可核實證據，暫不合併及不派審',
    'no_specific_link_evidence': '沒有共同聯絡或已登記的核實來源，等待新資料',
    'unverified_contact_discrepancy': '聯絡資料近似但未符合規則，尚無核實來源；不能靠猜測接受錯字',
    'registered_verification_source': 'Jarvis 已登記核實來源、位置及具體問題',
    'already_decided': '程式或人工已有結論', 'ambiguous_identity': '基本身份一致，聯絡或候選群組仍有歧義'}
ELIGIBLE = {'eligible', 'short_repeat', 'short_interval_followup', 'extra_followup'}


def _birthday(record):
    try:
        return date.fromisoformat(text(record.get('dob')))
    except ValueError:
        return None


class Router:
    def __init__(self, records, decisions=(), evidence=None):
        self.records = records
        self.evidence = evidence or {}
        self.excluded = set()
        self.parents = {kind: {sid: sid for sid in records} for kind in ('child', 'adult')}
        self.forbidden = {'child': set(), 'adult': set()}
        by_child = defaultdict(list)
        for sid, r in records.items():
            if r.get('child_id'):
                by_child[r['child_id']].append(sid)
        for ids in by_child.values():
            for sid in ids[1:]:
                self._join('child', ids[0], sid)
        pending = []
        for d in decisions:
            p = d['payload']
            action, a, b = p.get('action'), p.get('record_a'), p.get('record_b')
            if action == 'EXCLUDE' and a in records and records[a].get('version_id') == p.get('version_a'):
                self.excluded.add(a)
            if action not in {'LINK', 'UNLINK', 'LINK_ADULT', 'UNLINK_ADULT'} or not {a, b} <= records.keys():
                continue
            adult = action.endswith('_ADULT')
            if not all(self._unchanged(records[sid], p, side, adult) for sid, side in ((a, 'a'), (b, 'b'))):
                continue
            if adult and (not records[a].get('child_id') or records[a]['child_id'] != records[b].get('child_id')):
                continue
            kind = 'adult' if adult else 'child'
            if action.startswith('LINK'):
                self._join(kind, a, b)
            else:
                pending.append((kind, a, b))
        for kind, a, b in pending:
            self.forbidden[kind].add(tuple(sorted((self._find(kind, a), self._find(kind, b)))))

    @staticmethod
    def _unchanged(record, payload, side, adult):
        saved = payload.get('evidence_' + side)
        if saved is None:
            return bool(record.get('version_id') and record.get('version_id') == payload.get('version_' + side))
        return (adult_evidence_matches(record, saved, payload.get('version_' + side)) if adult
                else identity_evidence_matches(record, saved))

    def _find(self, kind, sid):
        parent = self.parents[kind]
        while parent[sid] != sid:
            parent[sid] = parent[parent[sid]]
            sid = parent[sid]
        return sid

    def _join(self, kind, a, b):
        a, b = self._find(kind, a), self._find(kind, b)
        self.parents[kind][max(a, b)] = min(a, b)

    def _base_classify(self, case):
        def result(route, *reasons):
            return {'route': route, 'reasons': list(reasons)}
        if case.get('group_review'):
            group = case['group_review']
            return result(group.get('eligibility_route', group['route']), 'group_' + group['issue'])
        kind, aid, bid = case.get('kind'), case.get('record_a'), case.get('record_b')
        if kind not in {'identity', 'family', 'respondent'} or not bid or aid == bid:
            return result('background', 'not_an_identity_pair')
        if not {aid, bid} <= self.records.keys():
            return result('background', 'missing_record')
        a, b = self.records[aid], self.records[bid]
        roles = (a.get('role'), b.get('role'))
        if (any(r not in {'student', 'parent'} for r in roles) or
                (kind == 'family' and set(roles) != {'student', 'parent'}) or
                (kind == 'identity' and roles[0] != roles[1]) or
                (kind == 'respondent' and roles != ('parent', 'parent'))):
            return result('background', 'invalid_roles')
        if any(r.get('status', 'eligible') not in ELIGIBLE for r in (a, b)) or {aid, bid} & self.excluded:
            return result('background', 'excluded_submission')
        birthdays = [_birthday(r) for r in (a, b)]
        genders = [text(r.get('gender')) for r in (a, b)]
        contradictions = []
        if all(birthdays) and birthdays[0] != birthdays[1]:
            contradictions.append('child_birthdate_conflict')
        if all(g in {'0', '1'} for g in genders) and genders[0] != genders[1]:
            contradictions.append('child_gender_conflict')
        if contradictions:
            return result('background', *contradictions)
        # Phone omitted is not equivalent to untraceable: an email is sufficient.
        # Use the contact parser shown on the corresponding identity card.
        contact_sets = [(set(adult_evidence(r)['all_contacts']) if kind == 'respondent'
                         else contacts(r.get('answer', {}))) for r in (a, b)]
        if any(not values for values in contact_sets):
            return result('untraceable', 'no_usable_contact')
        missing = []
        if not all(birthdays):
            missing.append('child_birthdate_missing_or_invalid')
        if not all(g in {'0', '1'} for g in genders):
            missing.append('child_gender_missing_or_invalid')
        if any(not text(r.get('school')) for r in (a, b)):
            missing.append('child_school_missing')
        if missing:
            return result('correction', *missing)
        constraint_kind = 'adult' if kind == 'respondent' else 'child'
        pair = tuple(sorted((self._find(constraint_kind, aid), self._find(constraint_kind, bid))))
        if pair in self.forbidden[constraint_kind]:
            return result('operator', 'manual_nonmatch')
        if kind == 'respondent':
            if not a.get('child_id') or a['child_id'] != b.get('child_id'):
                return result('background', 'child_identity_not_confirmed')
            years = [adult_evidence(r)['birth_year'] for r in (a, b)]
            maximum = min((timestamp(r.get('observed_at')) or timestamp(utcnow())).year for r in (a, b))
            if any(not y.isdigit() or len(y) != 4 or not 1900 <= int(y) <= maximum for y in years):
                return result('correction', 'adult_birth_year_missing_or_invalid')
            if years[0] != years[1]:
                return result('operator', 'adult_birth_year_conflict')
        if case.get('status') != 'pending':
            return result('settled', 'already_decided')
        return result('review', 'ambiguous_identity')

    def group_candidate(self, case):
        """Scientific candidate discovery is independent of worker dispatch."""
        return self._base_classify(case)['route'] == 'review'

    def classify(self, case):
        base = self._base_classify(case)
        if base['route'] != 'review' or case.get('status') != 'pending':
            return base
        if case['case_id'] in self.evidence:
            return {'route': 'review', 'reasons': ['registered_verification_source']}
        group = case.get('group_review')
        if group:
            if group['issue'] == 'contact_gap':
                return {'route': 'awaiting_evidence', 'reasons': ['group_no_verifiable_bridge']}
            return base
        a, b = (self.records[case[key]] for key in ('record_a', 'record_b'))
        values = [(set(adult_evidence(r)['all_contacts']) if case['kind'] == 'respondent'
                   else contacts(r.get('answer', {}))) for r in (a, b)]
        if values[0] & values[1]:
            return base
        reason = ('unverified_contact_discrepancy' if any(fuzzy_phone(x,y) for x in values[0] for y in values[1])
                  else 'no_specific_link_evidence')
        return {'route': 'awaiting_evidence', 'reasons': [reason]}

    def eligible(self, case, purpose='review'):
        route = self.classify(case)['route']
        if purpose == 'review':
            return route == 'review'
        if purpose == 'validation':
            return route in {'review', 'settled'}
        if purpose == 'adjudication':
            return route in {'review', 'settled', 'operator'}
        raise ValueError('Unknown review purpose')


def summary(ctx, work=None, include_cases=False):
    router = Router(ctx.records, ctx.decisions, getattr(ctx, 'review_evidence', {}))
    routed = {cid: router.classify(c) for cid, c in ctx.cases.items()}
    pending = {cid for cid, c in ctx.cases.items() if c['kind'] in {'identity', 'family', 'respondent'}
               and c.get('record_b') and c['status'] == 'pending' and not c.get('group_review')}
    comparisons = {cid for cid in pending if routed[cid]['route'] == 'review'}
    groups = getattr(ctx, 'group_cases', {})
    group_ids = {cid for cid, c in groups.items() if routed[cid]['route'] == 'review'}
    waiting_groups = {cid for cid in groups if routed[cid]['route'] == 'awaiting_evidence'}
    waiting_adults = {cid for cid in pending if ctx.cases[cid]['kind'] == 'respondent'
                      and routed[cid]['route'] == 'awaiting_evidence'}
    adults = {cid for cid in comparisons if ctx.cases[cid]['kind'] == 'respondent'}
    reviewable = group_ids | adults
    covered = {cid: gid for gid, g in groups.items() for cid in g['group_review']['comparison_ids']}
    assigned, labels = set(), defaultdict(set)
    if work is not None:
        assigned = {r[0] for r in work.execute("SELECT case_id FROM tasks WHERE state NOT IN ('cancelled','stale')")}
        for row in work.execute("SELECT t.case_id,r.payload FROM reviews r JOIN tasks t ON t.id=r.task_id "
                                "WHERE t.state NOT IN ('cancelled','stale') AND r.revision="
                                "(SELECT MAX(r2.revision) FROM reviews r2 WHERE r2.task_id=r.task_id)"):
            labels[row[0]].add(json.loads(row[1])['label'])
    resolved = {cid for cid, values in labels.items() if len(values) == 1 and values <= {'MATCH', 'NONMATCH'}}
    unfinished = ({r[0] for r in work.execute("SELECT case_id FROM tasks WHERE state IN ('assigned','submitted')")}
                  if work is not None else set())
    legacy_assigned_members = {sid for cid in unfinished if cid in ctx.cases and cid not in groups
                               and ctx.cases[cid]['kind'] in {'identity','family'}
                               and router.eligible(ctx.cases[cid])
                               for sid in (ctx.cases[cid]['record_a'], ctx.cases[cid]['record_b'])}
    assigned |= {cid for cid, c in groups.items() if set(c['group_review']['members']) & legacy_assigned_members}
    result = {'release_id': ctx.release['release_id'], 'dispatch_policy': DISPATCH_POLICY,
              'registered_verification_sources': len(getattr(ctx,'review_evidence',{})),
              'expired_verification_sources': len(getattr(ctx,'expired_review_evidence',[])),
              'awaiting_evidence_groups': len(waiting_groups), 'awaiting_evidence_adult_comparisons': len(waiting_adults),
              'awaiting_evidence_work': len(waiting_groups | waiting_adults),
              'pending_candidates_total': len(pending),
              'pending_routes': dict(Counter(routed[cid]['route'] for cid in pending)),
              'pending_reasons': dict(Counter(code for cid in pending for code in routed[cid]['reasons'])),
              'reviewable_pending': len(reviewable),
              'reviewable_comparisons_before_grouping': len(comparisons),
              'child_groups_pending': len(group_ids), 'adult_comparisons_pending': len(adults),
              'child_groups_operator': sum(routed[cid]['route'] == 'operator' for cid in groups),
              'group_issues': dict(Counter(groups[cid]['group_review']['issue'] for cid in group_ids)),
              'directly_supported_comparisons_in_groups': sum(len(groups[cid]['group_review']['passed_pairs']) for cid in group_ids),
              'unresolved_between_identity_comparisons': sum(len(groups[cid]['group_review']['unresolved_pairs']) for cid in group_ids | waiting_groups),
              'reviewable_by_kind': dict(Counter(ctx.cases[cid]['kind'] for cid in reviewable)),
              'reviewable_assigned': len(reviewable & assigned),
              'reviewable_unassigned': len(reviewable - assigned),
              'reviewable_answers_received': len(reviewable & labels.keys()),
              'reviewable_answered_awaiting_approval': len(reviewable & resolved),
              'assigned_outside_general_queue': len((assigned & pending) - reviewable),
              'remaining_general_reviews': len(reviewable - resolved)}
    if include_cases:
        result['cases'] = [{'case_id': cid, **({'route':'group_reference','reasons':['covered_by_group_review']}
                                             if cid in covered or (cid in comparisons and ctx.cases[cid]['kind'] != 'respondent') else route), 'group_id': covered.get(cid, '')}
                           for cid, route in routed.items()]
        result['groups'] = [{k: c[k] for k in ('case_id','kind','rule','status','reason','record_a','record_b')}
                            | {'members':len(c['group_review']['members']),
                               'passed_pairs':len(c['group_review']['passed_pairs']),
                               'missing_pairs':len(c['group_review']['missing_pairs']),
                               'unresolved_pairs':len(c['group_review']['unresolved_pairs']),
                               'contact_components':len(c['group_review']['contact_components']),
                               'route':c['group_review']['route']} for c in groups.values()]
        for row in result['groups']:
            a, b = (ctx.records[row['record_' + side]] for side in ('a','b'))
            for side, record in (('a',a),('b',b)):
                row.update({key+'_'+side: record.get(key) for key in
                            ('role','school','grade','observed_at','date_basis')})
            row.update(dob_agrees=bool(a.get('dob') and a['dob']==b.get('dob')),
                       gender_agrees=bool(a.get('gender') and a['gender']==b.get('gender')),
                       school_agrees=bool(a.get('school') and a['school']==b.get('school')),
                       exact_contact=bool(contacts(a.get('answer',{})) & contacts(b.get('answer',{}))))
    return result


def queue_snapshot(cfg, include_cases=False):
    """Dashboard/CLI query: both databases are opened read-only."""
    from .review_core import Context
    from .store import connect
    main = connect(Path(cfg['state_dir']), readonly=True)
    work = None
    try:
        path = Path(cfg['state_dir']) / 'review.sqlite'
        if path.exists():
            work = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        return summary(Context(main, cfg), work, include_cases)
    finally:
        main.close()
        if work is not None:
            work.close()


def export_waiting_dataset(cfg, output):
    """Freeze unresolved evidence, without decisions or changes to live state."""
    from itertools import combinations
    from .review_core import Context,record_snapshot
    from .store import connect
    from .common import digest
    output=Path(output)
    if output.exists():
        from .common import PipelineError
        raise PipelineError('固定資料集不可覆寫，請使用新資料夾')
    main=connect(Path(cfg['state_dir']),readonly=True)
    try:
        ctx=Context(main,cfg);router=Router(ctx.records,ctx.decisions,ctx.review_evidence)
        cases=[c for c in ctx.cases.values() if c.get('status')=='pending' and
               (c.get('group_review') or c['kind']=='respondent') and
               router.classify(c)['route']=='awaiting_evidence']
        output.mkdir(parents=True,mode=0o700)
        path=output/'awaiting_evidence.sqlite';snapshot=sqlite3.connect(path)
        path.chmod(0o600);snapshot.execute('PRAGMA foreign_keys=ON')
        snapshot.executescript('''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE cases(case_id TEXT PRIMARY KEY,kind TEXT,route TEXT,payload_json TEXT NOT NULL);
          CREATE TABLE members(submission_id TEXT PRIMARY KEY,version_id TEXT,role TEXT,child_id TEXT,payload_json TEXT NOT NULL);
          CREATE TABLE case_members(case_id TEXT REFERENCES cases,submission_id TEXT REFERENCES members,PRIMARY KEY(case_id,submission_id));
          CREATE TABLE comparisons(case_id TEXT REFERENCES cases,record_a TEXT REFERENCES members,record_b TEXT REFERENCES members,
            direct_rule TEXT,same_child INTEGER,PRIMARY KEY(case_id,record_a,record_b));''')
        seen=set()
        try:
            with snapshot:
                for c in sorted(cases,key=lambda c:c['case_id']):
                    group=c.get('group_review');ids=group['members'] if group else [c['record_a'],c['record_b']]
                    snapshot.execute('INSERT INTO cases VALUES(?,?,?,?)',(c['case_id'],c['kind'],'awaiting_evidence',dumps(c)))
                    for sid in ids:
                        if sid not in seen:
                            r=record_snapshot(ctx.records[sid]);snapshot.execute('INSERT INTO members VALUES(?,?,?,?,?)',
                                (sid,r['version_id'],r['role'],r['child_id'],dumps(r)));seen.add(sid)
                        snapshot.execute('INSERT INTO case_members VALUES(?,?)',(c['case_id'],sid))
                    direct={tuple(sorted((p['a'],p['b']))):p['rule'] for p in group['passed_pairs']} if group else {}
                    for a,b in combinations(sorted(ids),2):
                        snapshot.execute('INSERT INTO comparisons VALUES(?,?,?,?,?)',(c['case_id'],a,b,direct.get((a,b)),
                            int(bool(ctx.records[a].get('child_id') and ctx.records[a]['child_id']==ctx.records[b].get('child_id')))))
                metadata={'format_version':1,'dataset_id':'WAIT_'+digest([ctx.release['release_id'],utcnow()])[:28],
                    'release_id':ctx.release['release_id'],'dispatch_policy':DISPATCH_POLICY,'created_at':utcnow(),
                    'main_revision':ctx.main_revision,'code_hashes':{p.name:file_hash(p) for p in
                        [Path(__file__),Path(__file__).with_name('review_groups.py'),Path(__file__).with_name('review_core.py')]},
                    'child_groups':sum(bool(c.get('group_review')) for c in cases),
                    'adult_comparisons':sum(c['kind']=='respondent' for c in cases),'unique_submissions':len(seen),
                    'meaning':'證據不足，暫不合併；不是人工 NONMATCH，不是需要逐宗填卡的清單'}
                snapshot.executemany('INSERT INTO metadata VALUES(?,?)',[(k,dumps(v)) for k,v in metadata.items()])
            assert snapshot.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert not snapshot.execute('PRAGMA foreign_key_check').fetchall()
        finally:
            snapshot.close()
        atomic_json(output/'manifest.json',{**metadata,'files':{'awaiting_evidence.sqlite':file_hash(path)}})
        (output/'README.md').write_text('# 證據不足，待新資料\n\n此固定版本保留尚未證實的跨子群連結及成人比較，不要求同事猜測身份。\n'
            '各子群及原始問卷仍保留；沒有新增 MATCH、NONMATCH 或資料排除。\n'
            '找到可核實來源後，由 Jarvis 登記來源、位置和具體問題，再匯出審核卡。\n'
            '新問卷可能補上聯絡連結，屆時重新計算；此快照不會自動更新或取代正式資料庫。\n',encoding='utf-8')
        return {**metadata,'output':str(output)}
    finally:
        main.close()
