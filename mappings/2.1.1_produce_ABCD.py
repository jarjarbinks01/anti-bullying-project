# -*- coding: utf-8 -*-
"""
Step 2.1 – Build A/B/C/D datasets from messy raw panel files.

Input:
    - Latest numbered student_panel_responses_*.xlsx old-system export
    - Latest numbered parent_panel_responses_*.xlsx old-system export
    - The current Study 2 Qualtrics survey CSV exports (one per role/timepoint)

Qualtrics filenames are identified by Student/Parent and T0/T1 only; their
date suffix is ignored. Replace old exports before running. Duplicate files
for the same role/timepoint cause an error. An absent group contributes zero rows.

Output (all with STANDARDISED columns):
    base_dir/2.1_T0T1-student-parent(A,B,C,D)/
        A_T0-student_OG.xlsx
        B_T0-parent_OG.xlsx
        C_T1-student_OG.xlsx
        D_T1-parent_OG.xlsx

Key post-processing rules:
    - Only Qualtrics rows with Finished=True and Progress=100 are included.
    - Qualtrics choice labels are converted to the pipeline's numeric coding.
    - Qualtrics ResponseId is preserved inside the answer dictionary and is
      reconciled exactly once against the corresponding A/B/C/D output.
    - System FQOL raw item scores are 0–4 and are shifted to 1–5.
    - Phone-like contact fields are cleaned safely to avoid Excel numeric artefacts
      such as 12345678.0 becoming 123456780.
    - DOB fields are cleaned into yyyy-mm-dd where possible.
    - For selected student T0/T1 special versions, school-name_02 stores
      student_demographics_01.
    - For selected parent T0/T1 special versions, school-name_01 / school-name-parent_01
      may store school_from_parent, and school-name_02 / school-name-parent_02 may store
      adult_demographics_01.
"""

import ast
import csv
import glob
import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np  # not strictly needed, but kept in case needed later


# ============================================================
# Configuration
# ============================================================
base_dir = os.path.expanduser("~/Desktop/Python/Antibully_study2_v2")
if not os.path.isdir(base_dir):
    base_dir = os.path.dirname(os.path.abspath(__file__))

input_dir = os.path.join(base_dir, "1.1_raw_file")
output_dir = os.path.join(base_dir, "2.1.1_T0T1-student-parent(A,B,C,D)_OG")
os.makedirs(output_dir, exist_ok=True)

def latest_numbered_system_export(prefix: str) -> str:
    """Return the latest old-system export, based on its numeric filename suffix."""
    candidates = glob.glob(os.path.join(input_dir, f"{prefix}_*.xlsx"))
    numbered = []
    for path in candidates:
        match = re.search(r"_(\d+)\.xlsx$", os.path.basename(path), flags=re.IGNORECASE)
        if match:
            numbered.append((int(match.group(1)), path))
    if not numbered:
        raise FileNotFoundError(f"No old-system export found for {prefix!r} in {input_dir}")
    return max(numbered, key=lambda item: item[0])[1]


input_path_student = latest_numbered_system_export("student_panel_responses")
input_path_parent = latest_numbered_system_export("parent_panel_responses")

output_path_A = os.path.join(output_dir, "A_T0-student_OG.xlsx")
output_path_B = os.path.join(output_dir, "B_T0-parent_OG.xlsx")
output_path_C = os.path.join(output_dir, "C_T1-student_OG.xlsx")
output_path_D = os.path.join(output_dir, "D_T1-parent_OG.xlsx")


# ============================================================
# Special survey patterns where real school is inside Answers['school-name_01']
# ============================================================

STUDENT_SCHOOL_FROM_ANS_SURVEYS = [
    "panel_student_t0_questionnaire_all_schools",
    "panel_student_t0_questionnaire_little_red_note",
    "panel_student_t0_questionnaire_facebook",
    "panel_student_t1_questionnaire_email",
    "panel_student_t1_questionnaire_whatsapp",
]

PARENT_SCHOOL_FROM_ANS_SURVEYS = [
    "panel_parents_t0_questionnaire_all_schools",
    "panel_parents_t0_questionnaire_facebook",
]

PARENT_SCHOOL_FROM_PARENT_ANS_SURVEYS = [
    "panel_parents_t1_questionnaire_email",
    "panel_parents_t1_questionnaire_whatsapp",
]

# Student survey versions where school-name_02 stores student_demographics_01.
STUDENT_DEMO01_FROM_SCHOOL_NAME_02_SURVEYS = [
    "panel_student_t0_questionnaire_all_schools",
    "panel_student_t0_questionnaire_facebook",
    "panel_student_t1_questionnaire_email",
    "panel_student_t1_questionnaire_whatsapp",
]

# Parent survey versions where school-name-parent_01 should be used as a fallback
# school name if school-name_01 is missing or blank.
PARENT_SCHOOL_PARENT01_FALLBACK_SURVEYS = [
    "panel_parents_t0_questionnaire_facebook",
    "panel_parents_t0_questionnaire_all_schools",
]

# Parent survey versions where school-name_02 or school-name-parent_02 stores
# adult_demographics_01.
PARENT_DEMO01_FROM_SCHOOL_NAME_02_SURVEYS = [
    "panel_parents_t0_questionnaire_all_schools",
    "panel_parents_t0_questionnaire_facebook",
    "panel_parents_t1_questionnaire_whatsapp",
    "panel_parents_t1_questionnaire_email",
]

# ============================================================
# Utilities
# ============================================================

def parse_answer_field(answer_str):
    """Parse the 'Answers/答案' JSON-like string to a Python dict, safely."""
    if isinstance(answer_str, dict):
        return answer_str
    if not isinstance(answer_str, str):
        return {}
    try:
        return ast.literal_eval(answer_str)
    except Exception:
        return {}


def convert_value(v):
    """Convert digit-only strings to int; join lists by comma; otherwise return as-is."""
    if isinstance(v, list):
        return ",".join(map(str, v))
    if isinstance(v, str) and v.isdigit():
        try:
            return int(v)
        except Exception:
            return v
    return v


# ============================================================
# Phone and DOB cleaning helpers
# ============================================================

def clean_phone(v):
    """
    Clean phone-like contact values safely.

    Key fix:
      Excel or JSON parsing may represent 8-digit phone numbers as 12345678.0.
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
                digits = re.sub(r"\D", "", str(v))
        except Exception:
            digits = re.sub(r"\D", "", str(v))
    else:
        s = str(v).strip()
        if not s or s.lower() in {"nan", "none", "nat"}:
            return ""

        if re.match(r"^\d+\.0$", s):
            digits = str(int(float(s)))
        else:
            digits = re.sub(r"\D", "", s)

    if not digits:
        return str(v).strip()

    # Remove HK country code if present, e.g. +852 1234 5678 -> 12345678.
    if len(digits) == 11 and digits.startswith("852"):
        digits = digits[3:]

    return digits


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

    try:
        dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
        if pd.isna(dt):
            return ""
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def clean_output_contacts_and_dobs(df: pd.DataFrame, role_prefix: str) -> pd.DataFrame:
    """Clean standard contact and DOB columns after mapping."""
    df = df.copy()
    for c in ["contact_01", "contact_02"]:
        if c in df.columns:
            df[c] = df[c].apply(clean_phone)

    dob_col = "student_demographics_06" if role_prefix == "student" else "adult_demographics_03"
    if dob_col in df.columns:
        df[dob_col] = df[dob_col].apply(clean_dob_value)

    return df


def normalize_system_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise bilingual raw-system headers into the canonical names expected by
    this step, while keeping the Step 2.1.1 output schema unchanged.

    The online system may export its administrative columns in either English
    or Traditional Chinese. If both aliases appear, retain the canonical column
    and fill only its missing/blank cells from the other alias.

    Canonical internal/output names:
      - Survey
      - School
      - Answers
      - 建立時間
      - 更新時間
    """
    df = df.copy()
    aliases = {
        "Survey": ["Survey", "問卷"],
        "School": ["School", "學校"],
        "Answers": ["Answers", "答案"],
        "建立時間": ["建立時間", "Created on"],
        "更新時間": ["更新時間", "Updated on"],
    }

    for canonical, candidates in aliases.items():
        present = [col for col in candidates if col in df.columns]
        if not present:
            # Leave the missing column to the existing row.get(..., "") logic.
            continue

        if canonical not in df.columns:
            first = present.pop(0)
            df = df.rename(columns={first: canonical})

        for alias in present:
            if alias == canonical or alias not in df.columns:
                continue
            missing = df[canonical].isna() | df[canonical].astype(str).str.strip().eq("")
            df.loc[missing, canonical] = df.loc[missing, alias]
            df = df.drop(columns=[alias])

    return df


def detect_role_and_wave(survey_value):
    """
    Decide whether a row is student or parent, and whether it is T0 or T1,
    based on the 'Survey' string.
    """
    if pd.isna(survey_value):
        return None, None
    s = str(survey_value)
    s_lower = s.lower()

    role = None
    wave = None

    if "panel_student_" in s_lower:
        role = "student"
    elif "panel_parents_" in s_lower:
        role = "parent"
    else:
        # Unknown / irrelevant survey
        return None, None

    # Wave detection: Wave 0 vs Wave 1 vs t0/t1 hints
    if "wave 0" in s_lower or "_t0" in s_lower:
        wave = "T0"
    elif "wave 1" in s_lower or "_t1" in s_lower:
        wave = "T1"
    else:
        # Fallback: if explicitly t0_questionnaire / t1_questionnaire
        if "t0_questionnaire" in s_lower:
            wave = "T0"
        elif "t1_questionnaire" in s_lower:
            wave = "T1"

    return role, wave


# ============================================================
# Student mapping helpers
# ============================================================

# Demographics mapping for student
STU_DEMO_NORMAL_MAP = {
    "01":   "student_demographics_01",
    "02":   "student_demographics_02",
    "03":   "student_demographics_03",
    "04":   "student_demographics_04",
    "05":   "student_demographics_05",
    "06":   "student_demographics_06",
    "07":   "student_demographics_07",
    "07.1": "student_demographics_07.1",
    "08":   "student_demographics_08",
    "08.1": "student_demographics_08.1",
    "09.1": "student_demographics_09.1",
    "09.2": "student_demographics_09.2",
    "09.3": "student_demographics_09.3",
    "09.4": "student_demographics_09.4",
    "10":   "student_demographics_10",
    "11":   "student_demographics_11",
}

STU_DEMO_ALL_SCHOOLS_MAP = {
    "01":   "student_demographics_03",
    "02":   "student_demographics_04",
    "03":   "student_demographics_05",
    "04":   "student_demographics_06",
    "05":   "student_demographics_07",
    "05.1": "student_demographics_07.1",
    "06":   "student_demographics_08",
    "06.1": "student_demographics_08.1",
    "07.1": "student_demographics_09.1",
    "07.2": "student_demographics_09.2",
    "07.3": "student_demographics_09.3",
    "07.4": "student_demographics_09.4",
    "08":   "student_demographics_10",
    "09":   "student_demographics_11",
}


def map_student_scales(ans):
    """
    From a parsed answer dict (student row), extract:
      - PHQ, SEC, TBP, TBV, CBP, CBV, FQOL
    into standard student_* columns.
    """
    out = {}

    for k, v in ans.items():
        k_str = str(k)

        # PHQ-4
        if k_str.startswith("mh_2023_05_01_"):
            idx = k_str[-2:]
            out[f"student_PHQ_{idx}"] = convert_value(v)

        # SEC
        elif k_str.startswith("student_sec_"):
            idx = k_str[-2:]
            out[f"student_SEC_{idx}"] = convert_value(v)

        # Traditional bullying (perpetration / victimization)
        elif k_str.startswith("panel_student_tbp-olweus_"):
            idx = k_str.split("_")[-1]  # '01'..'07'
            out[f"student_TBP_{idx.zfill(2)}"] = convert_value(v)

        elif k_str.startswith("panel_student_tbv-olweus_"):
            idx = k_str.split("_")[-1]
            out[f"student_TBV_{idx.zfill(2)}"] = convert_value(v)

        # Cyberbullying – bully/victim items are 01.1..01.6 etc.
        elif k_str.startswith("panel_student_cyberbully_bully_"):
            last = k_str.split("_")[-1]  # e.g. '01.1'
            try:
                idx = last.split(".")[1]  # '1'..'6'
            except Exception:
                continue
            out[f"student_CBP_{idx.zfill(2)}"] = convert_value(v)

        elif k_str.startswith("panel_student_cyberbully_victim_"):
            last = k_str.split("_")[-1]
            try:
                idx = last.split(".")[1]
            except Exception:
                continue
            out[f"student_CBV_{idx.zfill(2)}"] = convert_value(v)

        # Family Quality of Life (21 items)
        elif k_str.startswith("panel_student_family_quality_of_life_"):
            idx = k_str[-2:]  # '01'..'21'
            out[f"student_FQOL_{idx}"] = convert_value(v)

    return out


def map_student_demographics(ans):
    """
    From answer dict (student), map both
    - 'panel_student_demographics_..._NN'
    - 'panel_student_demographics_..._all_schools_NN'
    into standard student_demographics_* columns.
    """
    out = {}

    # Detect if this row uses the "all_schools" variant
    has_all_schools = any(
        "panel_student_demographics_" in str(k) and "_all_schools_" in str(k)
        for k in ans.keys()
    )

    for k, v in ans.items():
        k_str = str(k)

        # all_schools variant
        if has_all_schools and "panel_student_demographics_" in k_str and "_all_schools_" in k_str:
            suffix = k_str.split("_all_schools_")[-1]  # '01', '05.1', etc.
            target = STU_DEMO_ALL_SCHOOLS_MAP.get(suffix)
            if target:
                out[target] = convert_value(v)

        # normal variant
        elif "panel_student_demographics_" in k_str and "_all_schools_" not in k_str:
            # suffix is the last token after last underscore
            suffix = k_str.split("_")[-1]  # '01', '02', '07.1', etc.
            target = STU_DEMO_NORMAL_MAP.get(suffix)
            if target:
                out[target] = convert_value(v)

    return out


def map_student_contacts(ans):
    """
    Standardise various student contact key variants into:
        contact_01, contact_02
    """
    out = {"contact_01": "", "contact_02": ""}

    contact1_candidates = [
        "panel-parent-contact-info-for-student-survey_01.1",
        "panel-parent-contact-info-for-student-survey_01",
        "panel-parent-contact-info-for-student-survey_sid_01",
        "panel-parent-contact-info-for-student-survey_skh_01",
    ]
    contact2_candidates = [
        "panel-parent-contact-info-for-student-survey_01.2",
        "panel-parent-contact-info-for-student-survey_sid_02",
        "panel-parent-contact-info-for-student-survey_skh_02",
    ]

    for k in contact1_candidates:
        if k in ans and ans[k] not in ["", None]:
            out["contact_01"] = clean_phone(ans[k]) # type: ignore
            break

    for k in contact2_candidates:
        if k in ans and ans[k] not in ["", None]:
            out["contact_02"] = clean_phone(ans[k]) # type: ignore
            break

    return out


def map_student_school_fields(ans):
    """
    Copy school-name and previous term school data if present.
    """
    return {
        "school-name_01": ans.get("school-name_01", ""),
        "school-name_02": ans.get("school-name_02", ""),
        "previous_term_school_data_01": ans.get("previous_term_school_data_01", ""),
        "previous_term_school_data_02": ans.get("previous_term_school_data_02", ""),
    }


# ============================================================
# Parent mapping helpers
# ============================================================

PAR_DEMO_NORMAL_MAP = {
    "01":   "adult_demographics_01",
    "02":   "adult_demographics_02",
    "03":   "adult_demographics_03",
    "04":   "adult_demographics_04",
    "04.1": "adult_demographics_04.1",
    "05":   "adult_demographics_05",
    "06":   "adult_demographics_06",
    "06.1": "adult_demographics_06.1",
    "07":   "adult_demographics_07",
    "07.1": "adult_demographics_07.1",
    "08":   "adult_demographics_08",
    "09":   "adult_demographics_09",
    "10":   "adult_demographics_10",
    "11":   "adult_demographics_11",
    "12":   "adult_demographics_12",
    "13":   "adult_demographics_13",
    "14":   "adult_demographics_14",
    "14.1": "adult_demographics_14.1",
}

PAR_DEMO_ALL_SCHOOLS_MAP = {
    "01":   "adult_demographics_03",
    "02":   "adult_demographics_04",
    "03":   "adult_demographics_05",
    "04":   "adult_demographics_06",
    "04.1": "adult_demographics_06.1",
    "05":   "adult_demographics_07",
    "05.1": "adult_demographics_07.1",
    "06":   "adult_demographics_08",
    "07":   "adult_demographics_09",
    "08":   "adult_demographics_10",
    "09":   "adult_demographics_11",
    "10":   "adult_demographics_12",
    "11":   "adult_demographics_13",
    "12":   "adult_demographics_14",
    "12.1": "adult_demographics_14.1",
}


def map_parent_scales(ans):
    """
    Extract parent PHQ, SEC, bullying, and FQOL scales.
    """
    out = {}

    for k, v in ans.items():
        k_str = str(k)

        # PHQ-4
        if k_str.startswith("mh_2023_05_01_"):
            idx = k_str[-2:]
            out[f"parent_PHQ_{idx}"] = convert_value(v)

        # SEC (parent)
        elif k_str.startswith("panel_lv3-parent_sec_"):
            idx = k_str.split("_")[-1]
            out[f"parent_SEC_{idx.zfill(2)}"] = convert_value(v)

        # Child bullying scales (as perceived by parent)
        elif k_str.startswith("panel_t0_parent_child_cbp_"):
            idx = k_str.split("_")[-1]
            out[f"parent_CBP_{idx.zfill(2)}"] = convert_value(v)

        elif k_str.startswith("panel_t0_parent_child_cbv_"):
            idx = k_str.split("_")[-1]
            out[f"parent_CBV_{idx.zfill(2)}"] = convert_value(v)

        elif k_str.startswith("panel_t0_parent_child_tbp_"):
            idx = k_str.split("_")[-1]
            out[f"parent_TBP_{idx.zfill(2)}"] = convert_value(v)

        elif k_str.startswith("panel_t0_parent_child_tbv_"):
            idx = k_str.split("_")[-1]
            out[f"parent_TBV_{idx.zfill(2)}"] = convert_value(v)

        # FQOL – same underlying key as student FQOL but for parent
        elif k_str.startswith("panel_student_family_quality_of_life_"):
            idx = k_str[-2:]
            out[f"parent_FQOL_{idx}"] = convert_value(v)

    return out


def map_parent_demographics(ans):
    """
    Map parent demographics (adult_demographics_*).
    """
    out = {}

    has_all_schools = any(
        "panel_adult_demographics_" in str(k) and "_all_schools_" in str(k)
        for k in ans.keys()
    )

    for k, v in ans.items():
        k_str = str(k)

        if has_all_schools and "panel_adult_demographics_" in k_str and "_all_schools_" in k_str:
            suffix = k_str.split("_all_schools_")[-1]
            target = PAR_DEMO_ALL_SCHOOLS_MAP.get(suffix)
            if target:
                out[target] = convert_value(v)

        elif "panel_adult_demographics_" in k_str and "_all_schools_" not in k_str:
            suffix = k_str.split("_")[-1]
            target = PAR_DEMO_NORMAL_MAP.get(suffix)
            if target:
                out[target] = convert_value(v)

    return out


def map_parent_contacts(ans):
    """
    Standardise parent contact info into:
        contact_01, contact_02, contact_03.1-03.4
    """
    out = {
        "contact_01": "",
        "contact_02": "",
        "contact_03.1": "",
        "contact_03.2": "",
        "contact_03.3": "",
        "contact_03.4": "",
    }

    # contact_01 & contact_02
    c01_keys = [
        "panel-contact-info-for-parent-survey_01.1",
        "panel-contact-info-for-parent-survey_studentid_01",
    ]
    c02_keys = [
        "panel-contact-info-for-parent-survey_01.2",
        "panel-contact-info-for-parent-survey_studentid_02",
    ]

    for k in c01_keys:
        if k in ans and ans[k] not in ["", None]:
            out["contact_01"] = clean_phone(ans[k]) # type: ignore
            break

    for k in c02_keys:
        if k in ans and ans[k] not in ["", None]:
            out["contact_02"] = clean_phone(ans[k]) # type: ignore
            break

    # contact_03.1-03.4
    c03x_map = {
        "contact_03.1": [
            "panel-contact-info-for-parent-survey_02.1",
            "panel-contact-info-for-parent-survey_studentid_03.1",
            "panel-contact-info-for-parent-survey_skhycmcj_03.1",
        ],
        "contact_03.2": [
            "panel-contact-info-for-parent-survey_02.2",
            "panel-contact-info-for-parent-survey_studentid_03.2",
            "panel-contact-info-for-parent-survey_skhycmcj_03.2",
        ],
        "contact_03.3": [
            "panel-contact-info-for-parent-survey_02.3",
            "panel-contact-info-for-parent-survey_studentid_03.3",
            "panel-contact-info-for-parent-survey_skhycmcj_03.3",
        ],
        "contact_03.4": [
            "panel-contact-info-for-parent-survey_02.4",
            "panel-contact-info-for-parent-survey_studentid_03.4",
            "panel-contact-info-for-parent-survey_skhycmcj_03.4",
        ],
    }

    for target, keys in c03x_map.items():
        for k in keys:
            if k in ans and ans[k] not in ["", None]:
                out[target] = convert_value(ans[k]) # type: ignore
                break

    return out


def map_parent_school_fields(ans):
    return {
        "school-name_01": ans.get("school-name_01", ans.get("school-name-parent_01", "")),
        "school-name_02": ans.get("school-name_02", ans.get("school-name-parent_02", "")),
        "previous_term_01": ans.get("previous_term_01", ""),
        "previous_term_02": ans.get("previous_term_02", ""),
    }


# ============================================================
# Column definitions (canonical output structure)
# ============================================================

STUDENT_COLUMNS = (
    ["Survey", "建立時間", "更新時間",
     "school_from_student", "school_from_parent", "student_answer",
     "school-name_01", "school-name_02",
     "previous_term_school_data_01", "previous_term_school_data_02",
     "contact_01", "contact_02"] +
    [f"student_demographics_{suffix}" for suffix in [
        "01", "02", "03", "04", "05", "06", "07", "07.1",
        "08", "08.1", "09.1", "09.2", "09.3", "09.4", "10", "11"
    ]] +
    [f"student_PHQ_{str(i).zfill(2)}" for i in range(1, 5)] +
    [f"student_TBV_{str(i).zfill(2)}" for i in range(1, 8)] +
    [f"student_TBP_{str(i).zfill(2)}" for i in range(1, 8)] +
    [f"student_CBV_{str(i).zfill(2)}" for i in range(1, 7)] +
    [f"student_CBP_{str(i).zfill(2)}" for i in range(1, 7)] +
    [f"student_FQOL_{str(i).zfill(2)}" for i in range(1, 22)] +
    [f"student_SEC_{str(i).zfill(2)}" for i in range(1, 23)]
)

PARENT_COLUMNS = (
    ["Survey", "建立時間", "更新時間",
     "school_from_student", "school_from_parent", "parent_answer",
     "school-name_01", "school-name_02",
     "previous_term_01", "previous_term_02",
     "contact_01", "contact_02", "contact_03.1", "contact_03.2", "contact_03.3", "contact_03.4"] +
    [f"adult_demographics_{suffix}" for suffix in [
        "01", "02", "03", "04", "04.1", "05", "06", "06.1",
        "07", "07.1", "08", "09", "10", "11", "12", "13", "14", "14.1"
    ]] +
    [f"parent_PHQ_{str(i).zfill(2)}" for i in range(1, 5)] +
    [f"parent_TBV_{str(i).zfill(2)}" for i in range(1, 8)] +
    [f"parent_TBP_{str(i).zfill(2)}" for i in range(1, 8)] +
    [f"parent_CBV_{str(i).zfill(2)}" for i in range(1, 7)] +
    [f"parent_CBP_{str(i).zfill(2)}" for i in range(1, 7)] +
    [f"parent_FQOL_{str(i).zfill(2)}" for i in range(1, 22)] +
    [f"parent_SEC_{str(i).zfill(2)}" for i in range(1, 23)]
)


# ============================================================
# FQOL post-processing helper
# ============================================================

def shift_fqol_cols(df: pd.DataFrame, role_prefix: str):
    """
    Add +1 to all FQOL items for the given role ('student' or 'parent')
    so that 0–4 becomes 1–5. Non-numeric / missing values are left as NaN.
    """
    fqol_cols = [f"{role_prefix}_FQOL_{i:02d}" for i in range(1, 22)]
    for col in fqol_cols:
        if col in df.columns:
            ser = pd.to_numeric(df[col], errors="coerce")
            df[col] = ser.where(ser.isna(), ser + 1)


# ============================================================
# Main processing for a single row
# ============================================================

def process_student_row(row, wave):
    """
    Build a standardised dict for a student row (T0 or T1).
    """
    survey = row.get("Survey", "")
    school = row.get("School", "")
    raw_ans_str = row.get("Answers", "")

    ans = parse_answer_field(raw_ans_str)

    # --- fix '全港適用' using school-name_01 for special student surveys ---
    survey_lower = str(survey).lower()
    if any(pat in survey_lower for pat in STUDENT_SCHOOL_FROM_ANS_SURVEYS):
        school_from_json = ans.get("school-name_01", "")
        if school_from_json not in ("", None, "全港適用"):
            school = school_from_json

    out = {col: "" for col in STUDENT_COLUMNS}

    out["Survey"] = survey
    out["建立時間"] = row.get("建立時間", "")
    out["更新時間"] = row.get("更新時間", "") 
    out["school_from_student"] = school
    out["school_from_parent"] = ""
    out["student_answer"] = raw_ans_str

    # school-related fields from JSON
    out.update(map_student_school_fields(ans))

    # contact info
    out.update(map_student_contacts(ans))

    # demographics
    out.update(map_student_demographics(ans))

    # Selected student T0/T1 special versions: school-name_02 stores student_demographics_01.
    if any(pat in survey_lower for pat in STUDENT_DEMO01_FROM_SCHOOL_NAME_02_SURVEYS):
        if not out.get("student_demographics_01"):
            val = ans.get("school-name_02", "")
            if val not in ("", None):
                out["student_demographics_01"] = convert_value(val) # type: ignore

    # scales
    out.update(map_student_scales(ans))

    return out


def process_parent_row(row, wave):
    """
    Build a standardised dict for a parent row (T0 or T1).
    """
    survey = row.get("Survey", "")
    school = row.get("School", "")
    raw_ans_str = row.get("Answers", "")

    ans = parse_answer_field(raw_ans_str)

    # --- fix '全港適用' using school name stored inside Answers for special parent surveys ---
    survey_lower = str(survey).lower()
    if any(pat in survey_lower for pat in PARENT_SCHOOL_FROM_PARENT_ANS_SURVEYS):
        school_from_json = ans.get("school-name-parent_01", "")
        if school_from_json not in ("", None, "全港適用"):
            school = school_from_json
    elif any(pat in survey_lower for pat in PARENT_SCHOOL_FROM_ANS_SURVEYS):
        school_from_json = ans.get("school-name_01", "")
        if school_from_json in ("", None, "全港適用") and any(
            pat in survey_lower for pat in PARENT_SCHOOL_PARENT01_FALLBACK_SURVEYS
        ):
            school_from_json = ans.get("school-name-parent_01", "")
        if school_from_json not in ("", None, "全港適用"):
            school = school_from_json

    out = {col: "" for col in PARENT_COLUMNS}

    out["Survey"] = survey
    out["建立時間"] = row.get("建立時間", "")
    out["更新時間"] = row.get("更新時間", "")
    out["school_from_student"] = ""
    out["school_from_parent"] = school
    out["parent_answer"] = raw_ans_str

    # school-related fields from JSON
    out.update(map_parent_school_fields(ans))

    # contacts
    out.update(map_parent_contacts(ans))

    # demographics
    out.update(map_parent_demographics(ans))

    # Selected parent T0/T1 special versions: school-name_02 or school-name-parent_02 stores adult_demographics_01.
    if any(pat in survey_lower for pat in PARENT_DEMO01_FROM_SCHOOL_NAME_02_SURVEYS):
        if not out.get("adult_demographics_01"):
            val = ans.get("school-name_02", "")
            if val in ("", None):
                val = ans.get("school-name-parent_02", "")
            if val not in ("", None):
                out["adult_demographics_01"] = convert_value(val) # type: ignore


    # scales
    out.update(map_parent_scales(ans))

    return out


# ============================================================
# Qualtrics export mapping
# ============================================================

QUALTRICS_FILENAME_RE = re.compile(
    r"^Study 2 (Student|Parent) Survey (T0|T1)(?:_.*)?\.csv$",
    flags=re.IGNORECASE,
)

# Qualtrics displays response labels in the exported data.  These dictionaries
# convert the labels back into the numeric coding already used by the pipeline.
GENDER_MAP = {"男": 0, "女": 1, "Male": 0, "Female": 1}
PLACE_MAP = {
    "香港特別行政區": 0, "中國內地": 1, "其他": 2,
    "Hong Kong SAR": 0, "Mainland China": 1, "Others": 2, "Other": 2,
}
YEARS_HK_MAP = {
    "不多於一年": 0, "一年至六年": 1, "七年或以上": 2,
    "Not more than one year": 0, "One to six years": 1, "Seven years or above": 2,
}
PERFORMANCE_MAP = {
    "差": 0, "稍差": 1, "中等": 2, "較好": 3, "很好": 4,
    "Very poor": 0, "Poor": 1, "Fair": 2, "Good": 3, "Very good": 4,
}
STUDENT_HOUSEHOLD_MAP = {
    "父親": 0, "母親": 1, "兄弟姐妹": 2, "兄弟姊妹": 2, "家傭": 3,
    "（外）祖父母": 4, "(外) 祖父母": 4, "其他": 5,
    "Father": 0, "Mother": 1, "Sibling(s)": 2, "Domestic helper": 3,
    "Grandparent(s)": 4, "Others": 5, "Other": 5,
}
PARENT_RELATION_MAP = {
    "父親": 0, "母親": 1, "其他": 2,
    "Father": 0, "Mother": 1, "Other": 2, "Others": 2,
}
PRIMARY_CARER_MAP = {
    "父母": 0, "(外) 祖父母": 1, "（外）祖父母": 1, "家傭": 2, "其他": 3,
    "Parent(s)": 0, "Grandparent(s)": 1, "Domestic helper": 2, "Other": 3, "Others": 3,
}
EDUCATION_MAP = {
    "從未入學/幼稚園": 0, "從未接受教育/幼稚園": 0,
    "小學": 1, "初中": 2, "高中": 3,
    "職業培訓/毅進計劃": 4, "預科 (中六及中七)": 5,
    "大專 (非學位課程/副學士課程)": 6, "大學 (本科)": 7, "碩士及以上": 8,
    "Never attended school/kindergarten": 0, "Primary school": 1,
    "Junior secondary": 2, "Senior secondary": 3,
    "Vocational training/Project Yi Jin": 4, "Matriculation (Form 6 and Form 7)": 5,
    "Sub-degree/associate degree": 6, "Bachelor's degree": 7, "Master's degree or above": 8,
}
MARITAL_MAP = {
    "未婚": 0, "已婚": 1, "離婚": 2, "喪偶": 3, "再婚": 4, "不方便提供": 5,
    "Single": 0, "Married": 1, "Divorced": 2, "Widowed": 3, "Remarried": 4,
    "Prefer not to say": 5,
}
EMPLOYMENT_MAP = {
    "全職": 0, "兼職或自由職業者": 1,
    "非從事經濟活動者（如學生、退休人員、家庭主婦）": 2, "失業": 3, "待業": 3,
    "Full-time": 0, "Part-time or freelance": 1,
    "Economically inactive (e.g. student, retired person, homemaker)": 2,
    "Unemployed": 3,
}
TEXTBOOK_MAP = {
    "有，現正領取全額津貼": 0, "有，現正領取半額津貼": 1, "沒有": 2,
    "Yes, full grant": 0, "Yes, half grant": 1, "No": 2,
}
CHILDREN_COUNT_MAP = {
    "1 位": 1, "2 位": 2, "3 位": 3, "4 位或以上": 4,
    "1": 1, "2": 2, "3": 3, "4 or above": 4,
}
YES_NO_MAP = {"是": 0, "否": 1, "Yes": 0, "No": 1}
SEN_MAP = {
    "有，被評估為專注力不足/ 過度活躍症 (AD/HD)": 0,
    "有，被評估為自閉症譜系障礙(ASD)": 1,
    "有，被評估為特殊學習障礙(SpLD)": 2,
    "沒有": 3, "其他": 4,
    "ADHD": 0, "ASD": 1, "SpLD": 2, "None": 3, "Other": 4, "Others": 4,
}
SEC_MAP = {
    "一點都不像我": 0, "不太像我": 1, "有點像我": 2, "很像我": 3,
    "一點都不像我孩子": 0, "不太像我孩子": 1, "有點像我孩子": 2, "很像我孩子": 3,
    "Not at all like me": 0, "Not much like me": 1, "Somewhat like me": 2, "Very much like me": 3,
    "Not at all like my child": 0, "Not much like my child": 1,
    "Somewhat like my child": 2, "Very much like my child": 3,
}
PHQ_MAP = {
    "完全沒有": 0, "幾天": 1, "一半以上的日子": 2, "幾乎每日": 3,
    "Not at all": 0, "Several days": 1, "More than half the days": 2, "Nearly every day": 3,
}
BULLY_MAP = {
    "沒有發生過": 0, "只發生過一、兩次": 1, "一個月發生兩至三次": 2,
    "約一星期一次": 3, "一星期幾次": 4,
    "Never": 0, "Only once or twice": 1, "Two or three times a month": 2,
    "About once a week": 3, "Several times a week": 4,
}
FQOL_MAP = {
    "非常不同意": 0, "不同意": 1, "介於同意與不同意之間": 2, "同意": 3, "非常同意": 4,
    "Strongly disagree": 0, "Disagree": 1, "Neither agree nor disagree": 2,
    "Agree": 3, "Strongly agree": 4,
}


def normalise_text(value) -> str:
    """Return a stripped string, treating pandas/CSV missing values as blank."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "nat"} else text


def map_qualtrics_choice(value, mapping: dict[str, int], field: str, unknowns: set[str]):
    """Strictly map one Qualtrics response label; record unexpected nonblank values."""
    text = normalise_text(value)
    if not text:
        return ""
    if text in mapping:
        return mapping[text]
    unknowns.add(f"{field}: {text!r}")
    return ""


def map_qualtrics_multiselect(value, mapping: dict[str, int], field: str, unknowns: set[str]) -> str:
    """Map a comma-separated Qualtrics multi-answer field into sorted pipeline codes."""
    text = normalise_text(value)
    if not text:
        return ""
    codes = []
    for token in (part.strip() for part in text.split(",")):
        if token in mapping:
            codes.append(mapping[token])
        else:
            unknowns.add(f"{field}: {token!r}")
    return ",".join(str(code) for code in sorted(set(codes)))


def read_qualtrics_csv(path: str) -> pd.DataFrame:
    """Read a Qualtrics CSV using stable ImportId metadata from its third header row."""
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            next(reader)  # display names (not stable and may contain duplicates)
            next(reader)  # question text
            metadata = next(reader)
        except StopIteration as exc:
            raise ValueError(f"Qualtrics export has fewer than three header rows: {path}") from exc

        import_ids = []
        for position, cell in enumerate(metadata):
            try:
                import_id = normalise_text(json.loads(cell).get("ImportId", ""))
            except (json.JSONDecodeError, AttributeError, TypeError):
                import_id = ""
            import_ids.append(import_id or f"unnamed_{position}")

        duplicates = sorted({name for name in import_ids if import_ids.count(name) > 1})
        if duplicates:
            raise ValueError(f"Duplicate Qualtrics ImportId values in {path}: {duplicates}")
        data = list(reader)

    return pd.DataFrame(data, columns=import_ids)


def parse_qualtrics_filename(path: str):
    """Return (role, wave), ignoring any export-date suffix."""
    match = QUALTRICS_FILENAME_RE.match(os.path.basename(path))
    if not match:
        return None
    role = match.group(1).lower()
    wave = match.group(2).upper()
    return role, wave


def select_current_qualtrics_files() -> dict[tuple[str, str], str]:
    """Use the single uploaded file per role/wave, regardless of export date."""
    selected: dict[tuple[str, str], str] = {}
    for path in sorted(glob.glob(os.path.join(input_dir, "*"))):
        if not os.path.isfile(path):
            continue
        details = parse_qualtrics_filename(path)
        if details:
            if details in selected:
                raise RuntimeError(
                    f"Multiple Qualtrics exports for {details}: {selected[details]}, {path}. "
                    "Remove the previous export and keep only one file per role/timepoint."
                )
            selected[details] = path
    if not selected:
        raise FileNotFoundError(f"No Study 2 Qualtrics survey CSV exports found in {input_dir}")
    return selected


def complete_qualtrics_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only responses explicitly marked Finished with 100% progress."""
    if "finished" not in df.columns or "progress" not in df.columns:
        raise KeyError("Qualtrics export is missing finished/progress metadata")
    finished = df["finished"].astype(str).str.strip().str.lower().eq("true")
    progress = pd.to_numeric(df["progress"], errors="coerce").eq(100)
    return df.loc[finished & progress].copy()


def qualtrics_timestamp_to_utc(value) -> str:
    """Convert Qualtrics' America/Denver export timestamps to timezone-aware UTC text."""
    text = normalise_text(value)
    if not text:
        return ""
    stamp = pd.to_datetime(text, errors="coerce")
    if pd.isna(stamp):
        return ""
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize(ZoneInfo("America/Denver"), ambiguous="NaT", nonexistent="shift_forward")
    if pd.isna(stamp):
        return ""
    return stamp.tz_convert("UTC").isoformat()


def clean_qualtrics_date(value) -> str:
    """Recover a calendar date from Qualtrics date-question exports."""
    text = normalise_text(value)
    if not text:
        return ""
    stamp = pd.to_datetime(text, errors="coerce")
    if pd.isna(stamp):
        return ""
    # Qualtrics date-picker exports may express Hong Kong midnight as 16:00 UTC
    # on the previous calendar day.  Convert non-midnight timestamps back to HK.
    if stamp.hour or stamp.minute or stamp.second:
        stamp = stamp.tz_localize("UTC").tz_convert("Asia/Hong_Kong")
    return stamp.strftime("%Y-%m-%d")


def answer_payload(row: pd.Series, extra: dict[str, object] | None = None) -> str:
    """Store question responses—not IP/location metadata—as an ast-readable dictionary."""
    payload = {
        key: normalise_text(value)
        for key, value in row.items()
        if (str(key).startswith("QID") or key == "source") and normalise_text(value)
    }
    if extra:
        payload.update(extra) # type: ignore
    return repr(payload)


def map_qualtrics_scales(
    row: pd.Series,
    role_prefix: str,
    out: dict,
    unknowns: set[str],
) -> None:
    """Map common SEC/PHQ/bullying/FQOL item blocks into canonical columns."""
    for i in range(1, 23):
        out[f"{role_prefix}_SEC_{i:02d}"] = map_qualtrics_choice(
            row.get(f"QID29_{i}", ""), SEC_MAP, f"QID29_{i}", unknowns
        )
    for i in range(1, 5):
        out[f"{role_prefix}_PHQ_{i:02d}"] = map_qualtrics_choice(
            row.get(f"QID30_{i}", ""), PHQ_MAP, f"QID30_{i}", unknowns
        )
    for prefix, qid, count in [("TBV", 32, 7), ("TBP", 33, 7), ("CBV", 34, 6), ("CBP", 35, 6)]:
        for i in range(1, count + 1):
            out[f"{role_prefix}_{prefix}_{i:02d}"] = map_qualtrics_choice(
                row.get(f"QID{qid}_{i}", ""), BULLY_MAP, f"QID{qid}_{i}", unknowns
            )
    # Keep FQOL as raw 0-4 here. The existing shared post-processing shifts it to 1-5.
    for i in range(1, 22):
        out[f"{role_prefix}_FQOL_{i:02d}"] = map_qualtrics_choice(
            row.get(f"QID37_{i}", ""), FQOL_MAP, f"QID37_{i}", unknowns
        )


def process_qualtrics_student(row: pd.Series, wave: str, unknowns: set[str]) -> dict:
    """Map one completed Qualtrics student response into the canonical student schema."""
    out = {col: "" for col in STUDENT_COLUMNS}
    email = normalise_text(row.get("QID47_TEXT", ""))
    if "@" not in email:
        email = normalise_text(row.get("QID44_TEXT", ""))
    response_id = normalise_text(row.get("_recordId", ""))

    out.update({
        "Survey": f"panel_student_{wave.lower()}_questionnaire_qualtrics (Wave {0 if wave == 'T0' else 1})",
        "建立時間": qualtrics_timestamp_to_utc(row.get("startDate", "")),
        "更新時間": qualtrics_timestamp_to_utc(row.get("recordedDate", row.get("endDate", ""))),
        "school_from_student": normalise_text(row.get("QID3_1", "")),
        "school_from_parent": "",
        "contact_01": clean_phone(row.get("QID39_TEXT", "")),
        "contact_02": clean_phone(row.get("QID40_TEXT", "")),
        "student_demographics_01": convert_value(normalise_text(row.get("QID4_TEXT", ""))),
        "student_demographics_03": map_qualtrics_choice(row.get("QID6", ""), GENDER_MAP, "QID6", unknowns),
        "student_demographics_04": convert_value(normalise_text(row.get("QID7_TEXT", ""))),
        "student_demographics_05": convert_value(normalise_text(row.get("QID8_TEXT", ""))),
        "student_demographics_06": clean_qualtrics_date(row.get("QID9_1", "")),
        "student_demographics_07": map_qualtrics_choice(row.get("QID10", ""), PLACE_MAP, "QID10", unknowns),
        "student_demographics_07.1": normalise_text(row.get("QID11_TEXT", "")),
        "student_demographics_08": map_qualtrics_multiselect(row.get("QID12", ""), STUDENT_HOUSEHOLD_MAP, "QID12", unknowns),
        "student_demographics_08.1": normalise_text(row.get("QID13_TEXT", "")),
        "student_demographics_09.1": convert_value(normalise_text(row.get("QID14_1_1", ""))),
        "student_demographics_09.2": convert_value(normalise_text(row.get("QID14_2_1", ""))),
        "student_demographics_09.3": convert_value(normalise_text(row.get("QID14_3_1", ""))),
        "student_demographics_09.4": convert_value(normalise_text(row.get("QID14_4_1", ""))),
        "student_demographics_10": map_qualtrics_choice(row.get("QID15", ""), YEARS_HK_MAP, "QID15", unknowns),
        "student_demographics_11": map_qualtrics_choice(row.get("QID16", ""), PERFORMANCE_MAP, "QID16", unknowns),
    }) # type: ignore
    out["student_answer"] = answer_payload(row, {
        "qualtrics_response_id": response_id,
        "panel-contact-info-for-student-survey-email_01": email,
    })
    map_qualtrics_scales(row, "student", out, unknowns)
    return out


def process_qualtrics_parent(row: pd.Series, wave: str, unknowns: set[str]) -> dict:
    """Map one completed Qualtrics parent response into the canonical parent schema."""
    out = {col: "" for col in PARENT_COLUMNS}
    email = normalise_text(row.get("QID42_TEXT", ""))
    response_id = normalise_text(row.get("_recordId", ""))
    out.update({
        "Survey": f"panel_parents_{wave.lower()}_questionnaire_qualtrics (Wave {0 if wave == 'T0' else 1})",
        "建立時間": qualtrics_timestamp_to_utc(row.get("startDate", "")),
        "更新時間": qualtrics_timestamp_to_utc(row.get("recordedDate", row.get("endDate", ""))),
        "school_from_student": "",
        "school_from_parent": normalise_text(row.get("QID3_1", "")),
        "contact_01": clean_phone(row.get("QID66_TEXT", "")),
        "contact_02": clean_phone(row.get("QID67_TEXT", "")),
        "contact_03.1": email,
        "adult_demographics_01": convert_value(normalise_text(row.get("QID4_TEXT", ""))),
        "adult_demographics_03": clean_qualtrics_date(row.get("QID51_1", "")),
        "adult_demographics_04": map_qualtrics_choice(row.get("QID52", ""), GENDER_MAP, "QID52", unknowns),
        "adult_demographics_05": convert_value(normalise_text(row.get("QID53_TEXT", ""))),
        "adult_demographics_06": map_qualtrics_choice(row.get("QID54", ""), PARENT_RELATION_MAP, "QID54", unknowns),
        "adult_demographics_06.1": normalise_text(row.get("QID55_TEXT", "")),
        "adult_demographics_07": map_qualtrics_choice(row.get("QID56", ""), PRIMARY_CARER_MAP, "QID56", unknowns),
        "adult_demographics_07.1": normalise_text(row.get("QID57_TEXT", "")),
        "adult_demographics_08": map_qualtrics_choice(row.get("QID58", ""), EDUCATION_MAP, "QID58", unknowns),
        "adult_demographics_09": map_qualtrics_choice(row.get("QID59", ""), MARITAL_MAP, "QID59", unknowns),
        "adult_demographics_10": map_qualtrics_choice(row.get("QID60", ""), EMPLOYMENT_MAP, "QID60", unknowns),
        "adult_demographics_11": map_qualtrics_choice(row.get("QID63", ""), TEXTBOOK_MAP, "QID63", unknowns),
        "adult_demographics_12": map_qualtrics_choice(row.get("QID61", ""), CHILDREN_COUNT_MAP, "QID61", unknowns),
        "adult_demographics_13": map_qualtrics_choice(row.get("QID62", ""), YES_NO_MAP, "QID62", unknowns),
        "adult_demographics_14": map_qualtrics_multiselect(row.get("QID64", ""), SEN_MAP, "QID64", unknowns),
        "adult_demographics_14.1": normalise_text(row.get("QID65_TEXT", "")),
    }) # type: ignore
    out["parent_answer"] = answer_payload(row, {"qualtrics_response_id": response_id})
    map_qualtrics_scales(row, "parent", out, unknowns)
    return out


def load_current_qualtrics_rows():
    """Load/map current files into A/B/C/D and retain IDs for reconciliation."""
    selected = select_current_qualtrics_files()
    expected = {
        ("student", "T0"): ("A", process_qualtrics_student),
        ("parent", "T0"): ("B", process_qualtrics_parent),
        ("student", "T1"): ("C", process_qualtrics_student),
        ("parent", "T1"): ("D", process_qualtrics_parent),
    }
    rows_by_sheet = {letter: [] for letter in "ABCD"}
    ids_by_sheet = {letter: [] for letter in "ABCD"}
    raw_and_complete_counts = {}
    unknowns: set[str] = set()

    for key, (letter, mapper) in expected.items():
        path = selected.get(key)
        if path is None:
            raw_and_complete_counts[letter] = (0, 0)
            continue
        raw = read_qualtrics_csv(path)
        complete = complete_qualtrics_rows(raw)
        response_ids = complete["_recordId"].map(normalise_text).tolist()
        if any(not value for value in response_ids):
            raise RuntimeError(f"Completed Qualtrics rows without ResponseId in {path}")
        if len(response_ids) != len(set(response_ids)):
            raise RuntimeError(f"Duplicate completed Qualtrics ResponseId values in {path}")
        rows_by_sheet[letter] = [mapper(row, key[1], unknowns) for _, row in complete.iterrows()]
        ids_by_sheet[letter] = response_ids
        raw_and_complete_counts[letter] = (len(raw), len(complete))

    if unknowns:
        formatted = "\n  - ".join(sorted(unknowns))
        raise RuntimeError(f"Unmapped Qualtrics response labels detected:\n  - {formatted}")
    return rows_by_sheet, ids_by_sheet, raw_and_complete_counts, selected


def extract_qualtrics_response_ids(df: pd.DataFrame, answer_column: str) -> list[str]:
    """Extract the immutable Qualtrics ResponseId values stored in an output answer column."""
    ids = []
    for value in df[answer_column]:
        parsed = parse_answer_field(value)
        response_id = normalise_text(parsed.get("qualtrics_response_id", ""))
        if response_id:
            ids.append(response_id)
    return ids


def validate_qualtrics_reconciliation(
    frames: dict[str, pd.DataFrame], expected_ids: dict[str, list[str]]
) -> None:
    """Require every accepted Qualtrics response to appear exactly once in its A/B/C/D output."""
    answer_columns = {"A": "student_answer", "B": "parent_answer", "C": "student_answer", "D": "parent_answer"}
    all_expected = {response_id for values in expected_ids.values() for response_id in values}
    for letter in "ABCD":
        actual = extract_qualtrics_response_ids(frames[letter], answer_columns[letter])
        expected = expected_ids[letter]
        if len(actual) != len(set(actual)):
            raise RuntimeError(f"Output {letter} contains duplicate Qualtrics ResponseId values")
        if set(actual) != set(expected):
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            raise RuntimeError(f"Qualtrics reconciliation failed for {letter}: missing={missing}, extra={extra}")
        wrong_sheet_ids = set(actual) & (all_expected - set(expected))
        if wrong_sheet_ids:
            raise RuntimeError(f"Qualtrics response(s) mapped to wrong sheet {letter}: {sorted(wrong_sheet_ids)}")


# ============================================================
# Main
# ============================================================

def main():
    # -------------------------------
    # Load raw student & parent files
    # -------------------------------
    student_df = pd.read_excel(input_path_student)
    parent_df  = pd.read_excel(input_path_parent)

    # Normalise English / Traditional Chinese raw-system headers into one
    # stable internal schema before any role, wave, or answer mapping occurs.
    student_df = normalize_system_columns(student_df)
    parent_df = normalize_system_columns(parent_df)

    # Lists to collect rows
    A_rows = []   # T0 student
    C_rows = []   # T1 student
    B_rows = []   # T0 parent
    D_rows = []   # T1 parent

    # Load one current Qualtrics file per role/wave, ignoring export dates.
    # A missing role/wave contributes zero rows; duplicates stop the run.
    (
        qualtrics_rows,
        qualtrics_ids,
        qualtrics_counts,
        qualtrics_selected,
    ) = load_current_qualtrics_rows()

    # ---------------------------------------
    # Process rows from student raw file
    # ---------------------------------------
    for _, row in student_df.iterrows():
        survey_val = row.get("Survey", "")
        role, wave = detect_role_and_wave(survey_val)
        if role is None or wave is None:
            continue

        if role == "student":
            std_row = process_student_row(row, wave)
            if wave == "T0":
                A_rows.append(std_row)
            elif wave == "T1":
                C_rows.append(std_row)

        elif role == "parent":
            par_row = process_parent_row(row, wave)
            if wave == "T0":
                B_rows.append(par_row)
            elif wave == "T1":
                D_rows.append(par_row)

    # ---------------------------------------
    # Process rows from parent raw file
    # ---------------------------------------
    for _, row in parent_df.iterrows():
        survey_val = row.get("Survey", "")
        role, wave = detect_role_and_wave(survey_val)
        if role is None or wave is None:
            continue

        # In parent file, all relevant rows should be parent-* surveys
        if role != "parent":
            continue

        par_row = process_parent_row(row, wave)
        if wave == "T0":
            B_rows.append(par_row)
        elif wave == "T1":
            D_rows.append(par_row)

    # Append the newly mapped Qualtrics responses to the old-system records.
    A_rows.extend(qualtrics_rows["A"])
    B_rows.extend(qualtrics_rows["B"])
    C_rows.extend(qualtrics_rows["C"])
    D_rows.extend(qualtrics_rows["D"])

    # ---------------------------------------
    # Build DataFrames with canonical columns
    # ---------------------------------------
    A_df = pd.DataFrame(A_rows, columns=STUDENT_COLUMNS)
    C_df = pd.DataFrame(C_rows, columns=STUDENT_COLUMNS)
    B_df = pd.DataFrame(B_rows, columns=PARENT_COLUMNS)
    D_df = pd.DataFrame(D_rows, columns=PARENT_COLUMNS)

    # Clean contacts and DOBs for matching robustness.
    A_df = clean_output_contacts_and_dobs(A_df, "student")
    C_df = clean_output_contacts_and_dobs(C_df, "student")
    B_df = clean_output_contacts_and_dobs(B_df, "parent")
    D_df = clean_output_contacts_and_dobs(D_df, "parent")

    # ---------------------------------------
    # Post-processing:
    #   1) Shift FQOL scores 0–4 -> 1–5
    #   2) Drop school-name_01 and school-name_02
    # ---------------------------------------

    # Shift FQOL scores
    shift_fqol_cols(A_df, "student")
    shift_fqol_cols(C_df, "student")
    shift_fqol_cols(B_df, "parent")
    shift_fqol_cols(D_df, "parent")

    # Drop school-name columns from all outputs
    cols_to_drop = ["school-name_01", "school-name_02"]
    for df in [A_df, B_df, C_df, D_df]:
        df.drop(columns=cols_to_drop, inplace=True, errors="ignore")

    frames = {"A": A_df, "B": B_df, "C": C_df, "D": D_df}
    validate_qualtrics_reconciliation(frames, qualtrics_ids)

    # ---------------------------------------
    # Save outputs
    # ---------------------------------------
    A_df.to_excel(output_path_A, index=False)
    B_df.to_excel(output_path_B, index=False)
    C_df.to_excel(output_path_C, index=False)
    D_df.to_excel(output_path_D, index=False)

    print("✅ Step 2.1.1 completed.")
    print(f"  Old-system student input: {input_path_student}")
    print(f"  Old-system parent input : {input_path_parent}")
    print("  Qualtrics selection     : one file per role/timepoint (dates ignored)")
    labels = {
        "A": "Student T0",
        "B": "Parent T0",
        "C": "Student T1",
        "D": "Parent T1",
    }
    keys = {
        "A": ("student", "T0"),
        "B": ("parent", "T0"),
        "C": ("student", "T1"),
        "D": ("parent", "T1"),
    }
    for letter in "ABCD":
        raw_count, complete_count = qualtrics_counts[letter]
        path = qualtrics_selected.get(keys[letter])
        source_name = os.path.basename(path) if path else "MISSING IN CURRENT BATCH (treated as 0)"
        print(
            f"  Qualtrics {letter} {labels[letter]}: "
            f"{complete_count}/{raw_count} complete rows; {source_name}"
        )
    print("  Qualtrics reconciliation: PASS (every accepted ResponseId appears once in A/B/C/D)")
    print(f"  A_T0-student: {len(A_df)} rows -> {output_path_A}")
    print(f"  B_T0-parent : {len(B_df)} rows -> {output_path_B}")
    print(f"  C_T1-student: {len(C_df)} rows -> {output_path_C}")
    print(f"  D_T1-parent : {len(D_df)} rows -> {output_path_D}")


if __name__ == "__main__":
    main()
