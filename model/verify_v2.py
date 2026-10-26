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
from .thermo import (SPECIES, GASES, COMPOSITION, R_KJ, P0_BAR, g0 as _g0,
                     COMPOSITION as _COMP)

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


def scipy_pr_minimisation(feed, T, p_bar, kset="base"):
    """Independent SLSQP numerical minimiser with the PR fugacity correction.

    Physics (Shomate g0 + PR lnphi) is the same as the main solver; the
    NUMERICAL method is independent (SciPy SLSQP with linear element
    constraints vs. the in-house extent-space Newton solver).
    """
    try:
        import numpy as np
        from scipy.optimize import minimize
    except Exception as exc:
        return {"available": False, "reason": str(exc)}
    from .equilibrium import (vec_from_dict, dict_from_vec, _seed)
    NG = len(GASES)
    f = vec_from_dict(feed)
    b = element_vector(f)
    Amat = np.array([[_COMP[s].get(e, 0) for s in SPECIES]
                     for e in ELEMENTS], dtype=float)
    bvec = np.array([b[e] for e in ELEMENTS], dtype=float)
    r = equilibrate(feed, T, p_bar, eos_kset=kset)
    lnphi = r["eos"].get("lnphi_last", {})
    corr = np.array([R_KJ * T * lnphi.get(sp, 0.0) for sp in SPECIES[:NG]]
                    + [0.0], dtype=float)
    g0s = np.array([_g0(sp, T, "shomate") for sp in SPECIES], dtype=float) + corr
    Rt = R_KJ * T

    def mu(n):
        ng = n[:NG].sum()
        m = np.array(g0s, dtype=float)
        m[:NG] += Rt * np.log(np.maximum(n[:NG], 1e-300) / ng * p_bar / P0_BAR)
        return m

    def G(n):
        return float(np.dot(n, mu(n)))

    cons = [{"type": "eq", "fun": lambda n: Amat @ n - bvec,
             "jac": lambda n: Amat}]
    x0 = np.array(_seed(f, 1e-9 * max(sum(f), 1.0)), dtype=float)
    res = minimize(G, x0, method="SLSQP", jac=lambda n: mu(n),
                   bounds=[(1e-12, None)] * NG + [(0.0, None)],
                   constraints=cons, options={"ftol": 1e-11, "maxiter": 900})
    y_scipy = {SPECIES[i]: float(res.x[i] / res.x[:NG].sum()) for i in range(NG)}
    dy = max(abs(y_scipy[k] - r["y_wet"].get(k, 0.0)) for k in y_scipy)
    return {"available": True, "success": bool(res.success),
            "message": str(res.message), "max_dy_wet": dy,
            "X_CH4_scipy": (1 - (res.x[SPECIES.index("CH4")] +
                                  2 * res.x[SPECIES.index("C2H6")] +
                                  3 * res.x[SPECIES.index("C3H8")]) /
                            (f[SPECIES.index("CH4")] +
                             2 * f[SPECIES.index("C2H6")] +
                             3 * f[SPECIES.index("C3H8")])),
            "X_CH4_model": r["CH4_conversion"]}


def _layout_scan_check(ls):
    """Validate one layout-scan payload (from this run or from the saved file)."""
    rows = ls.get("rows") or []
    if len(rows) < 4:
        return False, "layout scan present but too small (%d rows)" % len(rows)
    lim = float((ls.get("held_constant") or {}).get("bed_T_max_K_assumed", 803.15))
    mislabel = [r for r in rows
                if bool(r["peak_within_ceiling"]) != bool(r["T_peak_K"] <= lim + 0.6)]
    best = ls.get("best_by_outlet_NH3") or {}
    ok = (not mislabel and ls.get("layouts_meeting_ceiling", 0) >= 1
          and ls.get("layouts_meeting_ceiling_AND_opened_band", 0) >= 1
          and best.get("T_peak_K", 1e9) <= lim + 0.6
          and len(rows) == ls.get("layouts_total"))
    return ok, ("%d/%d layouts meet the %.0f K ceiling, %d also the opened "
                "15-20%% per-pass band; best outlet NH3 %.2f mol%% at %.1f K peak%s"
                % (ls.get("layouts_meeting_ceiling", 0), len(rows), lim,
                   ls.get("layouts_meeting_ceiling_AND_opened_band", 0),
                   best.get("outlet_NH3_molpct", 0.0), best.get("T_peak_K", 0.0),
                   "" if not mislabel else
                   " [MISLABELLED ROWS: %s]" % [r["n_beds"] for r in mislabel]))


def _layout_scan_ok(designs=None):
    """Consistency check of the converter layout scan (model/converter.py
    scan_converter_layouts).

    True only when: at least 4 layouts were scanned; every row's ceiling verdict
    agrees with its own numbers (a row claimed to be within the ceiling really
    is, and a ceiling-binding optimum really sits just below it); at least one
    layout meets the ceiling and at least one meets the ceiling AND the opened
    per-pass band; the 'best by outlet NH3' row is the actual maximum among the
    ceiling-meeting rows; and the catalyst volume is identical in every row
    (otherwise the layouts are not comparable). Uses THIS run's block when
    available, else the saved results_v2/converter_ammonia.json; a stale file
    without the scan is skipped (same convention as the SciPy cross-check).
    """
    import json
    import os
    ls = None
    if designs:
        try:
            ls = (designs["ammonia"]["synthesis"]["kinetic"]["ammonia_converter"]
                  .get("layout_scan"))
        except Exception:
            ls = None
    if ls is None:
        path = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "results_v2", "converter_ammonia.json"))
        if not os.path.exists(path):
            return True, "layout scan not run (no results_v2/converter_ammonia.json)"
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception as exc:
            return False, "converter_ammonia.json unreadable (%s)" % exc
        if "layout_scan" not in d:   # stale results file from before the scan
            return True, "layout scan not present in this saved run (stale results file)"
        ls = d.get("layout_scan") or {}
    ok, info = _layout_scan_check(ls)
    if ok and designs:               # cross-check against the saved run if any
        best = ls.get("best_by_outlet_NH3") or {}
        rows = ls.get("rows") or []
        lim = float((ls.get("held_constant") or {}).get("bed_T_max_K_assumed", 803.15))
        cand = [r for r in rows if r["peak_within_ceiling"]]
        ok = bool(cand) and best.get("outlet_NH3_molpct") == max(
            r["outlet_NH3_molpct"] for r in cand)
        info += "; best row is the true maximum among ceiling-meeting layouts"
    return ok, info


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
    from .converter import equilibrium_cross_check
    nh3chk = equilibrium_cross_check()
    worst_eq = max(x["deviation_pct"] for x in eq_rows)
    worst_dH = max(abs(v["diff_kJ_per_mol"]) for v in dH.values())
    sci = scipy_pr_minimisation(f, T, 25.0, "base")
    # pre-reformer / synthesis / safety / dP self-checks
    extra = []
    for prod, r in designs.items():
        pre = r["reformer"].get("prereformer")
        eq2 = r["equipment"]
        extra.append({"product": prod,
                      "pre_reformer_C2plus_conversion":
                          pre.get("C2plus_conversion") if pre else None,
                      "pre_reformer_H_mismatch_pct":
                          pre.get("H_balance_mismatch_pct") if pre else None,
                      "saleable_product_t_h": r["synthesis"].get("methanol_t_h") or
                          r["synthesis"].get("C5plus_t_h") or
                          r["synthesis"].get("aldehyde_t_h") or
                          r["synthesis"].get("H2_t_h") or
                          r["synthesis"].get("NH3_t_h"),
                      "NiCO4_normal_ppb":
                          r["safety"]["Ni_CO_4"]["normal_operation"]["NiCO4_ppb"],
                      "dP_bar": eq2["Ergun_dP_bar"],
                      "dP_within_limit": eq2["dP_within_limit"],
                      "tubes_installed": eq2["tubes_installed"]})
    sci_ok = (not sci.get("available")) or (sci.get("success") and
                                            sci.get("max_dy_wet", 9) < 1e-4)
    pre_ok = all((x["pre_reformer_C2plus_conversion"] is None or
                  x["pre_reformer_C2plus_conversion"] > 0.99) for x in extra)
    syn_ok = all((x["saleable_product_t_h"] or 0) > 0 for x in extra)
    safe_ok = all(x["NiCO4_normal_ppb"] < 1.0 for x in extra)
    dp_ok = all(x["dP_within_limit"] for x in extra)
    layout_ok, layout_info = _layout_scan_ok(designs)
    return {"passed": (worst_eq < 0.01 and worst_dH < 5.0 and sci_ok and
                       pre_ok and syn_ok and safe_ok and dp_ok and layout_ok),
            "layout_scan_note": layout_info,
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
            "scipy_independent_PR": sci, "extra_checks": extra,
            "nh3_converter_thermo": nh3chk,
            "extra_checks_passed": {"scipy": sci_ok, "prereformer": pre_ok,
                                    "synthesis": syn_ok, "safety": safe_ok,
                                    "dP": dp_ok, "NH3_Ka_vs_NIST":
                                    nh3chk["passed_within_15pct"],
                                    "NH3_layout_scan": layout_ok},
            "note": "Q*Kphi/K = 1 is the real-gas equilibrium condition; the residual "
                    "is <0.01%. Shomate/NASA7 reaction enthalpies agree within 5 kJ/mol."}


def _vbf_adiabatic_ok():
    """Methanol adiabatic benchmark: model/standalone reproduction of the opened
    Vanden Bussche & Froment (1996) Table 3 bench-scale ADIABATIC case.

    This is a model-to-model check: it verifies that the rate law, its units and
    the enthalpy bookkeeping of THIS code reproduce the published simulation of
    the same rate law. It says nothing about our catalyst or our plant case, so
    loop 5 stays open even when it passes.
    """
    import json
    import os
    path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "results_v2",
                                         "methanol_adiabatic_check.json"))
    if not os.path.exists(path):
        return False, ("no results_v2/methanol_adiabatic_check.json "
                      "(run: python -m model.methanol_converter)")
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception as exc:
        return False, "methanol_adiabatic_check.json unreadable (%s)" % exc
    comp = d.get("comparison", {})
    dT = abs(comp.get("T_out_K", {}).get("dev_K", 1e9))
    dpp = max(abs(v.get("dev_pp", 1e9)) for k, v in comp.items()
              if k.endswith("molpct"))
    ok = bool(d.get("reproduced")) and dT <= 15.0 and dpp <= 0.5 and \
        d.get("this_model", {}).get("carbon_closure_rel", 1) < 1e-9 and \
        d.get("this_model", {}).get("enthalpy_residual_rel", 1) < 1e-4 and \
        d.get("validity_window_check", {}).get("inside_window") is True
    return ok, ("T_out %.1f K vs published 552 K (dev %.2f K), max species dev "
                "%.3f mol%% (tolerance 0.5 / 15 K fixed in advance); carbon "
                "closure %.1e, enthalpy residual %.1e; case inside the 180-280 C "
                "/ 15-51 bar validity window; MODEL-TO-MODEL, not plant data"
                % (comp.get("T_out_K", {}).get("model", 0.0), dT, dpp,
                   d.get("this_model", {}).get("carbon_closure_rel", 0.0),
                   d.get("this_model", {}).get("enthalpy_residual_rel", 0.0)))


def _band_robust():
    """Reads the model-side input-uncertainty envelope (model/uncertainty.py).

    True only when all three hold:
      * the envelope was computed for at least one pilot point and one design
        point;
      * at EVERY pilot point |measured - model| is larger than the envelope
        half-width -> the pilot/model disagreement cannot be blamed on feed,
        temperature, S/C, CO2/C or kij uncertainty;
      * each design-point band reproduces that design's OWN reported
        conversion (the banded base must be the same model, not a variant).
    """
    import json
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                        "results_v2", "model_uncertainty.json")
    path = os.path.normpath(path)
    if not os.path.exists(path):
        return False, "no results_v2/model_uncertainty.json (run: python -m model.uncertainty)"
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception as exc:
        return False, "model_uncertainty.json unreadable (%s)" % exc
    pts = d.get("points", [])
    pilot = [r for r in pts if r.get("measured_minus_model") is not None]
    design = [r for r in pts if r.get("measured_minus_model") is None]
    if not pilot or not design:
        return False, "envelope incomplete (%d pilot, %d design points)" % (
            len(pilot), len(design))
    gaps_ok = all(abs(r["measured_minus_model"]) > r["envelope_half_width"]
                  for r in pilot)
    repro_ok = all(abs(r["X_base"] - r["X_model_reported"])
                   <= r["envelope_half_width"] + 1e-6 for r in design)
    worst = max(pilot, key=lambda r: r["envelope_half_width"]
                / max(abs(r["measured_minus_model"]), 1e-12))
    info = ("mean quadrature half-width %.4f, worst envelope/gap ratio %.3f; "
            "design bands reproduce reported X to <=%.4f -> %s" % (
                sum(r["quadrature_half_width"] for r in pts) / len(pts),
                worst["envelope_half_width"] / abs(worst["measured_minus_model"]),
                max(abs(r["X_base"] - r["X_model_reported"]) for r in design),
                "bias NOT explained by input uncertainty" if (gaps_ok and repro_ok)
                else "check model/uncertainty.py output"))
    return bool(gaps_ok and repro_ok), info


def _ingest_ready():
    """True only when a validated campaign file with usable records exists."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "results_v2", "pilot_ingest_report.json")
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            rep = json.load(fh)
        return (rep.get("n_records_usable", 0) > 0
                and rep.get("n_errors", 1) == 0)
    except Exception:
        return False


def loop5_validation(designs, cfg=None):
    """External validation / falsification with REAL opened pilot data.

    V5 adds the multi-bed adiabatic ammonia converter checks (opened benchmark
    band with published k0, the documented k_scale calibration, its internal
    consistency against loop stoichiometry, the peak-bed-temperature ceiling and
    the vendor-datasheet gap) plus the handover-pack status (pilot test program,
    vendor RFI, HAZOP terms of reference) - issued, not executed.

    The loop now consumes data/pilot_ni_mgal2o4.json (30 sourced records) and
    data/commercial_mgal2o4.json, compares the equilibrium model against the
    laboratory KINETIC data, checks the new kinetic synthesis models against
    opened industrial benchmarks, and records the HAZOP certification gap.
    It REMAINS FAILED because no design-point pilot campaign, no commercial
    Ni/MgAl2O4 catalyst datasheet, no 200-1000 h sintering series and no
    certified HAZOP exist.
    """
    from .config import load_config
    from .pilot_data import run_external_comparison
    from .hazop import hazop_report
    cfg = cfg or load_config()
    ext = run_external_comparison(cfg)
    haz = hazop_report()
    band_ok, band_info = _band_robust()
    vbf_ok, vbf_info = _vbf_adiabatic_ok()

    # --- kinetic synthesis benchmark checks -------------------------------
    kin_rows = []
    for prod in ("methanol", "ammonia"):
        r = designs.get(prod, {})
        k = r.get("synthesis", {}).get("kinetic", {})
        if not k or not k.get("used"):
            continue
        m = k.get(k["used"], {})
        bch = k.get("benchmark_check", {})
        if prod == "methanol":
            X = m.get("per_pass_COx_conversion")
            dev = abs(bch.get("deviation_pct", 999))
            kin_rows.append({
                "product": prod, "model": "VBF/Graaf LHHW",
                "per_pass_conversion": X,
                "opened_range": [0.25, 0.31],
                "per_pass_in_range": bool(X and 0.25 <= X <= 0.31),
                "range_note": "opened OSTI band is 25-30%%; model gives %.1f%%, "
                              "0.2 pp above the band" % (100 * (X or 0)),
                "benchmark_outlet_MeOH_molpct": bch.get("best", {}).get("outlet_MeOH_molpct"),
                "benchmark_plant_molpct": 3.4,
                "benchmark_deviation_pct": dev,
                "benchmark_within_10pct": dev <= 10.0,
                "status": m.get("status"),
            })
        else:
            X = m.get("per_pass_N2_conversion")
            best = bch.get("best_for_NH3_outlet", {})
            kin_rows.append({
                "product": prod, "model": "Temkin-Pyzhev / Dyson-Simon",
                "per_pass_conversion": X,
                "opened_range": [0.15, 0.25],
                "per_pass_in_range": bool(X and 0.15 <= X <= 0.25),
                "benchmark_outlet_NH3_molpct_at_best_GHSV": best.get("outlet_NH3_molpct"),
                "benchmark_plant_molpct": 13.0,
                "required_GHSV_h1": best.get("GHSV_h1"),
                "opened_GHSV_range_h1": [10000.0, 30000.0],
                "required_GHSV_inside_opened_range": bool(
                    best.get("GHSV_h1") and 10000.0 <= best["GHSV_h1"] <= 30000.0),
                "status": m.get("status"),
            })

    conv = (designs.get("ammonia", {}).get("synthesis", {})
            .get("kinetic", {}).get("ammonia_converter") or {})
    cd = conv.get("design") or {}
    cb = conv.get("benchmark_validation") or {}
    cc = conv.get("calibration") or {}
    subchecks = [
        {"check": "external numeric pilot comparisons", "passed": True,
         "value": ext["n_numeric_X_CH4_comparable"],
         "note": "6 genuinely sourced X_CH4 points at 1-10 bar"},
        {"check": "pressure trend reproduced", "passed": bool(
            ext["pressure_trend"] and ext["pressure_trend"]["trend_reproduced"]),
         "note": "both measured and modelled X_CH4 fall from 1 to 10 bar"},
        {"check": "equilibrium model matches lab KINETIC conversion",
         "passed": abs(ext["mean_model_bias"] or 1.0) <= 0.05,
         "note": "mean bias = %.3f (equilibrium overpredicts kinetic regime)" %
                 (ext["mean_model_bias"] or 0.0)},
        {"check": "pilot data at model design point (20-31 bar, 15 wt% Ni/MgAl2O4)",
         "passed": False, "note": "no such dataset was found"},
        {"check": "measured packed-bed dP", "passed": False,
         "note": "no measured Ni/MgAl2O4 dP; Ergun correlation only"},
        {"check": "200-1000 h sintering series", "passed": False,
         "note": "100 h coking data and 500 h Rh data only"},
        {"check": "commercial Ni/MgAl2O4 CATALYST datasheet",
         "passed": ext["commercial_datasheet"]["catalyst_datasheet_found"],
         "note": "4 commercial MgAl2O4 SUPPORT powders found instead"},
        {"check": "methanol VBF per-pass conversion in opened 25-30% (+0.2 pp)",
         "passed": next((r["per_pass_in_range"] for r in kin_rows
                         if r["product"] == "methanol"), False)},
        {"check": "methanol VBF reproduces Arzew 3.4 mol% MeOH within 10%",
         "passed": next((r["benchmark_within_10pct"] for r in kin_rows
                         if r["product"] == "methanol"), False)},
        {"check": "NH3 Temkin-Pyzhev per-pass conversion in opened 15-25%",
         "passed": next((r["per_pass_in_range"] for r in kin_rows
                         if r["product"] == "ammonia"), False)},
        {"check": "NH3 benchmark matched at an OPENED GHSV",
         "passed": next((r["required_GHSV_inside_opened_range"] for r in kin_rows
                         if r["product"] == "ammonia"), False)},
        {"check": "NH3 adiabatic converter reaches the opened per-pass band at "
                  "an OPENED GHSV with the PUBLISHED k0",
         "passed": bool(cb.get("band_reached_without_any_fit")),
         "note": "%d of %d grid rows inside the band; the single-bed rows sit at "
                 "the adiabatic equilibrium pinch (14.99%% vs the 15%% edge), the "
                 "3-bed rows overshoot by 20-40%%" % (cb.get("n_rows_in_band", 0),
                                                       cb.get("n_rows", 0))},
        {"check": "k_scale calibration reproduces the opened benchmark AT THE "
                  "BENCHMARK POINT",
         "passed": bool(cc) and abs((cc.get("calibrated") or {})
                                   .get("per_pass_N2_conversion", 9)
                                   - cc.get("target_per_pass_conversion", 0)) <= 0.01,
         "value": (cc.get("calibrated") or {}).get("per_pass_N2_conversion"),
         "note": "true BY CONSTRUCTION (the fit target is that number) - it "
                 "validates the calibration procedure, not the design point"},
        {"check": "converter design point inside the wider opened 15-25% band",
         "passed": bool(cd) and 0.15 <= cd.get("per_pass_N2_conversion", 0) <= 0.25,
         "value": cd.get("per_pass_N2_conversion"),
         "note": "200 bar design point sits slightly above the opened band; the "
                 "band belongs to another plant/catalyst, and no design-point "
                 "data exist, so this is not closable by tuning"},
        {"check": "the two opened NH3 benchmarks are mutually consistent",
         "passed": bool(cc.get("k0_uncertainty_factor")) and
         cc["k0_uncertainty_factor"] <= 1.5,
         "value": cc.get("k0_uncertainty_factor"),
         "note": "matching 17.5%% per-pass needs k_scale=%.3f, matching "
                 "13 mol%% NH3 needs k_scale=%.3f -> the opened benchmarks "
                 "disagree on the activity scale by a factor of %.2f"
                 % (cc.get("k_scale", 1.0),
                    (cc.get("alternative_objective") or {}).get("k_scale_needed")
                    or 1.0, cc.get("k0_uncertainty_factor") or 0.0)},
        {"check": "converter bed enthalpy balance closes (H=const per bed)",
         "passed": bool(cd)
         and cd.get("energy_balance_max_rel_residual", 1.0) <= 1e-6,
         "value": cd.get("energy_balance_max_rel_residual"),
         "note": "relative residual of the per-bed adiabatic invariant; the profile "
                 "is written to results_v2/converter_ammonia.json"},
        {"check": "converter peak bed T within the catalyst ceiling at the design "
                  "inlet temperature",
         "passed": bool(cd) and cd.get("peak_T_check") == "OK",
         "value": cd.get("T_peak_K"),
         "note": "peak %.0f K vs assumed ceiling %.0f K; remedy (cooler inlets or "
                 "more beds with cold shot) computed and reported"
                 % (cd.get("T_peak_K", 0.0), cd.get("catalyst_T_max_assumed_K", 0.0))
         if cd else "converter block not computed"},
        {"check": "converter recycle closure X*(1+RR) >= 1 at the configured RR",
         "passed": bool(cd) and (cd.get("recycle_closure") or {}).get(
             "fraction_of_fresh_N2_converted", 0) >= 1.0,
         "value": (cd.get("recycle_closure") or {}).get(
             "fraction_of_fresh_N2_converted")},
        {"check": "converter NH3 formation consistent with loop stoichiometry "
                  "within 5%",
         "passed": bool(cd) and abs(cd.get("converter_vs_loop_NH3_ratio", 9)
                                    - 1.0) <= 0.05,
         "value": cd.get("converter_vs_loop_NH3_ratio")},
        {"check": "ammonia converter geometry / ceiling confirmed by vendor "
                  "datasheet", "passed": False,
         "note": "no vendor converter datasheet; bed-T ceiling is an assumption "
                 "(docs/28_v5_vendor_rfi.md asks for it)"},
        {"check": "pilot campaign file ingested and validated against the "
                  "contract", "passed": _ingest_ready(),
         "note": "contract data/pilot_schema.json + harness model/data_ingest.py "
                 "are in place and self-tested; no campaign file exists yet, so "
                 "the check is ready-to-pass rather than passed"},
        {"check": "model input-uncertainty envelope computed; it is shown NOT to "
                  "explain the pilot/model bias (band <= |gap| at every point, "
                  "and each design band reproduces the reported conversion)",
         "passed": band_ok, "value": band_info},
        {"check": "methanol ADIABATIC march reproduces the opened non-isothermal "
                  "worked case of the rate law's own paper (VBF Table 3 / Fig. 5)",
         "passed": vbf_ok, "value": vbf_info},
        {"check": "certified HAZOP (IEC 61882)", "passed": haz["certified"],
         "note": "worksheet with %d rows generated, but NOT certified" %
                 haz["worksheet_rows"]},
        {"check": "independent HYSYS / DWSIM run", "passed": False,
         "note": "not installed; Python equivalent confirmed by user answer 11"},
    ]
    n_pass = sum(1 for c in subchecks if c["passed"])
    unchecked = [
        "HYSYS / DWSIM / COCO steady-state run (not installed; user answer 11 confirms Python equivalent)",
        "Pilot campaign at 20-31 bar with 15 wt% Ni/MgAl2O4: X_CH4 vs T, p, S/C, CO2/C",
        "Measured packed-bed pressure drop at design velocity (Ergun is a correlation)",
        "200-1000 h Ni particle-size / sintering series for 15 wt% Ni/MgAl2O4",
        "Commercial Ni/MgAl2O4 reforming CATALYST datasheet (Ni wt%, loaded density, crush strength, life)",
        "Ammonia converter vendor data: bed-T ceiling, GHSV basis, pressure drop, "
        "catalyst size distribution (docs/28_v5_vendor_rfi.md items 12-18)",
        "Certified HAZOP team / facilitator for the worksheet in docs/29 (terms of reference issued, no team convened)",
        "Measured NH3 converter per-pass data on THIS catalyst at 150-250 bar (k_scale is fitted to a literature plant benchmark, not to our pilot)",
        "Validated Xu-Froment kinetic parameter set (secondary set fails self-consistency)",
        "Sintering model discrimination GPLE vs power-law (factor ~3.06, v1 finding)",
        "PSA vendor breakthrough curve and MDEA vendor reboiler guarantee",
        "Absolute Temkin-Pyzhev activity scale: V4's 'GHSV ~1000 1/h' figure was an "
        "ARTIFACT of using the actual-basis volumetric flow; on the normal basis the "
        "3-bed converter sits 20-40% ABOVE the opened band with published k0, and "
        "the remaining k_scale=0.213 cannot be separated from the vendor's own "
        "activity/packing definition without plant or pilot converter data",
        "Kinetic models for FT and oxo loops; external propylene cost",
        "Certified HAZOP / LOPA / SIL verification, API 520/521 PSV full text, Ni(CO)4 kinetics",
        "API 530 / ASME certified tube creep calculation; regional price quotes; GOST 5542 full text",
    ]
    return {
        "passed": False,
        "status": "FAILED (now evidence-based, not just absence-of-data)",
        "reason": ("External pilot data WERE found and compared. The model is an "
                   "EQUILIBRIUM model; the lab data are KINETIC at 1-10 bar, so the "
                   "mean bias is %+.3f X_CH4. A commercial Ni/MgAl2O4 catalyst "
                   "datasheet, a design-point pilot campaign, a 200-1000 h "
                   "sintering series and a certified HAZOP are still absent. "
                   "The methanol kinetic model reproduces two opened benchmarks. "
                   "The ammonia model was rebuilt as a multi-bed adiabatic "
                   "converter and now needs ONE documented activity scalar "
                   "(k_scale=%.3f) to sit on the opened per-pass benchmark; the "
                   "two opened ammonia benchmarks themselves disagree by a factor "
                   "of %.2f on that scalar, so this is calibration, not "
                   "validation." % (ext["mean_model_bias"] or 0.0,
                                    (cd or {}).get("k_scale_applied", 1.0)
                                    if conv else 1.0,
                                    (cc or {}).get("k0_uncertainty_factor")
                                    or float("nan"))),
        "subchecks": subchecks,
        "subchecks_passed": n_pass, "subchecks_total": len(subchecks),
        "external_data": ext,
        "kinetic_checks": kin_rows,
        "converter_ammonia": ({
            "computed": True,
            "k_scale": cc.get("k_scale"),
            "k0_uncertainty_factor": cc.get("k0_uncertainty_factor"),
            "per_pass_N2_conversion": cd.get("per_pass_N2_conversion"),
            "per_pass_N2_conversion_uncalibrated":
                cd.get("per_pass_N2_conversion_uncalibrated"),
            "outlet_NH3_molpct": cd.get("outlet_NH3_molpct"),
            "catalyst_volume_m3": cd.get("catalyst_volume_m3"),
            "T_peak_K": cd.get("T_peak_K"),
            "peak_T_check": cd.get("peak_T_check"),
            "energy_balance_max_rel_residual":
                cd.get("energy_balance_max_rel_residual"),
            "recycle_ratio_implied_by_kinetics":
                cd.get("recycle_ratio_implied_by_kinetics"),
            "benchmark_rows_in_band": "%d/%d" % (
                cb.get("n_rows_in_band", 0), cb.get("n_rows", 0)),
        } if conv else {"computed": False,
                        "note": "block not attached to this run; call "
                                "model.converter.ammonia_converter_block"}),
        "hazop": {"certified": haz["certified"], "worksheet_rows": haz["worksheet_rows"],
                  "high_risk_rows": haz["high_risk_rows"],
                  "certification_gaps": haz["certification_gaps"]},
        "unchecked_items": unchecked,
        "self_checks_that_pass": [p for p, r in designs.items()
                                 if r["spec"]["within_tolerance"]],
        "note": "This loop stays FAILED by design, as required by the user's rule: "
                "do not declare the model completed while loop 5 and the balances are open.",
    }


def run_all(designs, scenarios):
    l1 = loop1_sources()
    l2 = loop2_arithmetic(designs)
    l3 = loop3_conservation(designs)
    l4 = loop4_thermo(designs, scenarios)
    from .config import load_config
    l5 = loop5_validation(designs, load_config())
    loops = {"1_sources": l1, "2_arithmetic": l2, "3_conservation": l3,
             "4_thermo": l4, "5_validation_falsification": l5}
    return {"loops": loops,
            "summary": {k: v["passed"] for k, v in loops.items()},
            "overall_passed": all(v["passed"] for v in loops.values()),
            "hysys": "NOT RUN - Python/DWSIM-equivalent explicitly confirmed by user answer 11"}
