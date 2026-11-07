"""Attach the existing read-only controls UI to the accepted selected-child UI."""
from .selected_client_assets import APP_JS, STYLES

PRIVATE_NOTE = ('UNAPPLIED LOCAL CANDIDATE. Counts include a draft projection of carried '
                'exclusions, not activated controls. Same-child B/D may have different '
                'responding adults. Paired parent PHQ requires confirmed same-adult '
                'evidence. No formal activation or deployment.')


def decorate_html(html):
    html = html.replace('Study 2 Research Dashboard', 'Local Candidate Review')
    html = html.replace('Published aggregate snapshot', 'UNAPPLIED LOCAL CANDIDATE')
    return once(html, '<div class="shell">', '<div class="shell"><aside class="notice controls-provenance" id="selected-rehearsal-provenance">' + PRIVATE_NOTE + '</aside>')


def once(value, before, after):
    if value.count(before) != 1:
        raise ValueError('selected_client_integration_anchor_changed')
    return value.replace(before, after, 1)


def assemble(controls_js, control_render):
    app = once(APP_JS, 'function reviewWorkload(){',
               controls_js + '\n' + control_render + '\nfunction reviewWorkload(){\n  controlStatus();')
    app = once(app, 'return {...bd,analytical_run_id:c.run_id,',
               'return {...bd,...(S.controls_status?{controls_status_revision:S.controls_status.revision}:{}),analytical_run_id:c.run_id,')
    app = once(app, 'download({...value,release_context:S.release_context},',
               'download({...value,release_context:S.release_context,...(S.controls_status?{controls_status:S.controls_status}:{}),...(S.bd_projection?{bd_projection:S.bd_projection,bd_pairing_policy:S.bd_pairing_policy}:{})},')
    start = app.index('function overview() {')
    end = app.index('function controls(st, independent)', start)
    overview = app[start:end]
    overview = once(overview, '  reviewWorkload();\n', '')
    overview = once(overview, 'function overview() {\n', 'function overview() {\n  try {\n')
    if not overview.endswith('}\n'):
        raise ValueError('selected_overview_boundary_changed')
    overview = overview[:-2] + '  } finally { reviewWorkload(); }\n}\n'
    app = app[:start] + overview + app[end:]
    app = once(app, "'Published '+date(S.published_at)",
               "(S.release_context?.workload_scope==='candidate_controls_unapplied'?'Unpublished local candidate':'Published '+date(S.published_at))")
    app = once(app, 'Release-wide work under the pinned applied controls.',
               'Review workload from the pinned controls. Candidate values are unapplied; applied values are separately labelled.')
    app = once(app, 'count:w.correction_bundles,unit:"bundles"',
               'count:w.correction_bundles===null?"Not established":w.correction_bundles,unit:"bundles"')
    app = once(app, 'unit:"comparisons within those bundles"', 'unit:"comparisons"')
    return app, STYLES + '\n.controls-provenance{overflow-wrap:anywhere}\n'
