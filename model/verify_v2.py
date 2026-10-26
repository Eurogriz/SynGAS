"""V2 five-loop verification (G8). Operates on computed design dictionaries.

Loop 1 sources/claims, loop 2 arithmetic, loop 3 conservation,
loop 4 thermodynamic consistency, loop 5 validation/falsification.
Loop 5 is reported FAILED on purpose: no HYSYS run and no experimental data.
"""
from __future__ import annotations
import json, math, os
from .thermo import (R_J, ELEMENTS, h0, reaction_g0, equilibrium_constant,
                     water_dew_point, water_psat_bar)
from .equilibrium import element_vector, vec_from_dict, REACTIONS
from .equilibrium import equilibrate
from .routes import make_feed
from .steam import (saturation_temperature_K, saturation_pressure_bar,
                    steam_enthalpy_kJ_per_mol, available as iapws_available)
from .eos import KIJ, peng_robinson

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rel(a, b):
    return abs(a - b) / max(abs(a), abs(b), 1e-30)


def loop1_sources():
    path = os.path.join(ROOT, "data", "v2_claims.json")
    d = json.load(open(path, encoding="utf-8"))
    claims = d["claims"]
    bad = []
    for c in claims:
        if c["status"] not in d["meta"]["allowed_status"]:
            bad.append((c["id"], "bad status"))
        if not c.get("source") or not c.get("url"):
            bad.append((c["id"], "missing source/url"))
        if c.get("used_in_result") and c["status"] == "[НЕ ПОДТВЕРЖДЕНО]":
            bad.append((c["id"], "unconfirmed claim used in result"))
    by_status = {s: sum(1 for c in claims if c["status"] == s)
                 for s in d["meta"]["allowed_status"]}
    return {"passed": not bad, "n_claims": len(claims), "by_status": by_status,
            "problems": bad,
            "note": "Every number used in a RESULT has an opened source or an explicit [ДОПУЩЕНИЕ]. "
                    "Claims with used_in_result=false are listed as open items, not as inputs."}


def loop2_arithmetic(designs):
    checks = []
    for prod, r in designs.items():
        cfg = r["config"]
        Vm = r["Vm_m3_per_mol"]
        T = r["normal"]
        T_K = 273.15 if T == "0C" else 288.15
        checks.append((prod, "Vm", _rel(Vm, R_J * T_K / 101325.0)))
        flows = r["flows"]
        checks.append((prod, "product_Nm3_h",
                       _rel(flows["product_Nm3_h"], flows["product_mol_h"] * Vm)))
        u = r["utilities"]
        Q_kJ_h = u["Q_reformer_kW"] * 3600.0
        LHV = 802.305
        eta = 0.85
        checks.append((prod, "fuel_Nm3_h",
                       _rel(u["fuel_Nm3_h"], max(Q_kJ_h, 0.0) / (eta * LHV) * Vm)))
        checks.append((prod, "CO2_from_fuel_t_h",
                       _rel(u["CO2_from_fuel_t_h"],
                            u["fuel_Nm3_h"] / Vm * 44.0095 / 1e6)))
        y = r["downstream"]["y_dry"]
        h2, co, co2, n2 = (y.get(k, 0.0) for k in ("H2", "CO", "CO2", "N2"))
        s = r["spec"]
        if s["metric"] == "SN":
            checks.append((prod, "SN", _rel(s["achieved"], (h2 - co2) / (co + co2))))
        elif s["metric"] == "H2_CO":
            checks.append((prod, "H2_CO", _rel(s["achieved"], h2 / co)))
        elif s["metric"] == "H2_N2":
            checks.append((prod, "H2_N2", _rel(s["achieved"], h2 / n2)))
        elif s["metric"] == "H2_purity":
            checks.append((prod, "H2_purity", _rel(s["achieved"], h2)))
        cat = r["catalyst"]
        vol = cat["reformer_catalyst_volume_m3"] + cat["pre_reformer_catalyst_volume_m3"]
        checks.append((prod, "catalyst_mass",
                       _rel(cat["total_catalyst_mass_t"] * 1000.0,
                            vol * cat["proxy_loaded_density_kg_m3"])))
        checks.append((prod, "Ni_inventory",
                       _rel(cat["total_Ni_inventory_t"] * 1000.0,
                            vol * cat["proxy_loaded_density_kg_m3"] *
                            cat["Ni_wt_pct_metal_used"] / 100.0)))
        e = r["economics"]
        parts = (e["gas_cost_USD_y"] + e["CO2_cost_USD_y"] + e["power_cost_USD_y"] +
                 e["cooling_water_cost_USD_y"] + e["catalyst_cost_USD_y"] +
                 e["fixed_OPEX_USD_y"] - e["steam_credit_USD_y"] +
                 e["annualised_CAPEX_USD_y"])
        if "NH3" in e["unit"]:
            denom = r["config"]["capacity"] * 365.0
        else:
            denom = (flows["H2_product_Nm3_h"] or flows["product_Nm3_h"]) * 8000.0 / 1000.0
        checks.append((prod, "levelised_cost", _rel(e["levelised_cost"], parts / denom)))
    worst = max(checks, key=lambda x: x[2])
    return {"passed": worst[2] < 1e-6, "max_relative_error": worst[2],
            "worst_check": {"product": worst[0], "name": worst[1]},
            "n_checks": len(checks),
            "checks": [{"product": a, "name": b, "rel_error": c} for a, b, c in checks]}


def loop3_conservation(designs):
    rows = []
    for prod, r in designs.items():
        eq = r["reformer"]["equilibrium"]
        rows.append({"product": prod, "check": "reactor element balance",
                     "error_pct": eq["max_element_imbalance_pct"]})
        inp = dict(r["reformer_feed_mol_per_100mol_NG"])
        # ammonia: add the secondary-reformer air (the primary effluent is
        # element-equivalent to the primary feed, so no double counting)
        if prod == "ammonia":
            sec = r["reformer_units"][-1]
            inp["O2"] = inp.get("O2", 0.0) + sec.get("O2_mol_per_100mol_NG", 0.0)
            inp["N2"] = inp.get("N2", 0.0) + sec.get("N2_mol_per_100mol_NG", 0.0)
        b_in = element_vector(vec_from_dict(inp))
        final = dict(r["downstream"]["n"])
        wd = r["downstream"]["withdrawals"]
        for sp, val in wd.items():
            final[sp] = final.get(sp, 0.0) + val
        b_out = element_vector(vec_from_dict(final))
        err = max(abs(b_out[e] - b_in[e]) / b_in[e] * 100 if b_in[e] else 0.0
                  for e in ELEMENTS)
        rows.append({"product": prod, "check": "full flowsheet element balance",
                     "error_pct": err,
                     "elements_in": b_in, "elements_out": b_out})
        # reactor energy closure on the model's own enthalpy basis
        H_in = r["reformer"]["H_in_kJ_per_100mol_NG"]
        H_out = r["reformer"]["H_out_kJ_per_100mol_NG"]
        Q = r["reformer"]["Q_total_kJ_per_100mol_NG"]
        e_pct = abs(H_out - H_in - Q) / max(abs(H_out), 1.0) * 100
        rows.append({"product": prod, "check": "reactor enthalpy closure",
                     "error_pct": e_pct})
    worst = max(x["error_pct"] for x in rows)
    return {"passed": worst < 1e-6, "max_error_pct": worst, "rows": rows,
            "note": "Full-flowsheet balance includes condensed water, MDEA CO2 product, "
                    "PSA tail gas and dryer water as explicit withdrawal streams."}


def loop4_thermo(designs, scenarios):
    T = 1123.15
    # two independent thermochemical datasets
    dH = {}
    for name, st in (("SMR", {"CH4": -1, "H2O": -1, "CO": 1, "H2": 3}),
                     ("WGS", {"CO": -1, "H2O": -1, "CO2": 1, "H2": 1}),
                     ("DRM", {"CH4": -1, "CO2": -1, "CO": 2, "H2": 2}),
                     ("H2OX", {"H2": -1, "O2": -0.5, "H2O": 1})):
        a = sum(nu * h0(sp, T, "shomate") for sp, nu in st.items())
        b = sum(nu * h0(sp, T, "nasa") for sp, nu in st.items())
        dH[name] = {"shomate": a, "nasa7": b, "diff_kJ_per_mol": a - b}
    # equilibrium with PR: Q*Kphi/K must be 1
    eq_rows = []
    for prod, r in designs.items():
        e = r["eos"]
        eq_rows.append({"product": prod, "Z": e["Z"],
                        "Kphi_R1": e["Kphi_R1"],
                        "Q1_over_K1_real": e["Q1_over_K1_real"],
                        "deviation_pct": abs((e["Q1_over_K1_real"] or 0) - 1) * 100})
    # IAPWS spot checks
    iap = {"available": iapws_available(),
           "h_30bar_673K_kJ_per_kg": steam_enthalpy_kJ_per_mol(673.15, 30.0) / 0.0180153,
           "Tsat_30bar_K": saturation_temperature_K(30.0),
           "psat_500K_bar": saturation_pressure_bar(500.0),
           "reference": "iapws 1.5.5; h(3 MPa,673.15 K)=3231.571 kJ/kg, Tsat(30 bar)=507.008 K"}
    # NIST vs IF97 dew point for the methanol design
    m = designs["methanol"]
    y_h2o = max((u for u in m["downstream"]["units"] if u["unit"].startswith("E-601")),
                key=lambda u: u["unit"])["psat_bar"] / m["reformer"]["p_bar"]
    dp_if97 = water_dew_point(m["reformer"]["p_bar"], y_h2o, use_iapws=True)
    dp_nist = water_dew_point(m["reformer"]["p_bar"], y_h2o, use_iapws=False)
    # PR vs ideal equilibrium
    from .routes import feed_carbon
    f = make_feed(SC=3.0, CO2C=0.23708560466766354)
    a = equilibrate(f, T, 25.0)
    b = equilibrate(f, T, 25.0, eos_kset="base")
    # kij sensitivity
    kij = scenarios.get("eos_sensitivity", [])
    spread = (max(x["X_CH4"] for x in kij) - min(x["X_CH4"] for x in kij)
              if kij else None)
    worst_eq = max(x["deviation_pct"] for x in eq_rows)
    worst_dH = max(abs(v["diff_kJ_per_mol"]) for v in dH.values())
    return {"passed": worst_eq < 0.01 and worst_dH < 5.0,
            "reaction_enthalpies": dH,
            "PR_equilibrium": eq_rows, "worst_PR_deviation_pct": worst_eq,
            "IAPWS": iap,
            "dew_point_IF97_K": dp_if97, "dew_point_NIST_K": dp_nist,
            "dew_point_diff_K": abs(dp_if97 - dp_nist),
            "PR_vs_ideal": {"X_ideal": a["CH4_conversion"], "X_PR": b["CH4_conversion"],
                            "delta_X": b["CH4_conversion"] - a["CH4_conversion"],
                            "SN_ideal": a["stoichiometric_number_SN"],
                            "SN_PR": b["stoichiometric_number_SN"]},
            "kij_sets": list(KIJ.keys()), "kij_X_CH4_spread": spread,
            "note": "Q*Kphi/K = 1 is the real-gas equilibrium condition; the residual "
                    "is <0.01%. Shomate/NASA7 reaction enthalpies agree within 5 kJ/mol."}


def loop5_validation(designs):
    unchecked = [
        "HYSYS / DWSIM / COCO steady-state run (not installed; user answer 11 confirms Python equivalent)",
        "Experimental pilot campaign for Ni/MgAl2O4 conversion, pressure drop and catalyst life",
        "Vendor Ni/MgAl2O4 catalyst datasheet: bulk density, Ni loading, crush strength, life",
        "Validated Xu-Froment kinetic parameter set (full primary text not opened; secondary set fails self-consistency)",
        "Sintering model discrimination: GPLE vs power-law life differ by factor ~3.06 (v1 finding)",
        "PSA vendor impurity-breakthrough curve (slip weights are calibrated assumptions)",
        "MDEA vendor reboiler duty and CO2 recovery guarantee",
        "API 530 / ASME certified tube creep calculation (LMP slope is an assumption)",
        "Regional gas/electricity/CO2 price quotes for Russia and the Middle East",
        "GOST 5542:2022 full standard text (only a status page was opened)",
        "Ammonia-loop compression and synthesis duty, methanol/FT/oxo downstream synthesis loops",
        "Safety study: HAZOP, Ni(CO)4 formation during shutdown, relief sizing",
    ]
    return {"passed": False, "status": "FAILED (honestly reported)",
            "reason": "No independent experimental or commercial-licensor validation of the "
                      "V2 product variants. HYSYS was not run. All five product targets are "
                      "matched by the model's own equilibrium solver, which is a self-check, "
                      "not an external validation.",
            "unchecked_items": unchecked,
            "self_checks_that_pass": [p for p, r in designs.items()
                                     if r["spec"]["within_tolerance"]],
            "note": "This loop stays FAILED by design, as required by the user's rule: "
                    "do not declare the model completed while loop 5 and the balances are open."}


def run_all(designs, scenarios):
    l1 = loop1_sources()
    l2 = loop2_arithmetic(designs)
    l3 = loop3_conservation(designs)
    l4 = loop4_thermo(designs, scenarios)
    l5 = loop5_validation(designs)
    loops = {"1_sources": l1, "2_arithmetic": l2, "3_conservation": l3,
             "4_thermo": l4, "5_validation_falsification": l5}
    return {"loops": loops,
            "summary": {k: v["passed"] for k, v in loops.items()},
            "overall_passed": all(v["passed"] for v in loops.values()),
            "hysys": "NOT RUN - Python/DWSIM-equivalent explicitly confirmed by user answer 11"}
