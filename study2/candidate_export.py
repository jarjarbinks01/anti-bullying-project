"""Read-only candidate aggregation. No database, publication pointer or activation."""
import argparse
import gzip
import json
import re
from pathlib import Path
import pandas as pd
from .common import PipelineError, digest, file_hash
from . import static_export as native
from .static_release_context import validate_release_context
from .controls_capture import code_revision as program_hash
from .bd_pairing import POLICY, project_published_selection
from .presentation.analysis_eligibility import candidate_exclusion_scope

SOURCES = {'merged_student_T0': ('student','T0'), 'merged_student_T1': ('student','T1'),
           'merged_parent_T0': ('parent','T0'), 'merged_parent_T1': ('parent','T1')}
REQUIRED = set(native.PUBLICATION_INPUTS) | {'checksums.json', 'run_manifest.json'}

def need(value, message):
    if not value: raise PipelineError('Candidate export: ' + message)

def export_candidate(spec, destination, *, progress=None):
    """Reviewed spec binds release files, draft manifest and candidate context.
    format=study2_local_candidate_export_v1, status=unapplied, release_dir,
    release_id, run_id, files={filename:sha256}, context={path,sha256},
    manual_manifest={path,sha256}, source_manifest={path,sha256}, exclusion_evidence={path,sha256}; optional controls={path,sha256}, minimum.
    """
    entry=spec['manual_manifest'];path=Path(entry['path'])
    need(path.is_file() and not path.is_symlink() and file_hash(path)==entry['sha256'], 'manifest pin mismatch')
    manifest=json.loads(path.read_text())
    need(manifest.get('format')=='study2_candidate_exclusion_manifest_v1' and
         manifest.get('status')=='draft_unapplied', 'draft candidate manifest required')
    with candidate_exclusion_scope(manifest['revision']):
        return _export_candidate(spec,destination,progress=progress)

def _export_candidate(spec, destination, *, progress=None):
    need(spec['format']=='study2_local_candidate_export_v1' and spec['status']=='unapplied', 'unsupported spec')
    folder=Path(spec['release_dir']); destination=Path(destination)
    need(folder.is_dir() and not folder.is_symlink(), 'regular release directory required')
    need(not destination.exists() and not destination.resolve().is_relative_to(folder.resolve()), 'fresh separate destination required')
    files=spec['files']; minimum=spec.get('minimum',0)
    required={'summary.json','analysis.parquet','parent_longitudinal.parquet','dyad_tracking.parquet',
              'descriptive_measurements.parquet','records.jsonl.gz','checksums.json','run_manifest.json'}
    need(required <= set(files) and set(files) <= REQUIRED, 'incomplete or unknown pin inventory')
    need({n for n in REQUIRED if (folder/n).exists()} == set(files), 'all available aggregation inputs must be pinned')
    def pin(path, wanted):
        path=Path(path);need(path.is_file() and not path.is_symlink(), 'regular input required')
        need(not getattr(path.stat(),'st_flags',0) & 0x40000000, 'input is not locally resident')
        need(file_hash(path)==wanted, 'input hash changed')
    def supplied(key):
        entry=spec[key];pin(entry['path'],entry['sha256']);return json.loads(Path(entry['path']).read_text())
    spec_revision=digest(spec);export_hash=program_hash()
    def verify():
        need(digest(spec)==spec_revision and program_hash()==export_hash,'spec or exporter changed')
        for name,wanted in files.items():pin(folder/name,wanted)
        for key in ('context','manual_manifest','controls','exclusion_evidence','source_manifest'):
            if key in spec:pin(spec[key]['path'],spec[key]['sha256'])
    verify()
    summary=json.loads((folder/'summary.json').read_text()); frozen=json.loads((folder/'run_manifest.json').read_text())
    checksums=json.loads((folder/'checksums.json').read_text())
    for name in set(files)-{'checksums.json','run_manifest.json'}:
        need(checksums.get(name)==files[name], 'release checksum mismatch: '+name)
    release_context=supplied('context');manual_manifest=supplied('manual_manifest')
    evidence=supplied('exclusion_evidence');source_manifest=supplied('source_manifest')
    from .presentation.analysis_eligibility import manifest_revision
    need(source_manifest.get('status')=='accepted' and
         source_manifest['revision']==manifest_revision(source_manifest)==manual_manifest['source_manifest_revision'],
         'accepted source manifest mismatch')
    entries=lambda m:sorted((r['submission_id'],r['version_id']) for r in m['entries'])
    need(entries(source_manifest)==entries(manual_manifest), 'candidate changed source exclusion union')
    need(evidence.get('format')=='study2_candidate_exclusion_evidence_v1' and
         evidence.get('status')=='draft_unapplied_not_native_staged' and
         evidence.get('draft_revision')==manual_manifest['revision'] and
         evidence.get('combined_entries')==len(manual_manifest['entries']) and
         evidence.get('source_approval',{}).get('revision')==source_manifest['revision'] and
         evidence.get('target_inventory_records')==summary['submissions'], 'draft evidence mismatch')
    need(all(evidence.get(k) is True for k in ('all_target_raw_hashes_verified','all_target_versions_match',
         'identical_copy_coverage_verified','no_new_exclusions','prior_union_exactly_equal')), 'draft evidence incomplete')
    need(any(Path(k).name=='records.jsonl.gz' and v['sha256']==files['records.jsonl.gz']
         for k,v in evidence['pins'].items()), 'draft target inventory pin mismatch')
    need(any(v['sha256']==spec['source_manifest']['sha256'] for v in evidence['pins'].values()),
         'draft source manifest pin mismatch')
    need(release_context['format']=='study2_candidate_release_context_v1', 'candidate context required')
    validate_release_context(release_context)
    need(summary['release_id']==spec['release_id']==release_context['release_id'], 'release mismatch')
    need(release_context['run_id']==spec['run_id'], 'run mismatch')
    need(release_context['program_hash']==summary['program_hash']==frozen['program_hash'], 'scientific program mismatch')
    need(release_context['run_fingerprint']==frozen['fingerprint'], 'run fingerprint mismatch')
    source_counts=summary['source_submission_counts']
    need(set(source_counts)==set(SOURCES) and sum(source_counts.values())==summary['submissions'], 'four-source count mismatch')
    imported=pd.DataFrame([{'source_type':'legacy_online','role':SOURCES[k][0],'wave':SOURCES[k][1], 'submissions':v} for k,v in source_counts.items()])
    frame=pd.read_parquet(folder/'analysis.parquet')
    need(set(frame.wave.unique()) <= {'T0','T1'}, 'only T0/T1 allowed')
    frame, parents, summary=project_published_selection(frame,pd.read_parquet(folder/'dyad_tracking.parquet'),summary)
    prepared=(frame,parents)
    bd_projection=dict(format='study2_bd_selected_projection_v1',policy=POLICY,source_release_id=spec['release_id'],
       source_analysis_sha256=files['analysis.parquet'],source_parent_sha256=files['parent_longitudinal.parquet'],
       source_tracking_sha256=files['dyad_tracking.parquet'],source_summary_sha256=files['summary.json'],
       source_checksums_sha256=files['checksums.json'])
    bd_projection['revision']=digest(bd_projection)
    release={'release_id':spec['release_id'],'run_id':spec['run_id']}
    run={'fingerprint':frozen['fingerprint']};school_binding=None;default_eligibility='on'
    build_scope_export=native.build_scope_export;build_snapshot=native.build_snapshot;plain=native.plain;pack_snapshot=native.pack_snapshot
    scope = build_scope_export(folder, summary, minimum, school_binding=school_binding, prepared=prepared)
    snapshot = build_snapshot(folder, summary, imported, minimum, progress, prepared=prepared)
    if bd_projection is not None:
        snapshot['bd_projection'] = bd_projection
    snapshot['published_at'] = None
    # Fine date/profile moments live only in separately lazy-loaded assets.
    # The same OFF/ON catalog is immutable in both snapshots, preserving the
    # existing exclusion wrapper's strict metadata comparison and hashes.
    if prepared is None:
        analysis = pd.read_parquet(folder / 'analysis.parquet')
        parent_path = folder / 'parent_longitudinal.parquet'
        parents = pd.read_parquet(parent_path) if parent_path.exists() else None
    else:
        analysis, parents = prepared
    measurements = pd.read_parquet(folder / 'descriptive_measurements.parquet')
    panel = None
    if summary.get('independent_parent'):
        from .parent_panel_views import read_panel
        panel = read_panel(folder)
    records = None
    if manual_manifest is not None:
        with gzip.open(folder / 'records.jsonl.gz', 'rt', encoding='utf-8') as handle:
            records = [json.loads(line) for line in handle if line.strip()]
    manual_export = None
    if release_context is not None and manual_manifest is None:
        raise PipelineError('Dashboard release context requires an accepted composed manifest.')
    if manual_manifest is not None:
        from .manual_exclusion_export import build_manual_export
        if release_context is not None:
            from .static_release_context import bind_release_context
            snapshot['release_context'] = bind_release_context(release_context, release, summary,
                run['fingerprint'], records, manual_manifest, default_eligibility=default_eligibility)
            snapshot['release_context']['workload_scope'] = 'candidate_controls_unapplied'
        manual_export = build_manual_export(snapshot, scope, records, analysis, parents,
            measurements, summary, imported, manual_manifest, panel=panel, progress=progress)
        if release_context is not None and manual_export['status'] != 'available':
            code = manual_export.get('code')
            suffix = ' (' + code + ')' if isinstance(code, str) and re.fullmatch('[a-z0-9_]+', code) else ''
            raise PipelineError('Dashboard release context requires a complete valid ON/OFF export.' + suffix)
    from .static_period_assets import prepare_assets, prepare_semester_assets
    accepted_on = manual_export is not None and manual_export['status'] == 'available'
    period_catalog, period_assets = prepare_assets(analysis, parents, measurements, summary,
        records=records, manifest=manual_manifest if accepted_on else None,
        panel=panel, minimum=minimum, progress=progress)
    semester_catalog, semester_assets = prepare_semester_assets(analysis, parents, measurements, summary,
        records=records, manifest=manual_manifest if accepted_on else None,
        panel=panel, minimum=minimum, progress=progress)
    snapshot['period_selection'] = period_catalog
    snapshot['period_semester_selection'] = semester_catalog
    if manual_export is not None:
        # Add the same validated lazy index to both immutable snapshots.
        # Only an already valid ON bundle can authorize an ON period cube.
        from .presentation.analysis_eligibility import sha
        from .manual_exclusion_export import validate_manual_export
        manual_export['off']['snapshot_revision'] = sha(plain(pack_snapshot(snapshot)))
        if accepted_on:
            manual_export['on']['snapshot']['period_selection'] = plain(period_catalog)
            manual_export['on']['snapshot']['period_semester_selection'] = plain(semester_catalog)
            manual_export['on_revision'] = sha(manual_export['on'])
        validate_manual_export(manual_export, snapshot, scope)

    for candidate_snapshot in (snapshot, manual_export['on']['snapshot']):
        candidate_snapshot['notes'] = [*candidate_snapshot['notes'], ['Candidate status', 'Draft carried exclusions; unapplied local candidate.']]
    from .presentation.analysis_eligibility import sha
    manual_export['off']['snapshot_revision']=sha(plain(pack_snapshot(snapshot)))
    manual_export['on_revision']=sha(manual_export['on'])
    if 'controls' in spec:
        from .static_controls import validate
        controls=supplied('controls')
        validate(controls,snapshot['release_id'],snapshot['release_context'])
        need(controls['applied_carry'].get('status')=='unavailable','candidate cannot claim applied carry')
        snapshot['controls_status']=controls
        manual_export['on']['snapshot']['controls_status']=controls
        from .presentation.analysis_eligibility import sha
        manual_export['off']['snapshot_revision']=sha(plain(pack_snapshot(snapshot)))
        manual_export['on_revision']=sha(manual_export['on'])
    verify()
    inventory={name:{'sha256':value} for name,value in files.items()}
    inventory.update(candidate_spec={'sha256':spec_revision},export_program_hash={'sha256':export_hash},
                     candidate_context={'sha256':spec['context']['sha256']},
                     candidate_exclusions={'sha256':spec['manual_manifest']['sha256']},
                     candidate_exclusion_evidence={'sha256':spec['exclusion_evidence']['sha256']},
                     source_exclusions={'sha256':spec['source_manifest']['sha256']})
    return native.write_site(snapshot,destination,scope_export=scope,manual_exclusion=manual_export,
        verify_inputs=verify,input_inventory=inventory,period_assets=period_assets,semester_assets=semester_assets)

def main():
    parser=argparse.ArgumentParser(description='Unapplied local candidate export; no activation')
    parser.add_argument('--spec',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();print(json.dumps(export_candidate(json.loads(args.spec.read_text()),args.output)))

if __name__=='__main__':main()
