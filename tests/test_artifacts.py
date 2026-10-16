import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from study2.artifacts import artifact_cache,compress_existing,logical_hash,write_json_lines
from study2.common import PipelineError,file_hash
from study2.outputs import write_excel


def test_identical_workbooks_are_reused_without_dropping_values(tmp_path):
    first=tmp_path/'first'/'value.xlsx';second=tmp_path/'second'/'value.xlsx'
    rows=pd.DataFrame([{'unicode':'繁體中文','empty':'','value':1.5}])
    with artifact_cache(tmp_path/'objects',first.parent):write_excel(first,{'sample':rows})
    with artifact_cache(tmp_path/'objects',second.parent):write_excel(second,{'sample':rows})
    assert first.samefile(second)
    assert pd.read_excel(second)['unicode'].tolist()==['繁體中文']


def test_compressed_audit_content_is_complete_and_deterministic(tmp_path):
    values=[{'unicode':'繁體中文','null':None,'number':1.0}]
    a=tmp_path/'a.jsonl.gz';b=tmp_path/'b.jsonl.gz'
    write_json_lines(a,values);write_json_lines(b,values)
    assert a.read_bytes()==b.read_bytes()
    with gzip.open(a,'rt',encoding='utf-8') as f:assert [json.loads(line) for line in f]==values


def test_old_export_compression_verifies_content_before_removing_original(tmp_path):
    p=tmp_path/'old.jsonl';p.write_text('{"synthetic": true}\n');expected=file_hash(p)
    archive=compress_existing(p,expected)
    assert not p.exists() and logical_hash(p)==expected
    p.write_text('changed')
    with pytest.raises(PipelineError):compress_existing(p,expected)
    assert p.exists()
