"""Registered source adapters. Reuse frozen mapping functions, never legacy runners."""
from __future__ import annotations

import ast
import csv
import json
import re
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from .common import PipelineError, digest, file_hash, phone, plain, text, timestamp, utcnow
from .grades import parse_grade


@lru_cache(maxsize=8)
def mapping_module(path: str) -> SimpleNamespace:
    """Only imports, constants and function definitions; no mkdir/read/main.

    These are reviewed local project files, not instructions from survey data.
    Input file hashes are pinned in config and included in every run fingerprint.
    """
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=path)
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)):
            nodes.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [x.id for x in targets if isinstance(x, ast.Name)]
            if names and all(n.isupper() or n == "_non_digit" for n in names) and not any(n in {"FILES", "TEMPLATE_STUDENT", "TEMPLATE_PARENT", "STUDENT_SHEET", "PARENT_SHEET"} for n in names):
                nodes.append(node)
    namespace = {"__name__": "study2_frozen_mapping", "__file__": path}
    exec(compile(ast.Module(nodes, type_ignores=[]), path, "exec"), namespace)
    return SimpleNamespace(**namespace)


def modules(cfg: dict):
    folder = Path(cfg["mapping_dir"])
    result = tuple(mapping_module(str(folder / name)) for name in [
        "2.1.1_produce_ABCD.py", "1.3.1_standardise_paperform_data.py", "1.3.2_standardise_separate_school_data.py"])
    # Preserve the newly observed relatives choice separately from legacy
    # code 5 (Other). Raw wording remains available in submission_versions.
    result[0].STUDENT_HOUSEHOLD_MAP.update({"親戚": 6, "親屬": 6, "Relatives": 6})
    # Replace the reviewed legacy helper in its shared function namespace too:
    # it must not extract digits from emails or arbitrary text.
    result[0].process_student_row.__globals__["clean_phone"] = phone
    result[0].clean_phone = phone
    return result


def read_source(path: Path, entry: dict, online, *, headers_only=False) -> pd.DataFrame:
    if entry["kind"] == "qualtrics":
        return online.read_qualtrics_csv(str(path))
    sheet = entry.get('sheet', 0)
    if not headers_only:
        return pd.read_excel(path, sheet_name=sheet)
    # pandas nrows=0 alone misses trailing unnamed columns with body values.
    # Use the declared worksheet width to detect that ambiguous case and fall
    # back to the full reader. Formatting-only extra columns can also trigger
    # the conservative fallback; they never change the registered schema.
    with pd.ExcelFile(path) as excel:
        if excel.engine != 'openpyxl':
            return excel.parse(sheet_name=sheet)
        worksheet = excel.book[sheet] if isinstance(sheet, str) else excel.book.worksheets[sheet]
        width = worksheet.max_column
        header = excel.parse(sheet_name=sheet, nrows=0)
        if width is None or width > len(header.columns):
            return excel.parse(sheet_name=sheet)
        return header


def source_root(cfg: dict) -> Path:
    project = Path(cfg["project_root"]).resolve()
    root = (project / cfg.get("source_folder", "1.1_raw_file")).resolve()
    if root != project and project not in root.parents:
        raise PipelineError("Registered source folder must remain inside the study project")
    return root


def discover(cfg: dict) -> list[dict]:
    raw = source_root(cfg)
    selected = []
    for entry in cfg["sources"]:
        paths = sorted(raw.glob(entry["pattern"]))
        if entry.get("selection") == "latest_numbered":
            paths = sorted(paths, key=lambda p: int(re.search(r"_(\d+)\.xlsx$", p.name)[1]))[-1:]
        if len(paths) != 1:
            raise PipelineError(f"Source {entry['source_id']} requires exactly one file, found {len(paths)}")
        selected.append({**entry, "file": paths[0].name, "sha256": file_hash(paths[0])})
    return selected


def make_manifest(cfg: dict, exported_at: str | None = None) -> dict:
    online, _, _ = modules(cfg)
    selected = discover(cfg)
    for source in selected:
        frame = read_source(source_root(cfg) / source["file"], source, online, headers_only=True)
        if set(map(str, frame.columns)) != set(source["columns"]):
            raise PipelineError(f"Unregistered columns in {source['source_id']}; approve schema change before running")
    return {"manifest_version": 1, "created_at": utcnow(), "exported_at": exported_at,
            "export_time_provenance": "collector_supplied" if exported_at else "unknown",
            "sources": [{k: s[k] for k in ["source_id", "file", "sha256"]} for s in selected]}


def check_manifest(cfg: dict, manifest: dict) -> list[dict]:
    if manifest.get("manifest_version") != 1:
        raise PipelineError("Unsupported manifest format")
    supplied = manifest.get("sources", [])
    required = {s["source_id"]: s for s in cfg["sources"]}
    if len(supplied) != len(required) or {s["source_id"] for s in supplied} != set(required):
        raise PipelineError("Batch must contain each registered source exactly once")
    selected = []
    root = source_root(cfg)
    for source in supplied:
        path = (root / source["file"]).resolve()
        if path.parent != root or not path.is_file():
            raise PipelineError("Manifest source must be an existing direct raw-folder file")
        entry = required[source["source_id"]]
        if not path.match(entry["pattern"]) or file_hash(path) != source["sha256"]:
            raise PipelineError("Source changed after batch completion or has wrong filename")
        selected.append({**entry, **source})
    for name, expected in cfg["mapping_hashes"].items():
        if file_hash(Path(cfg["mapping_dir"]) / name) != expected:
            raise PipelineError("Frozen mapping code changed; update mapping revision explicitly")
    return selected


def build_record(source: dict, raw: dict, answer: dict, role: str, wave: str,
                 row: int, key: str, actual_time=None, batch_time=None, status="eligible") -> dict:
    raw = plain(raw)
    answer = plain(answer)
    namespace = source.get("survey_namespace", source["source_id"])
    source_key = namespace + ":" + key
    sid = "SUB_" + digest(source_key)[:28]
    raw_hash = digest(raw)
    observed = timestamp(actual_time)
    return {"submission_id": sid, "source_key": source_key, "version_id": digest([sid, raw_hash]),
            "raw_hash": raw_hash, "raw": raw, "answer": answer, "role": role,
            "source_id": source["source_id"], "source_kind": source["kind"], "claimed_wave": wave,
            "observed_at": observed.isoformat() if observed else None,
            "time_confidence": "observed" if observed else ("batch_only" if batch_time else "unknown"),
            "batch_at": batch_time, "status": status, "issues": [],
            "location": {"file": source["file"], "sha256": source["sha256"], "sheet": source.get("sheet", 0), "row": row}}


def input_records(cfg: dict, manifest: dict, db=None) -> list[dict]:
    online, paper, school = modules(cfg)
    entries = check_manifest(cfg, manifest)
    records = []
    unknowns = set()
    for source in entries:
        path = source_root(cfg) / source["file"]
        frame = read_source(path, source, online)
        if set(map(str, frame.columns)) != set(source["columns"]):
            raise PipelineError(f"Source schema mismatch: {source['source_id']}")
        if source["kind"] == "merged":
            # Already standardized: never repeat FQOL +1 or reconstruct raw
            # questionnaires. Register immutable original row occurrences.
            from .paper_registry import resolve_paper_rows
            rows = [(i + 2, row.to_dict()) for i, row in frame.iterrows() if any(text(v) for v in row)]
            keys = resolve_paper_rows(db, source, rows)
            for position, raw in rows:
                creation = raw.get("建立時間")
                record = build_record(source, raw, dict(raw), source["role"], source["wave"],
                                      position, keys[position], actual_time=creation)
                label = text(raw.get("Survey"))
                record["date_basis"] = "batch_assigned_creation" if label.startswith(("paperform", "separate_data", "socialworkdream")) else "system_creation"
                record["time_confidence"] = ("accepted_creation_time" if record["date_basis"] == "batch_assigned_creation" else "observed") if record["observed_at"] else "unknown"
                record["date_policy"] = "current_creation_time_accepted_by_research_owner_20261006"
                record["source_label"] = label
                records.append(record)
        elif source["kind"] == "system":
            normalized = online.normalize_system_columns(frame.copy())
            for i, row in normalized.iterrows():
                raw = frame.iloc[i].to_dict()
                role, wave = online.detect_role_and_wave(row.get("Survey"))
                if not role or not wave:
                    # Preserve non-panel / unresolved rows but exclude from analysis.
                    role, wave = source["role"], "unknown"
                    answer, status = {}, "unrecognized_survey"
                else:
                    mapper = online.process_student_row if role == "student" else online.process_parent_row
                    answer = mapper(row, wave)
                    for n in range(1, 22):
                        col = f"{role}_FQOL_{n:02d}"
                        try:
                            answer[col] = float(answer.get(col)) + 1
                        except (ValueError, TypeError):
                            answer[col] = None
                    for col in ["contact_01", "contact_02"]:
                        answer[col] = online.clean_phone(answer.get(col))
                    col = "student_demographics_06" if role == "student" else "adult_demographics_03"
                    answer[col] = online.clean_dob_value(answer.get(col))
                    status = "eligible"
                created = text(row.get("建立時間"))
                if not created:
                    raise PipelineError("Nonempty old-system row without original creation time; identity requires review")
                key = digest([source["role"], text(row.get("Survey")), created])
                records.append(build_record(source, raw, answer, role, wave, i + 2, key, created, status=status))
        elif source["kind"] == "qualtrics":
            complete_indices = set(online.complete_qualtrics_rows(frame).index)
            for i, row in frame.iterrows():
                rid = text(row.get("_recordId"))
                if not rid:
                    if not any(text(v) for v in row):
                        continue
                    raise PipelineError("Qualtrics row without ResponseId")
                role, wave = source["role"], source["wave"]
                mapper = online.process_qualtrics_student if role == "student" else online.process_qualtrics_parent
                answer = mapper(row, wave, unknowns)
                for n in range(1, 22):
                    col = f"{role}_FQOL_{n:02d}"
                    try:
                        answer[col] = float(answer.get(col)) + 1
                    except (ValueError, TypeError):
                        answer[col] = None
                records.append(build_record(source, row.to_dict(), answer, role, wave, i + 4, rid,
                                            answer.get("建立時間"), status="eligible" if i in complete_indices else "incomplete"))
        else:
            role = source["role"]
            from .paper_registry import resolve_paper_rows
            paper_rows = [(i + 2, row.to_dict()) for i, row in frame.iterrows() if any(text(v) for v in row)]
            keys = resolve_paper_rows(db, source, paper_rows)
            cols = paper.STUDENT_COLUMNS if role == "student" else paper.PARENT_COLUMNS
            if source["kind"] == "school":
                prepared = school.replace_999_with_nan(frame.copy())
                fn = getattr(school, ("standardise_direct_" if source.get("direct") else "standardise_") + role + "_df")
                kwargs = {role + "_cols": cols}
                standardized = fn(prepared, source["school"], source["source_id"], **kwargs)
                standardized = school.clean_output_dobs(standardized)
            else:
                prepared = frame.copy()
                prepared["__source_file__"] = source["file"]
                mapping = getattr(paper, ("STUDENT" if role == "student" else "PARENT") + "_MAP_" + ("SWD" if source.get("swd") else "NORMAL"))
                if role == "student":
                    standardized = paper.standardise_student(prepared, mapping, source["file"], "contact_from_student")
                else:
                    standardized = paper.standardise_parent(prepared, mapping, source["file"])
                standardized = standardized.astype(object)
                # Correct numeric phone artefacts using original contact strings.
                for i, original in frame.iterrows():
                    if role == "student":
                        parts = paper.split_contacts(original.get("contact_from_student"))
                        standardized.loc[i, "contact_01"] = online.clean_phone(parts[0]) or None
                        standardized.loc[i, "contact_02"] = online.clean_phone(parts[1]) or None
                    else:
                        for raw_col, target in mapping.items():
                            if target in {"contact_01", "contact_02"} and raw_col in frame:
                                standardized.loc[i, target] = online.clean_phone(original.get(raw_col)) or None
            for i, row in standardized.iterrows():
                original = frame.iloc[i]
                if not any(text(v) for v in original):
                    continue
                wave = source.get("wave", "T0")
                if source["kind"] == "paper" and not source.get("swd"):
                    wave = "T1" if text(original.get("complete_T0_(Y/N)")).upper() == "Y" else "T0"
                # Legacy paper dates are explicitly unreliable. Raw date stays in raw_json.
                answer = row.to_dict()
                answer["Survey"] = source["source_id"]
                records.append(build_record(source, original.to_dict(), answer, role, wave, i + 2,
                                            keys[i + 2], batch_time=source.get("batch_at")))
        print(f"Imported adapter: {source['source_id']} ({len(frame):,} source rows)", flush=True)
    if unknowns:
        raise PipelineError(f"Unregistered Qualtrics answer codes in {len(unknowns)} fields; review mappings")
    return records


def normalize_records(records: list[dict], dictionary: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    lookup = {}
    school_queue = {}
    for row in dictionary.fillna("").to_dict("records"):
        key = text(row.get("normalized_key") or row.get("raw_name")).lower()
        if not key:
            continue
        canonical = {k: text(row.get(k)) for k in ["canonical_school_name", "action", "school_type", "school_sex", "school_district", "school_religion"]}
        if key in lookup and lookup[key] != canonical:
            raise PipelineError("Conflicting school dictionary keys")
        lookup[key] = canonical
    for record in records:
        ans = record["answer"]
        role = record["role"]
        primary = "school_from_student" if role == "student" else "school_from_parent"
        for column in ["school_from_student", "school_from_parent"]:
            value = text(ans.get(column))
            key = value.lower()
            if not key:
                continue
            info = lookup.get(key)
            if not info or info["action"].lower() != "map" or not info["canonical_school_name"]:
                if info and info["action"].lower() == "delete":
                    record["status"] = "excluded_school"
                else:
                    record["issues"].append("school_unmapped")
                    school_queue[key] = {"normalized_key": key, "raw_name": value}
                continue
            ans[column] = info["canonical_school_name"]
            if column == primary:
                ans.update({k: info[k] for k in ["school_type", "school_sex", "school_district", "school_religion"]})
        demo = "student_demographics_" if role == "student" else "adult_demographics_"
        record["dob"] = text(ans.get(demo + ("06" if role == "student" else "03")))
        record["gender"] = text(ans.get(demo + ("03" if role == "student" else "04")))
        born = timestamp(record["dob"])
        observed = timestamp(record.get("observed_at"))
        if not born or born.year < 1900 or born > (observed or timestamp(utcnow())):
            if record["dob"]:
                record["issues"].append("invalid_child_dob")
            record["dob"] = ""
        else:
            record["dob"] = born.date().isoformat()
        if record["gender"] not in {"0", "1"}:
            record["gender"] = ""
        record["school"] = text(ans.get(primary)) if "school_unmapped" not in record["issues"] else ""
        grade_raw = text(record.get("grade_raw", ans.get(demo + "01")))
        record["grade_raw"] = grade_raw
        grade = parse_grade(grade_raw).number
        record["issues"] = [issue for issue in record["issues"] if issue != "grade_unclear"]
        if grade is None and grade_raw:
            record["issues"].append("grade_unclear")
        ans[demo + "01"] = grade
        record["grade"] = grade
        empty = 0
        scale_count = 0
        for name in list(ans):
            match = re.fullmatch(r"(?:student|parent)_(PHQ|TBV|TBP|CBV|CBP|FQOL|SEC)_\d{2}", name)
            if not match:
                continue
            scale_count += 1
            lo, hi = {"PHQ": (0, 3), "SEC": (0, 3), "FQOL": (1, 5)}.get(match[1], (0, 4))
            raw_value = text(ans[name])
            try:
                number = float(raw_value)
                valid = number.is_integer() and lo <= number <= hi
            except ValueError:
                valid = False
            if not valid:
                if raw_value and raw_value not in {"999", "999.0"}:
                    record["issues"].append("invalid_scale_code:" + name)
                ans[name] = None
                empty += 1
            else:
                ans[name] = int(number)
        if record["status"] == "eligible" and (scale_count == 0 or empty / scale_count > .9):
            record["status"] = "sparse_response"
    return records, sorted(school_queue.values(), key=lambda r: r["normalized_key"])
