"""Visible, read-only review of an explicitly pinned candidate proposal.

The candidate is separate from published workload. Rendering never applies a
decision, creates an identity question, or treats lineage evidence as approval.
"""
import hashlib
import html
import json
import os
from pathlib import Path

from .analysis_eligibility import sha
from .group_decision_intents import KIND, validate
from .group_cleaning import PolicyError
from .common import PipelineError

PATH_ENV = 'STUDY2_GROUP_INTENT_PREVIEW'
SHA_ENV = 'STUDY2_GROUP_INTENT_PREVIEW_SHA256'
PENDING = {'held', 'requires_existing_continuity_proof'}

REASONS = {
    'source_pin_changed':'Recorded submission version changed',
    'relevant_evidence_changed':'Identity or routing evidence changed',
    'subject_missing':'An earlier submission is missing',
    'supported_subgroup_boundary_changed':'Supported subgroup membership changed',
    'comparison_not_in_original_authorized_scope':'Comparison falls outside the earlier answer',
    'native_scope_hold':'The current scope has an evidence hold',
    'existing_continuity_guard_required':'Existing continuity proof is required',
    'outside_t0_t1':'Submission is outside the supported waves',
    'unknown_decision_semantics':'Earlier decision needs interpretation',
}


def _mapping(value, field):
    if not isinstance(value,dict):
        raise ValueError('preview_'+field+'_shape')
    return value


def _mapping_rows(value, field):
    if not isinstance(value,list) or any(not isinstance(row,dict) for row in value):
        raise ValueError('preview_'+field+'_shape')
    return value


def review_model(proposal):
    """One administrative item per intent, even with no current comparison."""
    proposal = _mapping(proposal,'proposal')
    if proposal.get('format')=='study2_admin_carry_preview_v1':
        from .administrative_carry_preview import validate_preview
        native,carry=validate_preview(proposal)
        if 'decision_intents' in native or 'decision_application' in native:
            model=review_model(native)
        else:
            # The accepted native target snapshot predates intent migration.
            # Its missing intent result is unavailable, never a fabricated zero.
            from .burst_hold_view import burst_hold_view
            burst=burst_hold_view(native,validated_revision=native['revision'])
            burst['rows']=[{**row,'Scope':f'Scope {i}'} for i,row in enumerate(burst['rows'],1)]
            model={'release_id':native['base']['release_id'],'proposal_revision':native['revision'],
                   'pending_intents':None,'rows':[],'applied':False,'burst_review':burst,
                   'intent_status':'Historical group-intent migration is unavailable in this native snapshot.'}
        model['administrative_carry']=carry
        return model
    base = _mapping(proposal.get('base'),'base')
    if not isinstance(base.get('release_id'),str) or not base['release_id']:
        raise ValueError('preview_release_id_shape')
    application = _mapping(proposal.get('decision_application'),'application')
    entries = _mapping_rows(application.get('entries'),'application_entries')
    if proposal.get('revision') != sha({k:v for k,v in proposal.items() if k != 'revision'}):
        raise ValueError('preview_proposal_revision_changed')
    collection = validate(_mapping(proposal.get('decision_intents'),'collection'))
    if (application.get('revision') != sha({k:v for k,v in application.items() if k != 'revision'}) or
        application.get('intent_revision') != collection['revision'] or
        application.get('release_id') != base['release_id']):
        raise ValueError('preview_application_binding_changed')
    lineage = {}
    if 'historical_continuity' in proposal:
        from .continuity_integration import check_intent_lineage
        binding = _mapping(proposal['historical_continuity'],'continuity')
        _mapping(binding.get('proof'),'proof')
        evidence = _mapping(binding.get('intent_lineage'),'lineage')
        for row in _mapping_rows(evidence.get('entries'),'lineage_entries'):
            _mapping_rows(row.get('original_subject_pins'),'original_pins')
            _mapping_rows(row.get('current_subject_pins'),'current_pins')
        if binding.get('revision') != sha({k:v for k,v in binding.items() if k != 'revision'}):
            raise ValueError('preview_continuity_binding_changed')
        lineage = check_intent_lineage(proposal)
    items = {i['decision_id']:i for i in collection['intents']}
    grouped = {key:[] for key in items}
    for entry in entries:
        if entry['decision_id'] not in grouped or entry['status'] not in PENDING | {'carried','not_applicable'}:
            raise ValueError('preview_application_scope_changed')
        grouped[entry['decision_id']].append(entry)
    if any(not entries for entries in grouped.values()):
        raise ValueError('preview_intent_result_missing')
    rows = []
    for number,item in enumerate(collection['intents'],1):
        entries = grouped[item['decision_id']]
        pending = [e for e in entries if e['status'] in PENDING]
        if not pending:continue
        evidence = lineage.get(item['decision_id'])
        recorded = evidence is not None and evidence['relevant_evidence_unchanged']
        changed = evidence['changed_subjects'] if evidence is not None else None
        rows.append({
            'Earlier decision':f'Decision {number}',
            'Recorded answer':'Keep existing subgroups' if item['kind'] == KIND else 'Earlier decision needs interpretation',
            'Original submissions':len(item['subjects']),
            'Current scopes':len({e['group_id'] for e in pending if e['group_id'] is not None}),
            'Current comparisons':len({cid for e in pending for cid in e['comparison_ids']}),
            'Evidence':('Creation-time lineage recorded in candidate' if changed else 'Original full pins recorded in candidate')
                       if recorded else ('Time lineage recorded; other evidence changed' if evidence else
                                         'Continuity evidence not verified in this preview'),
            'Changed submissions':changed if changed is not None else 'Not established',
            'Hold reason':'; '.join(sorted({REASONS.get(r,'Unrecognised hold reason; inspect the pinned proposal')
                                          for e in pending for r in e['reasons']})),
            'Next step':('Verify recorded lineage and review the candidate package using the earlier answer' if recorded else
                         'Inspect the changed evidence and preserve the earlier answer pending review'),
        })
    model = {'release_id':base['release_id'], 'proposal_revision':proposal['revision'],
             'pending_intents':len(rows), 'rows':rows, 'applied':False}
    from .burst_hold_view import burst_hold_view
    burst = burst_hold_view(proposal,validated_revision=model['proposal_revision'])
    # Keep private scope references in the pinned proposal, rather than exposing
    # generated identifiers in the public preview rows or console summary.
    burst['rows'] = [{**row,'Scope':f'Scope {number}'} for number,row in enumerate(burst['rows'],1)]
    model['burst_review'] = burst
    return model


def review_html(proposal):
    model = review_model(proposal)
    esc = lambda value:html.escape(str(value))
    def table(rows):
        columns = list(rows[0])
        head = ''.join('<th>'+esc(c)+'</th>' for c in columns)
        body = ''.join('<tr>'+''.join('<td>'+esc(row[c])+'</td>' for c in columns)+'</tr>' for row in rows)
        return '<table><thead><tr>'+head+'</tr></thead><tbody>'+body+'</tbody></table>'
    burst = model['burst_review']
    historical=('<p><strong>'+str(model['pending_intents'])+' earlier decisions require package or evidence review.</strong></p>'+
                (table(model['rows']) if model['rows'] else '<p>No pending group intents in this pinned preview.</p>'))
    if model['pending_intents'] is None:historical='<p>'+esc(model['intent_status'])+'</p>'
    carry=model.get('administrative_carry');admin=''
    if carry is not None:
        admin=('<h2>Provisional administrative carry</h2><p>Snapshot-bound plan; no rebind applied.</p><p><strong>'+
               str(carry['proposed_preserved_comparisons'])+' recorded closures proposed for preservation; '+
               str(carry['projected_active_comparisons'])+' projected active correction comparisons.</strong></p>'
               '<p>The native target snapshot still has '+str(carry['native_target_closed'])+' closed, '+
               str(carry['native_target_active'])+' active and '+str(carry['native_target_expired'])+
               ' expired closure bindings. Current state must be checked before any future action.</p>'+table(carry['rows']))
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<title>Candidate group decisions</title><style>body{font:16px system-ui;margin:32px;line-height:1.5}'
            'table{border-collapse:collapse;width:100%}th,td{padding:12px;border:1px solid #bbb;text-align:left;vertical-align:top}'
            'th{background:#edf2f7}</style><h1>Candidate group decisions</h1>'
            '<p>Unapplied preview. These administrative holds are separate from published workload. '
            'The recorded answers are preserved. No new identity answer is requested.</p>'
            '<p>Candidate release: '+esc(model['release_id'])+'</p>'+historical+admin+
            '<h2>Burst-rule evidence holds</h2><p><strong>'+str(burst['scope_count'])+
            ' scopes awaiting evidence; '+str(burst['distinct_submission_count'])+' submission records.</strong></p>'
            '<p>Scopes and submission records are separate units. Keep these counts separate from earlier '
            'decisions, identity-comparison work and exclusion counts. These holds do not add exclusions.</p>'+
            (table(burst['rows']) if burst['rows'] else '<p>No burst-rule evidence holds in this pinned preview.</p>')+
            '<p>This view checks the pinned candidate artifact. It does not independently authenticate its proof. '
            'Verify the recorded lineage before action; it does not approve or apply the candidate.</p>'
            '<p>Proposal revision: '+esc(model['proposal_revision'])+'</p></html>')


def load_preview(path, expected_sha256):
    p = Path(path)
    before = p.lstat()
    if p.is_symlink() or not p.is_file() or getattr(before,'st_flags',0) & 0x40000000:
        raise ValueError('preview_not_resident_regular_file')
    raw = p.read_bytes()
    after = p.lstat()
    identity = lambda s:(s.st_ino,s.st_size,s.st_mtime_ns)
    if identity(before) != identity(after) or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('preview_file_pin_changed')
    return review_model(json.loads(raw))


def render_candidate_preview(st, *, path=None, expected_sha256=None):
    path = path if path is not None else os.environ.get(PATH_ENV)
    expected_sha256 = expected_sha256 if expected_sha256 is not None else os.environ.get(SHA_ENV)
    if not path and not expected_sha256:return False
    st.subheader('Candidate group decisions')
    try:
        if not path or not expected_sha256:raise ValueError('preview_pin_required')
        model = load_preview(path,expected_sha256)
    except (OSError,ValueError,KeyError,TypeError,RecursionError,PolicyError,PipelineError):
        st.warning('Candidate group decisions are unavailable. Supply the exact proposal and its recorded SHA-256. '
                   'Unavailable evidence does not mean zero pending decisions.')
        return False
    st.caption('Unapplied candidate preview for '+model['release_id']+
               '. Separate from Current review workload and the published release.')
    st.caption('This view checks the pinned candidate artifact. Recorded lineage still needs independent verification before action.')
    if model['pending_intents'] is None:
        st.warning(model['intent_status'])
    else:st.metric('Earlier decisions requiring review',model['pending_intents'])
    if model['rows']:
        st.dataframe(model['rows'],hide_index=True,width='stretch')
        st.info('The recorded answers remain intact. Review the candidate package or changed evidence; '
                'this preview does not request a new identity answer or apply any decision.')
    elif model['pending_intents'] is not None:st.caption('No pending group intents in this pinned preview.')
    carry=model.get('administrative_carry')
    if carry is not None:
        st.markdown('**Provisional administrative carry**')
        st.caption('Snapshot-bound plan; no rebind applied. Current state must be checked before any future action.')
        st.metric('Recorded closures proposed for preservation',carry['proposed_preserved_comparisons'])
        st.metric('Projected active correction comparisons',carry['projected_active_comparisons'])
        st.caption(f"Native target snapshot: {carry['native_target_closed']} closed, {carry['native_target_active']} active, "
                   f"{carry['native_target_expired']} expired closure bindings. These are correction comparisons, not people.")
        st.dataframe(carry['rows'],hide_index=True,width='stretch')
    burst = model['burst_review']
    st.markdown('**Burst-rule evidence holds**')
    st.metric('Burst-rule scopes awaiting evidence',burst['scope_count'])
    st.metric('Submission records in burst holds',burst['distinct_submission_count'])
    st.caption('Scopes and submission records are separate units. Keep these counts separate from earlier '
               'decisions, identity-comparison work and exclusion counts. These holds do not add exclusions.')
    if burst['rows']:st.dataframe(burst['rows'],hide_index=True,width='stretch')
    else:st.caption('No burst-rule evidence holds in this pinned preview.')
    return True
