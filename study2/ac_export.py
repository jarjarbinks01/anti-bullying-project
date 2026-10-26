"""Local full student AC export over fixed, already selected native pairs.

``output`` is a new directory, containing CSV, column dictionary and provenance.
No matching, response reselection, scoring, recovery or database writes occur.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
from itertools import zip_longest
import json
import math
import os
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

from .analysis_eligibility import project_eligibility, validate_manifest
from .artifacts import logical_hash
from .common import PipelineError, file_hash
from .store import current

BASE_COLUMNS = ('dataset_version', 'release_id', 'run_id', 'manual_exclusion', 'child_id')
SECTIONS = ('record', 'current', 'source', 'analysis')


def _need(ok, code):
    if not ok:
        raise PipelineError('AC export: ' + code)


def _published_release(state):
    # store.connect(readonly=True) can invoke activation recovery. Do not use it.
    db = sqlite3.connect((state / 'study2.sqlite').as_uri() + '?mode=ro', uri=True)
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        return current(db)
    finally:
        db.close()


def _records(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            _need(isinstance(row, dict), 'invalid record object')
            yield row


def _verify_published_files(folder, names):
    """Check consumed artifacts only, including legacy logical gzip entries."""
    path = folder / 'checksums.json'
    _need(path.is_file(), 'published checksum inventory required')
    checksums = json.loads(path.read_text(encoding='utf-8'))
    _need(isinstance(checksums, dict), 'invalid published checksum inventory')
    verified = {}
    for name in names:
        key = name if name in checksums else name[:-3] if name.endswith('.gz') else name
        expected = checksums.get(key)
        _need(isinstance(expected, str) and len(expected) == 64 and
              all(c in '0123456789abcdef' for c in expected), 'consumed artifact missing from published checksums')
        if key != name:
            # Hash the archive actually consumed, even if an unconsumed plain
            # copy is also present. logical_hash(plain) would prefer that copy.
            hasher = hashlib.sha256()
            with gzip.open(folder / name, 'rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    hasher.update(block)
            actual = hasher.hexdigest()
        else:
            actual = logical_hash(folder / name)
        _need(actual == expected, 'published artifact checksum mismatch')
        verified[name] = dict(inventory_key=key, expected_sha256=expected)
    return verified


def _json_value(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.datetime64):
        return None if np.isnat(value) else pd.Timestamp(value).isoformat()
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, dict):
        _need(all(isinstance(key, str) for key in value), 'non-text structured field name')
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, float):
        if math.isnan(value):
            return None
        _need(math.isfinite(value), 'infinite cell value')
    if isinstance(value, Decimal):
        if value.is_nan():
            return None
        _need(value.is_finite(), 'infinite cell value')
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    _need(isinstance(value, (str, int, float, bool)), 'unsupported cell type')
    return value


def _cell(value):
    value = _json_value(value)
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def _sections(record, analysis):
    result = dict(record={k: v for k, v in record.items() if k not in {'answer', 'raw'}},
                  current=record.get('answer'), source=record.get('raw'), analysis=analysis)
    for fields in result.values():
        _need(isinstance(fields, dict) and all(isinstance(k, str) for k in fields), 'missing or invalid full field section')
    return result


def _row(pair, records, analysis, metadata):
    result = {**metadata, 'child_id': records[pair[0]]['child_id']}
    for wave, sid in zip(('T0', 'T1'), pair):
        for section, fields in _sections(records[sid], analysis[sid]).items():
            result.update({f'{wave}_{section}__{key}': value for key, value in fields.items()})
    return result


def _verify_csv(path, headers, pairs, records, analysis, metadata):
    seen = set()
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        _need(reader.fieldnames == headers, 'CSV header round-trip mismatch')
        for pair, actual in zip_longest(pairs, reader):
            _need(pair is not None and actual is not None, 'CSV row count mismatch')
            expected = _row(pair, records, analysis, metadata)
            _need(actual == {key: _cell(expected.get(key)) for key in headers}, 'CSV cell round-trip mismatch')
            seen.add((actual['T0_record__submission_id'], actual['T1_record__submission_id']))
    _need(seen == set(pairs), 'CSV pair membership mismatch')
    with path.open('rb') as stream:
        _need(stream.read(3) == b'\xef\xbb\xbf', 'CSV UTF-8 BOM missing')


def _open_owned(path, owned, *, newline=None, encoding='utf-8'):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    stat = os.fstat(fd)
    owned[path] = (stat.st_dev, stat.st_ino)
    return os.fdopen(fd, 'w', encoding=encoding, newline=newline)


def _cleanup(output, directory_identity, owned):
    # Never remove pre-existing outputs or files another operation has added.
    for path, identity in reversed(list(owned.items())):
        try:
            stat = path.lstat()
            if (stat.st_dev, stat.st_ino) == identity:
                path.unlink()
        except OSError:
            pass
    try:
        stat = output.lstat()
        if (stat.st_dev, stat.st_ino) == directory_identity:
            output.rmdir()  # Refuses a nonempty directory containing foreign files.
    except OSError:
        pass


def export_student_ac(cfg, output: Path, *, manifest_path=None, enabled=False,
                      dataset_version='student_ac_full_v1'):
    """Export one wide row per fixed student AC pair into a new local directory.

    ON requires an accepted exact inventory/version-bound exclusion manifest.
    Any explicitly supplied manifest is validated and pinned, including in OFF.
    Outcome missingness never removes an otherwise valid pair. Returns local
    provenance and output paths; existing outputs are never overwritten.
    """
    _need(type(enabled) is bool, 'enabled must be boolean')
    _need(isinstance(dataset_version, str) and bool(dataset_version.strip()), 'dataset version required')
    _need(not enabled or manifest_path is not None, 'accepted exclusion manifest required for ON')
    state = Path(cfg['state_dir']).expanduser().resolve()
    requested_output = Path(output).expanduser()
    if requested_output.exists() or requested_output.is_symlink():
        raise FileExistsError(requested_output)
    output = requested_output.resolve()
    _need(not output.is_relative_to(state), 'output must be outside source state')
    if output.exists():
        raise FileExistsError(output)
    release = _published_release(state)
    _need(release and all(release.get(key) for key in ('release_id', 'run_id', 'path')), 'published release required')
    folder = Path(release['path']).resolve()
    _need(not output.is_relative_to(folder), 'output must be outside published release')
    consumed = ['records.jsonl.gz', 'analysis.parquet']
    consumed += [name for name in ('summary.json', 'run_manifest.json') if (folder / name).is_file()]
    source_paths = [folder / name for name in consumed] + [folder / 'checksums.json']
    _need((folder / 'checksums.json').is_file(), 'published checksum inventory required')
    locations = state / 'release_locations.json'
    if locations.exists():
        source_paths.append(locations)
    source_pins = {str(path): file_hash(path) for path in source_paths}
    published_checksums = _verify_published_files(folder, consumed)
    inventory = [{k: v for k, v in row.items() if k not in {'raw', 'answer'}}
                 for row in _records(folder / 'records.jsonl.gz')]
    analysis_frame = pd.read_parquet(folder / 'analysis.parquet')
    _need(analysis_frame.columns.is_unique and all(isinstance(k, str) for k in analysis_frame), 'invalid analysis columns')
    manifest = None
    manifest_pin = None
    if manifest_path is not None:
        manifest_path = Path(manifest_path).resolve()
        manifest_pin = file_hash(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        validate_manifest(manifest, inventory, release['release_id'])
    _need(not enabled or manifest is not None, 'accepted exclusion manifest required for ON')
    projection = project_eligibility(inventory, analysis_frame, None, manifest,
                                     release['release_id'], enabled=enabled)
    pairs = projection.members['AC']
    chosen = {sid for pair in pairs for sid in pair}
    _need(len(set(pairs)) == len(pairs) and len(chosen) == 2 * len(pairs), 'duplicate AC membership')
    records = {}
    for row in _records(folder / 'records.jsonl.gz'):
        if row['submission_id'] in chosen:
            _need(row['submission_id'] not in records, 'duplicate full record')
            records[row['submission_id']] = row
    selected = projection.frame.loc[projection.frame.submission_id.isin(chosen)].to_dict('records')
    analysis = {row['submission_id']: row for row in selected}
    _need(set(records) == set(analysis) == chosen and len(analysis) == len(selected), 'missing or duplicate selected analysis')
    children = set()
    categories = {}
    for pair in pairs:
        child = records[pair[0]].get('child_id')
        _need(isinstance(child, str) and child.strip() and child not in children, 'missing or duplicate child identity')
        children.add(child)
        for wave, sid in zip(('T0', 'T1'), pair):
            record = records[sid]
            _need(record.get('child_id') == child and record['role'] == 'student'
                  and record.get('selected_wave') == wave, 'wrong AC role, child or wave')
            for section, fields in _sections(record, analysis[sid]).items():
                for key in fields:
                    column = f'{wave}_{section}__{key}'
                    categories[column] = dict(wave=wave, section=section, source_field=key)
    headers = list(BASE_COLUMNS)
    for wave in ('T0', 'T1'):
        for section in SECTIONS:
            headers.extend(sorted(k for k, value in categories.items()
                                  if value['wave'] == wave and value['section'] == section))
    _need(len(headers) == len(set(headers)), 'duplicate export columns')
    metadata = dict(dataset_version=dataset_version, release_id=release['release_id'],
                    run_id=release['run_id'], manual_exclusion='ON' if enabled else 'OFF')
    owned = {}
    output.mkdir(mode=0o700)  # Exclusive reservation, including empty existing dirs.
    stat = output.stat()
    directory_identity = stat.st_dev, stat.st_ino
    try:
        csv_path = output / 'student_ac_full.csv'
        with _open_owned(csv_path, owned, encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=headers, quoting=csv.QUOTE_ALL, lineterminator='\r\n')
            writer.writeheader()
            for pair in pairs:
                row = _row(pair, records, analysis, metadata)
                writer.writerow({key: _cell(row.get(key)) for key in headers})
        _verify_csv(csv_path, headers, pairs, records, analysis, metadata)
        dictionary = dict(columns=[dict(column=key, **categories.get(key, {'section': 'export_provenance'})) for key in headers])
        with _open_owned(output / 'column_dictionary.json', owned) as stream:
            json.dump(dictionary, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        with _open_owned(output / 'README.txt', owned) as stream:
            stream.write('Full student AC, one row per original fixed T0/T1 pair. No parent responses joined.\n'
                         'No replacement responses or outcome-completeness filter. Current answers and original source cells stay separate.\n'
                         'T0/T1 prefixes contain record metadata, current answers, original source and analytical fields.\n'
                         'Structured values use JSON. Blank means missing/unavailable or empty text, never an invented zero.\n'
                         'UTF-8 BOM CSV has no Excel cell types. Import identifiers, source strings and numbers with leading zeros as Text.\n'
                         'This identifiable dataset and its provenance are local research exports.\n')
        receipt = dict(format='study2_student_ac_full_export_v1', **metadata,
            created_at=datetime.now(timezone.utc).isoformat(), local_only=True,
            row_count=len(pairs), unique_children=len(children), selected_student_records=len(chosen), column_count=len(headers),
            publication=release, source_sha256=source_pins, published_checksums=published_checksums,
            exclusion_manifest=dict(path=str(manifest_path), sha256=manifest_pin, manifest=manifest) if manifest_path else None,
            fixed_AC_members=[list(pair) for pair in pairs],
            output_sha256={path.name: file_hash(path) for path in owned},
            checks=dict(exact_fixed_membership=True, no_reselection=True, all_cells_roundtrip=True,
                        UTF8_BOM=True, no_parent_join=True, no_outcome_completeness_filter=True,
                        sources_and_publication_unchanged=True, published_consumed_artifacts_verified=True,
                        database_read_only=True))
        manifest_output = output / 'dataset_manifest.json'
        with _open_owned(manifest_output, owned) as stream:
            json.dump(receipt, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            stream.write('\n')
        _need(all(file_hash(Path(path)) == pin for path, pin in source_pins.items()), 'source changed during export')
        _need(manifest_path is None or file_hash(manifest_path) == manifest_pin, 'manifest changed during export')
        _need(_published_release(state) == release, 'publication changed during export')
        return {**receipt, 'output_dir': str(output), 'csv_path': str(csv_path),
                'manifest_path': str(manifest_output), 'manifest_sha256': file_hash(manifest_output)}
    except BaseException:
        _cleanup(output, directory_identity, owned)
        raise
