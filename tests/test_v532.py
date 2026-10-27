"""V5.3.2: the two opened NH3 benchmarks, reduced to one comparable quantity.

Why this exists: loop 5 quoted "the opened benchmarks disagree on the activity
scale by a factor of 2.36", and that sentence is easy to read as "the literature
contradicts itself by a factor".  It is not: a per-pass conversion band and an
outlet mole-fraction figure are different kinds of number, and comparing them
through k_scale passes through the steep part of the rate->outcome curve of a bed
sitting near its own equilibrium pinch.  These tests pin the reduction itself:
what is compared, on what basis, with what tolerance, and that the tolerance is
read from the opened bands in `cases/config.json` instead of being typed twice.

Nothing here invents a number: both objectives are model runs on the model's own
rate law, the bands come from opened sources already recorded in the config, and
the verdict rule is stated in the code before any result (see
`model/converter.py:benchmark_consistency`).
"""
import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results_v2")


@pytest.fixture(scope="session")
def pair():
    """One calibration + one consistency pass, shared by the whole module."""
    from model.config import load_config
    from model.converter import benchmark_consistency, calibrate_k0
    cfg = load_config(product="ammonia")
    cal = calibrate_k0(cfg)
    return cfg, cal, benchmark_consistency(cfg, cal)


def test_the_reduction_runs_and_says_what_it_is(pair):
    cfg, cal, b = pair
    assert b.get("computed") is True
    assert b["objective_a"].startswith("per-pass N2 conversion 17.5 %")
    assert "13.0 mol % NH3" in b["objective_b"]
    # the basis is stated in full, so a reader can check that both figures were
    # asked the same question at the same loop closure
    for part in ("3 beds", "698.15 K", "150 bar", "20 000 h^-1", "H2:N2 = 3",
                 "0.5 mol % NH3"):
        assert part in b["common_basis"], part
    assert "NOT external validation" in b["status_expected"]


def test_both_objectives_land_on_the_same_quantity(pair):
    cfg, cal, b = pair
    lo, hi = cfg.raw["kinetics"]["ammonia_benchmark"]["per_pass_conversion_range"]
    # objective A is matched by construction (it is the calibration target), so
    # the reduction must not move it
    assert b["A_per_pass_pct"] == pytest.approx(
        100.0 * cal["target_per_pass_conversion"], abs=0.05)
    assert b["A_outlet_molpct"] < b["B_outlet_molpct"] == pytest.approx(13.0, abs=0.05)
    assert 100.0 * lo < b["B_per_pass_pct"] and b["B_per_pass_pct"] < 100.0
    # the outlet figure needs MORE activity, hence a bigger per-pass conversion
    assert b["per_pass_gap_pp"] == pytest.approx(b["B_per_pass_pct"]
                                                 - b["A_per_pass_pct"], abs=1e-6)
    assert b["per_pass_gap_pp"] > 0.0


def test_the_two_code_paths_agree_on_the_alternative_objective(pair):
    """`calibrate_k0` used to hand back a `None` stub for the per-pass value the
    outlet objective implies; it must now be the same number the consistency
    analysis computes, otherwise the two reports could diverge."""
    cfg, cal, b = pair
    alt = cal["alternative_objective"]
    assert alt["per_pass_conversion_at_that_factor"] is not None
    assert 100.0 * alt["per_pass_conversion_at_that_factor"] == pytest.approx(
        b["B_per_pass_pct"], abs=1e-9)
    assert b["outlet_figure_implies_per_pass_pct"] == pytest.approx(
        100.0 * alt["per_pass_conversion_at_that_factor"], abs=1e-9)


def test_the_tolerance_is_the_opened_band_read_from_config(pair):
    cfg, cal, b = pair
    B = cfg.raw["kinetics"]["ammonia_benchmark"]
    wide = B["per_pass_conversion_range_wide"]
    assert list(wide) == [0.15, 0.25]
    assert "per_pass_conversion_range_wide" in b["band_source"]
    assert [w for w in b["band_used_for_the_verdict"]] == [
        pytest.approx(w) for w in wide]
    # the rule is stated in words and only depends on the two criteria
    assert "decided BEFORE the run" in b["verdict_rule"]
    assert "50 %" in b["verdict_rule"]
    assert set(b["consistency_criteria_met"]) == {"band", "slope_within_50pct",
                                                 "measured_slope_closeness_pct"}
    assert b["mutually_consistent_on_a_common_basis"] is bool(
        b["inside_wider_opened_band"]
        and b["consistency_criteria_met"]["measured_slope_closeness_pct"] <= 50.0)
    # the narrow Humphreys band is still reported honestly, even when it is missed
    assert b["inside_opened_band"] is (
        100.0 * B["per_pass_conversion_range"][0] <= b["B_per_pass_pct"]
        <= 100.0 * B["per_pass_conversion_range"][1])


def test_the_slope_is_measured_and_used_not_assumed(pair):
    cfg, cal, b = pair
    dec, slope = b["activity_disagreement_decades"], b["sensitivity_per_pass_pp_per_decade"]
    assert dec == pytest.approx(
        __import__("math").log10(b["activity_disagreement_factor"]), rel=1e-9)
    assert slope > 0.0 and b["sensitivity_outlet_molpct_per_decade"] > 0.0
    assert b["per_pass_gap_predicted_from_sensitivity_pp"] == pytest.approx(
        dec * slope, rel=1e-9)
    assert b["sensitivity_explains_gap_pct"] == pytest.approx(
        100.0 * b["per_pass_gap_predicted_from_sensitivity_pp"] / b["per_pass_gap_pp"],
        rel=1e-9)
    # the equilibrium denominator is reported, so the "approach" wording in the
    # notes can be checked against a number
    assert b["A_equilibrium_ceiling_molpct"] > b["A_outlet_molpct"]
    assert b["B_equilibrium_ceiling_molpct"] > b["B_outlet_molpct"]
    assert b["A_approach_to_ceiling_pct"] == pytest.approx(
        100.0 * b["A_outlet_molpct"] / b["A_equilibrium_ceiling_molpct"], rel=1e-9)
    assert 0.0 < b["approach_gap_pp"] < 100.0


def test_the_note_does_not_claim_validation(pair):
    cfg, cal, b = pair
    note = b["note"]
    assert "not self-contradictory" in note or "disagree by a few points" in note
    for forbidden in ("validated against pilot", "confirms the model", "closed"):
        assert forbidden not in note
    assert "docs/32" in note            # the corridor conclusion is kept attached


@pytest.mark.skipif(not os.path.exists(os.path.join(RESULTS, "verification_v2.json")),
                    reason="run model.run_v2 first")
def test_loop5_gains_the_subcheck_and_keeps_the_old_one_failing():
    v = json.load(open(os.path.join(RESULTS, "verification_v2.json"), encoding="utf-8"))
    l5 = v["loops"]["5_validation_falsification"]
    subs = {s["check"]: s for s in l5["subchecks"]}
    assert l5["passed"] is False, "loop 5 must stay FAILED while validation is open"
    assert l5["subchecks_total"] == len(l5["subchecks"])
    old = [c for c in subs if "mutually consistent" in c][0]
    new = [c for c in subs if "once BOTH are reduced to" in c][0]
    assert subs[old]["passed"] is False          # the activity ratio stays > 1.5
    assert subs[new]["passed"] is True           # the reduction closes the wording
    assert "MODEL-INTERNAL" in subs[new]["note"]
    assert "closes no item of docs/28" in subs[new]["note"]
    # and the wider band is quoted from the config in the subcheck NAME (C101)
    assert [c for c in subs if "design point inside the wider opened" in c][0].endswith(
        "15-25% band")


@pytest.mark.skipif(not os.path.exists(os.path.join(RESULTS, "converter_ammonia.json")),
                    reason="run model.run_v2 first")
def test_the_artifact_carries_the_block(pair):
    cfg, cal, b = pair
    cv = json.load(open(os.path.join(RESULTS, "converter_ammonia.json"),
                        encoding="utf-8"))
    art = cv["benchmark_consistency"]
    assert art["computed"] is True
    assert art["B_per_pass_pct"] == pytest.approx(b["B_per_pass_pct"], rel=1e-9)
    assert cv["calibration"]["alternative_objective"][
        "per_pass_conversion_at_that_factor"] is not None


@pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, "docs",
                                                    "26_v5_converter.md")),
                    reason="docs are generated by model.run_v2")
def test_docs26_section_is_written_with_the_table_and_honest_heading():
    txt = open(os.path.join(ROOT, "docs", "26_v5_converter.md"), encoding="utf-8").read()
    head, rest = txt.split("## 26.7", 1)
    body, rest2 = rest.split("## 26.8", 1)
    assert "Согласованность двух открытых ориентиров" in body[:120]
    assert "| A: per-pass" in body and "| B: converter outlet" in body
    assert "Правило вердикта зафиксировано" in body
    assert "не валидирует модель" in body
    assert "## 26.9 Следующий шаг" in rest2
    assert "26.7" in rest2                      # the next-step text points back
    assert not re.search(r"[\u3000-\u9fff\uff01-\uff5e]", body)
    for token in ("undefined", "None", "nan"):
        assert token not in body, token
