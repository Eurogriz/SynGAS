"""V5.2 tests: the catalyst-activity corridor through the ammonia case.

The point of V5.2 is that the x2.36 disagreement between the two opened
benchmarks (mid-band per-pass conversion vs 13 mol% outlet NH3) must stop being
a footnote about k0 and become a corridor on the quantities that are actually
reported: catalyst volume, peak temperature, duty, recycle, tonnage, money.

These tests therefore check three things, in this order:
  * the corridor is ANCHORED - its low edge reproduces the as-built design
    numbers from `results_v2/converter_ammonia.json` (same model, not a twin);
  * the corridor is INTERNALLY SOUND - volume bisection converged, monotone in
    activity, loop closure >= 1 at every activity, no NaN, money recomputes
    from the published config constants rather than being quoted;
  * the corridor is NOT OVERSOLD - the peak-temperature insensitivity is a
    statement about the equilibrium pinch, the density/price are placeholders,
    and the artifact must say so; loop 5 stays failed with it included.

Everything but one test reads the saved artifact (fast); the single live test
re-runs two activities of the march so the artifact cannot silently drift away
from the model that produced it.
"""
import json
import math
import os

import pytest

from model.activity_uncertainty import RHO_CAT, _design_feed, _run
from model.config import load_config
from model.verify_v2 import _activity_band_ok

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results_v2")


def _load(name):
    path = os.path.join(RESULTS, name)
    if not os.path.exists(path):
        pytest.skip("%s not written yet (run: python -m model.run_v2)" % name)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def ab():
    return _load("activity_uncertainty.json")


@pytest.fixture(scope="module")
def conv():
    return _load("converter_ammonia.json")


# ----------------------------------------------------------------- anchoring ---
def test_band_edges_are_the_published_k0_band(ab, conv):
    band, cal = ab["activity_band"], conv["calibration"]
    assert abs(band["k_scale_lo"] - cal["uncertainty_on_k0_band"][0]) < 1e-9
    assert abs(band["k_scale_hi"] - cal["uncertainty_on_k0_band"][1]) < 1e-9
    assert abs(band["factor"] - band["k_scale_hi"] / band["k_scale_lo"]) < 1e-9
    assert 2.0 < band["factor"] < 3.0
    assert ab["design_reference"]["k_scale"] == pytest.approx(cal["k_scale"],
                                                              abs=1e-9)


def test_grid_is_geometric_and_spans_the_edges(ab):
    ks = [r["k_scale"] for r in ab["rows"]]
    ratios = [b / a for a, b in zip(ks, ks[1:])]
    assert max(ratios) - min(ratios) < 1e-9
    assert len(ks) == 5
    assert ks[0] == pytest.approx(ab["activity_band"]["k_scale_lo"], rel=1e-6)
    assert ks[-1] == pytest.approx(ab["activity_band"]["k_scale_hi"], rel=1e-6)
    # labels are Russian on purpose (docs/32 and the panel print them verbatim)
    assert "нижний край" in ab["rows"][0]["position_in_band"]
    assert "верхний край" in ab["rows"][-1]["position_in_band"]


def test_low_edge_reproduces_the_as_built_design(ab, conv):
    """The corridor must sit on the real design point, not on a variant of it."""
    d, row, dr = conv["design"], ab["rows"][0], ab["design_reference"]
    f = row["at_fixed_geometry"]
    assert f["per_pass_N2_pct"] == pytest.approx(100.0 * d["per_pass_N2_conversion"],
                                                 abs=1e-6)
    assert f["outlet_NH3_molpct"] == pytest.approx(d["outlet_NH3_molpct"], abs=1e-6)
    assert f["T_peak_K"] == pytest.approx(d["T_peak_K"], abs=1e-6)
    assert f["interbed_cooling_duty_MW"] == pytest.approx(
        d["interbed_cooling_duty_MW"], abs=1e-6)
    assert dr["catalyst_volume_m3"] == pytest.approx(d["catalyst_volume_m3"],
                                                    abs=1e-6)
    assert dr["GHSV_normal_h1"] == pytest.approx(d["GHSV_normal_h1"], rel=1e-9)
    assert dr["p_bar"] == pytest.approx(d["p_bar"], rel=1e-9)


# ------------------------------------------------------------ internal soundness ---
def test_every_row_converged_and_volume_solver_is_tight(ab):
    for r in ab["rows"]:
        v = r["volume_to_hold_design_conversion"]
        assert v["converged"] is True, r["k_scale"]
        assert v["X_error_abs"] < 1e-4, (r["k_scale"], v["X_error_abs"])
        assert v["iterations"] >= 3
        for key in ("V_m3", "catalyst_mass_t", "GHSV_normal_h1",
                    "vessel_scale_factor_capex_exponent_0p7"):
            assert v[key] is not None and math.isfinite(v[key]), key


def test_required_volume_is_monotone_and_brackets_the_design(ab, conv):
    V = [r["volume_to_hold_design_conversion"]["V_m3"] for r in ab["rows"]]
    assert all(b < a for a, b in zip(V, V[1:]))
    V_ref = conv["design"]["catalyst_volume_m3"]
    assert abs(V[0] - V_ref) / V_ref < 0.02          # bisection grid resolution
    assert V[-1] < 0.5 * V_ref                       # high activity: half the bed
    assert V[0] == pytest.approx(max(V), rel=1e-9)   # design = conservative bound


def test_conversion_is_monotone_up_and_outlet_follows(ab):
    X = [r["at_fixed_geometry"]["per_pass_N2_pct"] for r in ab["rows"]]
    O = [r["at_fixed_geometry"]["outlet_NH3_molpct"] for r in ab["rows"]]
    assert all(b > a for a, b in zip(X, X[1:]))
    assert all(b > a for a, b in zip(O, O[1:]))
    assert X[-1] - X[0] > 4.0                        # percentage points, not noise
    assert O[-1] > O[0] + 2.5


def test_peak_temperature_is_activity_insensitive_but_ceiling_still_exceeded(ab):
    """A finding, asserted so it cannot be quietly lost: at fixed inlet T the
    peak is set by the equilibrium pinch, so the ceiling violation is NOT
    evidence about catalyst activity in either direction."""
    sp = ab["spans"]["T_peak_K"]
    assert sp[1] - sp[0] < 0.5
    assert all(r["at_fixed_geometry"]["peak_over_assumed_ceiling_K"] > 0
               for r in ab["rows"])
    assert ab["design_reference"]["assumed_bed_ceiling_K"] < sp[0]


def test_loop_closes_at_every_activity_and_tonnage_is_not_activity_limited(ab):
    """The corridor must not be smuggled into a production claim: at fixed fresh
    feed the saleable tonnage is set by the loop, only the recycle ratio needed
    to close it moves with activity."""
    cl = [r["at_fixed_geometry"]["loop_closure_X_times_1pRR"] for r in ab["rows"]]
    assert all(c >= 1.0 for c in cl)                 # configured recycle suffices
    assert cl[-1] > cl[0]                            # ... and gets more oversized
    d = _load("design_ammonia.json")
    prod = ab["production_is_not_activity_limited"]
    assert prod["NH3_design_t_h"] == pytest.approx(d["synthesis"]["NH3_t_h"],
                                                  rel=1e-12)
    gross = [r["at_fixed_geometry"]["NH3_formed_t_h"] for r in ab["rows"]]
    assert all(b > a for a, b in zip(gross, gross[1:]))   # converter gross output
    assert min(gross) > prod["NH3_design_t_h"]            # ... exceeds loop demand
    assert max(gross) < 1.30 * min(gross)
    rr = [r["at_fixed_geometry"]["recycle_ratio_implied"] for r in ab["rows"]]
    assert all(b < a for a, b in zip(rr, rr[1:]))
    assert rr[0] <= ab["design_reference"]["recycle_ratio_configured"] + 0.05
    assert "closure ABOVE 1.0" in prod["argument"] or "not more" in prod["argument"]


def test_ceiling_remedy_and_its_cost(ab):
    c = [r["ceiling_remedy"] for r in ab["rows"]]
    assert all(x["feasible"] is True for x in c)
    T = [x["T_in_common_K"] for x in c]
    assert all(b < a for a, b in zip(T, T[1:]))      # more active -> cooler inlet
    assert max(x["T_peak_K"] for x in c) <= ab["design_reference"]["assumed_bed_ceiling_K"] + 1.0
    assert c[0]["outlet_NH3_molpct"] < 13.0 < c[-1]["outlet_NH3_molpct"]


def test_money_recomputes_from_the_published_constants(ab):
    cfg = load_config()
    from model.economics import PRICES
    price = PRICES["catalyst_USD_per_kg"]
    for r in ab["rows"]:
        v = r["volume_to_hold_design_conversion"]
        assert v["catalyst_mass_t"] == pytest.approx(v["V_m3"] * RHO_CAT / 1000.0,
                                                      rel=1e-3)
        assert v["inventory_cost_USD"] == pytest.approx(
            v["V_m3"] * RHO_CAT * price, rel=5e-3)   # rounded to USD 1000
        assert v["vessel_scale_factor_capex_exponent_0p7"] == pytest.approx(
            (v["V_m3"] / ab["design_reference"]["catalyst_volume_m3"])
            ** cfg.raw["economics"]["CAPEX_scale_exponent"], rel=1e-3)
    inv = ab["money"]["catalyst_inventory_corridor_USD"]
    d_inv = abs(inv[1] - inv[0])
    d_opex = max(x["delta_cost_USD_y"]
                 for x in ab["money"]["recycle_compressor"]["power_by_loop_dP"])
    assert d_opex < 0.05 * d_inv                     # CAPEX question, not OPEX
    assert ab["money"]["price_used"] == price


def test_placeholders_are_flagged_not_hidden(ab):
    mo = ab["money"]
    assert mo["density_used_kg_m3"] == RHO_CAT
    assert mo["density_status"].startswith("[ЧАСТИЧНО]")
    assert "[ДОПУЩЕНИЕ]" in mo["price_status"]
    assert "docs/28" in mo["density_status"]
    assert "NOT plant validation" in ab["how_to_use"]
    assert len(ab["not_covered"]) >= 4


def test_live_recomputation_matches_the_artifact(ab):
    """The upper edge of the corridor, re-marched here, must reproduce the saved
    row - the artifact may not drift away from the code that wrote it."""
    d = _load("design_ammonia.json")
    feed = _design_feed(d, load_config(product="ammonia"))
    row = ab["rows"][-1]
    out = _run(feed, row["k_scale"])
    assert 100.0 * out["per_pass_N2_conversion"] == pytest.approx(
        row["at_fixed_geometry"]["per_pass_N2_pct"], abs=1e-6)
    assert out["outlet_NH3_molpct"] == pytest.approx(
        row["at_fixed_geometry"]["outlet_NH3_molpct"], abs=1e-6)
    assert out["catalyst_volume_m3"] == pytest.approx(
        ab["design_reference"]["catalyst_volume_m3"], rel=1e-9)


def test_loop4_check_passes_and_loop5_stays_open():
    ok, info = _activity_band_ok()
    assert ok is True, info
    assert "INTERNAL CONSISTENCY ONLY" in info
    v = _load("verification_v2.json")
    extras = v["loops"]["4_thermo"]["extra_checks_passed"]
    assert extras.get("NH3_activity_band") is True
    assert v["loops"]["5_validation_falsification"]["passed"] is False


def test_docs32_matches_the_artifact(ab):
    path = os.path.join(ROOT, "docs", "32_v5_activity_band.md")
    if not os.path.exists(path):
        pytest.skip("docs/32_v5_activity_band.md not generated yet")
    txt = open(path, encoding="utf-8").read()
    assert "2.362" in txt
    assert "%.2f" % ab["spans"]["T_peak_K"][0] in txt
    assert "%.2f" % ab["spans"]["T_peak_K"][1] in txt
    for r in ab["rows"]:
        assert "%.4f" % r["k_scale"] in txt
    assert "не является заводской валидацией" in txt or "NOT plant validation" in txt


def test_claims_registered_for_the_corridor():
    d = _load_claims()
    by = {c["id"]: c for c in d["claims"]}
    for cid in ("C82", "C83", "C84", "C85", "C86", "C87", "C88", "C89", "C90"):
        assert cid in by, cid
        c = by[cid]
        assert set(c) == {"id", "name", "value", "unit", "source", "url",
                          "status", "used_in_result"}
        assert c["status"] in d["meta"]["allowed_status"]
        assert c["source"] and c["url"]
    # the caveat claim is an open item, not an input -> must not be used
    assert by["C90"]["used_in_result"] is False
    assert by["C90"]["status"] == "[НЕ ПОДТВЕРЖДЕНО]"
    assert by["C88"]["status"] == "[ДОПУЩЕНИЕ]"


def _load_claims():
    with open(os.path.join(ROOT, "data", "v2_claims.json"), encoding="utf-8") as fh:
        return json.load(fh)
