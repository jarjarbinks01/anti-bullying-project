"""Private immutable file objects and verified compressed audit exports."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import tempfile
import zlib
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from .common import PipelineError, atomic_json, dumps, file_hash, secure_directory

_cache = ContextVar('study2_artifact_cache',default=None)


@contextmanager
def artifact_cache(root,folder=None):
    root=Path(root);secure_directory(root)
    value={'root':root,'folder':Path(folder) if folder else None,'files':{}}
    token=_cache.set(value)
    try:yield value
    finally:
        if value['folder'] and value['folder'].exists():
            atomic_json(value['folder']/'artifact_manifest.json',{'format_version':1,'objects':value['files']})
        _cache.reset(token)


def _object_path(root,h):
    if len(h)!=64 or any(c not in '0123456789abcdef' for c in h):raise PipelineError('Invalid artifact object hash')
    return Path(root)/'objects'/h[:2]/h[2:]


def publish_object(root,path):
    root=Path(root);path=Path(path);h=file_hash(path);target=_object_path(root,h)
    if target.exists():
        if file_hash(target)!=h:raise PipelineError('Immutable artifact object is corrupt')
    else:
        secure_directory(target.parent)
        temporary=target.with_name(target.name+'.partial')
        try:
            with path.open('rb') as src,temporary.open('xb') as dst:
                temporary.chmod(0o600);shutil.copyfileobj(src,dst)
                dst.flush();os.fsync(dst.fileno())
            if file_hash(temporary)!=h:raise PipelineError('Artifact changed during snapshot')
            os.replace(temporary,target)
        finally:temporary.unlink(missing_ok=True)
    return h,target


def copy_object(source,destination):
    source=Path(source);destination=Path(destination);secure_directory(destination.parent)
    temporary=destination.with_name(destination.name+'.object-link')
    try:
        try:os.link(source,temporary)
        except OSError:shutil.copy2(source,temporary)
        temporary.chmod(0o600);os.replace(temporary,destination)
    finally:temporary.unlink(missing_ok=True)


def freeze_file(source,destination,root=None):
    source=Path(source);destination=Path(destination);current=_cache.get()
    root=Path(root) if root else current['root'] if current else None
    if root is None:
        secure_directory(destination.parent);shutil.copy2(source,destination);return
    h,obj=publish_object(root,source);copy_object(obj,destination)
    if current and current['folder']:
        current['files'][str(destination.relative_to(current['folder']))]=h
    return h


def cached_excel(path,sheets,tracking,writer):
    current=_cache.get()
    if not current:return writer()
    import pandas as pd
    frames=[]
    for name,rows in sheets.items():
        frame=rows if isinstance(rows,pd.DataFrame) else pd.DataFrame(rows)
        frames.append({'sheet':name,'columns':list(frame.columns),'dtypes':[str(t) for t in frame.dtypes],
                       'rows':frame.to_dict('records')})
    key=hashlib.sha256(dumps({'export_format':2,'tracking':tracking,'frames':frames}).encode()).hexdigest()
    index=current['root']/'excel_keys'/key[:2]/(key[2:]+'.json')
    if index.exists():
        h=json.loads(index.read_text())['object_hash'];obj=_object_path(current['root'],h)
        if not obj.is_file() or file_hash(obj)!=h:raise PipelineError('Cached workbook failed integrity verification')
        copy_object(obj,path)
        if current['folder']:current['files'][str(Path(path).relative_to(current['folder']))]=h
        return
    writer();h,obj=publish_object(current['root'],path);copy_object(obj,path)
    secure_directory(index.parent);atomic_json(index,{'object_hash':h,'format_version':1})
    if current['folder']:current['files'][str(Path(path).relative_to(current['folder']))]=h


def write_json_lines(path,rows):
    """Deterministic gzip preserves complete UTF-8 logical audit content."""
    path=Path(path);secure_directory(path.parent)
    with path.open('wb') as target:
        path.chmod(0o600)
        with gzip.GzipFile(filename='',mode='wb',fileobj=target,mtime=0) as zipped:
            for row in rows:zipped.write((dumps(row)+'\n').encode('utf-8'))
    current=_cache.get()
    if current:freeze_file(path,path)


def logical_hash(path):
    path=Path(path)
    if path.is_file():return file_hash(path)
    archive=path.with_name(path.name+'.gz')
    if not archive.is_file():raise PipelineError('Published artifact is missing')
    h=hashlib.sha256()
    try:
        with gzip.open(archive,'rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    except (OSError,EOFError,zlib.error) as error:raise PipelineError('Compressed artifact failed verification') from error
    return h.hexdigest()


def compress_existing(path,expected_hash,root=None):
    path=Path(path);archive=path.with_name(path.name+'.gz')
    if archive.exists():
        h=hashlib.sha256()
        with gzip.open(archive,'rb') as restored:
            for chunk in iter(lambda:restored.read(1024*1024),b''):h.update(chunk)
        if h.hexdigest()!=expected_hash or (path.exists() and file_hash(path)!=expected_hash):
            raise PipelineError('Existing audit artifact checksum mismatch')
        if root:freeze_file(archive,archive,root)
        path.unlink(missing_ok=True)
        return archive
    partial=archive.with_name(archive.name+'.partial');h=hashlib.sha256()
    try:
        with path.open('rb') as source,partial.open('xb') as target:
            partial.chmod(0o600)
            with gzip.GzipFile(filename='',mode='wb',fileobj=target,mtime=0) as zipped:
                for chunk in iter(lambda:source.read(1024*1024),b''):h.update(chunk);zipped.write(chunk)
        if h.hexdigest()!=expected_hash:raise PipelineError('Original audit artifact checksum mismatch')
        os.replace(partial,archive)
        restored=hashlib.sha256()
        with gzip.open(archive,'rb') as source:
            for chunk in iter(lambda:source.read(1024*1024),b''):restored.update(chunk)
        if restored.hexdigest()!=expected_hash:raise PipelineError('Compressed audit artifact differs from original')
        if root:freeze_file(archive,archive,root)
        path.unlink();return archive
    finally:partial.unlink(missing_ok=True)
