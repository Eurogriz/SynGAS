"""V5 tests: NH3 thermo block, multi-bed adiabatic converter, k0 calibration,
pilot data contract and ingest harness, HAZOP template-artefact fix.

The tests are deliberately strict about the two things that matter in this
version: (a) no fitted parameter may hide inside a constant, and (b) the
ingest harness must REFUSE data that the model cannot interpret.
"""
import json, math, os

import pytest

from model.config import load_config
from model.converter import (ammonia_Ka, calibrate_k0, equilibrium_cross_check,
                             equilibrium_NH3, h_spec, reactor_inlet_flows,
                             recommend_bed_inlet_T, run_ammonia_converter,
                             validate_against_opened_benchmark)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- thermo ---
def test_nh3_shomate_added_without_touching_equilibrium_species():
    """NH3 must exist for the converter energy balance and must NOT enter the
    Gibbs species list (that would shift indices and every v1 regression)."""
    from model.thermo import SPECIES
    assert "NH3" not in SPECIES
    assert abs(h_spec("NH3", 298.15) - (-45.90)) < 0.05      # NIST/CODATA
    # sensible heat rises with T (positive cp); the REACTION enthalpy below does
    assert h_spec("NH3", 698.15) > h_spec("NH3", 298.15) + 4.0
    dH698 = (2 * h_spec("NH3", 698.15) - h_spec("N2", 698.15)
             - 3 * h_spec("H2", 698.15)) / 2.0
    assert dH698 < -50.0          # bigger than -45.9: the point of V5's fix


def test_equilibrium_constant_cross_check_against_nist_gibbs():
    chk = equilibrium_cross_check()
    assert len(chk["rows"]) == 6
    assert chk["passed_within_15pct"] is True
    assert chk["max_abs_deviation_pct"] < 15.0
    # Ka must decrease with T for an exothermic reaction
    assert ammonia_Ka(650.0) > ammonia_Ka(800.0)


# ------------------------------------------------------------ converter ----
def _bench_feed():
    return reactor_inlet_flows(25.0, 75.0, 0.3, 3.0, 0.5)[0]


def test_adiabatic_bed_heats_up_and_energy_balance_closes():
    r = run_ammonia_converter(_bench_feed(), 150.0, 20000.0, n_beds=1,
                              T_in_first=698.15, n_steps=200)
    assert r["T_bed_out_K"][0] > 698.15                    # exothermic, no cooling
    assert r["per_pass_N2_conversion"] > 0.05
    assert r["energy_balance_max_rel_residual"] < 1e-9
    assert r["dH_rxn_kJ_per_mol_NH3_at_bed_T"] < -45.9     # not the 298 K value


def test_single_bed_is_space_velocity_insensitive_at_the_equilibrium_pinch():
    """Physics, not a bug: one adiabatic bed runs into its own equilibrium
    locus, so doubling the catalyst volume cannot change the outcome."""
    a = run_ammonia_converter(_bench_feed(), 150.0, 10000.0, n_beds=1,
                              T_in_first=698.15, n_steps=200)
    b = run_ammonia_converter(_bench_feed(), 150.0, 30000.0, n_beds=1,
                              T_in_first=698.15, n_steps=200)
    assert abs(a["per_pass_N2_conversion"] - b["per_pass_N2_conversion"]) < 0.005
    # ... while multi-bed operation WITH interbed cooling does depend on it
    c = run_ammonia_converter(_bench_feed(), 150.0, 10000.0, n_beds=3,
                              T_in_bed=[698.15] * 3, n_steps=200)
    d = run_ammonia_converter(_bench_feed(), 150.0, 30000.0, n_beds=3,
                              T_in_bed=[698.15] * 3, n_steps=200)
    assert c["per_pass_N2_conversion"] > d["per_pass_N2_conversion"] + 0.01


def test_interbed_cooling_reduces_peak_and_catalyst_volume_is_physical():
    hot = run_ammonia_converter(_bench_feed(), 200.0, 10000.0, n_beds=1,
                                T_in_first=703.15, n_steps=200)
    cool = run_ammonia_converter(_bench_feed(), 200.0, 10000.0, n_beds=3,
                                 T_in_bed=[703.15] * 3, n_steps=200)
    assert cool["T_peak_K"] < hot["T_peak_K"]
    # volume comes from the NORMAL-basis TOTAL inlet flow (recycle included)
    # divided by the space velocity - nothing else
    assert cool["catalyst_volume_m3"] == pytest.approx(
        cool["reactor_inlet_total_mol_h"] * 0.02241397 / 10000.0, rel=1e-9)
    assert cool["reactor_inlet_total_mol_h"] > 400.0     # 100 mol fresh x (1+RR)
    assert cool["catalyst_volume_m3"] == pytest.approx(
        hot["catalyst_volume_m3"], rel=1e-12)   # same feed, same GHSV


def test_reactor_inlet_flows_respects_recycle_and_inlet_ammonia():
    F0, tot = reactor_inlet_flows(100.0, 300.0, 10.0, 3.0, 0.5)
    assert F0["N2"] == pytest.approx(400.0)
    assert F0["H2"] == pytest.approx(1200.0)
    assert F0["INERT"] == pytest.approx(40.0)
    assert F0["NH3"] == pytest.approx(0.005 * tot, rel=1e-9)
    assert tot == pytest.approx(F0["N2"] + F0["H2"] + F0["INERT"] + F0["NH3"])


def test_equilibrium_NH3_increases_with_pressure():
    F0 = _bench_feed()
    lo = equilibrium_NH3(698.15, 100.0, F0)
    hi = equilibrium_NH3(698.15, 250.0, F0)
    assert hi > lo > 0.05


# ---------------------------------------------------------- calibration ----
def test_calibration_is_a_single_documented_scalar():
    cfg = load_config(product="ammonia")
    from model.kinetics_synthesis import TEMKIN
    cal = calibrate_k0(cfg)
    assert 0.0 < cal["k_scale"] < 2.0
    assert abs(cal["deviation_after_pct"]) < 1e-6
    assert cal["uncalibrated"]["per_pass_N2_conversion"] > 0.10
    # nothing else may move
    assert cal["opened_band_per_pass"] == [0.15, 0.2]
    assert cfg.raw["kinetics"]["ammonia"]["alpha"] == TEMKIN["alpha"] == 0.654
    assert cfg.raw["kinetics"]["ammonia"]["Ea_J_mol"] == TEMKIN["Ea_J_mol"]


def test_opened_ammonia_benchmarks_disagree_and_that_is_reported():
    cfg = load_config(product="ammonia")
    cal = calibrate_k0(cfg)
    assert cal["k0_uncertainty_factor"] > 1.2        # the honest uncertainty
    assert cal["alternative_objective"]["k_scale_needed"] != cal["k_scale"]
    assert "NOT pilot validation" in cal["what_this_is"]


def test_benchmark_grid_reports_no_free_fit():
    cfg = load_config(product="ammonia")
    v = validate_against_opened_benchmark(cfg)
    assert v["n_rows"] == 6
    assert v["band_reached_without_any_fit"] in (True, False)
    assert all(r["catalyst_volume_per_100mol_h_feed_m3"] > 0 for r in v["rows"])


def test_bed_inlet_remedy_moves_peak_below_the_assumed_ceiling():
    cfg = load_config(product="ammonia")
    from model import products
    r = products.design(cfg)
    rec = recommend_bed_inlet_T(cfg, r, {"k_scale": 0.2134})
    K = cfg.raw["kinetics"]["ammonia"]
    assert rec["achieved_peak_T_K"] <= K["bed_T_max_K"] + 1.0
    assert rec["per_pass_N2_conversion_at_that_inlet"] > 0.15


# ------------------------------------------------------- data contract ----
def test_pilot_schema_covers_the_loop5_blockers():
    from model.data_ingest import load_schema
    sch = load_schema()
    req = set(sch["required_for_model_use"])
    for f in ("T_K", "p_bar", "S_C", "GHSV_h1_normal", "X_CH4", "X_CH4_u",
              "conversion_basis", "contact_time_regime"):
        assert f in req
    flat = [f for g in sch["required_for_loop5_closure"] for f in g]
    assert "dP_bed_bar" in flat and "Ni_size_nm" in flat
    assert "time_on_stream_h" in flat
    # every mandatory field must exist in the field list, or validation is a lie
    for f in req:
        assert f in sch["fields"] or f in ("run_id",)


def test_validate_rejects_ambiguous_or_misunit_records():
    from model.data_ingest import load_schema, validate
    good = {"run_id": "A1", "date": "2026-05-01", "catalyst_id": "Ni/MgAl2O4",
            "T_K": 1123.15, "p_bar": 25.0, "S_C": 2.5, "GHSV_h1_normal": 30000.0,
            "y_CH4_in_dry": 0.5, "y_H2O_in": 0.714, "conversion_basis": "dry",
            "X_CH4": 0.62, "X_CH4_u": 0.02, "contact_time_regime": "kinetic"}
    sch = load_schema()
    clean, issues = validate([good], sch)
    assert len(clean) == 1 and issues == []
    # 1) Celsius entered in the kelvin column
    bad_T = dict(good, run_id="A2", T_K=750.0)
    clean, iss = validate([bad_T], sch)
    assert clean == [] and any("Celsius" in i["msg"] for i in iss)
    # 2) missing uncertainty
    no_u = {k: v for k, v in good.items() if k != "X_CH4_u"}
    no_u["run_id"] = "A3"
    clean, iss = validate([no_u], sch)
    assert clean == [] and any("X_CH4_u" in i["msg"] for i in iss)
    # 3) unknown regime label
    bad_enum = dict(good, run_id="A4", contact_time_regime="maybe")
    clean, iss = validate([bad_enum], sch)
    assert clean == [] and any("allowed set" in i["msg"] for i in iss)
    # 4) pressure entered in kPa
    bad_p = dict(good, run_id="A5", p_bar=2500.0)
    clean, iss = validate([bad_p], sch)
    assert clean == [] and any("kPa" in i["msg"] for i in iss)
    # 5) unknown column is warned, not silently dropped
    extra = dict(good, run_id="A6", my_notes="x")
    clean, iss = validate([extra], sch)
    assert len(clean) == 1 and any("unknown column" in i["msg"] for i in iss)


def test_compare_uses_equilibrium_model_and_reports_regime():
    from model.data_ingest import compare_one
    rec = {"run_id": "A1", "T_K": 1123.15, "p_bar": 25.0, "S_C": 2.5,
           "CO2_C": 0.0, "O2_C": 0.0, "N2_C": 0.0, "y_CH4_in_dry": 0.5,
           "X_CH4": 0.62, "X_CH4_u": 0.02, "contact_time_regime": "kinetic",
           "GHSV_h1_normal": 30000.0}
    row = compare_one(rec)
    assert 0.0 < row["X_model_equilibrium"] <= 1.0
    assert row["delta"] is not None
    assert "kinetic" in row["note"]


def test_selftest_round_trips_the_existing_registry_and_loop5_stays_closed():
    from model.data_ingest import rerun_loop5, selftest
    st = selftest()
    assert st["n_usable"] >= 5
    assert abs(st["comparison"]["mean_bias"] - 0.287) < 0.02
    # placeholders must NOT be enough to flip any loop-5 subcheck
    assert all(not s["passed"] for s in st["loop5_subcheck_status"])
    subs = rerun_loop5(None, [], {"n_points": 0, "mean_bias": None},
                       {"n_usable": 0}, {"n_usable_series": 0})
    assert len(subs) == 3 and all(not s["passed"] for s in subs)


def test_dP_check_compares_against_ergun():
    from model.data_ingest import dP_check
    rec = {"run_id": "D1", "dP_bed_bar": 3.7e-4, "dP_bed_bar_u": 1e-5,
           "bed_height_mm": 50.0, "pellet_d_eq_mm": 2.0, "bed_voidage": 0.4,
           "T_K": 1123.15, "p_bar": 25.0, "y_CH4_in_dry": 0.5,
           "GHSV_h1_normal": 20000.0, "flow_total_NmL_min": 220.0}
    out = dP_check([rec])
    assert out["n_usable"] == 1
    row = out["rows"][0]
    assert row["dP_ergun_bar"] > 0
    assert 0.8 <= row["ratio_measured_over_ergun"] <= 1.3
    assert out["ergun_confirmed"] is True


def test_sintering_series_needs_three_points_and_200h():
    from model.data_ingest import sintering_check
    pts = [{"run_id": f"S{n}", "series_id": "A", "catalyst_id": "c",
            "T_K": 1123.15, "time_on_stream_h": th, "Ni_size_nm": d, "X_CH4": x}
           for n, (th, d, x) in enumerate(
               ((0.0, 6.6, 0.80), (200.0, 9.0, 0.77),
                (500.0, 11.0, 0.75), (1000.0, 14.0, 0.72)))]
    out = sintering_check(pts)
    assert out["n_usable_series"] == 1
    row = out["series"][0]
    assert row["cubic_k_d3_per_h"] > 0
    assert row["extrapolated_t50_cubic_h"] > 0
    assert row["activity_loss_pct_per_1000h"] > 0
    # too few points -> not usable
    assert sintering_check(pts[:2])["n_usable_series"] == 0


def test_regime_screening_flags_transport_limited_points():
    from model.data_ingest import regime_screening
    rec = {"run_id": "R1", "T_K": 1123.15, "p_bar": 25.0, "W_cat_g": 0.009,
           "X_CH4": 0.6, "y_CH4_in_dry": 0.45, "y_CH4_out_dry": 0.18,
           "flow_total_NmL_min": 220.0, "pellet_d_eq_mm": 0.3,
           "rho_loaded_kg_m3": 900.0}
    out = regime_screening([rec])
    assert out["n"] == 1
    assert out["rows"][0]["Weisz_Prater"] >= 0.0
    assert "ДОПУЩЕНИЕ" in out["status"]


# ------------------------------------------------------------ worksheet ----
def test_hazop_nico4_wording_is_confined_to_nickel_nodes():
    from model.hazop import hazop_report
    r = hazop_report()
    assert r["certified"] is False and r["worksheet_rows"] == 110
    for row in r["worksheet"]:
        if "Ni(CO)4" in row["consequence"]:
            assert row["node_id"] in ("N01", "N02", "N03", "N07", "N08", "N09")
    # the amine unit must not be blamed for tube creep / nickel sintering
    n05 = [x for x in r["worksheet"] if x["node_id"] == "N05"]
    assert any("MDEA thermal degradation" in x["consequence"] for x in n05)
    assert r["n_generic_template_rows"] > 50          # honestly reported


# ------------------------------------------------------------- results -----
def test_v5_docs_and_results_exist():
    for f in ("26_v5_converter.md", "27_v5_pilot_test_program.md",
              "28_v5_vendor_rfi.md", "29_v5_hazop_tor.md"):
        path = os.path.join(ROOT, "docs", f)
        assert os.path.exists(path), f
        text = open(path, encoding="utf-8").read()
        assert any(lbl in text for lbl in ("[ДОПУЩЕНИЕ]", "[ПОДТВЕРЖДЕНО]",
                                           "[ЧАСТИЧНО]", "[НЕ ПОДТВЕРЖДЕНО]"))
    v = os.path.join(ROOT, "results_v2", "verification_v2.json")
    if os.path.exists(v):
        l5 = json.load(open(v, encoding="utf-8"))["loops"][
            "5_validation_falsification"]
        assert l5["passed"] is False
        assert l5["subchecks_total"] >= 22
        assert l5["converter_ammonia"]["computed"] is True
        assert json.load(open(os.path.join(ROOT, "results_v2",
                                           "converter_ammonia.json"),
                               encoding="utf-8"))["design"]["k_scale_applied"] > 0
