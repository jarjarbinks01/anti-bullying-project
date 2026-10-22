"""Hand-calculated, 23-record synthetic oracle. No implementation imports.

EXPECTATIONS were written before either accepted engine was called. Never
regenerate them from query output. Version aliases below are local fixture
handles; public catalogue keys are resolved only by their explicit metadata.
"""
from copy import deepcopy

COUNT_COLUMNS=('student','parent','A','B','C','D','AC','BD','E','F','EF')
ADULT_POLICY='same_child_valid_equal_birth_year_any_exact_contact_relationship_informational'
VERSION_META={
    'ks0':('Alpha','student','kite-student-start'),
    'ks1':('Beta','student','kite-student-follow'),
    'kp0':('Alpha','parent','kite-parent-start'),
    'kp1':('Beta','parent','kite-parent-follow'),
    'kb1':('Gamma','parent','kite-formal-follow'),
    'ls0':('Beta','student','lily-student-start'),
    'ls1':('Gamma','student','lily-student-follow'),
    'lp0':('Beta','parent','lily-parent-start'),
    'lp1':('Gamma','parent','lily-parent-follow'),
    'ms':('Alpha','student','moss-student-shared'),
    'mp':('Alpha','parent','moss-parent-shared'),
    'unanchored':('Gamma','parent','parent-unanchored'),
    'extra_s':('Beta','student','kite-student-start'),
    'spare_s':('Alpha','student','student-spare'),
    'repeat_p':('Beta','parent','parent-spare'),
    'missing_s':('Gamma','student',None),
    'missing_p':('Alpha','parent',None),
    'exact_s':('Beta','student','student-spare'),
    'exact_p':('Gamma','parent','parent-spare'),
    'extra_p':('Gamma','parent','kite-parent-follow'),
}

# alias, child, version, Hong Kong day, published selected wave, original wave,
# terminal status, unselected reason, explicit fixed formal membership.
LEDGER=[
    ('ks0','kite','ks0','2025-02-01','T0','T0','eligible',None,('K.A','K.AC.T0','K.E.student','K.EF.studentT0')),
    ('ks1','kite','ks1','2025-05-01','T1','T0','eligible',None,('K.C','K.AC.T1','K.F.student','K.EF.studentT1')),
    ('kp0','kite','kp0','2025-02-01','T0','T0','eligible',None,('K.B','K.BD.T0','K.E.parent','K.EF.parentT0')),
    ('kp1','kite','kp1','2025-06-01','T1','T1','eligible',None,('K.D','K.F.parent','K.EF.parentT1')),
    ('kb1','kite','kb1','2025-05-01',None,'T1','extra_followup','parent_other_same_phase_response',('K.BD.T1',)),
    ('ls0','lily','ls0','2025-02-02','T0','T0','eligible',None,('L.A','L.AC.T0','L.E.student','L.EF.studentT0')),
    ('ls1','lily','ls1',None,'T1','T1','eligible',None,('L.C','L.AC.T1','L.F.student','L.EF.studentT1')),
    ('lp0','lily','lp0','2025-02-02','T0','T0','eligible',None,('L.B','L.E.parent','L.EF.parentT0')),
    ('lp1','lily','lp1','2025-06-02','T1','T1','eligible',None,('L.D','L.F.parent','L.EF.parentT1')),
    ('ms0','moss','ms','2025-03-01','T0','T0','eligible',None,('M.A','M.AC.T0','M.E.student','M.EF.studentT0')),
    ('ms1','moss','ms','2025-03-01','T1','T1','eligible',None,('M.C','M.AC.T1','M.F.student','M.EF.studentT1')),
    ('mp0','moss','mp','2025-03-01','T0','T0','eligible',None,('M.B','M.BD.T0','M.E.parent','M.EF.parentT0')),
    ('mp1','moss','mp','2025-03-01','T1','T1','eligible',None,('M.D','M.BD.T1','M.F.parent','M.EF.parentT1')),
    ('unanchored','alone','unanchored','2025-04-01',None,'T0','eligible','parent_no_reliable_student_baseline',()),
    ('extra_s','kite','extra_s','2025-02-01',None,'T0','extra_followup','extra_followup',()),
    ('repeat_s','kite','spare_s','2025-05-01',None,'T0','short_repeat',None,()),
    ('repeat_p','kite','repeat_p','2025-05-01',None,'T0','short_repeat',None,()),
    ('invalid_s','extra-student','missing_s',None,None,'T0','incomplete',None,()),
    ('naive_p','extra-parent','missing_p',None,None,'T0','sparse_response',None,()),
    ('exact_s','kite','exact_s','2025-02-01',None,'T0','exact_input_repeat',None,()),
    ('exact_p','kite','exact_p','2025-02-01',None,'T0','exact_input_repeat',None,()),
    ('pending_s','kite','spare_s','2025-01-31',None,'T0','eligible','pending_chronology',()),
    ('extra_p','kite','extra_p','2025-06-01',None,'T1','extra_followup','parent_other_same_phase_response',()),
]

CASE_SPECS={
    'all':{},'reset':{},'no_sources':{'sources':[]},'no_versions':{'versions':[]},
    'alpha':{'sources':['Alpha']},'beta':{'sources':['Beta']},'gamma':{'sources':['Gamma']},
    'sources_or':{'sources':['Alpha','Beta']},'alpha_gamma':{'sources':['Alpha','Gamma']},
    'versions_or':{'versions':['ks0','ks1']},
    'categories_and':{'sources':['Beta','Gamma'],'versions':['ks0','ks1']},
    'zero_availability':{'sources':['Beta'],'versions':['ks0']},
    'missing_names':{'versions':['missing_s','missing_p']},
    'hk_day':{'start':'2025-02-01','end':'2025-02-01'},
    'hk_day_unknown':{'start':'2025-02-01','end':'2025-02-01','include_unknown':True},
    'from_may':{'start':'2025-05-01'},'through_feb1':{'end':'2025-02-01'},
    'through_jan31':{'end':'2025-01-31'},
    'known_only':{'start':'2025-01-01','end':'2025-12-31'},
    'bounded_unknown':{'start':'2025-01-01','end':'2025-12-31','include_unknown':True},
    'unknown_only':{'start':'2030-01-01','end':'2030-12-31','include_unknown':True},
    'drop_student_t0':{'exclude_versions':['ks0']},'drop_student_t1':{'exclude_versions':['ks1']},
    'drop_parent_t0':{'exclude_versions':['kp0']},'drop_parent_t1':{'exclude_versions':['kp1']},
    'drop_formal_bd_t1':{'exclude_versions':['kb1']},'students_only':{'version_role':'student'},
    'drop_shared_student':{'exclude_versions':['ms']},'drop_shared_parent':{'exclude_versions':['mp']},
    'shared_profiles':{'versions':['ms','mp']},
    'unconfirmed_adult':{'versions':['ls0','ls1','lp0','lp1']},
    'unanchored_only':{'versions':['unanchored']},
    'unselected_only':{'versions':['extra_s','spare_s','missing_s','exact_s','unanchored','repeat_p','missing_p','exact_p','extra_p','kb1']},
    'followup_claimed_t0':{'versions':['ks1']},'same_form_other_source':{'versions':['ks0','extra_s']},
    'absent_adult_artifact':{'variant':'absent'},'empty_adult_artifact':{'variant':'empty'},
    'unsupported_adult_policy':{'variant':'unsupported'},
}

# Literal values independently enumerated in handoff/EXPECTED_FILTER_CASES.md.
EXPECTED_COUNTS={
    'all':(11,12,3,3,3,3,3,2,3,3,3),
    'reset':(11,12,3,3,3,3,3,2,3,3,3),
    'no_sources':(0,0,0,0,0,0,0,0,0,0,0),
    'no_versions':(0,0,0,0,0,0,0,0,0,0,0),
    'alpha':(5,4,2,2,1,1,1,1,2,1,1),
    'beta':(4,3,1,1,1,1,0,0,1,1,0),
    'gamma':(2,5,0,0,1,1,0,0,0,1,0),
    'sources_or':(9,7,3,3,2,2,2,1,3,2,2),
    'alpha_gamma':(7,9,2,2,2,2,1,2,2,2,1),
    'versions_or':(2,0,1,0,1,0,1,0,0,0,0),
    'categories_and':(1,0,0,0,1,0,0,0,0,0,0),
    'zero_availability':(0,0,0,0,0,0,0,0,0,0,0),
    'missing_names':(1,1,0,0,0,0,0,0,0,0,0),
    'hk_day':(3,2,1,1,0,0,0,0,1,0,0),
    'hk_day_unknown':(5,3,1,1,1,0,0,0,1,0,0),
    'from_may':(2,5,0,0,1,2,0,0,0,1,0),
    'through_feb1':(4,2,1,1,0,0,0,0,1,0,0),
    'through_jan31':(1,0,0,0,0,0,0,0,0,0,0),
    'known_only':(9,11,3,3,2,3,2,2,3,2,2),
    'bounded_unknown':(11,12,3,3,3,3,3,2,3,3,3),
    'unknown_only':(2,1,0,0,1,0,0,0,0,0,0),
    'drop_student_t0':(10,12,2,3,3,3,2,2,2,3,2),
    'drop_student_t1':(10,12,3,3,2,3,2,2,3,2,2),
    'drop_parent_t0':(11,11,3,2,3,3,3,1,2,3,2),
    'drop_parent_t1':(11,11,3,3,3,2,3,2,3,2,2),
    'drop_formal_bd_t1':(11,11,3,3,3,3,3,1,3,3,3),
    'students_only':(11,0,3,0,3,0,3,0,0,0,0),
    'drop_shared_student':(9,12,2,3,2,3,2,2,2,2,2),
    'drop_shared_parent':(11,10,3,2,3,2,3,1,2,2,2),
    'shared_profiles':(2,2,1,1,1,1,1,1,1,1,1),
    'unconfirmed_adult':(2,2,1,1,1,1,1,0,1,1,1),
    'unanchored_only':(0,1,0,0,0,0,0,0,0,0,0),
    'unselected_only':(5,6,0,0,0,0,0,0,0,0,0),
    'followup_claimed_t0':(1,0,0,0,1,0,0,0,0,0,0),
    'same_form_other_source':(2,0,1,0,0,0,0,0,0,0,0),
    'absent_adult_artifact':(11,12,3,3,3,3,3,None,3,3,3),
    'empty_adult_artifact':(11,12,3,3,3,3,3,0,3,3,3),
    'unsupported_adult_policy':(11,12,3,3,3,3,3,None,3,3,3),
}

REASON_KEYS={
    'screening':('excluded_school','sparse_response','incomplete','unrecognized_survey'),
    'exact_copies':('exact_input_repeat',),
    'repeat_handling':('short_repeat','manual_excluded'),
    'selection':('parent_no_reliable_student_baseline','parent_other_same_phase_response','extra_followup','short_interval_followup','pending_chronology','parent_before_student_baseline'),
}

def _lane(entering,remaining,**nonzero):
    return dict(entering=entering,remaining=remaining,exits=nonzero)

# Complete manual stage values; supported omitted reasons are explicit zero.
FLOW_EXPECTED={
    'all':{
        'student':dict(screening=_lane(11,10,incomplete=1),exact_copies=_lane(10,9,exact_input_repeat=1),repeat_handling=_lane(9,8,short_repeat=1),selection=_lane(8,6,extra_followup=1,pending_chronology=1)),
        'parent':dict(screening=_lane(12,11,sparse_response=1),exact_copies=_lane(11,10,exact_input_repeat=1),repeat_handling=_lane(10,9,short_repeat=1),selection=_lane(9,6,parent_no_reliable_student_baseline=1,parent_other_same_phase_response=2)),
    },
    'alpha':{
        'student':dict(screening=_lane(5,5),exact_copies=_lane(5,5),repeat_handling=_lane(5,4,short_repeat=1),selection=_lane(4,3,pending_chronology=1)),
        'parent':dict(screening=_lane(4,3,sparse_response=1),exact_copies=_lane(3,3),repeat_handling=_lane(3,3),selection=_lane(3,3)),
    },
    'known_only':{
        'student':dict(screening=_lane(9,9),exact_copies=_lane(9,8,exact_input_repeat=1),repeat_handling=_lane(8,7,short_repeat=1),selection=_lane(7,5,extra_followup=1,pending_chronology=1)),
        'parent':dict(screening=_lane(11,11),exact_copies=_lane(11,10,exact_input_repeat=1),repeat_handling=_lane(10,9,short_repeat=1),selection=_lane(9,6,parent_no_reliable_student_baseline=1,parent_other_same_phase_response=2)),
    },
}
for _roles in FLOW_EXPECTED.values():
    for _stages in _roles.values():
        for _stage,_values in _stages.items():
            _values['exits']={reason:_values['exits'].get(reason,0) for reason in REASON_KEYS[_stage]}


def synthetic_inputs(variant='base'):
    """Construct only explicit toy input fields, never an expected query result."""
    records=[];analysis=[]
    for alias,child,version,day,wave,claimed,status,reason,slots in LEDGER:
        source,role,form=VERSION_META[version]
        observed=day+'T00:00:00+08:00' if day else None
        confidence='observed' if day else 'unknown'
        basis='system_creation'
        if alias in ('ks0','kp0'):
            observed='2025-01-31T16:00:00Z'
        if alias=='pending_s':
            observed='2025-01-31T15:59:59Z'
        if alias=='kb1':
            confidence='manual_verified'
        if alias=='repeat_s':
            confidence='accepted_creation_time';basis='batch_assigned_creation'
        if alias=='invalid_s':
            observed='not-a-date';confidence='observed'
        if alias=='naive_p':
            observed='2025-02-01T00:00:00';confidence='observed'
        sid='toy-record-'+alias
        record=dict(submission_id=sid,child_id='toy-child-'+child,role=role,
            source_type=source,source_label=source,answer={'Survey':None if form is None else 'Common questionnaire'},
            survey_form_id=form,survey_form_version='v1' if form else None,
            observed_at=observed,time_confidence=confidence,date_basis=basis,
            claimed_wave=claimed,selected_wave=wave,status=status,wave_reason=reason,
            version_id='toy-input-revision-'+alias,hk_creation_day=day,fixture_version=version,
            formal_sample_slots=list(slots),adult_continuity='unconfirmed' if child=='lily' else 'formal_input_only')
        if alias=='naive_p':
            record['answer']['Survey']=''
        if alias in ('invalid_s','naive_p'):
            record.update(imported_at='2025-02-01T00:00:00+08:00',batch_at='2025-02-01T00:00:00+08:00')
        records.append(record)
        if wave:
            analysis.append(dict(submission_id=sid,child_id=record['child_id'],role=role,wave=wave))
    adults=[dict(submission_id='toy-record-'+sid,child_id='toy-child-'+child,role='parent',wave=wave)
        for sid,child,wave in [('kp0','kite','T0'),('kb1','kite','T1'),('mp0','moss','T0'),('mp1','moss','T1')]]
    summary=dict(release_id='synthetic-mm-r02',adult_identity_policy=ADULT_POLICY,submissions=23,
        status_counts=dict(eligible=14,extra_followup=3,short_repeat=2,incomplete=1,sparse_response=1,exact_input_repeat=2),
        stage_counts={'2.1.3':21,'2.1.4':{'eligible_submissions':19},'2.1.6':17},
        A=3,B=3,C=3,D=3,AC=3,BD=2,E=3,F=3,EF=3)
    if variant=='absent':
        adults=None;summary.pop('BD')
    elif variant=='empty':
        adults=[];summary['BD']=0
    elif variant=='unsupported':
        summary['adult_identity_policy']='unconfirmed_adult_policy';summary.pop('BD')
    else:
        assert variant=='base'
    return deepcopy((records,analysis,adults,summary))


def version_keys(index):
    """Resolve opaque category keys by supplied form/source/role metadata only."""
    source_keys={s['label']:s['key'] for s in index['sources']}
    keys={}
    for alias,(source,role,form) in VERSION_META.items():
        matches=[s for s in index['surveys'] if s['source_key']==source_keys[source] and s['role']==role and s['form_id']==form and s['missing_name']==(form is None)]
        assert len(matches)==1,(alias,matches)
        keys[alias]=matches[0]['key']
    return keys


def case_selection(index,name):
    spec=CASE_SPECS[name];out={}
    if 'sources' in spec:
        labels={s['label']:s['key'] for s in index['sources']}
        out['sources']=[labels[label] for label in spec['sources']]
    versions=version_keys(index)
    if 'versions' in spec:
        out['surveys']=[versions[alias] for alias in spec['versions']]
    if 'exclude_versions' in spec:
        excluded={versions[alias] for alias in spec['exclude_versions']}
        out['surveys']=[s['key'] for s in index['surveys'] if s['key'] not in excluded]
    if 'version_role' in spec:
        out['surveys']=[s['key'] for s in index['surveys'] if s['role']==spec['version_role']]
    for key in ('start','end','include_unknown'):
        if key in spec:
            out[key]=spec[key]
    return out
