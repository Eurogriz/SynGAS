"""V2 regression tests: five products, both normals, PR EOS, IF97, Ni inventory."""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from model.config import load_config, Config
from model.equilibrium import equilibrate, element_vector, vec_from_dict
from model.routes import make_feed
from model.products import design
from model.steam import (available, steam_enthalpy_kJ_per_mol,
                         saturation_temperature_K)
from model.thermo import ELEMENTS, R_J
from model.catalyst_inventory import nio_to_ni_wt_pct
from model.scenarios import PRODUCTS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_both_normal_conditions():
    a = load_config({"active.normal": "0C"})
    b = load_config({"active.normal": "15C"})
    assert abs(a.Vm - R_J * 273.15 / 101325.0) < 1e-12
    assert abs(b.Vm - R_J * 288.15 / 101325.0) < 1e-12
    assert 1.05 < b.Vm / a.Vm < 1.06


def test_dotted_overrides():
    e = load_config({"active.climate": "middle_east",
                     "products.methanol.knobs.SC": 3.5,
                     "economics.gas_USD_per_MMBtu": 6.0})
    assert e.active["climate"] == "middle_east"
    assert e.knobs["SC"] == 3.5
    assert e.economics["gas_USD_per_MMBtu"] == 6.0
    assert e.C["ambient_dry_bulb_C"] > 45


def test_pr_real_gas_equilibrium_condition():
    f = make_feed(SC=3.0, CO2C=0.237)
    ideal = equilibrate(f, 1123.15, 25.0)
    real = equilibrate(f, 1123.15, 25.0, eos_kset="base")
    assert abs(real["eos"]["Q1_over_K1_real"] - 1.0) < 1e-8
    assert 0.95 < real["eos"]["Z"] < 1.05
    assert abs(real["CH4_conversion"] - ideal["CH4_conversion"]) > 1e-4
    assert real["max_element_imbalance_pct"] < 1e-8


def test_iapws_if97_spot_values():
    if not available():
        pytest.skip("iapws not installed")
    h = steam_enthalpy_kJ_per_mol(673.15, 30.0) / 0.0180153
    assert abs(h - 3231.571) < 0.01
    assert abs(saturation_temperature_K(30.0) - 507.008) < 0.01


def test_nio_to_ni_conversion():
    assert abs(nio_to_ni_wt_pct(17.0) - 13.3578) < 0.01


def test_methanol_and_hydrogen_designs_hit_target():
    for product in ("methanol", "hydrogen"):
        r = design(load_config(product=product))
        assert r["spec"]["within_tolerance"], (product, r["spec"])
        assert not r["spec"]["carbon_stable"]
        assert all(v["pass"] for v in r["spec"]["limit_checks"].values()), product
        # full flowsheet element balance including withdrawals
        inp = dict(r["reformer_feed_mol_per_100mol_NG"])
        bin_ = element_vector(vec_from_dict(inp))
        out = dict(r["downstream"]["n"])
        for sp, v in r["downstream"]["withdrawals"].items():
            out[sp] = out.get(sp, 0.0) + v
        bout = element_vector(vec_from_dict(out))
        err = max(abs(bout[e] - bin_[e]) / bin_[e] for e in ELEMENTS)
        assert err < 1e-8, (product, err)


def test_ni_make_up_scales_inversely_with_life():
    r = design(load_config(product="methanol"))
    cat = r["catalyst"]
    for s in cat["life_sensitivity"]:
        assert abs(s["Ni_consumption_t_per_y"] * s["life_years"] -
                   cat["total_Ni_inventory_t"]) < 1e-9


def test_generated_results_for_all_five_products():
    p = os.path.join(ROOT, "results_v2", "summary_v2.json")
    if not os.path.exists(p):
        pytest.skip("run `python -m model.run_v2` first")
    s = json.load(open(p, encoding="utf-8"))
    assert list(s["key_numbers"]) == list(PRODUCTS)
    for prod, k in s["key_numbers"].items():
        assert k["within_tolerance"], prod
    v = json.load(open(os.path.join(ROOT, "results_v2", "verification_v2.json"),
                       encoding="utf-8"))
    for loop in ("1_sources", "2_arithmetic", "3_conservation", "4_thermo"):
        assert v["summary"][loop], loop
    assert v["summary"]["5_validation_falsification"] is False


def test_v2_claims_registry_integrity():
    d = json.load(open(os.path.join(ROOT, "data", "v2_claims.json"), encoding="utf-8"))
    assert len(d["claims"]) >= 30
    for c in d["claims"]:
        assert c["source"] and c["url"] and c["status"] in d["meta"]["allowed_status"]
        if c["used_in_result"]:
            assert c["status"] != "[НЕ ПОДТВЕРЖДЕНО]", c["id"]


def test_config_lists_all_user_requirements():
    raw = Config.load().raw
    assert len(raw["products"]) == 5
    assert {"0C", "15C"}.issubset(raw["normal_conditions"])
    assert {"russia", "middle_east"}.issubset(raw["climates"])
    assert raw["catalyst"]["basis"] == "Ni/MgAl2O4"
    assert raw["eos"]["enabled"] is True
    assert raw["active"]["steam_table"] == "IAPWS97"


# ---------------- V3 continuation ----------------
def test_methanol_co2_inside_licensor_window():
    r = design(load_config(product="methanol"))
    assert 4.0 <= r["spec"]["CO2_molpct"] <= 8.0
    assert r["spec"]["limit_checks"]["min_CO2_molpct"]["pass"]
    assert r["spec"]["limit_checks"]["max_CO2_molpct"]["pass"]
    assert any(u["unit"].startswith("A-302") for u in r["downstream"]["units"])
    assert r["utilities"]["CO2_net_t_h"] <= r["utilities"]["total_CO2_t_h"]


def test_prereformer_converts_c2plus_and_closes_enthalpy():
    from model.prereformer import adiabatic_prereformer
    from model.config import load_config
    from model.products import build_feed
    c = load_config(product="methanol")
    f = build_feed(c, c.knobs)[0]
    f.pop("O2", None)
    r = adiabatic_prereformer(f, 25.0, 623.15, eos_kset="base")
    assert r["converged"]
    assert r["C2plus_conversion"] > 0.99
    assert not r["carbon_stable"]
    assert r["H_balance_mismatch_pct"] < 0.1


def test_synthesis_and_safety_blocks_present():
    r = design(load_config(product="methanol"))
    assert r["synthesis"]["methanol_t_h"] > 0
    assert r["safety"]["Ni_CO_4"]["normal_operation"]["NiCO4_ppb"] < 1.0
    assert len(r["safety"]["HAZOP_nodes"]) >= 8
    assert r["safety"]["relief"]["orifice_diameter_mm"] > 0


def test_ni_carbonyl_purge_rule():
    from model.safety_v2 import ni_carbonyl_ppb
    # normal operation: 1123 K, p_CO = 3 bar -> negligible
    assert ni_carbonyl_ppb(1123.15, 3.0)["NiCO4_ppb"] < 1e-3
    # 200 C with unpurged CO -> equilibrium risk; with 10 ppm CO -> < 1 ppb
    assert ni_carbonyl_ppb(473.15, 3.0)["NiCO4_ppb"] > 1.0
    assert ni_carbonyl_ppb(473.15, 10e-6 * 25.0)["NiCO4_ppb"] < 1.0


def test_ergun_dp_is_in_bar_and_within_limit():
    r = design(load_config(product="methanol"))
    dp = r["equipment"]["Ergun_dP_bar"]
    assert 0 < dp < 10          # bar, not Pa
    assert r["equipment"]["dP_within_limit"]
    assert r["equipment"]["tubes_installed"] >= r["equipment"]["tubes_for_heat"]


def test_scipy_independent_pr_agrees():
    from model.verify_v2 import scipy_pr_minimisation
    r = scipy_pr_minimisation(make_feed(SC=3.0, CO2C=0.237), 1123.15, 25.0, "base")
    if not r.get("available"):
        pytest.skip("scipy not installed")
    assert r["success"]
    assert r["max_dy_wet"] < 1e-4


def test_v21_claims_and_full_matrix():
    d = json.load(open(os.path.join(ROOT, "data", "v2_claims.json"), encoding="utf-8"))
    assert len(d["claims"]) >= 44
    p = os.path.join(ROOT, "results_v2", "full_matrix.csv")
    if os.path.exists(p):
        import csv
        rows = list(csv.DictReader(open(p, encoding="utf-8")))
        assert len(rows) == 15
