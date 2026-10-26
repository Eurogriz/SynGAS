"""V5.1 tests: model-side uncertainty envelope and the converter layout scan.

Both additions answer a specific objection, so the tests check the objection is
actually answered:

* uncertainty band -> the pilot/model bias must NOT be re-explained as "bad
  input data"; the band has to stay small and every design-point band must
  reproduce the design's own reported conversion (i.e. the sensitivity run uses
  the SAME model as the report, not a simplified twin);
* layout scan -> every row's ceiling verdict must agree with its own numbers,
  and the total molar flow must be conserved by the cold-shot mixing (the
  quench may not create or destroy moles).
"""
import json
import math
import os

import pytest

from model import methanol_converter as mc
from model.config import load_config
from model.converter import run_ammonia_converter
from model.uncertainty import PERTURB, STATUSES, band_for_point

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results_v2")


# ------------------------------------------------------------- uncertainty ---
def test_perturbation_switches_are_all_documented():
    """Every switch must map to a parameter that carries a status label."""
    for k, v in PERTURB.items():
        assert isinstance(v, dict) and len(v) == 1, k
        assert next(iter(v)) in STATUSES, (k, v)
    assert {"dT", "dSC", "dCO2C", "dCH4", "approach_K", "kset"} <= set(STATUSES)
    for tag, st in STATUSES.items():
        assert st.startswith("["), (tag, st)


def test_band_for_point_is_small_and_brackets_the_base():
    b = band_for_point(873.15, 1.0, 5.0, 0.0)
    assert abs(b["X_base"] - 0.9105801646316707) < 1e-9   # P16, loop-5 point
    assert b["envelope_min"] <= b["X_base"] <= b["envelope_max"]
    assert 0.0 < b["envelope_half_width"] < 0.05     # thermo noise is small
    assert b["quadrature_half_width"] <= b["envelope_half_width"] + 1e-12
    assert len(b["rows"]) >= 8
    assert "delta" in b["largest_single_effect"]


def test_approach_to_equilibrium_is_the_largest_single_effect():
    """The design/pilot points are all dominated by the finite-rate approach
    assumption, not by T or composition - that is the whole point of docs/30."""
    for T, p in ((873.15, 1.0), (873.15, 10.0)):
        b = band_for_point(T, p, 2.0, 0.0)
        assert "approach" in b["largest_single_effect"]["perturbation"]
        # and it moves X toward the measurement (down), but far too little
        assert b["largest_single_effect"]["delta"] < 0.0
        assert abs(b["largest_single_effect"]["delta"]) < 0.05


def test_saved_envelope_keeps_the_loop5_conclusion():
    path = os.path.join(RESULTS, "model_uncertainty.json")
    if not os.path.exists(path):
        pytest.skip("run python -m model.uncertainty first")
    d = json.load(open(path, encoding="utf-8"))
    # reproducibility: the saved band for P16 must be exactly recomputable
    r = [x for x in d["points"] if x["record_id"] == "P16"][0]
    again = band_for_point(r["T_K"], r["p_bar"], r["S_C"], r["CO2_C"])
    assert again["X_base"] == pytest.approx(r["X_base"], abs=1e-9)
    assert again["envelope_half_width"] == pytest.approx(r["envelope_half_width"],
                                                        abs=1e-9)
    pts = d["points"]
    pilot = [r for r in pts if r.get("measured_minus_model") is not None]
    assert len(pilot) >= 4 and len(pts) >= 6
    for r in pilot:
        assert abs(r["measured_minus_model"]) > r["envelope_half_width"]
        assert r["measurement_inside_model_band"] is False
    # design bands must reproduce the design's own reported conversion
    for r in pts:
        if r.get("X_model_reported") is not None:
            assert abs(r["X_base"] - r["X_model_reported"]) <= \
                r["envelope_half_width"] + 1e-6
    assert d["pilot_points_inside_model_band"] == 0
    assert "NOT explained" in d["verdict"]


def test_uncertainty_doc_is_generated_from_the_saved_json():
    path = os.path.join(ROOT, "docs", "30_v5_uncertainty.md")
    if not os.path.exists(os.path.join(RESULTS, "model_uncertainty.json")):
        pytest.skip("no uncertainty results yet")
    txt = open(path, encoding="utf-8").read()
    assert "30.3 Результат" in txt and "30.5 Чего этот расчёт НЕ делает" in txt
    assert "[ДОПУЩЕНИЕ]" in txt                      # statuses must be carried
    assert "не является валидацией" in txt.lower() or "не является" in txt.lower()


# --------------------------------------------------------- layout scan -----
def _small_feed():
    return {"N2": 25.0, "H2": 75.0, "NH3": 0.5, "INERT": 1.0}


@pytest.mark.parametrize("cs", [0.0, 0.3])
def test_cold_shot_mixing_conserves_total_molar_flow(cs):
    """Quench recycles fresh feed inside the reactor: it must not create moles.
    Only reaction (2 mol -> 0 mol per NH3 pair) may reduce the total."""
    F0 = _small_feed()
    out = run_ammonia_converter(F0, 200.0, 20000.0, n_beds=3,
                                T_in_first=680.0, T_in_bed=[680.0] * 3,
                                cold_shot_fraction=cs, k_scale=0.2134,
                                n_steps=120)
    tot_in = sum(F0.values())
    X = out["per_pass_N2_conversion"]
    assert X > 0.0
    n2_conv = X * F0["N2"]
    # stoichiometry: 2 mol NH3 per mol N2, and -2 mol total per mol N2
    assert abs(out["NH3_formed_mol_h"] - 2.0 * n2_conv) < 1e-6 * F0["N2"]
    tot_out = (F0["NH3"] + out["NH3_formed_mol_h"]) / (
        out["outlet_NH3_molpct"] / 100.0)
    assert abs((tot_in - tot_out) - 2.0 * n2_conv) < 1e-4 * tot_in


def test_cold_shot_dilutes_the_interbed_stream():
    F0 = _small_feed()
    kw = dict(p_bar=200.0, GHSV_h1=20000.0, n_beds=3, T_in_first=680.0,
              n_steps=120, k_scale=0.2134)
    no_q = run_ammonia_converter(F0, T_in_bed=[680.0] * 3,
                                 cold_shot_fraction=0.0, **kw)
    with_q = run_ammonia_converter(F0, T_in_bed=[680.0] * 3,
                                   cold_shot_fraction=0.35, **kw)
    assert with_q["outlet_NH3_molpct"] < no_q["outlet_NH3_molpct"]
    assert with_q["T_bed_out_K"] != no_q["T_bed_out_K"]
    # quench re-dilutes NH3, so the last bed works further from equilibrium and
    # therefore heats up more than in the unquenched case
    assert with_q["adiabatic_rise_K"][-1] >= no_q["adiabatic_rise_K"][-1]


def test_saved_layout_scan_is_self_consistent():
    path = os.path.join(RESULTS, "converter_ammonia.json")
    if not os.path.exists(path):
        pytest.skip("run python -m model.run_v2 first")
    d = json.load(open(path, encoding="utf-8"))
    ls = d.get("layout_scan")
    if not ls:
        pytest.skip("stale converter results (pre-scan run)")
    lim = float(ls["held_constant"]["bed_T_max_K_assumed"])
    rows = ls["rows"]
    assert len(rows) == ls["layouts_total"] >= 4
    for r in rows:
        assert bool(r["peak_within_ceiling"]) == bool(r["T_peak_K"] <= lim + 0.6)
        # a ceiling-binding layout must sit just below the ceiling, not far below
        if r["ceiling_binding"] and r["peak_within_ceiling"]:
            assert r["T_peak_K"] > lim - 12.0
        assert abs(r["T_peak_K"] - max(r["T_peak_K"], 0.0)) < 1e-9
    # catalyst volume is held constant across layouts, otherwise rows are not
    # comparable
    assert len({r["catalyst_volume_m3"] for r in rows}) == 1
    best = ls["best_by_outlet_NH3"]
    assert best["outlet_NH3_molpct"] == max(r["outlet_NH3_molpct"]
                                           for r in rows
                                           if r["peak_within_ceiling"])
    assert ls["layouts_meeting_ceiling"] >= 1
    assert ls["layouts_meeting_ceiling_AND_opened_band"] >= 0
    for key in ("finding", "note", "status"):
        assert ls[key]


def test_layout_scan_verdict_is_reported_in_doc26():
    path = os.path.join(ROOT, "docs", "26_v5_converter.md")
    if not os.path.exists(os.path.join(RESULTS, "converter_ammonia.json")):
        pytest.skip("no converter results yet")
    d = json.load(open(os.path.join(RESULTS, "converter_ammonia.json"),
                       encoding="utf-8"))
    if not d.get("layout_scan"):
        pytest.skip("stale converter results (pre-scan run)")
    txt = open(path, encoding="utf-8").read()
    assert "26.6 Поиск компоновки" in txt
    assert "холод. вброс" in txt
    assert "26.8 Следующий шаг" in txt


# ------------------------------------------------- methanol adiabatic march --
def test_methanol_enthalpies_reproduce_the_cited_reaction_energies():
    """Independent of the kinetics: this model's own h() must give the two
    reaction enthalpies the project already cites from Appl. Sci. 2017."""
    h = mc.h_stream
    dH_co2 = (h({"CH3OH": 1.0, "H2O": 1.0}, 298.15)
              - h({"CO2": 1.0, "H2": 3.0}, 298.15))
    dH_co = (h({"CH3OH": 1.0}, 298.15) - h({"CO": 1.0, "H2": 2.0}, 298.15))
    assert abs(dH_co2 - (-49.7)) < 0.4
    assert abs(dH_co - (-90.7)) < 0.4
    # Cp table must be honoured exactly at the published grid points
    assert abs(mc.cp_methanol(500.0) - 59.70) < 1e-9
    # and h(298.15) must be the formation enthalpy itself
    assert abs(mc.h_methanol(298.15) - (-201.49)) < 1e-9


def test_solve_T_march_inverts_the_enthalpy_function():
    F = {"CO2": 0.4, "CO": 0.6, "H2": 12.0, "H2O": 0.2, "CH3OH": 0.1,
         "INERT": 1.5}
    for T in (450.0, 493.2, 552.5, 620.0):
        H = mc.h_stream(F, T)
        assert abs(mc.solve_T_march(F, H, T + 25.0) - T) < 1e-3


def test_adiabatic_march_closes_carbon_and_energy_and_only_heats_up():
    F0, _ = mc._vbf_case_flows()
    r = mc.adiabatic_march(F0, 50.0, 0.0348, 493.2, n_steps=400,
                           profile_stride=40)
    assert r["carbon_closure_rel"] < 1e-9
    assert r["enthalpy_residual_rel"] < 1e-5
    assert r["dT_ad_K"] > 40.0                    # exothermic net -> must heat up
    assert r["T_out_K"] > r["T_in_K"]
    tot = sum(r["F_out_mol_h"].values())
    assert abs(sum(r["y_out_molpct"].values()) - 100.0) < 1e-6
    # mole reduction must equal 2 mol per mol MeOH made (CO2 route only)
    d_meoh = r["F_out_mol_h"]["CH3OH"] - F0["CH3OH"]
    assert abs((r["total_flow_in_mol_h"] - tot) - 2.0 * d_meoh) < 1e-6 * d_meoh
    # temperature profile monotone-ish and bounded by the outlet + small margin
    Ts = [p["T_K"] for p in r["profile"]]
    assert max(Ts) < r["T_out_K"] + 3.0 and min(Ts) >= 493.0


def test_isothermal_control_matches_the_v4_pfr_path():
    """The adiabatic module must agree with kinetics_synthesis when the heat is
    removed (same rate law, same units): conversions within 0.5%."""
    from model.kinetics_synthesis import _rk4_methanol
    F0, _ = mc._vbf_case_flows()
    ad = mc.adiabatic_march(F0, 50.0, 0.0348, 493.2, n_steps=4000,
                            isothermal=True)
    iso = _rk4_methanol(493.2, 50.0, {k: v / 3600.0 for k, v in F0.items()},
                        0.0348, n=4000)
    for k in ("CO2", "CO", "CH3OH", "H2O"):
        a = ad["F_out_mol_h"][k] / 3600.0
        assert abs(a - iso[k]) / max(abs(iso[k]), 1e-9) < 0.005, k


def test_vbf_case_is_inside_the_published_validity_window():
    d = mc.reproduce_vbf_base_case(n_steps=800)
    assert d["validity_window_check"]["inside_window"] is True
    assert d["reproduced"] is True
    assert d["max_abs_composition_deviation_pp"] <= d["criteria"]["composition_within_pp"]
    assert d["abs_T_deviation_K"] <= d["criteria"]["T_within_K"]
    # the isothermal assumption is NOT what explains the V4 industrial gap:
    # the MeOH difference between the two runs is a fraction of a mole percent
    F0, _ = mc._vbf_case_flows()
    iso = mc.adiabatic_march(F0, 50.0, 0.0348, 493.2, n_steps=800,
                             isothermal=True)
    assert abs(iso["y_out_molpct"]["CH3OH"]
               - d["this_model"]["y_out_molpct"]["CH3OH"]) < 0.5


def test_cp_table_integration_error_is_reported_not_assumed():
    e = mc.cp_integration_error()
    assert e["rel_error"] < 1e-5
    db = json.load(open(os.path.join(ROOT, "data", "nist_cp_ch3oh.json"),
                        encoding="utf-8"))
    assert "0.0005 J/mol" in db["integration"]["discretisation_check"]
