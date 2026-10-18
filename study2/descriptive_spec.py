"""Versioned report definitions, independent of labels, Excel and Streamlit.

Question meanings were checked against the bilingual survey samples and the
canonical adapters. Numeric score bands are descriptive groups, not diagnoses.
"""
from dataclasses import dataclass

VERSION = 'study2_descriptive_v2'
DICTIONARY_VERSION = 'survey_demographics_v2'
# Jarvis approved the legacy reporting ranges on 2026-10-17. These inclusive
# bounds affect descriptive availability only, never answers or membership.
REPORT_RANGES = {'child_age': (5,20), 'adult_age': (20,70), 'height': (100,200), 'weight': (20,100),
                 'older_brothers': (0,5), 'older_sisters': (0,5), 'younger_brothers': (0,5),
                 'younger_sisters': (0,5), 'siblings_total': (0,10)}


def range_note(key):
    bounds = REPORT_RANGES[key]
    return ('描述統計有效範圍待核，暫不計算；原值保留。' if bounds is None else
            f'有效範圍 {bounds[0]}–{bounds[1]}（含上下限）；範圍外列缺失，原值及樣本保留。')
MODES = {
    'abcd': '各輪全部樣本（A／B／C／D）',
    'ef': '各輪親子樣本（E／F）',
    'acbd': '同一人跨期樣本（AC／BD）',
    'efmatched': '跨期親子樣本（EF）',
}
REPORT_FILES = {
    'abcd': 'descriptive_T0-T1_ABCD.xlsx',
    'ef': 'descriptive_paired_T0-T1_EF.xlsx',
    'acbd': 'descriptive_longitudinal_T0-T1_ACBD.xlsx',
    'efmatched': 'descriptive_longitudinal_T0-T1_EFmatched.xlsx',
}
GROUPS = {
    'all': '全部', 'male': '男', 'female': '女',
    'primary': '小學', 'secondary': '中學',
    'male_primary': '男小學', 'female_primary': '女小學',
    'male_secondary': '男中學', 'female_secondary': '女中學',
}
SECTIONS = {'scales': '量表及欺凌', 'student': '學生人口特徵', 'parent': '家長人口特徵'}


@dataclass(frozen=True)
class Variable:
    key: str
    label: str
    kind: str = 'continuous'
    role: str = 'both'
    section: str = 'scales'
    categories: tuple = ()
    unit: str = '分'
    source: str = '共用量表計分層；所需題目完整'
    note: str = ''


SCALE_LABELS = {
    'PHQ_anxiety': 'PHQ 焦慮', 'PHQ_depression': 'PHQ 抑鬱', 'PHQ_total': 'PHQ 總分',
    'FQOL_total': 'FQOL 總分', 'FQOL_family_interaction': 'FQOL 家庭互動',
    'FQOL_parenting': 'FQOL 親職', 'FQOL_emotional_wellbeing': 'FQOL 情緒福祉',
    'FQOL_physical_wellbeing': 'FQOL 身體及物質福祉',
    'SEC_total': 'SEC 總分', 'SEC_responsible_decision_making': 'SEC 負責任決策',
    'SEC_social_awareness': 'SEC 社會覺察', 'SEC_self_management': 'SEC 自我管理',
    'SEC_relationship_skills': 'SEC 關係技巧', 'SEC_self_awareness': 'SEC 自我覺察',
}
BULLY_LABELS = {'TBV': '傳統欺凌受害', 'TBP': '傳統欺凌施害',
                'CBV': '網絡欺凌受害', 'CBP': '網絡欺凌施害'}
SCALES = [Variable(k, v) for k, v in SCALE_LABELS.items()]
for domain, title in BULLY_LABELS.items():
    SCALES.append(Variable(domain + '_mean', title + '平均分'))
    for threshold, meaning in [(1, '至少一項曾發生（≥1）'), (2, '至少一項每月兩至三次或以上（≥2）')]:
        SCALES.append(Variable(domain + '_prevalence' + str(threshold), title + '：' + meaning,
                               'binary', unit='比例', note='過去三個月；整域所需題目完整'))
SCALES.append(Variable('phq_band', 'PHQ 總分分組', 'category',
    categories=(('0_2', '0–2 分'), ('3_5', '3–5 分'), ('6_8', '6–8 分'), ('9_12', '9–12 分')),
    unit='人', note='描述分數分布，不作臨床診斷'))


def demo(key, label, role, kind='continuous', categories=(), unit='', source='', note=''):
    return Variable('dem_' + key, label, kind, role, role, tuple(categories), unit, source, note)


GENDER = (('0', '男'), ('1', '女'))
STAGE = (('primary', '小學'), ('secondary', '中學'))
STUDENT = [
    demo('child_gender', '孩子性別', 'student', 'category', GENDER, source='student_demographics_03'),
    demo('child_age', '孩子觀察時年齡', 'student', unit='歲', source='既有 age_at_observation', note=range_note('child_age')),
    demo('birthplace', '出生地', 'student', 'category',
         (('0', '香港'), ('1', '中國內地'), ('2', '其他')), source='student_demographics_07'),
    demo('years_hk', '居港年期', 'student', 'category',
         (('0', '不多於一年'), ('1', '一至六年'), ('2', '七年或以上')), source='student_demographics_10'),
    *[demo(key, title, 'student', unit='位', source='student_demographics_09.' + str(i), note=range_note(key))
      for i, (key, title) in enumerate([('older_brothers', '哥哥人數'), ('older_sisters', '姐姐人數'),
                                      ('younger_brothers', '弟弟人數'), ('younger_sisters', '妹妹人數')], 1)],
    demo('siblings_total', '兄弟姊妹總數', 'student', unit='位', source='四個兄弟姊妹分項',
         note='四項均有效才加總；缺項不當零；分項超範圍亦列缺失。'+range_note('siblings_total')),
    demo('height', '身高', 'student', unit='cm', source='student_demographics_04', note=range_note('height')),
    demo('weight', '體重', 'student', unit='kg', source='student_demographics_05', note=range_note('weight')),
    demo('bmi', 'BMI（連續值）', 'student', unit='kg/m²', source='體重／身高（米）平方',
         note='身高及體重均在已確認範圍內才計算；不作兒童體重分類；分項超範圍亦列缺失'),
    demo('performance', '自評學業表現', 'student', 'category',
         (('4', '很好'), ('3', '較好'), ('2', '中等'), ('1', '稍差'), ('0', '差')),
         source='student_demographics_11'),
    demo('grade', '該輪年級', 'student', 'category', tuple((str(i), str(i)) for i in range(1, 7)),
         source='既有年級整理值', note='年級數字須配合學校階段閱讀'),
    demo('stage', '該輪學校階段', 'student', 'category', STAGE, source='校名字典及現有年級解析'),
]
PARENT = [
    demo('adult_gender', '成人性別（未獨立收集）', 'parent', 'category', GENDER,
         source='原問卷無獨立成人性別題', note='不從父親／母親稱謂推定'),
    demo('relationship', '填卷人與孩子關係', 'parent', 'category',
         (('0', '父親'), ('1', '母親'), ('2', '其他')), source='adult_demographics_06'),
    demo('adult_age', '成人觀察時估算年齡', 'parent', unit='歲',
         source='有效觀察年份減 adult_demographics_05', note='只有出生年份；未知正確年份不猜填。'+range_note('adult_age')),
    demo('carer', '孩子主要照顧者', 'parent', 'category',
         (('0', '父母'), ('1', '（外）祖父母'), ('2', '家傭'), ('3', '其他')), source='adult_demographics_07'),
    demo('education', '教育程度', 'parent', 'category',
         (('0', '小學或以下'), ('1', '中學／職業培訓／預科'), ('2', '大專／大學'), ('3', '碩士及以上')),
         source='adult_demographics_08；0–1／2–5／6–7／8 分組'),
    demo('marital', '婚姻狀況', 'parent', 'category',
         (('0', '未婚'), ('1', '已婚'), ('2', '離婚'), ('3', '喪偶'), ('4', '再婚'), ('5', '不方便提供')),
         source='adult_demographics_09', note='不方便提供為有效選項'),
    demo('employment', '就業狀況', 'parent', 'category',
         (('0', '全職'), ('1', '兼職／自由職業'), ('2', '非從事經濟活動'), ('3', '待業')),
         source='adult_demographics_10'),
    demo('textbook', '書簿津貼', 'parent', 'category',
         (('0', '全額'), ('1', '半額'), ('2', '沒有')), source='adult_demographics_11'),
    demo('children_count', '子女人數（分類）', 'parent', 'category',
         (('1', '1 個'), ('2', '2 個'), ('3', '3 個'), ('4', '4 個或以上')), source='adult_demographics_12',
         note='只正式解讀已確認的 Qualtrics 1–4 編碼；其他來源編碼待核；不求平均'),
    demo('cohabit', '與孩子同住', 'parent', 'category', (('0', '是'), ('1', '否')),
         source='adult_demographics_13'),
    demo('sen', '孩子 SEN 狀態', 'parent', 'category', (('yes', '有 SEN'), ('no', '沒有 SEN')),
         source='adult_demographics_14', note='缺失及矛盾選項不推定有／沒有'),
    demo('sen_types', '孩子 SEN 類別（可複選）', 'parent', 'multi',
         (('0', 'ADHD'), ('1', 'ASD'), ('2', 'SpLD'), ('4', '其他')), source='adult_demographics_14',
         note='分母為該題有效回答人數，包含有效回答「沒有」；各類比例可合計超過 100%'),
    demo('child_gender', '所指孩子性別', 'parent', 'category', GENDER, source='adult_demographics_04'),
    demo('child_age', '所指孩子觀察時年齡', 'parent', unit='歲', source='既有 age_at_observation', note=range_note('child_age')),
    demo('stage', '該輪孩子學校階段', 'parent', 'category', STAGE, source='校名字典及現有年級解析'),
]
VARIABLES = SCALES + STUDENT + PARENT
STATUS_LABELS = {'missing': '未填', 'invalid': '無效值', 'conflict': '選項矛盾',
                 'unverified_date': '日期未達年齡計算可信度', 'unconfirmed_year': '正確年份未確認',
                 'unverified_encoding': '來源編碼待核', 'not_collected': '未獨立收集',
                 'unknown_stage': '學段未能判定', 'range_pending': '描述統計有效範圍待核',
                 'outside_report_range': '超出已確認的描述統計範圍'}


def variables(role, section=None):
    return [v for v in VARIABLES if v.role in {'both', role} and (section is None or v.section == section)]


def dictionary_rows():
    return [dict(variable_id=v.key, label=v.label, kind=v.kind, role=v.role, section=v.section,
                 unit=v.unit, source=v.source, categories='；'.join(k + '=' + name for k, name in v.categories),
                 note=v.note, dictionary_version=DICTIONARY_VERSION) for v in VARIABLES]
