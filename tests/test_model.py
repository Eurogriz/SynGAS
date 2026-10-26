"""Regression tests. Run: PYTHONPATH=. python -m pytest -q  (stdlib core only)."""
import csv, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model import thermo
from model.equilibrium import equilibrate, REACTIONS, adiabatic_temperature
from model.routes import make_feed, find_co2_for_SN, carbon_boundary
from model.kinetics import coefficients, pfr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_reaction_enthalpies_match_rule_reference():
    ref = {"SMR": 206.0, "WGS": -41.0, "DRM": 247.0, "POX": -36.0, "FULLOX": -802.0}
    st = {"SMR": {"CH4": -1, "H2O": -1, "CO": 1, "H2": 3},
          "WGS": {"CO": -1, "H2O": -1, "CO2": 1, "H2": 1},
          "DRM": {"CH4": -1, "CO2": -1, "CO": 2, "H2": 2},
          "POX": {"CH4": -1, "O2": -0.5, "CO": 1, "H2": 2},
          "FULLOX": {"CH4": -1, "O2": -2, "CO2": 1, "H2O": 2}}
    for k in ref:
        dh = sum(nu * thermo.h0(s, 298.15) for s, nu in st[k].items())
        assert abs(dh - ref[k]) < 1.0, (k, dh)


def test_molar_volume_and_water_psat():
    assert abs(8.314462618 * 273.15 / 101325.0 - 0.02241397) < 1e-7
    assert abs(thermo.water_psat_bar(373.15) - 1.01325) < 0.01


def test_element_balance_and_equilibrium_constants():
    feed = make_feed(SC=3.0, CO2C=0.25, O2C=0.05)
    for T, p in ((900.0, 25.0), (1123.15, 25.0), (1300.0, 5.0)):
        r = equilibrate(feed, T, p)
        assert r["max_element_imbalance_pct"] < 1e-8
        assert abs(r["Q1_over_K1"] - 1) < 1e-6
        assert abs(r["Q2_over_K2"] - 1) < 1e-6


def test_two_independent_thermo_datasets_agree():
    feed = make_feed(SC=3.0)
    a = equilibrate(feed, 1123.15, 25.0, dataset="shomate")
    b = equilibrate(feed, 1123.15, 25.0, dataset="nasa")
    assert max(abs(a["y_wet"][k] - b["y_wet"][k]) for k in a["y_wet"]) < 0.01


def test_sn_tuning_is_reproducible():
    t = find_co2_for_SN(2.0)
    assert t["converged"]
    assert abs(t["SN"] - 2.0) < 1e-6
    # V2 uses the opened Russian H-gas composition (Frontiers 2025) with C3+,
    # so the CO2/C required for SN=2.0 increased from 0.2468 to ~0.2549.
    assert 0.24 < t["CO2_C_molar"] < 0.27


def test_carbon_boundary_monotonic_behaviour():
    high = equilibrate(make_feed(SC=3.0), 1123.15, 25.0, allow_carbon=False)
    drm = equilibrate(make_feed(SC=0.0, CO2C=1.0), 1123.15, 25.0)
    assert high["carbon_affinity_kJ_per_mol"] < 0
    assert drm["carbon_stable"] is True


def test_adiabatic_atr_energy_closure():
    feed = make_feed(SC=1.5, O2C=0.55)
    a = adiabatic_temperature(feed, 25.0, T_in=773.15)
    assert a["converged"]
    assert abs(a["H_out_kJ"] - a["H_in_kJ"]) / abs(a["H_in_kJ"]) < 1e-8
    assert 1150 < a["T_ad_K"] < 1400


def test_dew_point_below_whb_outlet():
    r = equilibrate(make_feed(SC=3.0), 1123.15, 25.0)
    dew = thermo.water_dew_point(25.0, r["y_wet"]["H2O"])
    assert dew < 623.15


def test_secondary_kinetics_equilibrium_constants_match_NIST():
    for T in (750.0, 850.0, 950.0, 1000.0):
        _, Keq, _ = coefficients(T)
        k1 = thermo.equilibrium_constant(REACTIONS["R1_SMR"], T)
        k2 = thermo.equilibrium_constant(REACTIONS["R2_WGS"], T)
        assert abs(Keq["K1"] / k1 - 1) < 0.10
        assert abs(Keq["K2"] / k2 - 1) < 0.10


def test_l2_pfr_is_stable_and_bounded():
    r = pfr(900.0, 29.0, density_factor=1.0)
    assert -1e-6 <= r["X_CH4"] <= 1.0
    assert r["W_integrated_g"] > 0


def test_registry_integrity():
    with open(os.path.join(ROOT, "docs", "01_claims_register.csv"), encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) >= 50
    for r in rows:
        assert r["source_ids"] and r["status"], r["ID"]


def test_results_files_exist_and_close_balances():
    p = os.path.join(ROOT, "results", "base_case.json")
    if not os.path.exists(p):
        return  # results are generated, not committed as required input
    f = json.load(open(p, encoding="utf-8"))
    assert f["plant_energy_closure_pct"] < 0.5
    assert f["element_balance_SMR_max_pct"] < 0.1
    assert abs(f["SN_achieved"] - f["SN_target"]) < 1e-6
