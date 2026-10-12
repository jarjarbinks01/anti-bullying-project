# -*- coding: utf-8 -*-
"""
Step 1.3.2 – Standardise separate-school T0 datasets (manual entry by helpers)
----------------------------------------------------------------------------

Read from 1.1_raw_file:
  (T0)明愛馬鞍山中學.xlsx
  (T0)東華三院李潤田紀念中學.xlsx
  樂善堂劉德student.xlsx
  樂善堂劉德parent.xlsx

For 明愛馬鞍山中學 and 東華三院李潤田紀念中學, each workbook contains 2 sheets:
  - student_sheet
  - parent_sheet

For 樂善堂劉德學校, student and parent data are stored in two separate workbooks.

Write standardised T0 outputs to 1.3_standardised_paperform_data:
  T0_student_明愛馬鞍山中學.xlsx
  T0_parent_明愛馬鞍山中學.xlsx
  T0_student_東華三院李潤田紀念中學.xlsx
  T0_parent_東華三院李潤田紀念中學.xlsx
  T0_student_樂善堂劉德學校.xlsx
  T0_parent_樂善堂劉德學校.xlsx

New additions (2026-02-xx):
1) Convert 999 (incl. "999", 999.0) to blank (NaN) BEFORE mapping.
2) After mapping, drop rows if >90% blank across measurement-scale columns ONLY:
   PHQ4, SEC, TBV, TBP, CBV, CBP, FQOL.
   Blank = NaN OR empty string OR whitespace-only.
3) For all separate-school outputs, fill both school_from_student and school_from_parent
   using the known school name from the file configuration.
4) Clean standard DOB columns after mapping:
   student_demographics_06 and adult_demographics_03 -> yyyy-mm-dd where possible.
5) Phone cleaning safely handles Excel numeric phone values such as 12345678.0,
   avoiding the erroneous output 123456780.
6) Separate-school creation time assignment:
   - overwrite 建立時間 using the known data-collection batch date
   - 明愛馬鞍山中學 -> 2025-06-01
   - 東華三院李潤田紀念中學 -> 2025-06-01
   - 樂善堂劉德學校 -> 2026-05-01

Notes:
- For mapping destinations/column order: this script tries to read template headers from:
    1.3_standardised_paperform_data/T0_student_paperform.xlsx
    1.3_standardised_paperform_data/T0_parent_paperform.xlsx
  If those templates are missing, it falls back to reasonable default column lists.

- For columns not mentioned in mapping rules: ignored.

- For 樂善堂劉德學校:
    * all cases are treated as T0;
    * contact_from_student maps to contact_01;
    * contact_from_parent_01 maps to contact_01;
    * contact_from_parent_02 maps to contact_02;
    * contact_from_parent_03 maps to contact_03.1;
    * bullying items stay 0–4;
    * FQOL items stay 1–5;
    * SEC items stay 0–3;
    * the 11 newly appended student items are ignored for now.
"""

import os
import re
import pandas as pd
import numpy as np


# ============================================================
# Configuration
# ============================================================
base_dir = os.path.expanduser("~/Desktop/Python/Antibully_study2_v2")
if not os.path.isdir(base_dir):
    base_dir = os.path.dirname(os.path.abspath(__file__))

raw_dir = os.path.join(base_dir, "1.1_raw_file")
out_dir = os.path.join(base_dir, "1.3_standardised_paperform_data")
os.makedirs(out_dir, exist_ok=True)

FILES = [
    {
        "school": "明愛馬鞍山中學",
        "path": os.path.join(raw_dir, "(T0)明愛馬鞍山中學.xlsx"),
        "survey_student": "separate_data_student_明愛馬鞍山中學_t0",
        "survey_parent": "separate_data_parent_明愛馬鞍山中學_t0",
        "assigned_creation_time": "2025-06-01",
        "out_student": os.path.join(out_dir, "T0_student_明愛馬鞍山中學.xlsx"),
        "out_parent": os.path.join(out_dir, "T0_parent_明愛馬鞍山中學.xlsx"),
    },
    {
        "school": "東華三院李潤田紀念中學",
        "path": os.path.join(raw_dir, "(T0)東華三院李潤田紀念中學.xlsx"),
        "survey_student": "separate_data_student_東華三院李潤田紀念中學_t0",
        "survey_parent": "separate_data_parent_東華三院李潤田紀念中學_t0",
        "assigned_creation_time": "2025-06-01",
        "out_student": os.path.join(out_dir, "T0_student_東華三院李潤田紀念中學.xlsx"),
        "out_parent": os.path.join(out_dir, "T0_parent_東華三院李潤田紀念中學.xlsx"),
    },
    {
        "school": "樂善堂劉德學校",
        "student_path": os.path.join(raw_dir, "樂善堂劉德student.xlsx"),
        "parent_path": os.path.join(raw_dir, "樂善堂劉德parent.xlsx"),
        "survey_student": "separate_data_student_樂善堂劉德學校_t0",
        "survey_parent": "separate_data_parent_樂善堂劉德學校_t0",
        "assigned_creation_time": "2026-05-01",
        "out_student": os.path.join(out_dir, "T0_student_樂善堂劉德學校.xlsx"),
        "out_parent": os.path.join(out_dir, "T0_parent_樂善堂劉德學校.xlsx"),
        "direct_standard_columns": True,
    },
]

STUDENT_SHEET = "student_sheet"
PARENT_SHEET = "parent_sheet"

# Try to load column templates from existing 1.3 outputs (best to keep identical schema/order)
TEMPLATE_STUDENT = os.path.join(out_dir, "T0_student_paperform.xlsx")
TEMPLATE_PARENT = os.path.join(out_dir, "T0_parent_paperform.xlsx")

# Drop threshold: >90% blank in scale columns
SCALE_BLANK_THRESHOLD = 0.90


# ============================================================
# Utilities
# ============================================================
_non_digit = re.compile(r"\D+")

def read_sheet(path: str, sheet_name: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return pd.read_excel(path, sheet_name=sheet_name)

def read_first_sheet(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return pd.read_excel(path)

def norm_col(c) -> str:
    """Normalize source column header: strip spaces."""
    return str(c).strip()

def to_num(x):
    """Coerce to numeric if possible; else NaN."""
    if pd.isna(x):
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).strip()
    if s == "" or s.lower() in {"nan", "none", "na"}:
        return np.nan
    try:
        return float(s)
    except Exception:
        return np.nan

def minus_one_series(s: pd.Series) -> pd.Series:
    """Return numeric series - 1, preserving NaN."""
    out = pd.to_numeric(s, errors="coerce")
    return out - 1

def clean_phone(v):
    """
    Clean phone-like contact values safely.

    Key fix:
      Excel may read 8-digit phone numbers as floats, e.g. 12345678.0.
      Converting this directly to string and removing non-digits would produce
      123456780, which is wrong. Therefore numeric values and numeric strings
      ending in .0 are converted to integers before digit extraction.

    Return:
      - an 8-digit HK phone string where possible
      - blank string for missing values
      - stripped original string only if no digit can be extracted
    """
    if pd.isna(v):
        return ""

    # Numeric Excel cell, e.g. 12345678.0 -> "12345678"
    if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
        try:
            if np.isnan(float(v)):
                return ""
        except Exception:
            pass
        try:
            if float(v).is_integer():
                digits = str(int(float(v)))
            else:
                digits = _non_digit.sub("", str(v))
        except Exception:
            digits = _non_digit.sub("", str(v))
    else:
        s = str(v).strip()
        if not s or s.lower() in {"nan", "none", "nat"}:
            return ""

        # Numeric string exported from Excel, e.g. "12345678.0" -> "12345678"
        if re.match(r"^\d+\.0$", s):
            digits = str(int(float(s)))
        else:
            digits = _non_digit.sub("", s)

    if not digits:
        return str(v).strip()

    # Remove HK country code if present, e.g. +852 1234 5678 -> 12345678.
    if len(digits) == 11 and digits.startswith("852"):
        digits = digits[3:]

    return digits

def clean_email(v):
    if pd.isna(v):
        return ""
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none"}:
        return ""
    return s.lower()

def clean_school(v):
    if pd.isna(v):
        return ""
    return str(v).strip()

def ymd_to_date_str(y, m, d) -> str:
    """
    y/m/d may be float/int/str; return yyyy-mm-dd or "" if incomplete.
    """
    yy = to_num(y)
    mm = to_num(m)
    dd = to_num(d)
    if np.isnan(yy) or np.isnan(mm) or np.isnan(dd):
        return ""
    try:
        yi = int(round(yy))
        mi = int(round(mm))
        di = int(round(dd))
        # basic sanity
        if yi < 1900 or yi > 2100:
            return ""
        if mi < 1 or mi > 12:
            return ""
        if di < 1 or di > 31:
            return ""
        return f"{yi:04d}-{mi:02d}-{di:02d}"
    except Exception:
        return ""


def clean_dob_value(v) -> str:
    """
    Clean DOB values into yyyy-mm-dd where possible.
    Return empty string if the value cannot be parsed safely.
    """
    if v is None:
        return ""
    if isinstance(v, float) and np.isnan(v):
        return ""

    if isinstance(v, pd.Timestamp):
        try:
            dt = pd.to_datetime(v, errors="coerce")
            if pd.isna(dt):
                return ""
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return ""

    if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
        try:
            num = float(v)
            if 20000 <= num <= 60000:
                dt = pd.to_datetime(num, unit="D", origin="1899-12-30", errors="coerce")
                if not pd.isna(dt):
                    return dt.strftime("%Y-%m-%d")
        except Exception:
            return ""

    s = str(v).strip()
    if s == "" or s.lower() in {"nan", "none", "nat"}:
        return ""

    # Remove a trivial time part if Excel exported a datetime-like string.
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
            dt = pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)), day=int(m.group(3)))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return ""

    # Day-first formats: d/m/yyyy, dd/mm/yyyy, d-m-yyyy, dd-mm-yyyy
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", s)
    if m:
        try:
            dt = pd.Timestamp(year=int(m.group(3)), month=int(m.group(2)), day=int(m.group(1)))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return ""

    # Final fallback: conservative pandas parsing with dayfirst=True.
    try:
        dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
        if pd.isna(dt):
            return ""
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def clean_output_dobs(df: pd.DataFrame) -> pd.DataFrame:
    """Clean standard DOB columns after mapping."""
    df = df.copy()
    for c in ["student_demographics_06", "adult_demographics_03"]:
        if c in df.columns:
            df[c] = df[c].apply(clean_dob_value)
    return df

def multiselect_indices_str(row: pd.Series, src_cols: list[str]) -> str:
    """
    src_cols represent options in order.
    If value == 1 => selected.
    Return "0,1,3" style (0-based indices), else "" if none.
    """
    idxs = []
    for i, c in enumerate(src_cols):
        if c not in row.index:
            continue
        v = row.get(c)
        vv = to_num(v)
        if not np.isnan(vv) and int(round(vv)) == 1:
            idxs.append(str(i))
    return ",".join(idxs)

def load_template_columns(template_path: str, fallback_cols: list[str]) -> list[str]:
    if os.path.exists(template_path):
        try:
            df = pd.read_excel(template_path, nrows=1)
            cols = [str(c) for c in df.columns.tolist()]
            return cols
        except Exception:
            return fallback_cols
    return fallback_cols

def make_empty_df(cols: list[str], nrows: int) -> pd.DataFrame:
    return pd.DataFrame({c: [np.nan]*nrows for c in cols})

def put_col(df: pd.DataFrame, col: str, values):
    """Set df[col] if exists; otherwise ignore silently."""
    if col in df.columns:
        df[col] = values


def assign_creation_time(df: pd.DataFrame, creation_time: str) -> pd.DataFrame:
    """
    Overwrite 建立時間 using the known separate-school data-collection batch date.
    """
    df = df.copy()
    if "建立時間" in df.columns:
        df["建立時間"] = creation_time
    return df

def replace_999_with_nan(df: pd.DataFrame) -> pd.DataFrame:
    """
    Replace 999 markers with NaN BEFORE mapping.
    Handles numeric 999/999.0 and string "999".
    """
    if df.empty:
        return df
    df = df.copy()
    df.replace({999: np.nan, 999.0: np.nan, "999": np.nan, "999.0": np.nan}, inplace=True)
    return df

def _is_blank_cell(x) -> bool:
    """Blank = NaN OR empty string OR whitespace-only string."""
    if pd.isna(x):
        return True
    if isinstance(x, str):
        return x.strip() == ""
    return False

def drop_sparse_scale_rows(df: pd.DataFrame, scale_cols: list[str], threshold: float, label: str) -> pd.DataFrame:
    """
    Drop rows if proportion blank across scale_cols is > threshold.
    Blank definition includes NaN and empty/whitespace strings.
    """
    if df.empty:
        return df

    cols = [c for c in scale_cols if c in df.columns]
    if not cols:
        print(f"⚠️  [{label}] No scale columns found in output; skip sparse-row drop.")
        return df

    # compute blank ratio row-wise
    blank_mat = df[cols].apply(lambda s: s.map(_is_blank_cell))
    blank_ratio = blank_mat.mean(axis=1)

    to_drop = blank_ratio > threshold
    n_drop = int(to_drop.sum())
    if n_drop > 0:
        print(f"🧹  [{label}] Dropping {n_drop} row(s) with >{int(threshold*100)}% blanks in scale columns.")
    return df.loc[~to_drop].copy()


# ============================================================
# Fallback schemas (used only if templates not found)
# ============================================================
FALLBACK_STUDENT_COLS = [
    "Survey", "建立時間", "更新時間",
    "school_from_student", "school_from_parent",
    "student_answer", "previous_term_school_data_01", "previous_term_school_data_02",
    "contact_01", "contact_02",
] + [f"student_demographics_{i:02d}" for i in range(1, 12)] + [
    "student_demographics_07.1", "student_demographics_08", "student_demographics_08.1",
    "student_demographics_09.1", "student_demographics_09.2", "student_demographics_09.3", "student_demographics_09.4",
] + [f"student_PHQ_{i:02d}" for i in range(1, 5)] + \
    [f"student_TBV_{i:02d}" for i in range(1, 8)] + \
    [f"student_TBP_{i:02d}" for i in range(1, 8)] + \
    [f"student_CBV_{i:02d}" for i in range(1, 7)] + \
    [f"student_CBP_{i:02d}" for i in range(1, 7)] + \
    [f"student_FQOL_{i:02d}" for i in range(1, 22)] + \
    [f"student_SEC_{i:02d}" for i in range(1, 23)]

FALLBACK_PARENT_COLS = [
    "Survey", "建立時間", "更新時間",
    "school_from_student", "school_from_parent",
    "parent_answer", "previous_term_school_data_01", "previous_term_school_data_02",
    "contact_01", "contact_02", "contact_03.1", "contact_03.2", "contact_03.3", "contact_03.4",
] + [f"adult_demographics_{i:02d}" for i in range(1, 15)] + [
    "adult_demographics_06.1", "adult_demographics_07.1", "adult_demographics_14.1"
] + [f"parent_PHQ_{i:02d}" for i in range(1, 5)] + \
    [f"parent_TBV_{i:02d}" for i in range(1, 8)] + \
    [f"parent_TBP_{i:02d}" for i in range(1, 8)] + \
    [f"parent_CBV_{i:02d}" for i in range(1, 7)] + \
    [f"parent_CBP_{i:02d}" for i in range(1, 7)] + \
    [f"parent_FQOL_{i:02d}" for i in range(1, 22)] + \
    [f"parent_SEC_{i:02d}" for i in range(1, 23)]


# ============================================================
# Scale column lists (for sparse-row dropping)
# ============================================================
STUDENT_SCALE_COLS = (
    [f"student_PHQ_{i:02d}" for i in range(1, 5)]
    + [f"student_SEC_{i:02d}" for i in range(1, 23)]
    + [f"student_TBV_{i:02d}" for i in range(1, 8)]
    + [f"student_TBP_{i:02d}" for i in range(1, 8)]
    + [f"student_CBV_{i:02d}" for i in range(1, 7)]
    + [f"student_CBP_{i:02d}" for i in range(1, 7)]
    + [f"student_FQOL_{i:02d}" for i in range(1, 22)]
)

PARENT_SCALE_COLS = (
    [f"parent_PHQ_{i:02d}" for i in range(1, 5)]
    + [f"parent_SEC_{i:02d}" for i in range(1, 23)]
    + [f"parent_TBV_{i:02d}" for i in range(1, 8)]
    + [f"parent_TBP_{i:02d}" for i in range(1, 8)]
    + [f"parent_CBV_{i:02d}" for i in range(1, 7)]
    + [f"parent_CBP_{i:02d}" for i in range(1, 7)]
    + [f"parent_FQOL_{i:02d}" for i in range(1, 22)]
)


# ============================================================
# Mapping – Student
# ============================================================
def standardise_student_df(src: pd.DataFrame, school_name: str, survey_label: str, student_cols: list[str]) -> pd.DataFrame:
    src = src.copy()
    src.columns = [norm_col(c) for c in src.columns]

    out = make_empty_df(student_cols, len(src))

    # constants
    put_col(out, "Survey", survey_label)
    put_col(out, "school_from_student", school_name)
    put_col(out, "school_from_parent", school_name)

    # contacts
    put_col(out, "contact_01", src.get("18(1)", "").apply(clean_phone)) # type: ignore
    put_col(out, "contact_02", src.get("18(2)", "").apply(clean_phone)) # type: ignore

    # demographics
    put_col(out, "student_demographics_01", src.get("1(1)", np.nan))
    put_col(out, "student_demographics_02", src.get("1(2)", np.nan))

    if "2" in src.columns:
        put_col(out, "student_demographics_03", minus_one_series(src["2"]))
    put_col(out, "student_demographics_04", src.get("3", np.nan))
    put_col(out, "student_demographics_05", src.get("4", np.nan))

    # DOB y/m/d: 5(1),5(2),5(3) -> demographics_06
    if all(c in src.columns for c in ["5(1)", "5(2)", "5(3)"]):
        dob = [ymd_to_date_str(y, m, d) for y, m, d in zip(src["5(1)"], src["5(2)"], src["5(3)"])]
        put_col(out, "student_demographics_06", dob)

    if "6(1)" in src.columns:
        put_col(out, "student_demographics_07", minus_one_series(src["6(1)"]))
    put_col(out, "student_demographics_07.1", src.get("6(2)", np.nan))

    # living together multi-select: 7(1)~7(7) -> demographics_08 (0-based indices)
    living_cols = [f"7({i})" for i in range(1, 8)]
    if any(c in src.columns for c in living_cols):
        sel = [multiselect_indices_str(r, living_cols) for _, r in src.iterrows()]
        put_col(out, "student_demographics_08", sel)

    # 8(1)~8(4)
    put_col(out, "student_demographics_09.1", src.get("8(1)", np.nan))
    put_col(out, "student_demographics_09.2", src.get("8(2)", np.nan))
    put_col(out, "student_demographics_09.3", src.get("8(3)", np.nan))
    put_col(out, "student_demographics_09.4", src.get("8(4)", np.nan))

    put_col(out, "student_demographics_10", src.get("9", np.nan))
    if "10" in src.columns:
        put_col(out, "student_demographics_11", minus_one_series(src["10"]))

    # SEC 11(1)~11(22) -> student_SEC_01~22 (-1)
    for i in range(1, 23):
        sc = f"11({i})"
        dc = f"student_SEC_{i:02d}"
        if sc in src.columns:
            put_col(out, dc, minus_one_series(src[sc]))

    # PHQ 12(1)~12(4) -> student_PHQ_01~04 (-1)
    for i in range(1, 5):
        sc = f"12({i})"
        dc = f"student_PHQ_{i:02d}"
        if sc in src.columns:
            put_col(out, dc, minus_one_series(src[sc]))

    # TBV 13(1)~13(7) -> student_TBV_01~07 (-1)
    for i in range(1, 8):
        sc = f"13({i})"
        dc = f"student_TBV_{i:02d}"
        if sc in src.columns:
            put_col(out, dc, minus_one_series(src[sc]))

    # TBP 14(1)~14(7) -> student_TBP_01~07 (-1)
    for i in range(1, 8):
        sc = f"14({i})"
        dc = f"student_TBP_{i:02d}"
        if sc in src.columns:
            put_col(out, dc, minus_one_series(src[sc]))

    # CBV 15(1)~15(6) -> student_CBV_01~06 (-1)
    for i in range(1, 7):
        sc = f"15({i})"
        dc = f"student_CBV_{i:02d}"
        if sc in src.columns:
            put_col(out, dc, minus_one_series(src[sc]))

    # CBP 16(1)~16(6) -> student_CBP_01~06 (-1)
    for i in range(1, 7):
        sc = f"16({i})"
        dc = f"student_CBP_{i:02d}"
        if sc in src.columns:
            put_col(out, dc, minus_one_series(src[sc]))

    # FQOL 17(1)~17(21) -> student_FQOL_01~21 (direct)
    for i in range(1, 22):
        sc = f"17({i})"
        dc = f"student_FQOL_{i:02d}"
        if sc in src.columns:
            put_col(out, dc, src[sc])

    return out


def standardise_direct_student_df(src: pd.DataFrame, school_name: str, survey_label: str, student_cols: list[str]) -> pd.DataFrame:
    """
    Standardise 樂善堂劉德學校 student file.
    Raw columns are already named using the target-style student_* schema.
    All cases are treated as T0. The 11 appended items are ignored for now.
    Bullying items stay 0-4; FQOL stays 1-5; SEC stays 0-3.
    """
    src = src.copy()
    src.columns = [norm_col(c) for c in src.columns]

    out = make_empty_df(student_cols, len(src))

    put_col(out, "Survey", survey_label)
    put_col(out, "school_from_student", school_name)
    put_col(out, "school_from_parent", school_name)

    if "sign_date" in src.columns:
        put_col(out, "建立時間", src["sign_date"])
        put_col(out, "更新時間", src["sign_date"])

    if "contact_from_student" in src.columns:
        put_col(out, "contact_01", src["contact_from_student"].apply(clean_phone))

    student_demo_cols = [
        "student_demographics_01", "student_demographics_02", "student_demographics_03",
        "student_demographics_04", "student_demographics_05", "student_demographics_06",
        "student_demographics_07", "student_demographics_07.1",
        "student_demographics_08", "student_demographics_08.1",
        "student_demographics_09.1", "student_demographics_09.2",
        "student_demographics_09.3", "student_demographics_09.4",
        "student_demographics_10", "student_demographics_11",
    ]

    for c in student_demo_cols:
        if c in src.columns:
            put_col(out, c, src[c])

    direct_scale_cols = (
        [f"student_PHQ_{i:02d}" for i in range(1, 5)]
        + [f"student_SEC_{i:02d}" for i in range(1, 23)]
        + [f"student_TBV_{i:02d}" for i in range(1, 8)]
        + [f"student_TBP_{i:02d}" for i in range(1, 8)]
        + [f"student_CBV_{i:02d}" for i in range(1, 7)]
        + [f"student_CBP_{i:02d}" for i in range(1, 7)]
        + [f"student_FQOL_{i:02d}" for i in range(1, 22)]
    )

    for c in direct_scale_cols:
        if c in src.columns:
            put_col(out, c, src[c])

    return out


# ============================================================
# Mapping – Parent
# ============================================================
def standardise_parent_df(src: pd.DataFrame, school_name: str, survey_label: str, parent_cols: list[str]) -> pd.DataFrame:
    src = src.copy()
    src.columns = [norm_col(c) for c in src.columns]

    out = make_empty_df(parent_cols, len(src))

    # constants
    put_col(out, "Survey", survey_label)
    put_col(out, "school_from_student", school_name)
    put_col(out, "school_from_parent", school_name)

    # contacts
    put_col(out, "contact_01", src.get("Student phone no.", "").apply(clean_phone)) # type: ignore
    put_col(out, "contact_02", src.get("Parent phone no.", "").apply(clean_phone)) # type: ignore
    put_col(out, "contact_03.1", src.get("Parent email", "").apply(clean_email)) # type: ignore

    # demographics
    put_col(out, "adult_demographics_01", src.get("1(1)", np.nan))
    put_col(out, "adult_demographics_02", src.get("1(2)", np.nan))

    # DOB y/m/d: 2(1),2(2),2(3) -> adult_demographics_03
    if all(c in src.columns for c in ["2(1)", "2(2)", "2(3)"]):
        dob = [ymd_to_date_str(y, m, d) for y, m, d in zip(src["2(1)"], src["2(2)"], src["2(3)"])]
        put_col(out, "adult_demographics_03", dob)

    # 3 -> 04 (-1)
    if "3" in src.columns:
        put_col(out, "adult_demographics_04", minus_one_series(src["3"]))

    # 4 -> 05 (D)
    put_col(out, "adult_demographics_05", src.get("4", np.nan))

    # 5(1) -> 06 (-1), 5(2) -> 06.1 (D)
    if "5(1)" in src.columns:
        put_col(out, "adult_demographics_06", minus_one_series(src["5(1)"]))
    put_col(out, "adult_demographics_06.1", src.get("5(2)", np.nan))

    # 6(1) -> 07 (-1), 6(2) -> 07.1 (D)
    if "6(1)" in src.columns:
        put_col(out, "adult_demographics_07", minus_one_series(src["6(1)"]))
    put_col(out, "adult_demographics_07.1", src.get("6(2)", np.nan))

    # 7..12 -> 08..13 (-1)
    for src_c, dest_i in zip(["7", "8", "9", "10", "11", "12"], range(8, 14)):
        if src_c in src.columns:
            put_col(out, f"adult_demographics_{dest_i:02d}", minus_one_series(src[src_c]))

    # 13(1)~13(4) multi-select -> adult_demographics_14 (0-based indices)
    multi_cols = [f"13({i})" for i in range(1, 5)]
    if any(c in src.columns for c in multi_cols):
        sel = [multiselect_indices_str(r, multi_cols) for _, r in src.iterrows()]
        put_col(out, "adult_demographics_14", sel)

    # 13(5) -> 14.1 (D)
    put_col(out, "adult_demographics_14.1", src.get("13(5)", np.nan))

    # PHQ 14(1)~14(4) -> parent_PHQ_01~04 (-1)
    for i in range(1, 5):
        sc = f"14({i})"
        dc = f"parent_PHQ_{i:02d}"
        if sc in src.columns:
            put_col(out, dc, minus_one_series(src[sc]))

    # SEC 15(1)~15(22) -> parent_SEC_01~22 (-1)
    for i in range(1, 23):
        sc = f"15({i})"
        dc = f"parent_SEC_{i:02d}"
        if sc in src.columns:
            put_col(out, dc, minus_one_series(src[sc]))

    # TBV 16(1)~16(7) -> parent_TBV_01~07 (-1)
    for i in range(1, 8):
        sc = f"16({i})"
        dc = f"parent_TBV_{i:02d}"
        if sc in src.columns:
            put_col(out, dc, minus_one_series(src[sc]))

    # TBP 17(1)~17(7) -> parent_TBP_01~07 (-1)
    for i in range(1, 8):
        sc = f"17({i})"
        dc = f"parent_TBP_{i:02d}"
        if sc in src.columns:
            put_col(out, dc, minus_one_series(src[sc]))

    # CBV 18(1)~18(6) -> parent_CBV_01~06 (-1)
    for i in range(1, 7):
        sc = f"18({i})"
        dc = f"parent_CBV_{i:02d}"
        if sc in src.columns:
            put_col(out, dc, minus_one_series(src[sc]))

    # CBP 19(1)~19(6) -> parent_CBP_01~06 (-1)
    for i in range(1, 7):
        sc = f"19({i})"
        dc = f"parent_CBP_{i:02d}"
        if sc in src.columns:
            put_col(out, dc, minus_one_series(src[sc]))

    # FQOL 20(1)~20(21) -> parent_FQOL_01~21 (direct)
    for i in range(1, 22):
        sc = f"20({i})"
        dc = f"parent_FQOL_{i:02d}"
        if sc in src.columns:
            put_col(out, dc, src[sc])

    return out


def standardise_direct_parent_df(src: pd.DataFrame, school_name: str, survey_label: str, parent_cols: list[str]) -> pd.DataFrame:
    """
    Standardise 樂善堂劉德學校 parent file.
    Raw columns are already named using parent_demographics_* and parent_* scale columns.
    All cases are treated as T0. Bullying items stay 0-4; FQOL stays 1-5; SEC stays 0-3.
    """
    src = src.copy()
    src.columns = [norm_col(c) for c in src.columns]

    out = make_empty_df(parent_cols, len(src))

    put_col(out, "Survey", survey_label)
    put_col(out, "school_from_student", school_name)
    put_col(out, "school_from_parent", school_name)

    if "sign_date_1" in src.columns:
        put_col(out, "建立時間", src["sign_date_1"])
        put_col(out, "更新時間", src["sign_date_1"])

    if "contact_from_parent_01" in src.columns:
        put_col(out, "contact_01", src["contact_from_parent_01"].apply(clean_phone))
    if "contact_from_parent_02" in src.columns:
        put_col(out, "contact_02", src["contact_from_parent_02"].apply(clean_phone))
    if "contact_from_parent_03" in src.columns:
        put_col(out, "contact_03.1", src["contact_from_parent_03"].apply(clean_email))

    parent_demo_to_adult_demo = {
        "parent_demographics_01": "adult_demographics_01",
        "parent_demographics_02": "adult_demographics_02",
        "parent_demographics_03": "adult_demographics_03",
        "parent_demographics_04": "adult_demographics_04",
        "parent_demographics_04.1": "adult_demographics_04.1",
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
    }

    for src_c, dst_c in parent_demo_to_adult_demo.items():
        if src_c in src.columns:
            put_col(out, dst_c, src[src_c])

    direct_scale_cols = (
        [f"parent_PHQ_{i:02d}" for i in range(1, 5)]
        + [f"parent_SEC_{i:02d}" for i in range(1, 23)]
        + [f"parent_TBV_{i:02d}" for i in range(1, 8)]
        + [f"parent_TBP_{i:02d}" for i in range(1, 8)]
        + [f"parent_CBV_{i:02d}" for i in range(1, 7)]
        + [f"parent_CBP_{i:02d}" for i in range(1, 7)]
        + [f"parent_FQOL_{i:02d}" for i in range(1, 22)]
    )

    for c in direct_scale_cols:
        if c in src.columns:
            put_col(out, c, src[c])

    return out


# ============================================================
# Main
# ============================================================
def main():
    # Load templates (for exact schema/order)
    student_cols = load_template_columns(TEMPLATE_STUDENT, FALLBACK_STUDENT_COLS)
    parent_cols = load_template_columns(TEMPLATE_PARENT, FALLBACK_PARENT_COLS)

    print("=== Step 1.3.2: Standardise separate-school T0 sheets ===")
    print(f"Base dir: {base_dir}")
    print(f"Raw dir : {raw_dir}")
    print(f"Out dir : {out_dir}")
    print("---------------------------------------------------------")

    for info in FILES:
        school = info["school"]

        print(f"\n[School] {school}")

        # ---- read raw sheets ----
        if info.get("direct_standard_columns"):
            stu_path = info["student_path"]
            par_path = info["parent_path"]
            print(f"  Reading student: {stu_path}")
            print(f"  Reading parent : {par_path}")
            stu_src = read_first_sheet(stu_path)
            par_src = read_first_sheet(par_path)
        else:
            path = info["path"]
            print(f"  Reading: {path}")
            stu_src = read_sheet(path, STUDENT_SHEET)
            par_src = read_sheet(path, PARENT_SHEET)

        print(f"  student_sheet rows (raw): {len(stu_src)}")
        print(f"  parent_sheet rows  (raw): {len(par_src)}")

        # ---- replace 999 -> NaN BEFORE mapping ----
        stu_src = replace_999_with_nan(stu_src)
        par_src = replace_999_with_nan(par_src)

        # ---- standardise mapping ----
        if info.get("direct_standard_columns"):
            stu_std = standardise_direct_student_df(
                src=stu_src,
                school_name=school,
                survey_label=info["survey_student"],
                student_cols=student_cols,
            )
            par_std = standardise_direct_parent_df(
                src=par_src,
                school_name=school,
                survey_label=info["survey_parent"],
                parent_cols=parent_cols,
            )
        else:
            stu_std = standardise_student_df(
                src=stu_src,
                school_name=school,
                survey_label=info["survey_student"],
                student_cols=student_cols,
            )
            par_std = standardise_parent_df(
                src=par_src,
                school_name=school,
                survey_label=info["survey_parent"],
                parent_cols=parent_cols,
            )

        # ---- overwrite 建立時間 using known separate-school batch date ----
        assigned_creation_time = info.get("assigned_creation_time", "")
        if assigned_creation_time:
            stu_std = assign_creation_time(stu_std, assigned_creation_time)
            par_std = assign_creation_time(par_std, assigned_creation_time)

        # ---- clean standard DOB columns after mapping ----
        stu_std = clean_output_dobs(stu_std)
        par_std = clean_output_dobs(par_std)

        # ---- drop sparse rows using SCALE columns ONLY ----
        before_stu = len(stu_std)
        before_par = len(par_std)

        stu_std = drop_sparse_scale_rows(
            df=stu_std,
            scale_cols=STUDENT_SCALE_COLS,
            threshold=SCALE_BLANK_THRESHOLD,
            label=f"{school} student",
        )
        par_std = drop_sparse_scale_rows(
            df=par_std,
            scale_cols=PARENT_SCALE_COLS,
            threshold=SCALE_BLANK_THRESHOLD,
            label=f"{school} parent",
        )

        print(f"  student rows after drop: {len(stu_std)} (dropped {before_stu - len(stu_std)})")
        print(f"  parent  rows after drop: {len(par_std)} (dropped {before_par - len(par_std)})")

        # Save
        stu_std.to_excel(info["out_student"], index=False)
        par_std.to_excel(info["out_parent"], index=False)

        print(f"  ✅ Saved student -> {info['out_student']} (rows={len(stu_std)})")
        print(f"  ✅ Saved parent  -> {info['out_parent']} (rows={len(par_std)})")

    print("\n✅ Step 1.3.2 completed. Separate-school T0 outputs written to 1.3_standardised_paperform_data.")


if __name__ == "__main__":
    main()