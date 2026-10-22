"""English-only presentation adapter for the local research dashboard.

Internal option values, widget keys, callbacks, data and download payloads retain
exactly their original values. Only copies sent to Streamlit are translated.
This is an explicit adapter, not a monkey-patch of Streamlit or research modules.
"""
from __future__ import annotations

import re
from functools import lru_cache

import streamlit

from .dashboard_english_catalog import TEXT

# Longest-first replacement handles dynamic captions assembled from literals.
# CJK boundaries prevent replacing short labels inside school names or raw prose.
_PHRASES = TEXT
_PATTERN = re.compile('|'.join((r'(?<![\u3400-\u9fff])' if '\u3400' <= k[0] <= '\u9fff' else '') + re.escape(k) + (r'(?![\u3400-\u9fff])' if '\u3400' <= k[-1] <= '\u9fff' else '') for k in sorted(_PHRASES, key=len, reverse=True)))
_CJK = re.compile('[\u3400-\u9fff]')


@lru_cache(maxsize=8192)
def english(value):
    """Translate known display text; unknown source text is preserved."""
    if not isinstance(value, str) or not _CJK.search(value):
        return value
    if value.startswith('學校：'):
        return 'School: ' + value[len('學校：'):]
    if value in TEXT:
        return TEXT[value]
    if value.startswith('下載'):
        return 'Download ' + english(value[2:]).lstrip()
    result = _PATTERN.sub(lambda match: _PHRASES[match[0]], value)
    if result == value:
        return value
    return result.translate(str.maketrans({'：': ': ', '；': '; ', '。': '.',
        '（': ' (', '）': ')', '／': '/', '「': '“', '」': '”', '，': ', '}))


def _source_column(column):
    """Do not translate school names, source filenames, raw answers or notes."""
    name = str(column).lower()
    school = ('school' in name or '學校' in name or '校名' in name)
    derived = any(word in name for word in ('type', 'stage', 'agree', '類型', '階段', '一致'))
    return ((school and not derived) or any(word in name for word in (
        'submission', '提交id', '提交a', '提交b', '孩子id', 'dyad_id',
        'case_id', 'child_id', 'filename', 'file_name', '檔案', 'raw', '原始答案',
        'reason_note', 'reason_text', '理由', '備註', 'actor', '執行者',
        'filters_json', 'email', 'phone', '電話號碼', '電郵地址')))


def display_frame(frame):
    """Return a translated display copy, retaining numbers, IDs and raw fields."""
    import pandas as pd
    if not isinstance(frame, pd.DataFrame):
        return frame
    shown = frame.copy(deep=True)
    for col in frame.columns:
        if not _source_column(col) and (pd.api.types.is_object_dtype(frame[col])
                                      or isinstance(frame[col].dtype, pd.CategoricalDtype)
                                      or pd.api.types.is_string_dtype(frame[col])):
            # Exact catalogue labels only for cells, plus composed generated
            # descriptions in explicitly derived columns. Never infer raw data.
            derived = any(word in str(col).lower() for word in (
                'rule', '規則', 'reason', '原因', '目的', '結果', 'missing', 'variable',
                '指標', 'group_label', '分組', 'review_warning', '提示'))
            convert = english if derived else lambda x: TEXT.get(x, x) if isinstance(x, str) else x
            shown[col] = frame[col].map(lambda x: convert(x) if isinstance(x, str) else x)
    shown.columns = [english(c) if isinstance(c, str) else c for c in frame.columns]
    shown.index = frame.index.copy()
    if isinstance(shown.index.name, str):
        shown.index.name = english(shown.index.name)
    return shown


def display_figure(figure):
    """Translate a Plotly copy without changing numbers, bins or membership."""
    import plotly.graph_objects as go
    import numpy as np
    if not hasattr(figure, 'to_plotly_json'):
        return figure
    def walk(value):
        if isinstance(value, str):
            return english(value)
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [walk(v) for v in value]
        if isinstance(value, np.ndarray) and value.dtype.kind in {'O', 'U', 'S'}:
            return np.array([walk(v) for v in value], dtype=object)
        return value
    return go.Figure(walk(figure.to_plotly_json()))


class EnglishUI:
    """Wrap only rendering calls; all returned selection values stay canonical."""
    _TEXT = {'title', 'header', 'subheader', 'caption', 'markdown', 'text',
             'info', 'warning', 'error', 'success', 'button', 'download_button',
             'checkbox', 'toggle', 'text_input', 'text_area', 'number_input',
             'date_input', 'slider', 'metric', 'expander', 'spinner', 'status'}
    _SELECT = {'selectbox', 'multiselect', 'radio', 'select_slider', 'pills', 'segmented_control'}
    _CONTAINER = {'container', 'expander', 'empty', 'form', 'status'}

    def __init__(self, target):
        self._target = target

    def __enter__(self):
        self._target.__enter__()
        return self

    def __exit__(self, *args):
        return self._target.__exit__(*args)

    def __getattr__(self, name):
        target = getattr(self._target, name)
        if name == 'sidebar':
            return EnglishUI(target)
        handled = self._TEXT | self._SELECT | self._CONTAINER | {
            'columns', 'tabs', 'dataframe', 'table', 'plotly_chart', 'write', 'set_page_config'}
        if name not in handled:
            return target

        def render(*args, **kwargs):
            args = list(args)
            if name in self._TEXT | self._SELECT:
                if args and isinstance(args[0], str):
                    args[0] = english(args[0])
                for key in ('label', 'body', 'help', 'placeholder'):
                    if isinstance(kwargs.get(key), str):
                        kwargs[key] = english(kwargs[key])
            if name in self._SELECT:
                # Preserve actual option objects and caller-provided formatting.
                formatter = kwargs.get('format_func', str)
                label = args[0] if args else kwargs.get('label', '')
                school_names = label in {'School', 'Independent sample school'}
                kwargs['format_func'] = (formatter if school_names else
                    lambda option: english(formatter(option)))
            if name == 'metric':
                if len(args) > 1 and isinstance(args[1], str):
                    args[1] = english(args[1])
                for key in ('value', 'delta'):
                    if isinstance(kwargs.get(key), str):
                        kwargs[key] = english(kwargs[key])
            if name == 'tabs':
                if args:
                    args[0] = [english(x) for x in args[0]]
                elif 'tabs' in kwargs:
                    kwargs['tabs'] = [english(x) for x in kwargs['tabs']]
            if name == 'set_page_config' and 'page_title' in kwargs:
                kwargs['page_title'] = english(kwargs['page_title'])
            if name in {'dataframe', 'table'}:
                def convert(value):
                    from pandas.io.formats.style import Styler
                    # Current dashboard uses Styler only to hide the stage-table
                    # index. Recreate the same style over a translated copy.
                    if isinstance(value, Styler):
                        return display_frame(value.data).style.hide(axis='index')
                    return display_frame(value)
                if args:
                    args[0] = convert(args[0])
                elif 'data' in kwargs:
                    kwargs['data'] = convert(kwargs['data'])
            if name == 'plotly_chart':
                if args:
                    args[0] = display_figure(args[0])
                elif 'figure_or_data' in kwargs:
                    kwargs['figure_or_data'] = display_figure(kwargs['figure_or_data'])
            if name == 'write':
                args = [english(x) if isinstance(x, str) else x for x in args]
            result = target(*args, **kwargs)
            if name in {'columns', 'tabs'}:
                return [EnglishUI(item) for item in result]
            if name in self._CONTAINER:
                return EnglishUI(result)
            return result
        return render


st = EnglishUI(streamlit)
