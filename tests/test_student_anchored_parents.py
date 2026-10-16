import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from study2.common import PipelineError
from study2.matching import select_waves
from study2.parent_waves import POLICY, LEGACY_POLICY, hk_day
from study2.respondents import adult_followups
from study2.store import connect, current
from study2 import dyads
from test_identity_and_time import rec
from test_pipeline_integration import execute, project


def parent(sid, day, **kw):
    r = rec(sid, day, "parent", **kw)
    r["answer"].update(adult_demographics_05=1980, contact_02="62345678")
    return r


def select(rows, policy=POLICY):
    return select_waves(rows, {r["submission_id"]: "child" for r in rows},
                        parent_requires_same_adult=True, parent_wave_policy=policy)[0]


def test_student_dates_segment_all_parent_labels_and_cancel_parent_90_days():
    rows = [rec("s0"), rec("s1", 90), parent("past", -1), parent("p0", 86),
            parent("p1", 90, claimed_wave="T0")]
    select(rows, LEGACY_POLICY)
    assert [r["selected_wave"] for r in rows] == ["T0", "T1", None, "T0", "T1"]
    assert rows[2]["parent_phase"] == "historical"
    assert rows[4]["parent_response_interval_days"] == 4
    assert all(r["status"] != "short_repeat" for r in rows)
    assert rows[4]["claimed_wave"] == "T0"
    pairs, _, _ = adult_followups(rows, [], parent_wave_policy=POLICY)
    assert [(r["t0"], r["t1"]) for r in pairs] == [("p0", "p1")]


def test_hong_kong_day_accepts_earlier_clock_time_but_not_previous_day():
    rows = [rec("s", observed_at="2026-01-01T01:00:00+00:00"),
            parent("same", 0, observed_at="2025-12-31T17:00:00+00:00"),
            parent("before", 0, observed_at="2025-12-31T15:59:59+00:00")]
    select(rows, LEGACY_POLICY)
    assert rows[1]["selected_wave"] == "T0" and rows[1]["student_parent_calendar_gap_days"] == 0
    assert rows[2]["parent_phase"] == "historical"
    assert hk_day(rows[1]["observed_at"]).isoformat() == "2026-01-01"


def test_original_T1_is_not_consumed_as_T0_and_parent_T1_can_exist_without_baseline():
    rows = [rec("s0"), rec("s1", 90), parent("old", -20), parent("p1", 90, claimed_wave="T1")]
    select(rows, LEGACY_POLICY)
    assert rows[-1]["selected_wave"] == "T1"
    assert not any(r["role"] == "parent" and r["selected_wave"] == "T0" for r in rows)
    assert not adult_followups(rows, [], parent_wave_policy=POLICY)[0]


def test_no_student_T1_allows_uncapped_nearest_parent_T0():
    rows = [rec("s0"), parent("later", 500, claimed_wave="T1"), parent("latest", 800)]
    select(rows)
    assert rows[1]["selected_wave"] == "T0" and rows[2]["selected_wave"] is None
    assert rows[1]["student_parent_calendar_gap_days"] == 500


def test_parent_only_is_retained_unanchored_not_inferred_T0():
    r = parent("p", 0, claimed_wave="T1")
    select([r])
    assert r["selected_wave"] is None and r["status"] == "eligible"
    assert r["wave_reason"] == "parent_no_reliable_student_baseline"


def test_unreliable_parent_date_holds_parents_without_discarding_student_AC():
    rows = [rec("s0"), rec("s1", 90), parent("p0", 0), parent("p1", 90, time_confidence="batch_only")]
    select(rows)
    assert [r["selected_wave"] for r in rows] == ["T0", "T1", None, None]


def test_parent_timestamp_tie_only_holds_the_affected_phase():
    rows = [rec("s0"), rec("s1", 90), parent("p0", 0), parent("p1", 90), parent("p2", 90)]
    select(rows)
    assert rows[2]["selected_wave"] == "T0"
    assert rows[3]["selected_wave"] is rows[4]["selected_wave"] is None


@pytest.mark.parametrize("gap,duplicate", [(29, True), (30, False)])
def test_parent_repeat_boundary_within_T1_phase(gap, duplicate):
    rows = [rec("s0"), rec("s1", 90), parent("p0", 0), parent("p1", 100), parent("p2", 100 + gap)]
    select(rows)
    assert rows[-1]["selected_wave"] == "T1"
    assert (rows[-2]["status"] == "short_repeat") == duplicate


def test_order_independence_and_adult_replacement_retains_BD_alternative():
    rows = [rec("s0"), rec("s1", 90), parent("p0", 70), parent("mother", 90), parent("father", 95)]
    rows[-1]["answer"].update(adult_demographics_05=1978, contact_02="63456789")
    reversed_rows = copy.deepcopy(rows[::-1])
    select(rows); select(reversed_rows)
    assert {r["submission_id"]: (r["selected_wave"], r["status"]) for r in rows} == {
        r["submission_id"]: (r["selected_wave"], r["status"]) for r in reversed_rows}
    assert rows[-1]["selected_wave"] == "T1"
    assert adult_followups(rows, [], parent_wave_policy=POLICY)[0][0]["t1"] == "mother"


def test_invalid_policy_cannot_silently_fall_back():
    with pytest.raises(PipelineError, match="Unsupported parent wave policy"):
        select_waves([rec("s")], {"s": "child"}, parent_wave_policy="unknown")


def test_unknown_adults_cannot_deduplicate_each_other_and_nonmatch_still_blocks_BD():
    from study2.respondents import adult_evidence
    rows = [rec('s0'), rec('s1',90), parent('p0',80), parent('p1',90), parent('p2',91)]
    rows[-1]['answer']['adult_demographics_05'] = ''
    select(rows)
    assert rows[-2]['status'] != 'short_repeat'
    decision = {'decision_id':'manual','payload':{'action':'UNLINK_ADULT','record_a':'p0','record_b':'p1',
                'evidence_a':adult_evidence(rows[2]),'evidence_b':adult_evidence(rows[3])}}
    assert adult_followups(rows,[decision],parent_wave_policy=POLICY)[0] == []


def test_old_review_rules_are_not_carried_across_parent_wave_policy(project):
    from study2.review_core import rules_hash
    cfg = project[0]
    old = rules_hash(cfg)
    cfg['parent_wave_policy'] = POLICY
    assert rules_hash(cfg) != old


def test_outputs_reconcile_T1_only_family_and_preserve_student_count(project):
    cfg, _, rows, _ = project
    cfg.update(parent_wave_policy=LEGACY_POLICY, bd_requires_same_adult=True)
    rows[2]["observed_at"] = rec("old", -1)["observed_at"]
    for r in rows[2:]:
        r["answer"].update(adult_demographics_05=1980, contact_02="62345678")
    result = execute(project)
    assert {k: result[k] for k in ["A", "B", "C", "D", "AC", "BD", "E", "F", "EF"]} == {
        "A": 1, "B": 0, "C": 1, "D": 1, "AC": 1, "BD": 0, "E": 0, "F": 1, "EF": 0}
    folder = Path(cfg["release_dir"]) / result["release_id"]
    audit = pd.read_parquet(folder / "parent_wave_audit.parquet")
    assert set(audit["parent_phase"]) == {"historical", "T1"}
    assert len(pd.read_parquet(folder / "analysis.parquet")) == 3


def test_permanent_id_survives_loss_of_parent_baseline_under_new_measurement_policy(project):
    cfg, _, rows, _ = project
    rows[2]["observed_at"] = rec("old", -1)["observed_at"]
    first = execute(project)
    db = connect(Path(cfg["state_dir"])); reg = dict(db.execute("SELECT * FROM dyad_registry").fetchone()); db.close()
    cfg.update(parent_wave_policy=LEGACY_POLICY, bd_requires_same_adult=True)
    after = execute(project, force=True)
    db = connect(Path(cfg["state_dir"]))
    mapping = dyads.staged_rows(db, after["release_id"])[0]
    assert after["E"] == 0 and after["F"] == 1
    assert mapping["dyad_id"] == reg["dyad_id"] and mapping["registration_state"] == "active"
    assert mapping["analysis_t0_pair_available"] is False
    assert dict(db.execute("SELECT * FROM dyad_registry").fetchone()) == reg
    assert not mapping["parent_t0_id"]
    db.close()


def test_nearest_baseline_can_be_before_student_and_is_not_the_earliest_parent():
    rows = [rec('s0'), rec('s1',120), parent('old',-500), parent('near',-2), parent('later',40), parent('p1',120)]
    select(rows)
    assert rows[2]['selected_wave'] is None and rows[3]['selected_wave']=='T0'
    assert rows[3]['student_parent_calendar_gap_days']==-2
    assert rows[3]['student_parent_elapsed_gap_days']==-2
    assert rows[-1]['selected_wave']=='T1'


def test_nearest_before_or_after_uses_elapsed_time_not_source_order():
    rows = [rec('s0'), parent('before',-4), parent('after',1)]
    other = copy.deepcopy(rows[::-1])
    select(rows);select(other)
    assert rows[2]['selected_wave']=='T0'
    assert {r['submission_id']:r['selected_wave'] for r in rows}=={r['submission_id']:r['selected_wave'] for r in other}


def test_nearest_within_same_hk_day_preserves_closest_instead_of_earliest():
    rows = [rec('s',observed_at='2026-01-01T04:00:00+00:00'),
            parent('early',0,observed_at='2026-01-01T00:00:00+00:00'),
            parent('near',0,observed_at='2026-01-01T03:59:00+00:00')]
    select(rows)
    assert rows[-1]['selected_wave']=='T0'
    assert rows[1]['status']=='short_repeat' and rows[1]['duplicate_of']=='near'
    assert rows[-1]['student_parent_calendar_gap_days']==0
    assert rows[-1]['student_parent_elapsed_gap_days']<0


def test_early_only_parent_is_allowed_without_a_hard_limit():
    rows=[rec('s'),parent('p',-900)]
    select(rows)
    assert rows[-1]['selected_wave']=='T0' and rows[-1]['student_parent_calendar_gap_days']==-900


def test_T1_reservation_precedes_nearest_baseline_even_when_T1_is_closer():
    rows=[rec('s0'),rec('s1',90),parent('p0',-200),parent('p1',90,claimed_wave='T1')]
    select(rows)
    assert rows[2]['selected_wave']=='T0' and rows[3]['selected_wave']=='T1'


def test_raw_T0_after_student_T1_keeps_the_previously_approved_T1_rule():
    rows=[rec('s0'),rec('s1',90),parent('p1',91,claimed_wave='T0')]
    select(rows)
    assert rows[-1]['selected_wave']=='T1' and rows[-1]['claimed_wave']=='T0'


def test_equally_close_opposite_sides_needs_review_without_discarding_T1():
    rows=[rec('s0'),rec('s1',90),parent('before',-10),parent('after',10),parent('p1',90)]
    result,cases=select_waves(rows,{r['submission_id']:'child' for r in rows},parent_wave_policy=POLICY)
    assert rows[2]['selected_wave'] is rows[3]['selected_wave'] is None
    assert rows[-1]['selected_wave']=='T1'
    assert any(c['rule']=='ambiguous_parent_baseline_distance' for c in cases)


def test_nearest_baseline_survives_short_repeats_on_both_sides():
    rows=[rec('s'),parent('early',-4),parent('near',-2),parent('later',5)]
    select(rows)
    assert rows[2]['selected_wave']=='T0'
    assert rows[1]['duplicate_of']==rows[3]['duplicate_of']=='near'


def test_v2_restores_baseline_and_reuses_registered_id(project):
    cfg,_,rows,_=project
    rows[2]['observed_at']=rec('earlier',-1)['observed_at']
    first=execute(project)
    db=connect(Path(cfg['state_dir']));reg=dict(db.execute('SELECT * FROM dyad_registry').fetchone());db.close()
    cfg.update(parent_wave_policy=LEGACY_POLICY,bd_requires_same_adult=True)
    assert execute(project,force=True)['E']==0
    cfg['parent_wave_policy']=POLICY
    result=execute(project,force=True)
    assert result['E']==result['F']==result['EF']==1
    db=connect(Path(cfg['state_dir']));mapping=dyads.staged_rows(db,result['release_id'])[0]
    assert mapping['dyad_id']==reg['dyad_id'] and dict(db.execute('SELECT * FROM dyad_registry').fetchone())==reg
    db.close()
    frame=pd.read_parquet(Path(cfg['release_dir'])/result['release_id']/'parent_wave_audit.parquet')
    assert frame.loc[frame.submission_id.eq('p0'),'student_parent_calendar_gap_days'].iloc[0]==-1
