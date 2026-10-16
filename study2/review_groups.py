"""One review per ambiguous child component, without changing scientific links.

Directly supported pairs are evidence, not repeated questions. A group verdict
is expanded into explicit, versioned pair decisions only after Jarvis approval.
"""
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from .common import PipelineError, contacts, digest, file_hash
from .matching import automatic_rule, hard_conflict


def direct_components(ids, passed_pairs):
    """Stable connected components of accepted direct contact evidence only."""
    parent = {sid: sid for sid in ids}
    def find(sid):
        while parent[sid] != sid:
            parent[sid] = parent[parent[sid]]
            sid = parent[sid]
        return sid
    for pair in passed_pairs:
        a, b = find(pair['a']), find(pair['b'])
        parent[max(a, b)] = min(a, b)
    components = defaultdict(list)
    for sid in sorted(ids):
        components[find(sid)].append(sid)
    return sorted(components.values())


def _group_pair_evidence(ids, prepared, router, policy):
    """Record all direct evidence and restrictions, including existing members."""
    passed, gaps, conflicts, restrictions = [], [], [], []
    for left, right in combinations(ids, 2):
        if hard_conflict(prepared[left], prepared[right]):
            conflicts.append([left, right])
        identities = tuple(sorted((router._find('child', left), router._find('child', right))))
        if identities in router.forbidden['child']:
            restrictions.append([left, right])
        rule = automatic_rule(prepared[left], prepared[right], policy)
        evidence = {'a': left, 'b': right, 'rule': rule}
        (passed if rule else gaps).append(evidence)
    return passed, gaps, conflicts, restrictions


def _has_incomplete_members(ids, records, prepared):
    from .review_dispatch import ELIGIBLE, _birthday

    return any(
        not _birthday(records[sid])
        or str(records[sid].get('gender')) not in {'0', '1'}
        or not records[sid].get('school')
        or not prepared[sid]['contacts']
        or records[sid].get('status') not in ELIGIBLE
        for sid in ids
    )


def _group_issue(conflicts, restrictions, incomplete, directly_connected):
    """Give contradictions priority over missing links when describing a group."""
    if conflicts:
        return 'identity_conflict'
    if restrictions:
        return 'manual_nonmatch'
    if incomplete:
        return 'incomplete_members'
    return 'contact_bridge' if directly_connected else 'contact_gap'


def build_groups(records, cases, decisions=(), policy=None):
    """Build scientific comparison scopes, independently of worker dispatch.

    Existing identities remain atomic. Pending comparisons add scope, not
    confirmed links; dispatch may later park a scope without changing it.
    """
    from .review_dispatch import Router
    router = Router(records, decisions)
    pairs = [c for c in cases.values() if c.get('kind') in {'identity', 'family'}
             and not c.get('group_review') and router.group_candidate(c)]
    parent = {sid: sid for sid in records}

    def find(sid):
        while parent[sid] != sid:
            parent[sid] = parent[parent[sid]]
            sid = parent[sid]
        return sid

    def join(a, b):
        a, b = find(a), find(b)
        parent[max(a, b)] = min(a, b)

    for sid in records:
        join(sid, router._find('child', sid))
    for c in pairs:
        join(c['record_a'], c['record_b'])
    members, selected = defaultdict(list), defaultdict(list)
    for sid in records:
        members[find(sid)].append(sid)
    for c in pairs:
        selected[find(c['record_a'])].append(c)
    prepared = {sid: {**r, 'contacts': contacts(r.get('answer', {}))} for sid, r in records.items()}
    groups = {}
    for root, candidates in sorted(selected.items()):
        ids = sorted(members[root])
        # The published group already settles these comparisons. No new question.
        if len({router._find('child', sid) for sid in ids}) == 1:
            continue
        passed, gaps, conflicts, restrictions = _group_pair_evidence(ids, prepared, router, policy)
        # Check every member: a clean representative must not conceal a
        # conflicting or incomplete response inherited from an existing identity.
        incomplete = _has_incomplete_members(ids, records, prepared)
        problem = bool(conflicts or restrictions or incomplete)
        gap = next((p for p in gaps if router._find('child', p['a']) != router._find('child', p['b'])), None)
        exemplar = gap or {'a': candidates[0]['record_a'], 'b': candidates[0]['record_b']}
        a, b = exemplar['a'], exemplar['b']
        components = direct_components(ids, passed)
        linked = len(components) == 1
        unresolved = [p for p in gaps if router._find('child', p['a']) != router._find('child', p['b'])]
        issue = _group_issue(conflicts, restrictions, incomplete, linked)
        gid = 'GROUP_' + digest(['child_review_v1', ids])[:28]
        groups[gid] = {'case_id': gid, 'kind': 'identity', 'rule': 'child_group_' + issue,
            'status': 'pending', 'record_a': a, 'record_b': b,
            'version_a': records[a]['version_id'], 'version_b': records[b]['version_id'],
            'reason': {'identity_conflict': '群組內存在孩子生日或性別矛盾，交指定執行者處理',
                       'manual_nonmatch': '群組含有效人工不配對限制，交指定執行者處理',
                       'incomplete_members': '已連結群組內有不合資格或身份／聯絡資料不足的提交，交指定執行者核對',
                       'contact_bridge': '直接規則已連起整組，但部分提交沒有直接共同聯絡；只核實整組連結',
                       'contact_gap': '組內有尚未連起的身份子群；請核實缺少直接證據的連結'}[issue],
            'group_review': {'format': 1, 'members': ids, 'comparison_ids': sorted(c['case_id'] for c in candidates),
                'member_roles': sorted({records[sid]['role'] for sid in ids}),
                'passed_pairs': passed, 'missing_pairs': gaps, 'conflicts': conflicts,
                'contact_components': components, 'unresolved_pairs': unresolved,
                'manual_restrictions': restrictions, 'issue': issue, 'route': 'operator' if problem else 'review'},
            'review_warnings': ['只核實子群之間尚缺證據的連結；已確認子群內的直接或間接連結毋須重審。',
                                '代表比較只指出缺口；結論適用於群組參考內的全部提交。',
                                '確認不同時，請在理由用 R 編號列出分組，交 Jarvis 裁定。']}
    return groups


def snapshot(ctx, case, record_snapshot):
    """Freeze complete group evidence and constraints for later version checks."""
    ids = set(case['group_review']['members'])
    records = {sid: record_snapshot(ctx.records[sid]) for sid in sorted(ids)}
    candidates = sorted((c for c in ctx.cases.values() if not c.get('group_review')
                         and c.get('record_a') in ids and c.get('record_b') in ids), key=lambda c: c['case_id'])
    evidence = {sid: {k: v for k, v in r.items() if k not in
                {'version_id', 'location', 'answer', 'source_id', 'source_label'}} for sid, r in records.items()}
    constraints = [d['payload'] for d in ctx.decisions
                   if {d['payload'].get('record_a'), d['payload'].get('record_b')} & ids]
    stable_cases = [{k: v for k, v in c.items() if k not in {'version_a', 'version_b'}} for c in candidates]
    signature = digest({'format': 1, 'group': case['group_review'], 'evidence': evidence,
                        'candidates': stable_cases, 'constraints': constraints, 'rules': ctx.rules,
                        'group_code': file_hash(Path(__file__))})
    return {'records': records, 'candidates': candidates, 'release_id': ctx.release['release_id'],
            'rules_hash': ctx.rules, 'signature': signature, 'original_manual_constraints': constraints}


def commands(ctx, task, answer, resolution, base_command):
    """Keep the group verdict and generate auditable pair instructions.

    NONMATCH means not all members are one child. It never means that every
    pair is different; Jarvis must specify a complete partition first.
    """
    case = ctx.cases[task['snapshot']['case']['case_id']]
    group = case['group_review']
    ids = group['members']
    if group['route'] != 'review':
        raise PipelineError('群組存在身份矛盾或有效人工不配對限制，須先用既有更正／裁定流程處理')
    label = answer['label']
    header = {**case, 'release_id': ctx.release['release_id'], 'action': '', 'label': label,
              'value': '', 'reviewer': answer['reviewer'], 'reason': answer['reason'],
              'evidence_source': answer['evidence_source'], 'pre_review': task['snapshot']['case'],
              'pre_review_release_id': task['snapshot']['release_id'], 'review_task_id': task['task_id']}
    if label == 'UNRESOLVED':
        return [header]
    partitions = [ids]
    if label == 'NONMATCH':
        partitions = (resolution or {}).get('group_partition')
        if not isinstance(partitions, list) or len(partitions) < 2 or any(not isinstance(p, list) or not p for p in partitions):
            raise PipelineError('整組確認不同需要 Jarvis 指定完整 group_partition；同事請在理由用 R 編號列出哪些提交屬同一孩子')
        flat = [s for p in partitions for s in p]
        if len(flat) != len(set(flat)) or set(flat) != set(ids):
            raise PipelineError('group_partition 必須完整涵蓋本組，每份提交只可出現一次')
    rows = [header]
    generated = set()

    def append(a, b, verdict):
        a, b = sorted((a, b))
        if (a, b) in generated:
            return
        generated.add((a, b))
        kind = 'family' if ctx.records[a]['role'] != ctx.records[b]['role'] else 'identity'
        from .matching import candidate
        pair = candidate(ctx.records[a], ctx.records[b], kind, 'group_review_decision', 'pending', '群組審核決定')
        pair = ctx.cases.get(pair['case_id'], pair)
        fake_task = {**task, 'snapshot': {**task['snapshot'], 'case': pair}}
        # NEW is supported by the canonical core for previously absent pairs.
        absent = pair['case_id'] not in ctx.cases
        if absent:
            ctx.cases[pair['case_id']] = pair
        command = base_command(ctx, fake_task, {**answer, 'label': verdict}, resolution)
        if absent:
            del ctx.cases[pair['case_id']]
            command['case_id'] = 'NEW'
        command.update(group_review_id=case['case_id'], group_review_signature=task['snapshot']['signature'])
        rows.append(command)
    for part in partitions:
        # A star records the complete explicitly reviewed membership, without
        # requiring helpers to answer n*(n-1)/2 repeated comparisons.
        for sid in sorted(part)[1:]:
            append(min(part), sid, 'MATCH')
    if label == 'NONMATCH':
        for i, left in enumerate(partitions):
            for right in partitions[i+1:]:
                for a in left:
                    for b in right:
                        append(a, b, 'NONMATCH')
    return rows
