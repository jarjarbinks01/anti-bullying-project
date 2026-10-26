"""Separate explicit stage annotations from a researcher-provided school name."""
import re


class SchoolAnswerAmbiguous(ValueError):
    pass


def separate_stage(value):
    if not isinstance(value, str) or not value.strip():
        raise SchoolAnswerAmbiguous('school_answer_not_nonempty_text')
    name = value.strip()
    annotations = []
    stages = []
    prefix = re.fullmatch(r'(Primary\s+School|Secondary\s+School)\s*[:：]\s*(.+)', name, flags=re.I | re.S)
    if prefix:
        stages.append('primary' if prefix[1].casefold().startswith('primary') else 'secondary')
        annotations.append(dict(position='prefix', literal=prefix[1]))
        name = prefix[2].strip()
    suffix = re.fullmatch(r'(.+?)\s*[,，]\s*(primary|secondary)', name, flags=re.I | re.S)
    if suffix:
        stages.append(suffix[2].casefold())
        annotations.append(dict(position='suffix', literal=suffix[2]))
        name = suffix[1].strip()
    if len(set(stages)) > 1:
        raise SchoolAnswerAmbiguous('explicit_stage_annotations_conflict')
    if not name:
        raise SchoolAnswerAmbiguous('school_name_missing_after_annotation')
    return dict(school_name=name, stage_annotation=stages[0] if stages else None,
                removed_annotations=annotations)
