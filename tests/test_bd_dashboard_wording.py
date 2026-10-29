"""The displayed BD rule must follow the published policy, including history."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'dashboard.py'
POLICY = 'selected_parent_waves_same_child_v1'


def render(nodes, **context):
    messages = []
    st = SimpleNamespace(caption=messages.append, markdown=messages.append)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), {'st': st, **context})
    return '\n'.join(messages)


def bd_detail(summary):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    node = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                and ast.unparse(node.test) == "sample == 'BD'")
    return render([node], sample='BD', summary=summary)


def methods(summary, nearest):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    section = next(node for node in ast.walk(tree) if isinstance(node, ast.With) and
                   any(isinstance(item.context_expr, ast.Name) and item.context_expr.id == 'method'
                       for item in node.items))
    return render(section.body, summary=summary, student_anchored=True, nearest_parent_baseline=nearest)


@pytest.mark.parametrize('nearest', [False, True])
def test_selected_bd_explanations_keep_child_and_adult_evidence_distinct(nearest):
    summary = dict(bd_pairing_policy=POLICY, bd_requires_same_adult=False)
    detail, method = bd_detail(summary), methods(summary, nearest)
    assert '已選定的B' in detail and 'D（家長T1）' in detail and '成人可以不同' in detail
    assert '不會另選T1' in detail and 'T1可與D／F' not in detail
    assert '已選定的 B' in method and '不是BD入選條件' in method
    assert '家長PHQ描述各輪填卷成人' in method and 'BD仍須同一成人' not in method
    assert '重填' in method


@pytest.mark.parametrize('nearest', [False, True])
def test_historical_same_adult_description_remains_available(nearest):
    summary = dict(bd_requires_same_adult=True)
    assert '同一成人選擇' in bd_detail(summary)
    assert 'T1可與D／F' in bd_detail(summary)
    assert 'BD仍須同一成人' in methods(summary, nearest)


def test_unknown_policy_does_not_guess_a_same_adult_rule():
    summary = dict(bd_pairing_policy='unrecognised', bd_requires_same_adult=True)
    assert '同一成人選擇' not in bd_detail(summary)
    assert '未提供可識別的BD配對政策' in methods(summary, True)
