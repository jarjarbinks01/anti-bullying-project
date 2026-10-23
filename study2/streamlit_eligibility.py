"""Session-only Streamlit adapter over the shared fixed-membership projection.

This module never discovers a manifest, applies a correction, or writes a release.
Callers supply canonical frames; all exposed analytical frames are copies.
"""
from copy import deepcopy
from dataclasses import dataclass, field, replace
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re

import pandas as pd

from .analysis_eligibility import (EligibilityError, POLICY, inventory_revision,
                                   project_eligibility, projected_cohorts)
from .dashboard_views import SAMPLE_NAMES, SLOTS, selected_sample
from .descriptive_spec import VERSION

ENVIRONMENT_KEY = 'STUDY2_MANUAL_EXCLUSION_MANIFEST'
SESSION_KEY = 'manual_exclusion_enabled'
NATIVE_CODES = ('A','B','C','D','AC','BD','E','F','EF')


class ActiveEligibilityUnavailable(RuntimeError):
    """A requested ON view has no validated projection; never substitute OFF."""


def _copy_panel(panel):
    return None if panel is None else {k:v.copy(deep=True) for k,v in panel.items()}


@dataclass(frozen=True)
class EligibilityState:
    release_id: str
    enabled: bool = False
    ready: bool = False
    reason: str = 'accepted_manifest_not_supplied'
    revision: str | None = None
    inventory: str | None = None
    _off: object = field(default=None, repr=False)
    _on: object = field(default=None, repr=False)
    _off_rows: dict = field(default_factory=dict, repr=False)
    _on_rows: dict = field(default_factory=dict, repr=False)
    _measurements: object = field(default=None, repr=False)
    _panel: object = field(default=None, repr=False)

    @property
    def allowed(self):
        return not self.enabled or self.ready

    def select(self, enabled):
        if type(enabled) is not bool:
            raise TypeError('eligibility_mode_must_be_boolean')
        return replace(self, enabled=enabled)

    def require_active(self):
        if not self.allowed:
            raise ActiveEligibilityUnavailable(self.reason)

    def metadata(self, *, reference=False):
        return dict(eligibility_mode='off' if reference else 'on' if self.enabled else 'off',
                    eligibility_revision=self.revision or 'not_available',
                    eligibility_inventory_revision=self.inventory or 'not_available',
                    eligibility_release_id=self.release_id, eligibility_policy=POLICY,
                    eligibility_status='available' if self.ready else 'unavailable',
                    eligibility_reference='published_off_reference' if reference else 'active_analysis',
                    eligibility_requested_mode='on' if self.enabled else 'off')

    def cohort(self, mode, role):
        self.require_active()
        table=(self._on_rows if self.enabled else self._off_rows).get((mode,role))
        if table is None and self.enabled:
            raise ActiveEligibilityUnavailable('prepared_cohort_unavailable')
        return None if table is None else table.copy(deep=True)

    def catalogue(self, mode, role):
        table=self._off_rows.get((mode,role))
        return None if table is None else table.copy(deep=True)

    def measurements(self):
        return None if self._measurements is None else self._measurements.copy(deep=True)

    def canonical_panel(self):
        return _copy_panel(self._panel)

    def analytical_frame(self, canonical):
        self.require_active()
        return (self._on.frame if self.enabled else canonical).copy(deep=True)

    def independent_pairs(self, canonical, branch):
        self.require_active()
        if not self.enabled:
            return canonical.copy(deep=True)
        mode='independent_adult' if branch=='same_adult' else 'independent_child'
        ids=set(self.cohort(mode,'parent').submission_id)
        return canonical.loc[canonical.panel_branch.eq(branch)&canonical.t0.isin(ids)&canonical.t1.isin(ids)].copy(deep=True)

    def impact(self, summary, intake=None):
        self.require_active()
        projection=self._on if self.enabled else self._off
        if projection is not None:
            return deepcopy(projection.impact)
        totals=intake or {}
        return dict(intake={r:dict(baseline=totals.get(r),excluded=0,retained=totals.get(r)) for r in ('student','parent')},
                    samples=[dict(code=c,baseline=summary.get(c),active=summary.get(c),
                                  excluded=0 if summary.get(c) is not None else None) for c in NATIVE_CODES],independent=None)

    def sample_rows(self, canonical, parents, sample):
        self.require_active()
        result=selected_sample(canonical,parents,sample)
        if not self.enabled:
            return result
        if sample=='BD' and self._on.parents is None:
            raise ActiveEligibilityUnavailable('formal_adult_artifact_unavailable')
        fields=[role+'_'+wave+'_submission_id' for role,wave in SLOTS[sample]]
        if sample in self._on.members:
            allowed=set(self._on.members[sample])
            mask=[tuple(row) in allowed for row in result[fields].itertuples(index=False,name=None)]
        else:
            # Supported supplementary same-child parent tuples stay separate
            # from the nine native deltas. Filter only original tuples.
            mask=[not self._on.excluded.intersection(row) for row in result[fields].itertuples(index=False,name=None)]
        return result.loc[mask].copy(deep=True)

    def sample_count(self, sample, canonical_rows, summary):
        if not self.enabled:
            return summary.get(sample)
        self.require_active()
        row=next((r for r in self._on.impact['samples'] if r['code']==sample),None)
        return row['active'] if row is not None else len(canonical_rows)


    def reconciliation(self, canonical, parents, summary):
        self.require_active()
        rows=[]
        for sample,label in SAMPLE_NAMES.items():
            if sample not in summary:continue
            try:
                detail=self.sample_rows(canonical,parents,sample)
                active=self.sample_count(sample,detail,summary)
                actual=len(detail) if active is not None else None
            except ActiveEligibilityUnavailable:
                active=actual=None
            rows.append(dict(sample=sample,label=label,baseline=summary.get(sample),active=active,
                             detail=actual,reconciled=active==actual if active is not None else None))
        return pd.DataFrame(rows)


def prepare_eligibility(records, analysis, parents, measurements, summary, manifest, *, panel=None):
    """Pure boundary: original cohorts are prepared before any UI masking."""
    release=summary['release_id']
    original=analysis.copy(deep=True)
    original_parents=None if parents is None else parents.copy(deep=True)
    measured=measurements.copy(deep=True)
    original_panel=_copy_panel(panel)
    # Require exact versions on every supplied analytical occurrence, even on
    # old releases whose core backwards-compatible API permits absent fields.
    by_id={r['submission_id']:r for r in records}
    frames=[original,*([original_parents] if original_parents is not None else []),
            *([original_panel['analysis']] if original_panel is not None else [])]
    for frame in frames:
        if 'version_id' not in frame:
            raise EligibilityError('analysis_version_evidence_required')
        for row in frame.to_dict('records'):
            source=by_id.get(row['submission_id'])
            if source is None or row['version_id']!=source.get('version_id'):
                raise EligibilityError('analysis_version_mismatch')
    off=project_eligibility(records,original,original_parents,None,release,enabled=False,panel=original_panel)
    canonical={(m,r):rows.copy(deep=True) for m,r,rows in projected_cohorts(
        records,original,original_parents,measured,off,panel=original_panel)}
    on=project_eligibility(records,original,original_parents,manifest,release,panel=original_panel)
    active={(m,r):rows.copy(deep=True) for m,r,rows in projected_cohorts(
        records,original,original_parents,measured,on,panel=original_panel)}
    return EligibilityState(release,ready=True,reason='',revision=manifest['revision'],inventory=inventory_revision(records),
                            _off=off,_on=on,_off_rows=canonical,_on_rows=active,
                            _measurements=measured,_panel=original_panel)


class _LegacyPublication:
    """Release-local proof for adding absent versions to old parquet schemas."""
    def __init__(self, folder, summary):
        self.folder=Path(folder).resolve()
        self.catalogues=[]
        self.cache={}
        checks=self.folder/'checksums.json'
        if checks.exists():self.catalogues.append((self._hashes(json.loads(self._local(checks.name))),True))
        artifacts=self.folder/'artifact_manifest.json'
        if artifacts.exists():
            manifest=json.loads(self.bytes(artifacts.name))
            if not isinstance(manifest,dict) or manifest.get('format_version')!=1:
                raise EligibilityError('legacy_release_provenance_invalid')
            self.catalogues.append((self._hashes(manifest.get('objects')),False))
        published=json.loads(self.bytes('summary.json'))
        if published!=summary or published.get('release_id')!=summary['release_id']:
            raise EligibilityError('legacy_release_summary_mismatch')

    @staticmethod
    def _hashes(value):
        if not isinstance(value,dict) or any(not isinstance(k,str) or not isinstance(v,str)
                or re.fullmatch('[a-f0-9]{64}',v) is None for k,v in value.items()):
            raise EligibilityError('legacy_release_provenance_invalid')
        return value

    def _local(self, name):
        path=self.folder/name
        if path.resolve().parent!=self.folder or not path.is_file():
            raise EligibilityError('legacy_release_artifact_unavailable')
        return path.read_bytes()

    def bytes(self, name):
        if name not in self.cache:
            blob=self._local(name)
            for hashes,complete in self.catalogues:
                key=name if name in hashes else name[:-3] if name.endswith('.gz') and name[:-3] in hashes else None
                if key is None:
                    if complete:raise EligibilityError('legacy_release_artifact_unpinned')
                    continue
                content=blob if key==name else gzip.decompress(blob)
                if hashlib.sha256(content).hexdigest()!=hashes[key]:
                    raise EligibilityError('legacy_release_artifact_hash_mismatch')
            self.cache[name]=blob
        return self.cache[name]

    def frame(self, name):
        return pd.read_parquet(io.BytesIO(self.bytes(name)))

    def bind(self, supplied, name, by_id):
        canonical=self.frame(name)
        for frame in (canonical,supplied):
            if not isinstance(frame,pd.DataFrame) or not frame.columns.is_unique or 'submission_id' not in frame:
                raise EligibilityError('legacy_published_frame_schema_mismatch')
            ids=frame.submission_id
            if ids.duplicated().any() or not ids.map(lambda sid:isinstance(sid,str) and sid in by_id).all():
                raise EligibilityError('legacy_published_frame_identity_mismatch')
            if 'version_id' in frame and any(r.version_id!=by_id[r.submission_id]['version_id'] for r in frame.itertuples()):
                raise EligibilityError('analysis_version_mismatch')
        columns=[c for c in canonical if c!='version_id']
        extra=set(supplied)-set(columns)
        if not set(columns)<=set(supplied) or not extra<={'version_id','observed_at','claimed_wave'}:
            raise EligibilityError('legacy_published_frame_schema_mismatch')
        if set(supplied.submission_id)!=set(canonical.submission_id):
            raise EligibilityError('legacy_published_frame_identity_mismatch')
        try:
            pd.testing.assert_frame_equal(supplied[columns].set_index('submission_id').loc[canonical.submission_id],
                canonical[columns].set_index('submission_id'),check_exact=True)
            # dashboard.sample_frames adds only these two record_metadata fields.
            # Compare to this release's inventory, never to a current database.
            for field in extra-{'version_id'}:
                expected=pd.Series([by_id[sid].get(field) for sid in supplied.submission_id],index=supplied.index,name=field)
                pd.testing.assert_series_equal(supplied[field],expected,check_dtype=False,check_exact=True)
        except AssertionError as error:
            raise EligibilityError('legacy_published_frame_mismatch') from error
        result=supplied.copy(deep=True)
        if 'version_id' not in result:
            result['version_id']=[by_id[sid]['version_id'] for sid in result.submission_id]
        return result


def load_eligibility(folder, summary, analysis, parents, *, manifest_path=None):
    """Only an explicit optional path enables reads of the private inputs."""
    release=summary['release_id']
    path=manifest_path if manifest_path is not None else os.environ.get(ENVIRONMENT_KEY)
    if not path:
        return EligibilityState(release)
    try:
        manifest=json.loads(Path(path).read_bytes())
        if summary.get('descriptive',{}).get('version')!=VERSION:
            raise EligibilityError('descriptive_evidence_unavailable')
        folder=Path(folder)
        legacy='version_id' not in analysis or parents is not None and 'version_id' not in parents
        publication=_LegacyPublication(folder,summary) if legacy else None
        blob=publication.bytes('records.jsonl.gz') if publication is not None else (folder/'records.jsonl.gz').read_bytes()
        records=[json.loads(line) for line in gzip.decompress(blob).decode('utf-8').splitlines() if line.strip()]
        if publication is not None:
            inventory_revision(records)  # Validate unique identities and exact versions before attaching anything.
            by_id={r['submission_id']:r for r in records}
            analysis=publication.bind(analysis,'analysis.parquet',by_id)
            if parents is not None:parents=publication.bind(parents,'parent_longitudinal.parquet',by_id)
            elif (folder/'parent_longitudinal.parquet').exists():
                raise EligibilityError('legacy_published_parent_frame_required')
        measurements=publication.frame('descriptive_measurements.parquet') if publication is not None else pd.read_parquet(folder/'descriptive_measurements.parquet')
        panel=None
        if summary.get('independent_parent') is not None:
            from .parent_panel_views import read_panel,verify_panel
            panel=({name:publication.frame('independent_parent_'+name+'.parquet') for name in
                    ('analysis','pairs','audit','candidates','sensitivity')} if publication is not None else read_panel(folder))
            verify_panel(panel,summary['independent_parent'])
        return prepare_eligibility(records,analysis,parents,measurements,summary,manifest,panel=panel)
    except EligibilityError as error:
        code=str(error)
        return EligibilityState(release,reason=code if re.fullmatch(r'[a-z][a-z0-9_]{0,100}',code) else 'manual_exclusion_inputs_invalid')
    except Exception:
        # Exceptions can contain a private path, identifier or contact. Never
        # pass their values to a Streamlit message or public download.
        return EligibilityState(release,reason='manual_exclusion_inputs_unavailable')



def preserve_filter_state(st):
    """Keep filter widget values through an unavailable rerun's widget cleanup."""
    backup_key='manual_exclusion_filter_state'
    saved=deepcopy(st.session_state.get(backup_key,{}))
    def retained(key):
        return isinstance(key,str) and key.startswith(('ds_','dx_','ipp_')) and not (
            'report_' in key or key.endswith(('_csv','_xlsx','_settings','_reset','_home','_date_gaps')))
    for key,value in list(st.session_state.items()):
        if retained(key):saved[key]=deepcopy(value)
    for key,value in saved.items():
        if key not in st.session_state:st.session_state[key]=deepcopy(value)
    st.session_state[backup_key]=saved


def render_selector(st, prepared):
    preserve_filter_state(st)
    # Keep the widget identity stable when the manifest becomes unavailable.
    # Changing disabled during an uncheck rerun can restore its previous True
    # value, trapping the session in blocked ON instead of accepting OFF.
    enabled=st.checkbox('Exclude manually flagged submissions',key=SESSION_KEY)
    state=prepared.select(enabled)
    st.caption('Manual exclusion '+('ON' if enabled else 'OFF')+'; release '+state.release_id+
               '; revision '+(state.revision or 'not available')+'. Original members and anchors; no reselection.')
    if not prepared.ready:
        (st.error if enabled else st.info)('ON unavailable: '+prepared.reason+'. Select OFF for canonical analysis.')
    st.download_button('Download eligibility context',json.dumps(state.metadata(),ensure_ascii=False,indent=2).encode(),
                       'study2-eligibility-context.json','application/json',key='manual_exclusion_context_download')
    return state


def render_impact(st, state, summary, intake=None):
    if not state.allowed:
        st.info('Active analytical counts are unavailable for the requested ON mode. Published reference facts remain below.')
        return
    effect=state.impact(summary,intake)
    st.subheader('Manual exclusion: active intake and nine original samples')
    st.dataframe(pd.DataFrame([dict(role=role,**values) for role,values in effect['intake'].items()]),hide_index=True,width='stretch')
    st.dataframe(pd.DataFrame(effect['samples']),hide_index=True,width='stretch')
    st.caption('Samples overlap. Raw/stage/admin facts remain published references. Supplementary same-child parent counts are outside these nine deltas.')


def stamp_frame(frame, metadata):
    result=frame.copy(deep=True)
    for key,value in metadata.items():
        if key.startswith('eligibility_'):
            result[key]=value
    return result


def download_name(name, metadata):
    if 'eligibility_mode' not in metadata:return name
    stem,suffix=os.path.splitext(name)
    mode=metadata.get('eligibility_mode','off')
    revision=str(metadata.get('eligibility_revision','not_available'))[:12]
    return stem+'-eligibility-'+mode+'-'+revision+suffix
