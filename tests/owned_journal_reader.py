"""Synthetic native reader used only by owner/journal integration tests."""
import fcntl
import importlib.util
from pathlib import Path
import sqlite3
import sys

entry = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('owned_selected_entry', entry)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
_, cfg, _ = module.prepare(sys.argv[2:] + ['dashboard'])
state = Path(cfg['state_dir'])
with (state / 'writer.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_SH)
    with sqlite3.connect((state / 'study2.sqlite').as_uri() + '?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        assert db.execute('SELECT release_id FROM publication WHERE singleton=1').fetchone()
        if (state / 'synthetic-noisy-reader').exists():
            for stream in (sys.stdout, sys.stderr):
                stream.write('x' * (1024 * 1024) + '\n')
                stream.flush()
        (state / 'synthetic-reader-ready').write_text('ready')
        print('READY', flush=True)
        sys.stdin.readline()
