"""Reversible review routing. Never matching, field correction or wave selection.

User policy retains documented PHONE similarity only. Exact accepted phone/email
identity evidence remains protected. No fuzzy-email check exists in this module.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date
from pathlib import Path
import re

from .analysis_eligibility import (COPY_POLICY, MANIFEST_FORMAT, inventory_revision,
    manifest_revision, sha, validate_manifest)
from .common import PipelineError, contacts, fuzzy_phone, phone, text, timestamp, digest, file_hash

POLICY = 'phone_similarity_review_and_reversible_scope_separation_v1'
BURST_POLICY = 'more_than_5_established_children_same_genuine_source_full_span_le120s_v1'
SOURCE_FORMAT = 'study2_group_source_evidence_v1'
PROPOSAL_FORMAT = 'study2_group_cleaning_proposal_v1'
PHONE_FIELDS = ('contact_01','contact_02','contact_03.1','contact_03.2','contact_03.3','contact_03.4')


def implementation_revision():
    return sha({n:file_hash(Path(__file__).parent/n) for n in
        ('group_cleaning.py','group_cleaning_operator.py','review_dispatch.py','common.py','manual_flags.py','analysis_eligibility.py')})


class PolicyError(PipelineError):
    pass


def need(ok, code):
    if not ok:
        raise PolicyError(code)


def pin(record):
    need(isinstance(record.get('submission_id'),str) and bool(record['submission_id'])
         and isinstance(record.get('version_id'),str) and bool(record['version_id']), 'record_pin_required')
    return {k:record[k] for k in ('submission_id','version_id')}


def _contact_view(record):
    answer=record.get('answer',{})
    parsed=contacts(answer)  # Exactly the child engine's existing parser.
    invalid=[]
    for name in PHONE_FIELDS:
        for token in re.split(r'[/;,]',text(answer.get(name))):
            token=token.strip()
            if token and not phone(token) and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',token):
                invalid.append(dict(field=name,raw=token))
    return dict(values=sorted(parsed),phones=sorted(x for x in parsed if '@' not in x),
                invalid=invalid,current_values={k:deepcopy(answer[k]) for k in PHONE_FIELDS if k in answer},
                source_values={k:deepcopy(record.get('raw',{}).get(k)) for k in PHONE_FIELDS},
                source_location=deepcopy(record.get('location')),source_id=record.get('source_id'),
                source_label=record.get('source_label'),child_id=record.get('child_id'),
                role=record.get('role'),selected_wave=record.get('selected_wave'),status=record.get('status'))


def _profile(record):
    try:
        dob=date.fromisoformat(text(record.get('dob'))).isoformat()
    except ValueError:
        dob=''
    return dob,text(record.get('gender')),text(record.get('school'))


def _atoms(records, ids, passed, extra):
    parent={sid:sid for sid in ids}
    def find(s):
        while parent[s]!=s:
            parent[s]=parent[parent[s]];s=parent[s]
        return s
    def join(a,b):
        need(a in parent and b in parent,'protected_member_outside_scope')
        a,b=find(a),find(b);parent[max(a,b)]=min(a,b)
    child={}
    for sid in ids:
        c=records[sid].get('child_id')
        if c:
            if c in child:join(child[c],sid)
            else:child[c]=sid
    for pair in passed:
        a,b=pair.get('a',pair.get('record_a')),pair.get('b',pair.get('record_b'))
        need(a in parent and b in parent,'protected_member_outside_scope')
        # A direct-rule witness does not silently repair a disagreement with the
        # established identity inventory. The caller gets an explicit hold.
        if not (records[a].get('child_id') and records[b].get('child_id') and
                records[a]['child_id']!=records[b]['child_id']):join(a,b)
    for members in extra:
        members=list(members)
        need(len({records[s].get('child_id') for s in members if records[s].get('child_id')})<=1,
             'protected_set_conflicts_with_established_identity')
        for sid in members[1:]:join(members[0],sid)
    groups=defaultdict(list)
    for sid in ids:groups[find(sid)].append(sid)
    return sorted(sorted(v) for v in groups.values())


def classify_scope(records, group, comparisons, *, protected_sets=(), partition=None):
    """Question units come only from concrete original cross-atom comparisons."""
    need(isinstance(records,dict) and isinstance(comparisons,dict),'mapping_inputs_required')
    g=group['group_review'];ids=sorted(g['members'])
    need(ids and len(ids)==len(set(ids)) and set(ids)<=records.keys(),'scope_members_invalid')
    atoms=_atoms(records,ids,g.get('passed_pairs',()),protected_sets)
    atom_of={sid:i for i,atom in enumerate(atoms) for sid in atom}
    if partition is not None:
        need(isinstance(partition,list) and all(isinstance(x,list) and x for x in partition),'partition_shape')
        flat=[sid for block in partition for sid in block]
        need(len(flat)==len(set(flat)) and set(flat)==set(ids),'partition_membership')
        where={sid:i for i,block in enumerate(partition) for sid in block}
        need(all(len({where[s] for s in atom})==1 for atom in atoms),'partition_splits_supported_identity')
        # This extension closes between existing subgroups; it grants no new LINK.
        need({tuple(sorted(x)) for x in partition}=={tuple(x) for x in atoms},'partition_must_preserve_existing_subgroups')
    snapshot=[dict(pin(records[s]),child_id=records[s].get('child_id'),
        dob=records[s].get('dob'),gender=records[s].get('gender'),school=records[s].get('school'),
        contacts=_contact_view(records[s]),status=records[s].get('status')) for s in ids]
    concrete=[]
    for cid in sorted(set(g.get('comparison_ids',()))):
        need(cid in comparisons,'concrete_comparison_missing')
        c=comparisons[cid];a,b=c.get('record_a'),c.get('record_b')
        need(a in atom_of and b in atom_of,'comparison_outside_scope')
        if atom_of[a]!=atom_of[b]:concrete.append(c)
    binding=sha(dict(policy=POLICY,group_id=group['case_id'],records=snapshot,atoms=atoms,
                     cases=concrete,partition=partition,scope_constraints={
                         k:g.get(k) for k in ('conflicts','manual_restrictions','issue')}))
    pairs=defaultdict(list)
    for c in concrete:pairs[tuple(sorted((atom_of[c['record_a']],atom_of[c['record_b']])))].append(c)
    result=dict(group_id=group['case_id'],policy=POLICY,binding=binding,
                protected_atoms=atoms,partition=deepcopy(partition),questions=[],holds=[],closures=[])
    scope_problem=bool(g.get('conflicts') or g.get('manual_restrictions') or g.get('issue') in
                       {'identity_conflict','manual_nonmatch','incomplete_members'})
    scope_problem=scope_problem or any(atom_of[p['a']]!=atom_of[p['b']] for p in g.get('passed_pairs',()))
    for (left,right),cs in sorted(pairs.items()):
        members=atoms[left]+atoms[right]
        views={sid:_contact_view(records[sid]) for sid in members}
        profiles=[_profile(records[sid]) for sid in members]
        reasons=[];fuzzy=[];exact=[]
        if scope_problem:reasons.append('scope_conflict_or_manual_restriction')
        if any(not records[s].get('child_id') or records[s].get('status') not in
               {'eligible','short_repeat','short_interval_followup','extra_followup'} for s in members):
            reasons.append('unestablished_or_ineligible_member')
        if any(not d or sex not in {'0','1'} or not school for d,sex,school in profiles):
            reasons.append('missing_or_invalid_identity_field')
        if len({d for d,_,_ in profiles if d})>1 or len({s for _,s,_ in profiles if s in {'0','1'}})>1:
            reasons.append('contradictory_child_identity')
        contact_problem=any(v['invalid'] or not v['values'] for v in views.values())
        # All original members of both supported atoms are inspected. Retained
        # edges remain concrete; similarity elsewhere is evidence on that same
        # atom pair, never a new question to an unrelated third atom.
        for a in atoms[left]:
            for b in atoms[right]:
                common=set(views[a]['values']) & set(views[b]['values'])
                if common:exact.append(dict(a=a,b=b,values=sorted(common)))
                for x in views[a]['phones']:
                    for y in views[b]['phones']:
                        if fuzzy_phone(x,y):fuzzy.append(dict(a=a,b=b,phone_a=x,phone_b=y,
                            criterion='one_position_substitution_or_two_position_digit_exchange'))
        if exact:reasons.append('exact_contact_across_unconfirmed_atoms')
        row=dict(question_id='GQ_'+sha([POLICY,group['case_id'],atoms[left],atoms[right],sorted(c['case_id'] for c in cs)])[:28],
                 group_id=group['case_id'],binding=binding,atom_a=atoms[left],atom_b=atoms[right],
                 comparison_ids=sorted(c['case_id'] for c in cs),
                 member_pins=[pin(records[s]) for s in sorted(members)],
                 contact_evidence=views,similarity=fuzzy,exact_cross_contacts=exact,
                 scientific_identity_changed=False,permanent_nonmatch=False)
        if reasons:
            result['holds'].append(dict(row,reasons=sorted(set(reasons))))
        elif partition is not None:
            result['closures'].append(dict(row,reasons=['explicit_user_partition_of_existing_subgroups']))
        elif contact_problem:
            result['holds'].append(dict(row,reasons=['missing_invalid_or_uncertain_contact']))
        elif fuzzy:
            result['questions'].append(dict(row,reasons=['existing_valid_phone_similarity']))
        else:
            result['closures'].append(dict(row,reasons=['known_nonblank_contacts_without_phone_similarity_user_policy']))
    return result


def burst_candidate(records, member_ids, source_evidence):
    ids=sorted(member_ids)
    need(ids and len(ids)==len(set(ids)) and set(ids)<=records.keys(),'burst_members_invalid')
    out=dict(policy=BURST_POLICY,member_pins=[pin(records[s]) for s in ids],
             established_identities=len({records[s].get('child_id') for s in ids if records[s].get('child_id')}),
             outcome='not_burst',reasons=[],span_seconds=None,source_key=None)
    if any(not records[s].get('child_id') for s in ids):
        return dict(out,outcome='hold',reasons=['unestablished_child_identity'])
    if out['established_identities']<=5:return dict(out,reasons=['identity_count_not_more_than_five'])
    if (not isinstance(source_evidence,dict) or set(source_evidence)!={'format','records','revision'} or
            source_evidence['format']!=SOURCE_FORMAT or source_evidence['revision']!=sha(
                {k:v for k,v in source_evidence.items() if k!='revision'})):
        return dict(out,outcome='hold',reasons=['source_evidence_revision_invalid_or_missing'])
    times=[];sources=[];evidence=[];reasons=[]
    required={'submission_id','version_id','raw_hash','source_key','observed_at','raw_timestamp',
              'timestamp_kind','precision','origin_kind','source'}
    for sid in ids:
        r=records[sid];p=source_evidence['records'].get(sid)
        if not isinstance(p,dict) or set(p)!=required:
            reasons.append('source_proof_shape_or_membership');continue
        if any(p.get(k)!=r.get(k) for k in ('submission_id','version_id','raw_hash')):
            reasons.append('source_proof_version_drift');continue
        if not isinstance(r.get('raw'),dict) or digest(r['raw'])!=r.get('raw_hash'):
            reasons.append('source_record_raw_hash_invalid');continue
        ref=p.get('source')
        if (not isinstance(ref,dict) or set(ref)!={'path','sha256','sheet','row','column'} or
                not all(isinstance(ref[k],str) and ref[k] for k in ('path','sheet','column')) or
                not re.fullmatch('[0-9a-f]{64}',str(ref.get('sha256',''))) or
                type(ref['row']) is not int or ref['row']<1):
            reasons.append('source_cell_provenance_invalid');continue
        if (r.get('date_basis') != 'system_creation' or
                r.get('time_confidence') != 'observed' or
                p['timestamp_kind']!='genuine_submission' or p['precision'] not in {'second','subsecond'} or
                p['origin_kind'] not in {'qualtrics','old_system'}):
            reasons.append('timestamp_not_proven_genuine_precise_submission');continue
        observed=timestamp(p['observed_at'])
        genuine=text(r.get('raw',{}).get('Survey')).lower()
        label=text(r.get('source_label')).lower()
        pattern=r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})'
        raw_created=text(r.get('raw',{}).get('建立時間'))
        if (not isinstance(p['observed_at'],str) or not re.fullmatch(pattern,p['observed_at']) or
                not isinstance(p['raw_timestamp'],str) or not re.fullmatch(pattern,p['raw_timestamp']) or
                not re.fullmatch(pattern,raw_created) or timestamp(raw_created)!=observed or
                not observed or observed!=timestamp(r.get('observed_at')) or
                timestamp(p['raw_timestamp'])!=observed or
                not genuine or not label or genuine!=label or
                p['source_key']!=genuine or
                p['origin_kind']!=('qualtrics' if 'qualtrics' in genuine else 'old_system') or
                genuine.startswith(('paperform','separate_data','socialworkdream'))):
            reasons.append('timestamp_or_source_binding_invalid');continue
        times.append(observed);sources.append(p['source_key']);evidence.append(deepcopy(p))
    if reasons:return dict(out,outcome='hold',reasons=sorted(set(reasons)),source_evidence_revision=source_evidence['revision'])
    if len(set(sources))!=1:return dict(out,reasons=['multiple_genuine_sources'],source_evidence_revision=source_evidence['revision'])
    span=(max(times)-min(times)).total_seconds()
    return dict(out,outcome='candidate' if span<=120 else 'not_burst',
                reasons=['same_source_full_range_within_120_seconds'] if span<=120 else ['full_range_exceeds_120_seconds'],
                span_seconds=span,source_key=sources[0],source_evidence_revision=source_evidence['revision'],
                source_proofs=evidence,earliest=min(times).isoformat(),latest=max(times).isoformat())


def project_workload(records, cases, groups, decisions=(), *, excluded=(), partitions=None):
    """Read-only projection. Correction cases are never policy-closed."""
    from .review_dispatch import Router
    excluded=set(excluded);partitions=partitions or {}
    need(excluded<=records.keys(),'unknown_excluded_member')
    results={gid:classify_scope(records,g,cases,partition=partitions.get(gid))
             for gid,g in sorted(groups.items()) if not excluded.intersection(g['group_review']['members'])}
    # Exclusion is not a reason to discard a whole scope. Reduce its members and
    # concrete edges, preserving surviving child atoms and supported pairs.
    for gid,g in sorted(groups.items()):
        if not excluded.intersection(g['group_review']['members']):continue
        cut=deepcopy(g);v=cut['group_review'];v['members']=[s for s in v['members'] if s not in excluded]
        v['comparison_ids']=[cid for cid in v['comparison_ids'] if not excluded.intersection(
            {cases[cid]['record_a'],cases[cid]['record_b']})]
        v['passed_pairs']=[p for p in v.get('passed_pairs',[]) if not excluded.intersection({p['a'],p['b']})]
        endpoints=lambda p:{p.get('a'),p.get('b')} if isinstance(p,dict) else set(p)
        v['conflicts']=[p for p in v.get('conflicts',[]) if not excluded.intersection(endpoints(p))]
        v['manual_restrictions']=[p for p in v.get('manual_restrictions',[]) if not excluded.intersection(endpoints(p))]
        if not v['members'] or not v['comparison_ids']:continue
        partition=partitions.get(gid)
        partition=[[s for s in block if s not in excluded] for block in partition] if partition is not None else None
        partition=[b for b in partition if b] if partition is not None else None
        results[gid]=classify_scope(records,cut,cases,partition=partition)
    router=Router(records,decisions)
    corrections=[cid for cid,c in cases.items() if not c.get('group_review') and c.get('status')=='pending'
        and router.classify(c)['route']=='correction' and not excluded.intersection({c['record_a'],c.get('record_b')})]
    questions=[q for r in results.values() for q in r['questions']]
    holds=[q for r in results.values() for q in r['holds']]
    closures=[q for r in results.values() for q in r['closures']]
    closed_ids={cid for q in closures for cid in q['comparison_ids']}
    need(not closed_ids.intersection(corrections),'policy_closure_cannot_erase_field_correction')
    pending=[cid for cid,c in cases.items() if c.get('status')=='pending' and not c.get('group_review')
             and c.get('kind') in {'identity','family','respondent'} and c.get('record_b')
             and cid not in closed_ids and not excluded.intersection({c['record_a'],c['record_b']})]
    adults=[cid for cid in pending if cases[cid]['kind']=='respondent']
    return dict(policy=POLICY,scopes=results,questions=questions,holds=holds,closures=closures,
                correction_comparison_ids=sorted(corrections),excluded_ids=sorted(excluded),
                pending_comparison_ids=sorted(pending),adult_comparison_ids=sorted(adults),
                counts=dict(similarity_questions=len(questions),similarity_scopes=len({q['group_id'] for q in questions}),
                    edge_holds=len(holds),held_scopes=len({q['group_id'] for q in holds}),
                    policy_closed_links=len(closures),policy_closed_scopes=len({q['group_id'] for q in closures}),
                    field_correction_comparisons=len(corrections),remaining_pending_comparisons=len(pending),
                    remaining_open_group_scopes=len({q['group_id'] for q in questions+holds}),
                    separate_adult_comparisons=len(adults)),science_changed=False)


def exclusion_manifest(records, release_id, ids, *, operator, at):
    ids=set(ids);need(ids<={r['submission_id'] for r in records},'unknown_flag_id')
    need(isinstance(operator,str) and bool(operator.strip()),'operator_required')
    m=dict(format=MANIFEST_FORMAT,release_id=release_id,inventory_revision=inventory_revision(records),
        status='accepted',approved_by=operator,approved_at=at,copy_policy=COPY_POLICY,
        entries=sorted([pin(r) for r in records if r['submission_id'] in ids],key=lambda p:p['submission_id']))
    m['revision']=manifest_revision(m);validate_manifest(m,records,release_id)
    return m


def combined_manifest(records, release_id, eric_manifest, policy_manifest, *, operator, at):
    a=validate_manifest(eric_manifest,records,release_id)
    b=validate_manifest(policy_manifest,records,release_id)
    return exclusion_manifest(records,release_id,a|b,operator=operator,at=at)


def make_proposal(records, cases, groups, decisions, *, release_id, main_revision,
                  rules_hash, eric_manifest, source_evidence, partitions=None,
                  user_exclusions=None, authorization=None, prior_policy_manifest=None,
                  prior_policy_origin_revision=None, prior_policy_head=None):
    """Deterministic dry-run used again at apply; no approval or persistence."""
    rows=list(records.values());partitions=partitions or {};user_exclusions=user_exclusions or {}
    eric=validate_manifest(eric_manifest,rows,release_id)
    need(re.fullmatch('[0-9a-f]{64}',str(main_revision)) and
         re.fullmatch('[0-9a-f]{64}',str(rules_hash)),'control_revision_required')
    authorization=authorization or {}
    if partitions or user_exclusions:
        need(set(authorization)=={'workbook_sha256','request_sha256','partition_groups','user_exclusion_groups'},'explicit_authorization_shape')
        need(all(re.fullmatch('[0-9a-f]{64}',str(authorization[k])) for k in
                 ('workbook_sha256','request_sha256')),'authorization_hash_required')
        need(set(partitions)==set(authorization['partition_groups']) and
             set(user_exclusions)==set(authorization['user_exclusion_groups']),'authorization_group_scope_mismatch')
    need(set(partitions)<=groups.keys() and set(user_exclusions)<=groups.keys(),'explicit_group_missing_or_changed')
    directed=[]
    for gid,targets in sorted(user_exclusions.items()):
        expected=sorted([pin(records[s]) for s in groups[gid]['group_review']['members']],key=lambda p:p['submission_id'])
        need(sorted(targets,key=lambda p:p['submission_id'])==expected,'user_exclusion_exact_versions_required')
        directed.append(dict(group_id=gid,member_pins=expected,authority='explicit_user_exclusion',
                             fraud_proven=False))
    bursts=[];burst_holds=[]
    for gid,g in sorted(groups.items()):
        b=burst_candidate(records,g['group_review']['members'],source_evidence)
        if b['outcome']=='candidate':bursts.append(dict(b,group_id=gid))
        elif b['outcome']=='hold':burst_holds.append(dict(b,group_id=gid))
    user_ids={p['submission_id'] for g in directed for p in g['member_pins']}
    burst_ids={p['submission_id'] for g in bursts for p in g['member_pins']}
    prior_ids=(validate_manifest(prior_policy_manifest,rows,release_id)
               if prior_policy_manifest is not None else frozenset())
    active_ids=user_ids|burst_ids|prior_ids
    # Existing copy/version policy is reused, not circumvented by a new lane.
    exclusion_manifest(rows,release_id,active_ids,operator='dry_run_only',at=eric_manifest['approved_at'])
    before=project_workload(records,cases,groups,decisions,excluded=eric,partitions={})
    after=project_workload(records,cases,groups,decisions,excluded=eric|active_ids,partitions=partitions)
    dispositions=Counter()
    for gid,g in groups.items():
        active=after['scopes'].get(gid)
        if set(g['group_review']['members'])<=(eric|active_ids):dispositions['fully_flag_excluded']+=1
        elif active and active['questions']:dispositions['retains_phone_question']+=1
        elif active and active['holds']:dispositions['edge_hold_only']+=1
        else:dispositions['policy_closed']+=1
    bindings={gid:classify_scope(records,g,cases,partition=partitions.get(gid))['binding']
              for gid,g in sorted(groups.items())}
    base=dict(release_id=release_id,inventory_revision=inventory_revision(rows),
              main_revision=main_revision,rules_hash=rules_hash,eric_revision=eric_manifest['revision'],
              implementation_revision=implementation_revision(),
              prior_policy_revision=prior_policy_manifest['revision'] if prior_policy_manifest else None,
              prior_policy_origin_revision=prior_policy_origin_revision,
              prior_policy_head=prior_policy_head,
              source_evidence_revision=source_evidence.get('revision') if isinstance(source_evidence,dict) else None,
              view_revision=sha(dict(records=records,cases=cases,groups=groups,decisions=decisions)))
    result=dict(format=PROPOSAL_FORMAT,policy=POLICY,burst_policy=BURST_POLICY,base=base,
        authorization=deepcopy(authorization),partitions=deepcopy(partitions),group_bindings=bindings,
        user_directed_flags=directed,rule_derived_flags=bursts,burst_holds=burst_holds,
        flag_entries=sorted([pin(records[s]) for s in active_ids],key=lambda p:p['submission_id']),
        projection=after,group_dispositions=dict(dispositions),
        baseline_counts=dict(before['counts'],original_child_scopes=len(groups),
            original_scope_comparison_ids=len({cid for g in groups.values() for cid in g['group_review']['comparison_ids']}),
            original_pending_comparisons=sum(bool(c.get('status')=='pending' and c.get('record_b') and not c.get('group_review')
                and not eric.intersection({c['record_a'],c['record_b']})) for c in cases.values())),
        flag_counts=dict(user_groups=len(directed),user_records=len(user_ids),rule_groups=len(bursts),
            rule_records=len(burst_ids),user_rule_overlap=len(user_ids&burst_ids),
            union_policy_records=len(active_ids),eric_overlap=len(active_ids&eric),
            preserved_prior_policy_records=len(prior_ids),newly_excluded=len(active_ids-eric-prior_ids)),
        science_changed=False,permanent_nonmatch=False)
    result['revision']=sha(result)
    return result


def validate_proposal(proposal, records, cases, groups, decisions, **options):
    need(isinstance(proposal,dict) and proposal.get('format')==PROPOSAL_FORMAT,'proposal_format')
    need(proposal.get('revision')==sha({k:v for k,v in proposal.items() if k!='revision'}),'proposal_revision_mismatch')
    expected=make_proposal(records,cases,groups,decisions,**options)
    need(proposal==expected,'proposal_context_or_decision_drift')
    return proposal
