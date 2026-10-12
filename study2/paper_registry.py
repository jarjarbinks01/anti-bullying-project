"""Register original paper rows once; resolve later order by exact content.

Unknown edits/deletions cannot safely reuse row-position identities. Stop and
request controlled corrections rather than treating them as new people.
"""
from collections import Counter, defaultdict

from .common import PipelineError, digest, utcnow


def resolve_paper_rows(db, source, rows):
    hashes = [(position, digest(raw)) for position, raw in rows]
    if db is None:
        return {position: f"{source.get('sheet', 0)}:registered_row:{position}" for position, _ in hashes}
    known = list(db.execute("SELECT * FROM paper_registry WHERE source_id=? ORDER BY slot", (source["source_id"],)))
    count = Counter(h for _, h in hashes)
    old_count = Counter(r["raw_hash"] for r in known)
    if any(count[h] < n for h, n in old_count.items()):
        raise PipelineError("Registered paper rows were edited/deleted; cannot infer identity. Use controlled corrections or explicitly register a new source")
    slots = defaultdict(list)
    for row in known:
        slots[row["raw_hash"]].append(row["slot"])
    consumed = Counter()
    next_slot = max((r["slot"] for r in known), default=1) + 1
    resolved = {}
    for position, h in hashes:
        ordinal = consumed[h]
        if ordinal < len(slots[h]):
            slot = slots[h][ordinal]
        else:
            slot = position if not known else next_slot
            next_slot = max(next_slot, slot + 1)
            db.execute("INSERT INTO paper_registry VALUES(?,?,?,?,?,?)", (source["source_id"], slot, h, source["file"], position, utcnow()))
        consumed[h] += 1
        resolved[position] = f"{source.get('sheet', 0)}:registered_row:{slot}"
    return resolved
