"""One horizontal tab is text, not normalization or a new public-label policy."""
from copy import deepcopy
import json,subprocess,shutil
from pathlib import PurePosixPath

import pytest

from study2.common import digest
from study2.static_export import SCOPE_EXPORT_FORMAT,write_site
from study2.static_scope import ScopeError,build_scope_index,default_selection,query_scope,validate_index
from study2.static_scope_client import JS_SOURCE
from test_static_scope import fixture
from test_static_scope_client import node_batch
from test_static_export import snapshot


TAB_NAME='Learning\tQuestionnaire'
SPACE_NAME='Learning Questionnaire'


def tab_fixture():
    data=fixture()
    records=data[0]
    selected=[r for r in records if r['role']=='student' and r['source_type']=='alpha']
    selected[0]['answer']['Survey']=TAB_NAME
    selected[1]['answer']['Survey']=SPACE_NAME
    # Existing legacy intake classifier, with the same literal tab preserved.
    selected[0].pop('source_type');selected[0]['source_label']='qualtrics\tintake'
    selected[1]['source_type']='qualtrics'
    return data


def test_horizontal_tab_preserves_exact_name_and_distinct_group_identity_in_both_engines():
    data=tab_fixture();original=deepcopy(data);index=build_scope_index(*data)
    named={r['label']:r['key'] for r in index['surveys'] if r['role']=='student' and r['label'] in [TAB_NAME,SPACE_NAME]}
    assert set(named)=={TAB_NAME,SPACE_NAME} and named[TAB_NAME]!=named[SPACE_NAME]
    assert data==original
    selections=[]
    for name in [TAB_NAME,SPACE_NAME]:
        choice=default_selection(index);choice['surveys']=[named[name]];selections.append(choice)
        assert query_scope(index,choice)['raw']=={'student':1,'parent':0}
    for choice,answer in zip(selections,node_batch(index,selections)):
        assert answer['ok'] and answer['result']==query_scope(index,choice)
    assert '\\t' in json.dumps(index,ensure_ascii=False)
    assert json.loads(json.dumps(index,ensure_ascii=False))==index


@pytest.mark.parametrize('control',[chr(i) for i in range(32) if i!=9]+[chr(127)])
def test_other_controls_remain_rejected_by_python_and_javascript(control):
    data=fixture();data[0][0]['answer']['Survey']='Learning'+control+'Questionnaire'
    with pytest.raises(ScopeError,match='unsafe_or_missing_label:survey_name'):build_scope_index(*data)
    index=build_scope_index(*fixture());index['surveys'][0]['label']='Learning'+control+'Questionnaire'
    with pytest.raises(ScopeError):validate_index(index)
    assert not node_batch(index,[None])[0]['ok']


@pytest.mark.parametrize('value',['\t','x\t<script>','x\t'+str(PurePosixPath('/', 'Users', 'Synthetic', 'file')),'x\tmail@example.org',
    'Contact\t9123-4567','Contact 9123\t4567','9123\t4567','Contact\t9123\t4567','CHILD_'+'a'*24])
def test_tab_does_not_exempt_unsafe_or_empty_text(value):
    data=fixture();data[0][0]['answer']['Survey']=value
    with pytest.raises(ScopeError,match='unsafe_or_missing_label:survey_name'):build_scope_index(*data)
    index=build_scope_index(*fixture());index['surveys'][0]['label']=value
    assert not node_batch(index,[None])[0]['ok']


def test_tab_remains_invalid_inside_version_tokens():
    data=fixture();data[3]['release_id']='synthetic\trelease'
    with pytest.raises(ScopeError,match='invalid_metadata'):build_scope_index(*data)
    index=build_scope_index(*fixture());index['meta']['release_id']='synthetic\trelease'
    assert not node_batch(index,[None])[0]['ok']


def test_tab_scope_script_roundtrip_is_valid_and_retains_exact_string(tmp_path):
    index=build_scope_index(*tab_fixture());scope=dict(format=SCOPE_EXPORT_FORMAT,status='available',
        release_id='synthetic-release',index_revision=digest(index),index=index,school_bindings=[],
        reconciliation=query_scope(index)['reconciliation'])
    value={**snapshot(), 'minimum_cell_n':0,'small_sample_policy':'none'}
    write_site(value,tmp_path/'site',scope_export=scope)
    text=(tmp_path/'site/scope-index.js').read_text()
    assert '\\t' in text and TAB_NAME not in text
    node=shutil.which('node');assert node
    script=JS_SOURCE+'''\nconst vm=require('node:vm'),fs=require('node:fs');const context={window:{}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context);
const index=context.window.STUDY2_SCOPE_EXPORT.index;Study2Scope.validate(index);
const label=index.surveys.find(r=>r.label.includes('\\t')).label;
process.stdout.write(JSON.stringify({exact:label==='Learning\\tQuestionnaire',spaceAlsoPresent:index.surveys.some(r=>r.label==='Learning Questionnaire')}));'''
    run=subprocess.run([node,'-e',script,str(tmp_path/'site/scope-index.js')],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    assert json.loads(run.stdout)==dict(exact=True,spaceAlsoPresent=True)
