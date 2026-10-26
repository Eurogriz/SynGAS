"""Adiabatic methanol-synthesis march on the VBF kinetics, validated against
the ONE opened non-isothermal worked case that exists for this rate law:
Vanden Bussche & Froment, J. Catal. 161 (1996) 1-10, Table 3 (bench-scale
adiabatic reactor) and the profile end-points printed in Fig. 5.

Why this module exists
---------------------
`model/kinetics_synthesis.py` integrates VBF ISOTHERMALLY, which is what the
493-552 K plant-like comparison in V4 needed, and it reported a methanol outlet
of 30.22 %/pass against an industrial spec of 3.4 mol% -- a mismatch that could
have come either from the rate law or from the isothermal assumption. An
adiabatic march removes that ambiguity: the same published rate law, the same
ideal-gas assumption, but the temperature is now obtained from enthalpy
conservation of THIS model (NIST Shomate for CO/CO2/H2/H2O + the NIST TRC
tabulated Cp for CH3OH), not imposed.

The comparison below is a MODEL-TO-MODEL benchmark: the paper's Table 3 case is
their own simulation of a bench reactor, not a plant measurement, so reproducing
it verifies the implementation (rate wiring, units, energy balance), and nothing
about the catalyst in cases/config.json. Loop 5 stays open.

Run:  PYTHONPATH=. python -m model.methanol_converter
"""
from __future__ import annotations
import json, math, os

from .converter import h_spec, ROOT
from .kinetics_synthesis import vbf_parameters, vbf_rates

R_J = 8.314462618
T_REF = 298.15
VM_NORMAL = 0.02241397

# species carried by the march. 'INERT' is the 11.0 mol% inert of Table 3.
SPECIES = ("CO2", "CO", "H2", "H2O", "CH3OH", "INERT")

_CP = None
_H_CACHE = {}


# ------------------------------------------------------------------ methanol
def _cp_db():
    global _CP
    if _CP is None:
        d = json.load(open(os.path.join(ROOT, "data", "nist_cp_ch3oh.json"),
                           encoding="utf-8"))
        pts = sorted(d["cp_ideal_gas_J_per_mol_K"])
        _CP = {"pts": pts, "dHf": float(d["dHf_gas_298_kJ_per_mol"]["used"]),
               "dHf_alt": float(d["dHf_gas_298_kJ_per_mol"]["alternative"]),
               "db": d}
    return _CP


def cp_methanol(T):
    """Piecewise-linear interpolation of the NIST/TRC ideal-gas Cp table."""
    pts = _cp_db()["pts"]
    if T <= pts[0][0]:
        return pts[0][1]
    if T >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        t0, c0 = pts[i]
        t1, c1 = pts[i + 1]
        if t0 <= T <= t1:
            return c0 + (c1 - c0) * (T - t0) / (t1 - t0)
    return pts[-1][1]


def _h_from(T, cp_fun, dHf):
    """kJ/mol, formation reference at 298.15 K: dHf + int_298^T Cp dT."""
    key = (round(T, 4), dHf, cp_fun.__name__)
    if key in _H_CACHE:
        return _H_CACHE[key]
    pts = [p[0] for p in _cp_db()["pts"] if T_REF <= p[0] <= T]
    grid = sorted(set(pts + [T_REF, T]))
    s = 0.0
    for a, b in zip(grid, grid[1:]):
        s += 0.5 * (cp_fun(a) + cp_fun(b)) * (b - a)          # J/mol
    v = dHf + s / 1000.0
    _H_CACHE[key] = v
    return v


def h_methanol(T, alt_dHf=False):
    db = _cp_db()
    return _h_from(T, cp_methanol, db["dHf_alt"] if alt_dHf else db["dHf"])


def cp_mixture(F, T, inert="N2"):
    """J/K per mol-basis flow unit."""
    tot = 0.0
    for k, v in F.items():
        if v <= 0:
            continue
        if k == "CH3OH":
            tot += v * cp_methanol(T)
        elif k == "INERT" and inert.upper() == "AR":
            tot += v * 2.5 * R_J
        else:
            tot += v * _cp_shomate("N2" if k == "INERT" else k, T)
    return tot


def _cp_shomate(name, T):
    from .thermo import shomate
    from .converter import _pick
    return shomate(_pick(name, T), T)[0]


def h_stream(F, T, inert="N2", alt_dHf=False):
    """kJ per unit-of-flow-hour (F in mol/h)."""
    tot = 0.0
    for k, v in F.items():
        if v <= 0:
            continue
        if k == "CH3OH":
            tot += v * h_methanol(T, alt_dHf)
        elif k == "INERT" and inert.upper() == "AR":
            tot += v * 2.5 * R_J * (T - T_REF) / 1000.0
        else:
            tot += v * h_spec("N2" if k == "INERT" else k, T)
    return tot


def solve_T_march(F, H_target, T_guess, inert="N2", alt_dHf=False,
                  T_lo=350.0, T_hi=1000.0):
    """Adiabatic energy balance: find T with h_stream(F,T) = H_target."""
    T = T_guess
    for _ in range(6):
        H = h_stream(F, T, inert, alt_dHf)
        cp = cp_mixture(F, T, inert)
        if cp <= 0:
            break
        dT = (H_target - H) * 1000.0 / cp
        if not math.isfinite(dT) or abs(dT) > 300.0:
            break
        T += dT
        if abs(dT) < 1e-7:
            return T
    lo, hi = T_lo, T_hi
    for _ in range(80):
        m = 0.5 * (lo + hi)
        if h_stream(F, m, inert, alt_dHf) < H_target:
            lo = m
        else:
            hi = m
    return 0.5 * (lo + hi)


# ------------------------------------------------------------------- the march
def adiabatic_march(F0, p_bar, W_cat_kg, T_in_K, n_steps=800,
                    clamp_fraction=0.10, inert="N2", alt_dHf=False,
                    isothermal=False, profile_stride=0):
    """dF/dW = nu.r (VBF), T from enthalpy conservation. F in mol/h, r in
    mol/(kg_cat s) -> the 3600 factor converts W-basis hours to seconds."""
    h_step = W_cat_kg / n_steps
    F = {k: max(float(F0.get(k, 0.0)), 0.0) for k in SPECIES}
    T = float(T_in_K)
    H0 = h_stream(F, T, inert, alt_dHf)
    nu1 = {"CO2": -1.0, "H2": -3.0, "H2O": 1.0, "CH3OH": 1.0, "CO": 0.0,
           "INERT": 0.0}
    nu2 = {"CO2": -1.0, "H2": -1.0, "H2O": 1.0, "CH3OH": 0.0, "CO": 1.0,
           "INERT": 0.0}
    profile = []
    resid = 0.0
    for i in range(n_steps):
        F_s = {k: v / 3600.0 for k, v in F.items()}        # mol/s for vbf_rates
        r1, r2, _beta = vbf_rates(T, p_bar, F_s)
        r1 = r1 * 3600.0                                    # mol/(kg h)
        r2 = r2 * 3600.0
        # never consume more than clamp_fraction of the limiting reactant per step
        for idx, (r, nu) in enumerate(((r1, nu1), (r2, nu2))):
            if r == 0.0:
                continue
            if r > 0:
                lim = min([F[k] / abs(nu[k]) for k in SPECIES if nu[k] < 0]
                          or [0.0])
            else:
                lim = min([F[k] / abs(nu[k]) for k in SPECIES if nu[k] > 0]
                          or [0.0])
            cap = clamp_fraction * lim / h_step
            if idx == 0:
                r1 = math.copysign(min(abs(r1), cap), r1)
            else:
                r2 = math.copysign(min(abs(r2), cap), r2)
        F = {k: max(F[k] + h_step * (nu1[k] * r1 + nu2[k] * r2), 1e-12)
             for k in SPECIES}
        if isothermal:
            T = float(T_in_K)
        else:
            T = solve_T_march(F, H0, T, inert, alt_dHf)
            resid = max(resid, abs(h_stream(F, T, inert, alt_dHf) - H0)
                        / max(abs(H0), 1e-12))
        if profile_stride and (i % profile_stride == 0 or i == n_steps - 1):
            tot = sum(F.values())
            profile.append({"W_over_Wtot": (i + 1.0) / n_steps, "T_K": round(T, 2),
                            "y_MeOH_molpct": round(100.0 * F["CH3OH"] / tot, 3),
                            "y_CO2_molpct": round(100.0 * F["CO2"] / tot, 3),
                            "y_CO_molpct": round(100.0 * F["CO"] / tot, 3),
                            "y_H2O_molpct": round(100.0 * F["H2O"] / tot, 3)})
    tot_in = sum(F0.get(k, 0.0) for k in SPECIES)
    tot_out = sum(F.values())
    c_in = F0.get("CO2", 0.0) + F0.get("CO", 0.0)
    c_out = F["CO2"] + F["CO"] + F["CH3OH"]
    return {
        "T_in_K": float(T_in_K), "T_out_K": T, "dT_ad_K": T - float(T_in_K),
        "p_bar": p_bar, "W_cat_kg": W_cat_kg, "n_steps": n_steps,
        "isothermal": isothermal, "inert_model": inert,
        "F_in_mol_h": {k: F0.get(k, 0.0) for k in SPECIES},
        "F_out_mol_h": dict(F),
        "total_flow_in_mol_h": tot_in, "total_flow_out_mol_h": tot_out,
        "y_out_molpct": {k: 100.0 * F[k] / tot_out for k in SPECIES},
        "MeOH_formed_mol_h": F["CH3OH"] - F0.get("CH3OH", 0.0),
        "CO2_consumed_mol_h": F0.get("CO2", 0.0) - F["CO2"],
        "CO_consumed_mol_h": F0.get("CO", 0.0) - F["CO"],
        "carbon_closure_rel": abs(c_out - c_in) / max(c_in, 1e-12),
        "enthalpy_residual_rel": resid,
        "dH_meoh_from_this_model_kJ_per_mol": (
            h_stream({"CH3OH": 1.0, "H2O": 1.0}, T, inert, alt_dHf)
            - h_stream({"CO2": 1.0, "H2": 3.0}, T, inert, alt_dHf)),
        "dH_meoh_from_this_model_kJ_per_mol_at_298": (
            h_stream({"CH3OH": 1.0, "H2O": 1.0}, T_REF, inert, alt_dHf)
            - h_stream({"CO2": 1.0, "H2": 3.0}, T_REF, inert, alt_dHf)),
        "dH_co_route_kJ_per_mol_at_298": (
            h_stream({"CH3OH": 1.0}, T_REF, inert, alt_dHf)
            - h_stream({"CO": 1.0, "H2": 2.0}, T_REF, inert, alt_dHf)),
        "profile": profile,
    }


# ------------------------------------------------- the opened worked example
VBF_TABLE3 = {
    "reference": ("Vanden Bussche & Froment, J. Catal. 161 (1996) 1-10, "
                  "Table 3 (operating conditions for the simulation of the "
                  "bench scale reactor) and the end-point values printed for "
                  "Fig. 5 (a)/(b)"),
    "url": "https://terpconnect.umd.edu/~nsw/chbe446/VandenBussche-syngas2MeOH.pdf",
    "doi": "10.1006/jcat.1996.0156",
    "T_in_K": 493.2, "p_bar": 50.0, "mass_flow_kg_s": 2.8e-5,
    "catalyst_mass_g": 34.8, "pellet_diameter_m": 0.0005,
    "reactor_diameter_m": 0.016, "reactor_length_m": 0.15,
    "catalyst_density_kg_m3": 1775.0, "pellet_porosity": 0.5,
    "feed_molpct": {"CO": 4.00, "CO2": 3.00, "H2": 82.00, "H2O": 0.00,
                    "CH3OH": 0.00, "INERT": 11.0},
    "figure5_end": {"CO_molpct": 2.9, "MeOH_molpct": 2.4, "CO2_molpct": 2.1,
                    "H2O_molpct": 1.1, "T_K": 552.0},
    "figure5_start": {"CO_molpct": 4.1, "MeOH_molpct": 0.1, "CO2_molpct": 2.9,
                      "H2O_molpct": 0.1, "T_K": 493.0},
}


def _vbf_case_flows():
    """mol/h of each species for the Table 3 case (mass flow / mean molar mass)."""
    f = VBF_TABLE3["feed_molpct"]
    mw = sum(f[k] * mw_ for k, mw_ in (
        ("CO", 28.010), ("CO2", 44.009), ("H2", 2.0159), ("H2O", 18.0153),
        ("CH3OH", 32.0419), ("INERT", 28.0134))) / 100.0
    mol_s = VBF_TABLE3["mass_flow_kg_s"] / (mw / 1000.0)
    return {k: f[k] / 100.0 * mol_s * 3600.0 for k in SPECIES}, mw


def reproduce_vbf_base_case(n_steps=1200, inert="N2", alt_dHf=False):
    """Run this model on the opened case and compare with the published end point."""
    F0, mw = _vbf_case_flows()
    tgt = VBF_TABLE3["figure5_end"]
    run = adiabatic_march(F0, VBF_TABLE3["p_bar"],
                          VBF_TABLE3["catalyst_mass_g"] / 1000.0,
                          VBF_TABLE3["T_in_K"], n_steps=n_steps, inert=inert,
                          alt_dHf=alt_dHf, profile_stride=max(n_steps // 20, 1))
    iso = adiabatic_march(F0, VBF_TABLE3["p_bar"],
                          VBF_TABLE3["catalyst_mass_g"] / 1000.0,
                          VBF_TABLE3["T_in_K"], n_steps=n_steps, inert=inert,
                          alt_dHf=alt_dHf, isothermal=True)
    y = run["y_out_molpct"]
    comp = {
        "CO_molpct": {"model": y["CO"], "published": tgt["CO_molpct"],
                      "dev_pp": y["CO"] - tgt["CO_molpct"]},
        "CO2_molpct": {"model": y["CO2"], "published": tgt["CO2_molpct"],
                       "dev_pp": y["CO2"] - tgt["CO2_molpct"]},
        "MeOH_molpct": {"model": y["CH3OH"], "published": tgt["MeOH_molpct"],
                        "dev_pp": y["CH3OH"] - tgt["MeOH_molpct"]},
        "H2O_molpct": {"model": y["H2O"], "published": tgt["H2O_molpct"],
                       "dev_pp": y["H2O"] - tgt["H2O_molpct"]},
        "T_out_K": {"model": run["T_out_K"], "published": tgt["T_K"],
                    "dev_K": run["T_out_K"] - tgt["T_K"]},
    }
    # extents reconstructed from the published mole fractions (independent check
    # that the figure end-points are themselves internally consistent)
    # Reconstruct the two reaction extents from the published end point alone, on
    # a basis of 100 mol of feed. MeOH fixes extent a (CO2 + 3H2 -> MeOH + H2O),
    # CO then fixes extent b (RWGS, negative here = net WGS), and CO2/H2O become
    # predictions - a self-consistency test of the published numbers themselves.
    pub = VBF_TABLE3["feed_molpct"]
    y_meoh = tgt["MeOH_molpct"] / 100.0
    a = 100.0 * y_meoh / (1.0 + 2.0 * y_meoh)       # total_out = 100 - 2a
    tot_out = 100.0 - 2.0 * a
    b = tgt["CO_molpct"] / 100.0 * tot_out - pub["CO"]
    pred = {"CO2_molpct": 100.0 * (pub["CO2"] - a - b) / tot_out,
            "H2O_molpct": 100.0 * (pub["H2O"] + a + b) / tot_out,
            "H2_molpct": 100.0 * (pub["H2"] - 3.0 * a - b) / tot_out}
    implied = {
        "basis_mol_feed": 100.0,
        "extent_MeOH_per_100mol_feed": round(a, 3),
        "extent_RWGS_per_100mol_feed": round(b, 3),
        "total_out_mol": round(tot_out, 3),
        "predicted_from_extents": {k: round(v, 3) for k, v in pred.items()},
        "published": {"CO2_molpct": tgt["CO2_molpct"],
                      "H2O_molpct": tgt["H2O_molpct"], "H2_molpct": None},
        "max_self_inconsistency_pp": max(abs(pred[k] - tgt[k])
                                         for k in ("CO2_molpct", "H2O_molpct")),
        "note": ("the published CO2 value is the only tabulated end point that "
                 "does not follow from (a, b) within rounding; the difference is "
                 "smaller than one printed digit, so the figure numbers are usable"),
    }
    max_pp = max(abs(comp[k]["dev_pp"]) for k in comp if k.endswith("molpct"))
    dT = abs(comp["T_out_K"]["dev_K"])
    return {
        "case": "VBF 1996 Table 3 adiabatic bench reactor (base case, Fig. 5)",
        "what_it_is": ("model-to-model benchmark: the published numbers are the "
                       "authors' own simulation of a bench-scale adiabatic "
                       "reactor, computed with the same rate law this module "
                       "uses; it is NOT plant or pilot data"),
        "validity_window_check": {
            "applicability": "180-280 C, 15-51 bar (VBF)",
            "case_T_range_K": [VBF_TABLE3["T_in_K"], round(run["T_out_K"], 1)],
            "inside_window": bool(453.15 <= VBF_TABLE3["T_in_K"] <= 553.15
                                  and 453.15 <= run["T_out_K"] <= 553.15
                                  and 15.0 <= VBF_TABLE3["p_bar"] <= 51.0),
        },
        "inputs": {
            "F_mol_h": F0, "mean_molar_mass_g_per_mol": mw,
            "W_cat_kg": VBF_TABLE3["catalyst_mass_g"] / 1000.0,
            "GHSV_normal_per_m3_pellet_volume_h1": round(
                sum(F0.values()) * VM_NORMAL / (VBF_TABLE3["catalyst_mass_g"]
                                                / 1775.0), 1),
            "space_time_kg_cat_s_per_mol_feed": round(
                (VBF_TABLE3["catalyst_mass_g"] / 1000.0)
                / (sum(F0.values()) / 3600.0), 3),
            "inert_enthalpy_model": inert,
            "dHf_CH3OH_used_kJ_per_mol": _cp_db()["dHf_alt"] if alt_dHf
            else _cp_db()["dHf"],
        },
        "this_model": {
            "T_out_K": run["T_out_K"], "dT_ad_K": run["dT_ad_K"],
            "T_out_K_ignoring_inert_cp_difference_note": None,
            "dT_ad_isothermal_control_K": iso["dT_ad_K"],
            "y_out_molpct": y,
            "MeOH_formed_mol_h": run["MeOH_formed_mol_h"],
            "CO2_consumed_mol_h": run["CO2_consumed_mol_h"],
            "CO_consumed_mol_h": run["CO_consumed_mol_h"],
            "dH_CO2_route_kJ_per_mol_at_T_out":
                run["dH_meoh_from_this_model_kJ_per_mol"],
            "dH_CO2_route_kJ_per_mol_at_298_K":
                run["dH_meoh_from_this_model_kJ_per_mol_at_298"],
            "dH_CO_route_kJ_per_mol_at_298_K": run["dH_co_route_kJ_per_mol_at_298"],
            "carbon_closure_rel": run["carbon_closure_rel"],
            "enthalpy_residual_rel": run["enthalpy_residual_rel"],
        },
        "comparison": comp,
        "max_abs_composition_deviation_pp": max_pp,
        "abs_T_deviation_K": dT,
        "published_end_point_self_consistency": implied,
        "criteria": {
            "composition_within_pp": 0.5,
            "T_within_K": 15.0,
            "note": ("thresholds fixed before looking at the result: 0.5 mol% "
                     "because the published values are printed to one decimal at "
                     "a digitised profile end point, 15 K because the same rise is "
                     "sensitive to the (unstated) inert species and to dHf(CH3OH) "
                     "by a few K"),
        },
        "reproduced": bool(max_pp <= 0.5 and dT <= 15.0),
        "profile": run["profile"],
        "status": ("[ПОДТВЕРЖДЕНО] сравнение смоделировано по открытому кейсу; "
                   "[ЧАСТИЧНО] инерт в Table 3 не назван, dHf(CH3OH) на странице "
                   "NIST дан как −205±10 (использовано −201,49 из той же страницы)"),
        "conclusion": "",
    }


def sensitivity_to_open_choices(n_steps=1200):
    """Same case, same code, three documented alternatives."""
    out = []
    for label, kw in (
            ("base: inert = N2, dHf(CH3OH) = -201.49 kJ/mol", {}),
            ("inert = Ar (Table 3 does not name the inert)", {"inert": "AR"}),
            ("dHf(CH3OH) = -205 kJ/mol (NIST 'AVG of 9 values')",
             {"alt_dHf": True}),
            ("isothermal 493.2 K (what kinetics_synthesis.py does today)",
             {"isothermal_note": True}),
    ):
        if kw.pop("isothermal_note", False):
            F0, _ = _vbf_case_flows()
            r = adiabatic_march(F0, VBF_TABLE3["p_bar"],
                                VBF_TABLE3["catalyst_mass_g"] / 1000.0,
                                VBF_TABLE3["T_in_K"], n_steps=n_steps,
                                isothermal=True)
            out.append({"variant": label, "T_out_K": r["T_out_K"],
                        "MeOH_molpct": r["y_out_molpct"]["CH3OH"],
                        "CO2_molpct": r["y_out_molpct"]["CO2"],
                        "CO_molpct": r["y_out_molpct"]["CO"],
                        "H2O_molpct": r["y_out_molpct"]["H2O"]})
            continue
        r = reproduce_vbf_base_case(n_steps=n_steps, **kw)
        y = r["this_model"]["y_out_molpct"]
        out.append({"variant": label, "T_out_K": r["this_model"]["T_out_K"],
                    "dT_ad_K": r["this_model"]["dT_ad_K"],
                    "MeOH_molpct": y["CH3OH"], "CO2_molpct": y["CO2"],
                    "CO_molpct": y["CO"], "H2O_molpct": y["H2O"],
                    "reproduced": r["reproduced"]})
    return out


def cp_integration_error(T_lo=298.15, T_hi=600.0, n=400):
    """Trapezoid on the published grid vs a refined integration of the same
    piecewise-linear Cp (exact for linear segments), plus the same on Simpson."""
    fine = 0.0
    h = (T_hi - T_lo) / n
    for i in range(n):
        t = T_lo + (i + 0.5) * h
        fine += cp_methanol(t) * h                 # midpoint, exact for linear
    pts = [p[0] for p in _cp_db()["pts"] if T_lo <= p[0] <= T_hi]
    grid = sorted(set(pts + [T_lo, T_hi]))
    trap = 0.0
    for a, b in zip(grid, grid[1:]):
        trap += 0.5 * (cp_methanol(a) + cp_methanol(b)) * (b - a)
    return {"T_range_K": [T_lo, T_hi], "coarse_J_per_mol": trap,
            "refined_J_per_mol": fine, "abs_error_J_per_mol": trap - fine,
            "rel_error": abs(trap - fine) / max(fine, 1e-12)}


def build_report(n_steps=1200):
    """Everything docs/31 and the loop-5 subcheck need, in one dict."""
    rep = reproduce_vbf_base_case(n_steps=n_steps)
    rep["sensitivity"] = sensitivity_to_open_choices(n_steps=n_steps)
    rep["cp_integration_error"] = cp_integration_error()
    dT_pub = VBF_TABLE3["figure5_end"]["T_K"] - VBF_TABLE3["T_in_K"]
    mine = rep["this_model"]["dT_ad_K"]
    rep["adiabatic_rise"] = {"published_K": dT_pub, "this_model_K": mine,
                             "ratio": mine / dT_pub if dT_pub else None}
    verdict = ("reproduced" if rep["reproduced"] else "NOT reproduced")
    rep["conclusion"] = (
        "the adiabatic march on the published VBF rate law gives T_out = "
        "%.1f K (rise %.1f K vs %.1f K published) and outlet CO2/CO/MeOH/H2O = "
        "%.2f/%.2f/%.2f/%.2f mol%% vs published 2.1/2.9/2.4/1.1 mol%% -> %s "
        "within the pre-declared tolerances (0.5 mol%%, 15 K). Carbon closes to "
        "%.1e and the enthalpy residual is %.1e, so the energy balance and the "
        "rate wiring are internally consistent."
        % (rep["this_model"]["T_out_K"], mine, dT_pub,
           rep["this_model"]["y_out_molpct"]["CO2"],
           rep["this_model"]["y_out_molpct"]["CO"],
           rep["this_model"]["y_out_molpct"]["CH3OH"],
           rep["this_model"]["y_out_molpct"]["H2O"], verdict,
           rep["this_model"]["carbon_closure_rel"],
           rep["this_model"]["enthalpy_residual_rel"]))
    return rep


def main():
    rep = build_report()
    os.makedirs(os.path.join(ROOT, "results_v2"), exist_ok=True)
    path = os.path.join(ROOT, "results_v2", "methanol_adiabatic_check.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, ensure_ascii=False, default=float)
    print(json.dumps({k: rep[k] for k in
                      ("reproduced", "max_abs_composition_deviation_pp",
                       "abs_T_deviation_K", "adiabatic_rise")},
                     indent=1, ensure_ascii=False))
    print(rep["conclusion"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
