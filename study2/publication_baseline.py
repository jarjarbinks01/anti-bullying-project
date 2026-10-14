"""Small publication revision bound to verified recovery and output manifests."""
import json
import sqlite3
from pathlib import Path

from .common import PipelineError, atomic_json, digest, file_hash
from .store import backup_path


def ensure_baseline(folder,release_id):
    folder=Path(folder);path=folder/'PUBLICATION_BASELINE.json'
    if path.exists():return read_baseline(folder,release_id)
    backup=folder/'backup.sqlite'
    if not backup.is_file() and not backup.with_name(backup.name+'.gz').is_file():return None
    original=json.loads((folder/'backup.sha256.json').read_text())['backup.sqlite']
    with backup_path(backup,original) as plain:
        db=sqlite3.connect(plain.resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
        try:
            from .dyad_operator import _review_revision
            body={'format_version':1,'release_id':release_id,'source_backup_sha256':original,
                  'review_revision':_review_revision(db),
                  'applied_batches':[r[0] for r in db.execute('SELECT batch_id FROM review_applications ORDER BY batch_id')]}
        finally:db.close()
    atomic_json(path,body)
    checks=json.loads((folder/'checksums.json').read_text())
    checks[path.name]=file_hash(path);atomic_json(folder/'checksums.json',checks)
    return body


def read_baseline(folder,release_id):
    folder=Path(folder);path=folder/'PUBLICATION_BASELINE.json'
    if not path.exists():return None
    checks=json.loads((folder/'checksums.json').read_text())
    if checks.get(path.name)!=file_hash(path):raise PipelineError('Published revision baseline checksum mismatch')
    body=json.loads(path.read_text())
    original=json.loads((folder/'backup.sha256.json').read_text())['backup.sqlite']
    if body.get('format_version')!=1 or body.get('release_id')!=release_id or body.get('source_backup_sha256')!=original:
        raise PipelineError('Published revision baseline does not match its verified backup')
    return body
