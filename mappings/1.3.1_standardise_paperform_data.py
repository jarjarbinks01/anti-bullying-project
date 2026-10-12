# -*- coding: utf-8 -*-
"""
Step 1.3 – Standardise paper-form raw files into the SAME schema as A (student) / B (parent)

Input (under base_dir/1.1_raw_file):
    - HKU_2026_Student_final.xlsx
    - HKU_2026_Parent_final.xlsx
    - HKU_2026_Student (Social Work Dream).xlsx
    - HKU_2026_Parent (Social Work Dream).xlsx

    NEW (log2; same schema as the above):
    - HKU_2026_Student_final_log2.xlsx
    - HKU_2026_Parent_final_log2.xlsx
    - HKU_2026_Student (Social Work Dream)_log2.xlsx
    - HKU_2026_Parent (Social Work Dream)_log2.xlsx

Output (under base_dir/1.3_standardised_paperform_data):
(A) Normal (split by complete_T0_(Y/N)):
    - T0_student_paperform.xlsx
    - T0_parent_paperform.xlsx
    - T1_student_paperform.xlsx
    - T1_parent_paperform.xlsx

(B) Social Work Dream (NO T0/T1 classification yet):
    - student_socialworkdream.xlsx
    - parent_socialworkdream.xlsx

Key rules:
1) For Normal files:
   - If complete_T0_(Y/N) == "Y" => treat as T1
   - Else (N/empty/missing)      => treat as T0
2) Mapping:
   - Use hard-coded maps (converted from your student_map.xlsx / parent_map.xlsx)
   - Unspecified measurement-scale columns are assumed already standardised
     (e.g., student_SEC_08 -> student_SEC_08).
3) FQOL shift: 0/1/2/3/4 -> 1/2/3/4/5 for all *_FQOL_01..21 (student + parent).
4) Convert numeric-looking strings to numeric where sensible (avoid contacts by default).
5) contact_from_student may contain multiple contacts separated by '/':
   - extract first 2 and map to contact_01 / contact_02.

New amendments (2026-02-03):
6) Convert phone columns to numbers where possible:
   - Student outputs: contact_01 & contact_02 -> numeric (phone)
   - Parent outputs:  contact_01 & contact_02 -> numeric (phone)
7) Fix "empty rows between records" in Normal outputs:
   - Ensure post-split indices are reset; ensure_schema assigns by position.
8) DOB cleanup:
   - Student: student_demographics_06
   - Parent:  adult_demographics_03
   - Accept common Excel/date formats where possible; output yyyy-mm-dd; else empty.
9) School-name cleaning is NOT handled in this script:
   - 1.3.1 only standardises paperform/SWD data into the target schema.
   - School names are cleaned later in Step 2.1.3 together with all A/B/C/D sources.
10) Invalid-entry filter:
    - If a row has >90% cells empty, treat as invalid and drop (applies to all inputs).

NEW amendments (2026-03-04):
11) Support *_log2.xlsx inputs:
    - read BOTH original + log2 files (if present), concat row-wise
    - Survey column is set per-row to the TRUE source filename (so you can differentiate versions)

12) Paper-form creation time assignment:
    - overwrite 建立時間 using the source file batch because raw paper-form dates are not reliable
    - original files -> 2026-02-01
    - *_log2.xlsx files -> 2026-03-01
"""

import os
import re
import pandas as pd
import numpy as np
import warnings
from datetime import datetime
from typing import Optional, Tuple, Set, List

# ------------------------------------------------------------
# Warnings (keep terminal clean)
# ------------------------------------------------------------
warnings.filterwarnings(
    "ignore",
    message="Cannot parse header or footer so it will be ignored",
    category=UserWarning,
    module="openpyxl"
)

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
base_dir = os.path.expanduser("~/Desktop/Python/Antibully_study2_v2")
if not os.path.isdir(base_dir):
    base_dir = os.path.dirname(os.path.abspath(__file__))

raw_dir = os.path.join(base_dir, "1.1_raw_file")
out_dir = os.path.join(base_dir, "1.3_standardised_paperform_data")
os.makedirs(out_dir, exist_ok=True)

# Raw filenames (exact)
STU_NORMAL_FILE = "HKU_2026_Student_final.xlsx"
PAR_NORMAL_FILE = "HKU_2026_Parent_final.xlsx"
STU_SWD_FILE = "HKU_2026_Student (Social Work Dream).xlsx"
PAR_SWD_FILE = "HKU_2026_Parent (Social Work Dream).xlsx"

# NEW: log2 raw filenames (same schema)
STU_NORMAL_FILE_LOG2 = "HKU_2026_Student_final_log2.xlsx"
PAR_NORMAL_FILE_LOG2 = "HKU_2026_Parent_final_log2.xlsx"
STU_SWD_FILE_LOG2 = "HKU_2026_Student (Social Work Dream)_log2.xlsx"
PAR_SWD_FILE_LOG2 = "HKU_2026_Parent (Social Work Dream)_log2.xlsx"

# Invalid entry threshold: >90% empty => drop
INVALID_EMPTY_RATIO = 0.90

# ------------------------------------------------------------
# Target schema (exact headers of A/B)
# ------------------------------------------------------------
STUDENT_COLUMNS = [
    "Survey", "建立時間", "更新時間", "school_from_student", "school_from_parent", "student_answer",
    "previous_term_school_data_01", "previous_term_school_data_02", "contact_01", "contact_02",
    "student_demographics_01", "student_demographics_02", "student_demographics_03",
    "student_demographics_04", "student_demographics_05", "student_demographics_06",
    "student_demographics_07", "student_demographics_07.1", "student_demographics_08",
    "student_demographics_08.1", "student_demographics_09.1", "student_demographics_09.2",
    "student_demographics_09.3", "student_demographics_09.4", "student_demographics_10",
    "student_demographics_11",
    "student_PHQ_01", "student_PHQ_02", "student_PHQ_03", "student_PHQ_04",
    "student_TBV_01", "student_TBV_02", "student_TBV_03", "student_TBV_04", "student_TBV_05", "student_TBV_06", "student_TBV_07",
    "student_TBP_01", "student_TBP_02", "student_TBP_03", "student_TBP_04", "student_TBP_05", "student_TBP_06", "student_TBP_07",
    "student_CBV_01", "student_CBV_02", "student_CBV_03", "student_CBV_04", "student_CBV_05", "student_CBV_06",
    "student_CBP_01", "student_CBP_02", "student_CBP_03", "student_CBP_04", "student_CBP_05", "student_CBP_06",
    "student_FQOL_01", "student_FQOL_02", "student_FQOL_03", "student_FQOL_04", "student_FQOL_05", "student_FQOL_06",
    "student_FQOL_07", "student_FQOL_08", "student_FQOL_09", "student_FQOL_10", "student_FQOL_11", "student_FQOL_12",
    "student_FQOL_13", "student_FQOL_14", "student_FQOL_15", "student_FQOL_16", "student_FQOL_17", "student_FQOL_18",
    "student_FQOL_19", "student_FQOL_20", "student_FQOL_21",
    "student_SEC_01", "student_SEC_02", "student_SEC_03", "student_SEC_04", "student_SEC_05", "student_SEC_06", "student_SEC_07",
    "student_SEC_08", "student_SEC_09", "student_SEC_10", "student_SEC_11", "student_SEC_12", "student_SEC_13", "student_SEC_14",
    "student_SEC_15", "student_SEC_16", "student_SEC_17", "student_SEC_18", "student_SEC_19", "student_SEC_20", "student_SEC_21",
    "student_SEC_22",
]

PARENT_COLUMNS = [
    "Survey", "建立時間", "更新時間", "school_from_student", "school_from_parent", "parent_answer",
    "previous_term_01", "previous_term_02", "contact_01", "contact_02",
    "contact_03.1", "contact_03.2", "contact_03.3", "contact_03.4",
    "adult_demographics_01", "adult_demographics_02", "adult_demographics_03", "adult_demographics_04", "adult_demographics_04.1",
    "adult_demographics_05", "adult_demographics_06", "adult_demographics_06.1", "adult_demographics_07", "adult_demographics_07.1",
    "adult_demographics_08", "adult_demographics_09", "adult_demographics_10", "adult_demographics_11", "adult_demographics_12",
    "adult_demographics_13", "adult_demographics_14", "adult_demographics_14.1",
    "parent_PHQ_01", "parent_PHQ_02", "parent_PHQ_03", "parent_PHQ_04",
    "parent_TBV_01", "parent_TBV_02", "parent_TBV_03", "parent_TBV_04", "parent_TBV_05", "parent_TBV_06", "parent_TBV_07",
    "parent_TBP_01", "parent_TBP_02", "parent_TBP_03", "parent_TBP_04", "parent_TBP_05", "parent_TBP_06", "parent_TBP_07",
    "parent_CBV_01", "parent_CBV_02", "parent_CBV_03", "parent_CBV_04", "parent_CBV_05", "parent_CBV_06",
    "parent_CBP_01", "parent_CBP_02", "parent_CBP_03", "parent_CBP_04", "parent_CBP_05", "parent_CBP_06",
    "parent_FQOL_01", "parent_FQOL_02", "parent_FQOL_03", "parent_FQOL_04", "parent_FQOL_05", "parent_FQOL_06",
    "parent_FQOL_07", "parent_FQOL_08", "parent_FQOL_09", "parent_FQOL_10", "parent_FQOL_11", "parent_FQOL_12",
    "parent_FQOL_13", "parent_FQOL_14", "parent_FQOL_15", "parent_FQOL_16", "parent_FQOL_17", "parent_FQOL_18",
    "parent_FQOL_19", "parent_FQOL_20", "parent_FQOL_21",
    "parent_SEC_01", "parent_SEC_02", "parent_SEC_03", "parent_SEC_04", "parent_SEC_05", "parent_SEC_06", "parent_SEC_07",
    "parent_SEC_08", "parent_SEC_09", "parent_SEC_10", "parent_SEC_11", "parent_SEC_12", "parent_SEC_13", "parent_SEC_14",
    "parent_SEC_15", "parent_SEC_16", "parent_SEC_17", "parent_SEC_18", "parent_SEC_19", "parent_SEC_20", "parent_SEC_21",
    "parent_SEC_22",
]

# ------------------------------------------------------------
# Hard-coded mapping maps (from your uploaded maps)
# ------------------------------------------------------------
STUDENT_MAP_NORMAL = {
    "sign_date": "建立時間",
    "student_demographics_01": "school_from_student",
    "student_demographics_02": "student_demographics_01",
    "ClassNo": "student_demographics_02",
    "student_demographics_03": "student_demographics_03",
    "student_demographics_04": "student_demographics_04",
    "student_demographics_05": "student_demographics_05",
    "student_demographics_06": "student_demographics_06",
    "student_demographics_07": "student_demographics_07",
    "student_demographics_07.1": "student_demographics_07.1",
    "student_demographics_08": "student_demographics_08",
    "student_demographics_08.1": "student_demographics_08.1",
    "student_demographics_09.1": "student_demographics_09.1",
    "student_demographics_09.2": "student_demographics_09.2",
    "student_demographics_09.3": "student_demographics_09.3",
    "student_demographics_09.4": "student_demographics_09.4",
    "student_demographics_10": "student_demographics_10",
    "student_demographics_11": "student_demographics_11",
    # special: complete_T0_(Y/N), contact_from_student
}

PARENT_MAP_NORMAL = {
    "school_from_parent": "school_from_parent",
    "sign_date_1": "建立時間",
    "parent_demographics_01": "adult_demographics_01",
    "parent_demographics_02": "adult_demographics_02",
    "parent_demographics_03": "adult_demographics_03",
    "parent_demographics_04": "adult_demographics_04",
    "parent_demographics_05": "adult_demographics_05",
    "parent_demographics_06": "adult_demographics_06",
    "parent_demographics_06.1": "adult_demographics_06.1",
    "parent_demographics_07": "adult_demographics_07",
    "parent_demographics_07.1": "adult_demographics_07.1",
    "parent_demographics_08": "adult_demographics_08",
    "parent_demographics_09": "adult_demographics_09",
    "parent_demographics_10": "adult_demographics_10",
    "parent_demographics_11": "adult_demographics_11",
    "parent_demographics_12": "adult_demographics_12",
    "parent_demographics_13": "adult_demographics_13",
    "parent_demographics_14": "adult_demographics_14",
    "parent_demographics_14.1": "adult_demographics_14.1",
    "contact_from_parent_01": "contact_01",
    "contact_from_parent_02": "contact_02",
    "contact_from_parent_03": "contact_03.1",
    # special: complete_T0_(Y/N)
}

STUDENT_MAP_SWD = {
    "sign_date": "建立時間",
    "student_demographics_01": "school_from_student",
    "student_demographics_02": "student_demographics_01",
    "student_demographics_03": "student_demographics_03",
    "student_demographics_04": "student_demographics_04",
    "student_demographics_05": "student_demographics_05",
    "student_demographics_06": "student_demographics_06",
    "student_demographics_07": "student_demographics_07",
    "student_demographics_07.1": "student_demographics_07.1",
    "student_demographics_08": "student_demographics_08",
    "student_demographics_08.1": "student_demographics_08.1",
    "student_demographics_09.1": "student_demographics_09.1",
    "student_demographics_09.2": "student_demographics_09.2",
    "student_demographics_09.3": "student_demographics_09.3",
    "student_demographics_09.4": "student_demographics_09.4",
    "student_demographics_10": "student_demographics_10",
    "student_demographics_11": "student_demographics_11",
    "contact_from_student": "contact_01",  # may contain '/', we still split
}

PARENT_MAP_SWD = {
    "SCHOOL": "school_from_parent",
    "Class": "adult_demographics_01",
    "sign_date_1": "建立時間",
    "parent_demographics_03": "adult_demographics_03",
    "parent_demographics_04": "adult_demographics_04",
    "parent_demographics_05": "adult_demographics_05",
    "parent_demographics_06": "adult_demographics_06",
    "parent_demographics_06.1": "adult_demographics_06.1",
    "parent_demographics_07": "adult_demographics_07",
    "parent_demographics_07.1": "adult_demographics_07.1",
    "parent_demographics_08": "adult_demographics_08",
    "parent_demographics_09": "adult_demographics_09",
    "parent_demographics_10": "adult_demographics_10",
    "parent_demographics_11": "adult_demographics_11",
    "parent_demographics_12": "adult_demographics_12",
    "parent_demographics_13": "adult_demographics_13",
    "parent_demographics_14": "adult_demographics_14",
    "parent_demographics_14.1": "adult_demographics_14.1",
    "contact_from_parent_01": "contact_01",
    "contact_from_parent_02": "contact_03.1",
    "contact_from_parent_03": "contact_02",
}

# ============================================================
# IO helpers
# ============================================================
def read_excel_any(path: str) -> pd.DataFrame:
    """
    Read .xls/.xlsx robustly.
    NOTE: for .xls you may need: pip install xlrd==2.0.1
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    try:
        return pd.read_excel(path, engine="xlrd")
    except Exception:
        return pd.read_excel(path)

def read_excel_if_exists(path: str, source_tag: str) -> pd.DataFrame:
    """
    Read excel if exists; return empty df if missing.
    Adds a helper column __source_file__ for row-level provenance,
    so Survey can reflect original vs log2.
    """
    if not os.path.exists(path):
        return pd.DataFrame()
    df = read_excel_any(path)
    df["__source_file__"] = source_tag
    return df


def assigned_creation_time_from_source(source_tag: str) -> str:
    """
    Assign batch-level 建立時間 for paper-form data.

    The raw sign_date / sign_date_1 values in paper-form files are not reliable
    enough for later same-person ordering. We therefore overwrite 建立時間 based
    on the raw file batch.
    """
    s = "" if source_tag is None else str(source_tag)
    if "_log2" in s:
        return "2026-03-01"
    return "2026-02-01"

def ensure_schema(df: pd.DataFrame, target_cols: List[str]) -> pd.DataFrame:
    """
    Align by position (RangeIndex) to avoid blank-row artifacts.
    """
    df = df.reset_index(drop=True).copy()
    out = pd.DataFrame({c: pd.Series([np.nan] * len(df)) for c in target_cols})
    for c in target_cols:
        if c in df.columns:
            out[c] = df[c].values
    return out

# ============================================================
# Data cleaning / transforms
# ============================================================
FQOL_STU_RE = re.compile(r"^student_FQOL_\d{2}$")
FQOL_PAR_RE = re.compile(r"^parent_FQOL_\d{2}$")

def shift_fqol(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        if FQOL_STU_RE.match(c) or FQOL_PAR_RE.match(c):
            s = pd.to_numeric(df[c], errors="coerce")
            df[c] = np.where(s.notna(), s + 1, df[c])
    return df

def split_contacts(value) -> Tuple[str, str]:
    """
    Extract first 2 contacts separated by '/'.
    Initially keep as strings (we later try to convert to numeric for requested columns).
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ("", "")
    s = str(value).strip()
    if s == "":
        return ("", "")
    parts = [p.strip() for p in s.split("/") if p.strip() != ""]
    c1 = parts[0] if len(parts) >= 1 else ""
    c2 = parts[1] if len(parts) >= 2 else ""
    return (c1, c2)

def maybe_convert_numeric(df: pd.DataFrame, protect_cols: Set[str]) -> pd.DataFrame:
    """
    Convert numeric-looking strings to numbers, but avoid protected cols.
    Heuristic: if >=80% of non-empty values in a column can be converted -> convert column.
    """
    df = df.copy()
    for c in df.columns:
        if c in protect_cols:
            continue
        if c.startswith("contact_") or "contact" in c:
            continue

        series = df[c]
        if series.isna().all():
            continue

        raw = series.astype(str)
        raw = raw.replace({"": np.nan, "nan": np.nan, "None": np.nan})
        non_missing = raw.dropna()
        if non_missing.empty:
            continue

        converted = pd.to_numeric(non_missing, errors="coerce")
        ok_rate = converted.notna().mean()
        if ok_rate >= 0.80:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def fill_school_fields(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure both school_from_student and school_from_parent exist.
    If one missing/blank, copy from the other if available.
    """
    df = df.copy()

    if "school_from_student" not in df.columns:
        df["school_from_student"] = ""
    if "school_from_parent" not in df.columns:
        df["school_from_parent"] = ""

    s = df["school_from_student"].astype(str).replace("nan", "").str.strip()
    p = df["school_from_parent"].astype(str).replace("nan", "").str.strip()

    df["school_from_student"] = np.where((s == "") & (p != ""), p, s)
    df["school_from_parent"] = np.where((p == "") & (s != ""), s, p)
    return df

def strip_object_whitespace_to_nan(df: pd.DataFrame) -> pd.DataFrame:
    """
    Avoid pandas FutureWarning from regex replace by doing explicit object-column cleanup.
    """
    df = df.copy()
    obj_cols = df.select_dtypes(include=["object"]).columns
    if len(obj_cols) == 0:
        return df

    def _clean_cell(v):
        if isinstance(v, str):
            vv = v.strip()
            return np.nan if vv == "" else vv
        return v

    df[obj_cols] = df[obj_cols].apply(lambda col: col.map(_clean_cell))
    return df

def drop_invalid_rows(df: pd.DataFrame, empty_ratio_threshold: float = INVALID_EMPTY_RATIO) -> pd.DataFrame:
    """
    Drop:
      (a) fully empty rows
      (b) rows with >empty_ratio_threshold cells empty (default: >90% empty)
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    # 1) treat whitespace-only strings as empty (NaN) WITHOUT pandas regex replace warnings
    obj_cols = df.select_dtypes(include=["object"]).columns
    if len(obj_cols) > 0:
        df[obj_cols] = df[obj_cols].apply(lambda col: col.map(
            lambda v: np.nan if (isinstance(v, str) and v.strip() == "") else v
        ))

    # 2) drop fully empty rows
    df = df.dropna(how="all")

    # 3) drop sparse rows: >90% empty by default
    total_cols = len(df.columns)
    empty_counts = df.isna().sum(axis=1)
    empty_ratio = empty_counts / float(total_cols)
    df = df.loc[empty_ratio <= empty_ratio_threshold]

    return df.reset_index(drop=True)

def drop_sparse_rows(df: pd.DataFrame, empty_ratio_threshold: float = INVALID_EMPTY_RATIO) -> pd.DataFrame:
    """
    Drop rows where >empty_ratio_threshold of cells are empty.
    Empty = NaN or "" (after trimming object columns).
    """
    if df is None or df.empty:
        return df

    df = strip_object_whitespace_to_nan(df)

    total = len(df.columns)
    if total == 0:
        return df.iloc[0:0].copy()

    empty_counts = df.isna().sum(axis=1)
    empty_ratio = empty_counts / float(total)

    keep = empty_ratio <= empty_ratio_threshold
    return df.loc[keep].reset_index(drop=True)

def coerce_phone_to_int(series: pd.Series) -> pd.Series:
    """
    Convert phone-like values into integers:
      - Extract digits only
      - If no digits -> NA
      - If too short (<6 digits) -> NA
    Output dtype: Int64 (nullable integer)
    """
    if series is None:
        return series

    def parse_phone(value):
        if value is None or pd.isna(value):
            return pd.NA
        digits = re.sub(r"\D+", "", str(value).strip())
        if len(digits) < 6:
            return pd.NA
        try:
            number = int(digits)
        except (TypeError, ValueError, OverflowError):
            return pd.NA
        # Nullable Int64 cannot represent values outside the signed 64-bit
        # range. Such values are not valid single phone numbers and should not
        # abort the whole standardisation step.
        if number > np.iinfo(np.int64).max:
            return pd.NA
        return number

    return series.map(parse_phone).astype("Int64")

def clean_dob_value(v) -> Optional[str]:
    """
    Clean DOB values into yyyy-mm-dd where possible.

    Accept common formats such as:
      - yyyy-m-d / yyyy-mm-dd
      - yyyy/m/d / yyyy/mm/dd
      - yyyy.m.d / yyyy.mm.dd
      - d/m/yyyy / dd/mm/yyyy
      - d-m-yyyy / dd-mm-yyyy
      - Excel date serials within a plausible range
      - pandas Timestamp / datetime objects

    Return None if the value cannot be parsed safely.
    """
    if v is None:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None

    if isinstance(v, (pd.Timestamp, datetime)):
        try:
            dt = pd.to_datetime(v, errors="coerce")
            if pd.isna(dt):
                return None
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None

    # Excel serial date, but avoid interpreting ordinary years such as 2012 as serial dates.
    if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
        try:
            num = float(v)
            if 20000 <= num <= 60000:
                dt = pd.to_datetime(num, unit="D", origin="1899-12-30", errors="coerce")
                if not pd.isna(dt):
                    return dt.strftime("%Y-%m-%d")
        except Exception:
            return None

    s = str(v).strip()
    if s == "" or s.lower() in {"nan", "none", "nat"}:
        return None

    # Remove time part if Excel exported a datetime-like string.
    s = re.sub(r"\s+00:00:00$", "", s)

    # Numeric string Excel serial date.
    if re.match(r"^\d+(\.0)?$", s):
        try:
            num = float(s)
            if 20000 <= num <= 60000:
                dt = pd.to_datetime(num, unit="D", origin="1899-12-30", errors="coerce")
                if not pd.isna(dt):
                    return dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    # Year-first formats: yyyy-m-d, yyyy/m/d, yyyy.m.d
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", s)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None

    # Day-first formats: d/m/yyyy, dd/mm/yyyy, d-m-yyyy, dd-mm-yyyy
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", s)
    if m:
        try:
            dt = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None

    # Final fallback: conservative pandas parsing with dayfirst=True.
    try:
        dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
        if pd.isna(dt):
            return None
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None

def clean_dob_column(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if df is None or df.empty or col not in df.columns:
        return df
    df = df.copy()
    df[col] = df[col].apply(clean_dob_value)
    df[col] = df[col].where(df[col].notna(), np.nan)
    return df

# ============================================================
# School dictionary logic (for SWD only)
# ============================================================
def normalize_school_key(x: str) -> str:
    """
    Normalise school name into a key.
    """
    if x is None:
        return ""
    s = str(x).strip()
    if s == "" or s.lower() in {"nan", "none", "nat"}:
        return ""

    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[\u3000\s]+", " ", s).strip()

    if re.search(r"[A-Za-z]", s):
        s = s.lower()

    return s

def load_school_dictionary(dict_path: str) -> pd.DataFrame:
    if not os.path.exists(dict_path):
        raise FileNotFoundError(f"school_dictionary.xlsx not found: {dict_path}")

    df = pd.read_excel(dict_path)
    needed = {"raw_name", "normalized_key", "canonical_school_name", "action"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"school_dictionary.xlsx missing columns: {sorted(list(missing))}")

    df = df.copy()
    df["__dict_norm_key__"] = df["normalized_key"].apply(normalize_school_key)
    return df

def save_school_dictionary(df_dict: pd.DataFrame, dict_path: str) -> None:
    out = df_dict.copy()
    if "__dict_norm_key__" in out.columns:
        out = out.drop(columns=["__dict_norm_key__"])
    out.to_excel(dict_path, index=False)

def clean_swd_schools_and_update_dict(
    df: pd.DataFrame,
    df_dict: pd.DataFrame,
    school_cols: List[str],
) -> Tuple[pd.DataFrame, pd.DataFrame, Set[str], Set[str]]:
    """
    Clean SWD school columns using dictionary.
    """
    if df is None or df.empty:
        return df, df_dict, set(), set()

    df = df.copy()
    unknown_raw: Set[str] = set()
    unknown_keys: Set[str] = set()

    lookup = {}
    for idx, k in enumerate(df_dict["__dict_norm_key__"].tolist()):
        if k not in lookup:
            lookup[k] = idx

    def _apply_one(value):
        raw = "" if value is None else str(value).strip()
        if raw == "" or raw.lower() in {"nan", "none", "nat"}:
            return ""

        k = normalize_school_key(raw)
        if k == "":
            return ""

        if k in lookup:
            row = df_dict.iloc[lookup[k]]
            action = str(row.get("action", "")).strip().lower()
            canonical = row.get("canonical_school_name", None)

            if action == "delete":
                return ""

            if action == "map":
                if canonical is not None and not (isinstance(canonical, float) and np.isnan(canonical)):
                    canon_str = str(canonical).strip()
                    if canon_str != "" and canon_str.lower() not in {"nan", "none"}:
                        return canon_str
                return raw

            return raw

        unknown_raw.add(raw)
        unknown_keys.add(k)
        return raw

    for col in school_cols:
        if col in df.columns:
            df[col] = df[col].apply(_apply_one)

    if unknown_keys:
        existing_keys = set(df_dict["__dict_norm_key__"].tolist())

        rows_to_add = []
        for raw_name in sorted(list(unknown_raw)):
            k = normalize_school_key(raw_name)
            if k == "" or k in existing_keys:
                continue

            rows_to_add.append({
                "raw_name": raw_name,
                "normalized_key": k,
                "canonical_school_name": np.nan,
                "action": "map",
                "__dict_norm_key__": k,
            })
            existing_keys.add(k)

        if rows_to_add:
            df_dict = pd.concat([df_dict, pd.DataFrame(rows_to_add)], ignore_index=True)

    return df, df_dict, unknown_raw, unknown_keys

# ============================================================
# Core standardiser
# ============================================================
def standardise_student(df_raw: pd.DataFrame, mapping: dict, source_tag: str, contact_raw_col: Optional[str]) -> pd.DataFrame:
    df = df_raw.copy().reset_index(drop=True)
    df.columns = [str(c).strip() for c in df.columns]

    contact_series = df[contact_raw_col] if (contact_raw_col and contact_raw_col in df.columns) else None

    rename_map = {k: v for k, v in mapping.items() if v not in ["***", "/", "", None]}
    df = df.rename(columns=rename_map)

    # Survey: per-row source file if available (original vs log2), else fallback
    if "__source_file__" in df.columns:
        df["Survey"] = df["__source_file__"]
        df["建立時間"] = df["__source_file__"].apply(assigned_creation_time_from_source)
    else:
        df["Survey"] = source_tag
        df["建立時間"] = assigned_creation_time_from_source(source_tag)

    if "更新時間" not in df.columns:
        df["更新時間"] = ""

    df = fill_school_fields(df)

    if contact_series is not None:
        c1c2 = contact_series.apply(split_contacts)
        c1 = c1c2.apply(lambda x: x[0])
        c2 = c1c2.apply(lambda x: x[1])
        # ``contact_series`` is the authoritative raw student-contact field.
        # Assign both split values directly. In the Social Work Dream mapping,
        # contact_from_student is also renamed to contact_01; preserving that
        # renamed value here would concatenate two slash-separated phone
        # numbers during numeric cleaning and could overflow Int64.
        df["contact_01"] = c1
        df["contact_02"] = c2

    df = shift_fqol(df)

    protect = {
        "Survey", "建立時間", "更新時間", "school_from_student", "school_from_parent",
        "student_answer", "previous_term_school_data_01", "previous_term_school_data_02",
        "contact_01", "contact_02",
    }
    df = maybe_convert_numeric(df, protect)

    df = ensure_schema(df, STUDENT_COLUMNS)

    # Phone numeric requirement: student contact_01 & contact_02 -> numeric
    for c in ["contact_01", "contact_02"]:
        if c in df.columns:
            df[c] = coerce_phone_to_int(df[c])

    # DOB cleanup: student_demographics_06
    df = clean_dob_column(df, "student_demographics_06")

    # Drop helper column if it survived
    if "__source_file__" in df.columns:
        df = df.drop(columns=["__source_file__"])

    return df.reset_index(drop=True)

def standardise_parent(df_raw: pd.DataFrame, mapping: dict, source_tag: str) -> pd.DataFrame:
    df = df_raw.copy().reset_index(drop=True)
    df.columns = [str(c).strip() for c in df.columns]

    rename_map = {k: v for k, v in mapping.items() if v not in ["***", "/", "", None]}
    df = df.rename(columns=rename_map)

    # Survey: per-row source file if available (original vs log2), else fallback
    if "__source_file__" in df.columns:
        df["Survey"] = df["__source_file__"]
        df["建立時間"] = df["__source_file__"].apply(assigned_creation_time_from_source)
    else:
        df["Survey"] = source_tag
        df["建立時間"] = assigned_creation_time_from_source(source_tag)

    if "更新時間" not in df.columns:
        df["更新時間"] = ""

    df = fill_school_fields(df)
    df = shift_fqol(df)

    protect = {
        "Survey", "建立時間", "更新時間", "school_from_student", "school_from_parent",
        "parent_answer", "previous_term_01", "previous_term_02",
        "contact_01", "contact_02", "contact_03.1", "contact_03.2", "contact_03.3", "contact_03.4",
        "adult_demographics_14",
    }
    df = maybe_convert_numeric(df, protect)

    df = ensure_schema(df, PARENT_COLUMNS)

    # Phone numeric requirement: parent contact_01 & contact_02 -> numeric
    for c in ["contact_01", "contact_02"]:
        if c in df.columns:
            df[c] = coerce_phone_to_int(df[c])

    # DOB cleanup: adult_demographics_03
    df = clean_dob_column(df, "adult_demographics_03")

    if "__source_file__" in df.columns:
        df = df.drop(columns=["__source_file__"])

    return df.reset_index(drop=True)

# ============================================================
# Normal split helper
# ============================================================
def split_t0_t1(df: pd.DataFrame, flag_col: str = "complete_T0_(Y/N)") -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Return (T0_df, T1_df) based on flag_col:
      - "Y" (case-insensitive) => T1
      - else => T0
    """
    if flag_col not in df.columns:
        t0 = df.copy().reset_index(drop=True)
        t1 = df.iloc[0:0].copy().reset_index(drop=True)
        return t0, t1

    flag = df[flag_col].astype(str).str.strip().str.upper()
    t1_mask = flag == "Y"
    t1 = df.loc[t1_mask].copy().reset_index(drop=True)
    t0 = df.loc[~t1_mask].copy().reset_index(drop=True)
    return t0, t1

# ============================================================
# MAIN
# ============================================================
def main():
    # Paths (original + log2)
    stu_normal_path = os.path.join(raw_dir, STU_NORMAL_FILE)
    par_normal_path = os.path.join(raw_dir, PAR_NORMAL_FILE)
    stu_swd_path = os.path.join(raw_dir, STU_SWD_FILE)
    par_swd_path = os.path.join(raw_dir, PAR_SWD_FILE)

    stu_normal_path2 = os.path.join(raw_dir, STU_NORMAL_FILE_LOG2)
    par_normal_path2 = os.path.join(raw_dir, PAR_NORMAL_FILE_LOG2)
    stu_swd_path2 = os.path.join(raw_dir, STU_SWD_FILE_LOG2)
    par_swd_path2 = os.path.join(raw_dir, PAR_SWD_FILE_LOG2)

    print("Reading raw files (original + log2 if present)...")

    # Read (if exists) and concat. Each row carries __source_file__ => Survey can differentiate.
    df_stu_normal = pd.concat([
        read_excel_if_exists(stu_normal_path, STU_NORMAL_FILE),
        read_excel_if_exists(stu_normal_path2, STU_NORMAL_FILE_LOG2),
    ], ignore_index=True)

    df_par_normal = pd.concat([
        read_excel_if_exists(par_normal_path, PAR_NORMAL_FILE),
        read_excel_if_exists(par_normal_path2, PAR_NORMAL_FILE_LOG2),
    ], ignore_index=True)

    df_stu_swd = pd.concat([
        read_excel_if_exists(stu_swd_path, STU_SWD_FILE),
        read_excel_if_exists(stu_swd_path2, STU_SWD_FILE_LOG2),
    ], ignore_index=True)

    df_par_swd = pd.concat([
        read_excel_if_exists(par_swd_path, PAR_SWD_FILE),
        read_excel_if_exists(par_swd_path2, PAR_SWD_FILE_LOG2),
    ], ignore_index=True)

    # Fail early if nothing was read
    if df_stu_normal.empty and df_par_normal.empty and df_stu_swd.empty and df_par_swd.empty:
        raise FileNotFoundError(
            "None of the expected raw files (original/log2) were found in 1.1_raw_file."
        )

    # Drop invalid entries (fully empty OR >90% empty)
    df_stu_normal = drop_invalid_rows(df_stu_normal).reset_index(drop=True)
    df_par_normal = drop_invalid_rows(df_par_normal).reset_index(drop=True)
    df_stu_swd    = drop_invalid_rows(df_stu_swd).reset_index(drop=True)
    df_par_swd    = drop_invalid_rows(df_par_swd).reset_index(drop=True)

    # ---- Normal: split T0/T1 ----
    t0_stu_raw, t1_stu_raw = split_t0_t1(df_stu_normal, "complete_T0_(Y/N)")
    t0_par_raw, t1_par_raw = split_t0_t1(df_par_normal, "complete_T0_(Y/N)")

    # extra safety: ensure consecutive indices after split (prevents blank rows)
    t0_stu_raw = t0_stu_raw.reset_index(drop=True)
    t1_stu_raw = t1_stu_raw.reset_index(drop=True)
    t0_par_raw = t0_par_raw.reset_index(drop=True)
    t1_par_raw = t1_par_raw.reset_index(drop=True)

    # ---- Standardise Normal ----
    print("Standardising Normal (T0/T1)...")
    t0_stu = standardise_student(
        t0_stu_raw, STUDENT_MAP_NORMAL, source_tag=STU_NORMAL_FILE, contact_raw_col="contact_from_student"
    )
    t1_stu = standardise_student(
        t1_stu_raw, STUDENT_MAP_NORMAL, source_tag=STU_NORMAL_FILE, contact_raw_col="contact_from_student"
    )
    t0_par = standardise_parent(t0_par_raw, PARENT_MAP_NORMAL, source_tag=PAR_NORMAL_FILE)
    t1_par = standardise_parent(t1_par_raw, PARENT_MAP_NORMAL, source_tag=PAR_NORMAL_FILE)

    # Final tidy: run invalid-row removal post-standardisation too (safe)
    t0_stu = drop_invalid_rows(t0_stu).reset_index(drop=True)
    t1_stu = drop_invalid_rows(t1_stu).reset_index(drop=True)
    t0_par = drop_invalid_rows(t0_par).reset_index(drop=True)
    t1_par = drop_invalid_rows(t1_par).reset_index(drop=True)

    # ---- Save Normal outputs ----
    print("Saving Normal outputs...")
    t0_stu.to_excel(os.path.join(out_dir, "T0_student_paperform.xlsx"), index=False)
    t0_par.to_excel(os.path.join(out_dir, "T0_parent_paperform.xlsx"), index=False)
    t1_stu.to_excel(os.path.join(out_dir, "T1_student_paperform.xlsx"), index=False)
    t1_par.to_excel(os.path.join(out_dir, "T1_parent_paperform.xlsx"), index=False)

    # ---- Social Work Dream (no T0/T1 classification yet) ----
    print("Standardising Social Work Dream (NO T0/T1 split)...")
    swd_stu = standardise_student(
        df_stu_swd, STUDENT_MAP_SWD, source_tag=STU_SWD_FILE, contact_raw_col="contact_from_student"
    )
    swd_par = standardise_parent(df_par_swd, PARENT_MAP_SWD, source_tag=PAR_SWD_FILE)

    swd_stu = drop_invalid_rows(swd_stu).reset_index(drop=True)
    swd_par = drop_invalid_rows(swd_par).reset_index(drop=True)

    # School-name cleaning is intentionally handled later in Step 2.1.3,
    # after paperform/SWD files have been merged into A/B/C/D.

    # ---- Save SWD outputs ----
    print("Saving Social Work Dream outputs...")
    swd_stu.to_excel(os.path.join(out_dir, "student_socialworkdream.xlsx"), index=False)
    swd_par.to_excel(os.path.join(out_dir, "parent_socialworkdream.xlsx"), index=False)

    print("\n✅ Step 1.3 done.")
    print(f"Output folder: {out_dir}")
    print(f"Normal T0/T1 sizes (student): {len(t0_stu)} / {len(t1_stu)}")
    print(f"Normal T0/T1 sizes (parent):  {len(t0_par)} / {len(t1_par)}")
    print(f"SocialWorkDream sizes: student={len(swd_stu)}, parent={len(swd_par)}")

if __name__ == "__main__":
    main()
