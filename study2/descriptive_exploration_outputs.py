"""Versioned aggregate artifacts and publication gates for exploration."""
import json
from pathlib import Path

import pandas as pd

from .common import PipelineError, atomic_json, file_hash
from .descriptive_exploration import METHODS, TABLES, VERSION, explore, validate_exploration
from .descriptive_spec import GROUPS, MODES
from .descriptives import cohort, filter_cohort, independent_cohort

FILES = {key:'descriptive_'+key+'.parquet' for key in TABLES}
MANIFEST = 'descriptive_exploration_manifest.json'


def write_exploration(folder, measurements, frame, parents, release_id, *, prepared=None):
    folder=Path(folder)
    collected={key:[] for key in TABLES}; coverage=[]
    def add(rows, role, paired, *, already_selected=False):
        selected=rows if already_selected else filter_cohort(rows)[0]
        result=explore(selected,role,GROUPS,release_id,paired=paired,metadata={'mainstream':True})
        for key in TABLES:
            collected[key].append(result[key])
        coverage.append({k:result['metadata'][k] for k in ['mode','role','basis']})
    for mode in MODES:
        for role in ['student','parent']:
            rows=(prepared[mode,role][1] if prepared is not None else
                  filter_cohort(cohort(frame,parents,measurements,mode,role))[0])
            add(rows,role,False,already_selected=True)
            if mode in {'acbd','efmatched'}:
                add(rows,role,True,already_selected=True)
    independent=folder/'independent_parent_analysis.parquet'
    if independent.exists():
        source=pd.read_parquet(independent)
        for branch in ['child_report','same_adult']:
            rows=filter_cohort(independent_cohort(source,measurements,branch,True))[0]
            add(rows,'parent',False,already_selected=True);add(rows,'parent',True,already_selected=True)
    artifacts={}
    for key,filename in FILES.items():
        data=pd.concat(collected[key],ignore_index=True)
        data.to_parquet(folder/filename,index=False)
        (folder/filename).chmod(0o600)
        artifacts[key]={'file':filename,'sha256':file_hash(folder/filename),'rows':len(data)}
    result={'version':VERSION,'release_id':release_id,'methods':METHODS,'coverage':coverage,'files':artifacts,
            'independent_parent':independent.exists()}
    atomic_json(folder/MANIFEST,result)
    verify_exploration(folder,result)
    return result


def verify_exploration(folder, expected):
    folder=Path(folder)
    actual=json.loads((folder/MANIFEST).read_text())
    if actual != expected or actual['version']!=VERSION or actual['release_id']!=folder.name:
        raise PipelineError('Exploration manifest does not match this release')
    if set(actual['files'])!=set(TABLES):
        raise PipelineError('Required exploration artifacts are missing')
    required={(mode,role,'wave_valid') for mode in MODES for role in ['student','parent']}
    required|={(mode,role,'paired_valid') for mode in ['acbd','efmatched'] for role in ['student','parent']}
    if actual.get('independent_parent'):
        required|={('independent_'+branch,'parent',basis) for branch in ['same_adult','child_report'] for basis in ['wave_valid','paired_valid']}
    observed={(r['mode'],r['role'],r['basis']) for r in actual['coverage']}
    if observed!=required or len(actual['coverage'])!=len(required):
        raise PipelineError('Exploration sample coverage is incomplete')
    result={}
    for key,filename in FILES.items():
        entry=actual['files'][key]
        if entry['file']!=filename or file_hash(folder/filename)!=entry['sha256']:
            raise PipelineError('Exploration artifact fingerprint mismatch')
        result[key]=pd.read_parquet(folder/filename)
        if len(result[key])!=entry['rows']:
            raise PipelineError('Exploration artifact row count mismatch')
        data=result[key]
        if not data.empty and (not data['release_id'].eq(folder.name).all() or not data['exploration_version'].eq(VERSION).all()):
            raise PipelineError('Exploration artifact belongs to another release')
        if not data.empty:
            keys=['mode','role','basis','group','variable_id']
            keys+=['wave','bin_index'] if key=='histograms' else ['wave','category_code'] if key=='categories' else ['t0_value','t1_value'] if key=='pair_transitions' else ['wave'] if key=='distribution_summary' else []
            if data.duplicated(keys).any():
                raise PipelineError('Exploration artifact has duplicate aggregate keys')
        if any(word in col.lower() for col in data for word in ['submission_id','child_id','contact','phone','email','dob']):
            raise PipelineError('Exploration artifacts must be aggregate only')
    validate_exploration(result)


def available(folder, summary):
    """An old release has no capability. A damaged new release is an error."""
    expected=summary.get('descriptive',{}).get('exploration')
    if not expected:
        return False
    verify_exploration(folder,expected)
    return True
