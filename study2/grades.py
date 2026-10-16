"""Parse reported grade formats without inferring promotion or foreign grades."""
import re
import unicodedata
from functools import lru_cache
from typing import NamedTuple

from .common import text


class Grade(NamedTuple):
    number: int | None
    stage: str | None


# Keep the exact old parser solely to recognise already-frozen evidence. It is
# never the cleaning rule used by outputs, matching, or grade progression hints.
_V1 = re.compile(r"(?:PRIMARY|SECONDARY|FORM|GRADE|CLASS|P|S|F|小|中)?\s*([1-6一二三四五六])(?:\s*[A-Za-z]|年級|年|級|班)?", re.I)
_GRADE = re.compile(
    r"(?:(?P<prefix>PRIMARY|SECONDARY|FORM|GRADE|CLASS|YEAR|小學|中學|P|S|F|G|Y|小|中)\.?)?"
    r"(?P<number>[1-6一二三四五六])"
    r"(?:年級|年班|年|級)?"
    r"(?:[A-Z]{1,3}[0-9]{0,2}|[仁義禮智信忠孝愛敬誠勤德善勇望甲乙丙丁戊己庚辛壬癸]{1,2})?班?"
)


def legacy_grade(value):
    match = _V1.fullmatch(text(value))
    return _number(match[1]) if match else None


def _number(token):
    return int(token) if token.isdigit() else "一二三四五六".index(token) + 1


def parse_grade(value) -> Grade:
    return _parse(text(value))


@lru_cache(maxsize=4096)
def _parse(raw):
    value = unicodedata.normalize('NFKC', raw).upper().translate(str.maketrans({'学': '學', '级': '級'}))
    value = re.sub(r'\s+', '', value)
    if re.search(r'[1-6一二三四五六](?:OR|AND|或|至|到|升)[1-6一二三四五六]', value):
        return Grade(None, None)
    # A whole numeric string such as "1.0" is an integer export, not F.1.
    numeric = re.fullmatch(r'([1-6])\.0+', value)
    if numeric:
        return Grade(int(numeric[1]), None)
    match = _GRADE.fullmatch(value)
    if not match:
        return Grade(None, None)
    prefix = match['prefix']
    stage = ('primary' if prefix in {'PRIMARY', 'P', '小', '小學'} else
             'secondary' if prefix in {'SECONDARY', 'FORM', 'S', 'F', '中', '中學'} else None)
    return Grade(_number(match['number']), stage)
