from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


class PipelineError(RuntimeError):
    """A failure that must not replace the last published release."""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def plain(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [plain(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return plain(value.item())
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if str(value) in {"NaT", "<NA>"}:
        return None
    return value


def dumps(value: Any) -> str:
    return json.dumps(plain(value), sort_keys=True, ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def text(value: Any) -> str:
    value = plain(value)
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def phone(value: Any) -> str:
    s = text(value)
    if "@" in s or not s:
        return ""
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    s = re.sub(r"[\s()+\-]", "", s)
    if s.startswith("852") and len(s) == 11:
        s = s[3:]
    # Do not concatenate slash-separated numbers, extract digits from arbitrary
    # words or use six-digit strings as identity evidence.
    return s if re.fullmatch(r"[0-9]{8}", s) else ""


def contacts(answer: dict) -> set[str]:
    found = set()
    for name in ["contact_01", "contact_02", "contact_03.1", "contact_03.2", "contact_03.3", "contact_03.4"]:
        for part in re.split(r"[/;,]", text(answer.get(name))):
            p = phone(part)
            if p:
                found.add(p)
            elif "@" in part and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", part.strip()):
                found.add(part.strip().lower())
    return found


def fuzzy_phone(a: str, b: str) -> bool:
    if not phone(a) or not phone(b) or a == b:
        return False
    differences = [(x, y) for x, y in zip(a, b) if x != y]
    return len(differences) == 1 or (len(differences) == 2 and differences[0] == differences[1][::-1])


def timestamp(value: Any) -> datetime | None:
    s = text(value)
    if not s:
        return None
    try:
        result = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(dumps(value), encoding="utf-8")
    os.replace(temporary, path)


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text())
    for name in ["project_root", "state_dir", "release_dir", "inbox_dir"]:
        cfg[name] = str(Path(cfg[name]).expanduser().resolve())
    state = Path(cfg["state_dir"])
    if any(part.lower() in {"onedrive", "dropbox", "google drive", "icloud drive"} or "onedrive" in part.lower() for part in state.parts):
        raise PipelineError("Live state/database must be outside a synchronized drive")
    if cfg["minimum_followup_days"] < cfg["duplicate_days"]:
        raise PipelineError("Follow-up interval cannot be shorter than the duplicate interval")
    return cfg


def secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
