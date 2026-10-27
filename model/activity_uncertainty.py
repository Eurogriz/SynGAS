"""V5.2 - propagate the ONE undocumented model parameter (catalyst activity)
through the whole ammonia project, so the design is reported as a corridor.

Where the factor comes from
---------------------------
`model/converter.py:calibrate_k0` fits a single dimensionless activity scalar
`k_scale` on the Temkin-Pyzhev pre-exponential against TWO opened industrial
benchmarks that disagree:

  * mid-band per-pass objective (17.5 % N2 per pass at 150 bar / 20 000 h-1)
    -> k_scale = k_lo;
  * outlet-ammonia objective (13.0 mol % NH3) -> k_scale = k_hi.

k_hi / k_lo is the activity uncertainty that the opened literature leaves the
project with (about a factor 2.4). It is NOT reduced by anything in this
repository - only a plant or pilot converter dataset on THIS catalyst can
reduce it (docs/27, docs/28). Everything else in the converter model is either
published (alpha, Ea, K_a, enthalpies) or fixed by the flowsheet.

What this module does
---------------------
For a log-spaced set of k_scale values across [k_lo, k_hi] it recomputes, with
the SAME code path the design uses:

  (a) the design at FIXED geometry (catalyst volume from the configured GHSV):
      per-pass conversion, peak bed temperature, outlet NH3, interbed cooling
      duty, implied recycle ratio, loop-closure factor;
  (b) the catalyst volume REQUIRED to hold the design's own per-pass
      conversion, i.e. what the vessel and the catalyst inventory cost do when
      the activity is uncertain (bisection on volume);
  (c) the remedy that keeps the peak bed temperature at the assumed ceiling,
      and how much conversion/outlet NH3 survives at that ceiling;
  (d) the money: recycle-compressor power for the changed recycle flow (using
      the project's own polytropic model), catalyst inventory at the project's
      screening price, and a vessel-size scaling with the project's own CAPEX
      exponent - each labelled, because every one of those prices is an
      assumption in this repository, not a quote.

Run:  PYTHONPATH=. python -m model.activity_uncertainty
"""
from __future__ import annotations
import json, math, os

from .config import load_config
from .converter import (VM_NORMAL, calibrate_k0, reactor_inlet_flows,
                        run_ammonia_converter, tp_params)
from .economics import PRICES
from .equipment import compressor_power

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RHO_CAT = 1775.0          # kg/m3 - VBF Cu/ZnO bulk density, used because no NH3
                          # catalyst datasheet was opened (docs/28); flagged below


def _design_feed(r, cfg):
    """Everything a converter march needs at the ammonia design point, taken
    from the design result and config exactly as ammonia_converter_design does."""
    K = tp_params(cfg)
    S = r["synthesis"]
    inert = max(S["dry_syngas_mol_h"] - S["N2_in_mol_h"] - S["H2_in_mol_h"], 0.0)
    fresh = {"N2": S["N2_in_mol_h"], "H2": S["H2_in_mol_h"], "inert": inert}
    RR = float(K["recycle_ratio"])
    F0, _tot = reactor_inlet_flows(fresh["N2"], fresh["H2"], fresh["inert"], RR,
                                   K.get("inlet_NH3_molpct", 0.5))
    n_beds = int(K.get("n_beds", 3))
    T_in = [float(t) for t in K.get("T_in_bed_K", [K["T_K"]] * n_beds)][:n_beds]
    kw = dict(alpha=K["alpha"], k0=K["k0_kmol_m3cat_h"], Ea=K["Ea_J_mol"],
              cold_shot_fraction=float(K.get("cold_shot_fraction", 0.0)),
              n_steps=int(K.get("n_steps", 400)))
    return {"K": K, "F0": F0, "fresh": fresh, "RR": RR, "n_beds": n_beds,
            "T_in": T_in, "kw": kw, "p": float(K["p_bar"]),
            "G": float(K["GHSV_h1"]), "Q": sum(F0.values()) * VM_NORMAL,
            "ceiling": float(K.get("bed_T_max_K", 803.15))}


def _run(feed, k_scale, GHSV=None, V_m3=None, T_in=None, n_steps=None):
    """One converter march; V_m3 (if given) overrides the GHSV so the volume is
    the controlled variable."""
    Q = feed["Q"]
    if GHSV is None and V_m3 is not None:
        GHSV = Q / V_m3
    G = GHSV if GHSV is not None else feed["G"]
    kw = dict(feed["kw"])
    if n_steps:
        kw["n_steps"] = n_steps
    return run_ammonia_converter(feed["F0"], feed["p"], G, n_beds=feed["n_beds"],
                                 T_in_first=(T_in[0] if T_in else feed["T_in"][0]),
                                 T_in_bed=T_in or feed["T_in"],
                                 k_scale=k_scale, Q_normal_m3_h=Q, **kw)


def _volume_for_conversion(feed, k_scale, X_target, V_lo, V_hi, tol=2e-4):
    """Bisection on catalyst volume so that the per-pass N2 conversion matches
    X_target at this activity. Returns (V_m3, info)."""
    lo, hi = V_lo, V_hi
    f_lo = _run(feed, k_scale, V_m3=lo)["per_pass_N2_conversion"] - X_target
    f_hi = _run(feed, k_scale, V_m3=hi)["per_pass_N2_conversion"] - X_target
    if f_lo > 0 or f_hi < 0:
        return None, {"converged": False,
                      "reason": ("X_target outside [X at V_min, X at V_max] = "
                                 "[%.4f, %.4f] - the target cannot be held at this "
                                 "activity by sizing alone" % (f_lo + X_target,
                                                               f_hi + X_target))}
    it = 0
    while hi - lo > tol * hi and it < 40:
        it += 1
        m = 0.5 * (lo + hi)
        if _run(feed, k_scale, V_m3=m)["per_pass_N2_conversion"] < X_target:
            lo = m
        else:
            hi = m
    out = _run(feed, k_scale, V_m3=hi)
    return hi, {"converged": True, "iterations": it,
                "achieved_X": out["per_pass_N2_conversion"],
                "X_error_abs": abs(out["per_pass_N2_conversion"] - X_target)}


def _ceiling_inlet(feed, k_scale, T_lo=600.0, T_hi=780.0, tol=0.5):
    """Highest common bed-inlet temperature whose peak stays at/below the
    assumed ceiling (same procedure as docs/26 sec. 26.5, now at each activity)."""
    def peak(T):
        o = _run(feed, k_scale, T_in=[T] * feed["n_beds"])
        return o["T_peak_K"], o
    if peak(T_hi)[0] <= feed["ceiling"]:
        Tp, o = peak(T_hi)
        return {"feasible": True, "binding": False, "T_in_K": T_hi,
                "T_peak_K": Tp, "out": o}
    a, b = T_lo, T_hi
    if peak(a)[0] > feed["ceiling"]:
        Tp, o = peak(a)
        return {"feasible": False, "binding": True, "T_in_K": a, "T_peak_K": Tp,
                "out": o}
    for _ in range(10):
        m = 0.5 * (a + b)
        if peak(m)[0] > feed["ceiling"]:
            b = m
        else:
            a = m
    Tp, o = peak(a)
    return {"feasible": Tp <= feed["ceiling"] + 0.6, "binding": True,
            "T_in_K": round(a, 1), "T_peak_K": Tp, "out": o}


def band(n_grid=5, designs=None, cfg=None, dp_loop_bar=(1.0, 2.0, 3.0)):
    cfg = cfg or load_config(product="ammonia")
    if designs is None:
        from .products import design
        r = design(cfg)
    else:
        r = designs["ammonia"] if isinstance(designs, dict) and "ammonia" in designs \
            else designs
    cal = calibrate_k0(cfg)
    k_lo = float(cal["k_scale"])
    alt = cal.get("alternative_objective") or {}
    k_hi = float(alt.get("k_scale_needed", k_lo))
    factor = k_hi / k_lo if k_lo else 1.0

    feed = _design_feed(r, cfg)
    ref = _run(feed, k_lo)                      # the design as reported
    V_ref = ref["catalyst_volume_m3"]
    X_ref = ref["per_pass_N2_conversion"]
    grid = [k_lo * (factor ** (i / (n_grid - 1.0)) if n_grid > 1 else 1.0)
            for i in range(n_grid)]
    rows = []
    for k in grid:
        at = _run(feed, k)
        V_need, vinfo = _volume_for_conversion(feed, k, X_ref, V_ref / 8.0,
                                               V_ref * 8.0, tol=1e-3)
        ceil = _ceiling_inlet(feed, k)
        RR_imp = at["recycle_ratio_implied_by_kinetics"]
        recycle_mol_h = (RR_imp or 0.0) * (feed["fresh"]["N2"] + feed["fresh"]["H2"]
                                           + feed["fresh"]["inert"])
        pw = []
        for dp in dp_loop_bar:
            p_in = max(feed["p"] - dp, 1.0)
            c = compressor_power(recycle_mol_h / 1000.0, 298.15, p_in,
                                 feed["p"], k=1.40, MW=8.5)
            pw.append({"dP_loop_bar": dp, "power_MW": c["power_kW"] / 1000.0,
                       "power_cost_USD_y": c["power_kW"] *
                       PRICES["operating_hours_per_year"] *
                       PRICES["electricity_USD_per_MWh"] / 1000.0})
        row = {
            "k_scale": k,
            "k0_effective_kmol_m3cat_h":
                float(cfg.raw["kinetics"]["ammonia"]["k0_kmol_m3cat_h"]) * k,
            "position_in_band": ("lower edge (= calibrated design point)" if
                                 abs(k - k_lo) < 1e-12 else
                                 "upper edge" if abs(k - k_hi) < 1e-12 else
                                 "interior"),
            "at_fixed_geometry": {
                "catalyst_volume_m3": V_ref,
                "per_pass_N2_pct": 100.0 * at["per_pass_N2_conversion"],
                "outlet_NH3_molpct": at["outlet_NH3_molpct"],
                "T_peak_K": at["T_peak_K"],
                "peak_over_assumed_ceiling_K": at["T_peak_K"] - feed["ceiling"],
                "bed_out_K": at["T_bed_out_K"],
                "reaction_heat_MW": at["reaction_heat_MW"],
                "interbed_cooling_duty_MW": at["interbed_cooling_duty_MW"],
                "equilibrium_NH3_molpct_at_inlet_T":
                    at["equilibrium_NH3_molpct_at_inlet_T"],
                "approach_to_equilibrium": at["approach_to_equilibrium"],
                "recycle_ratio_implied": RR_imp,
                "loop_closure_X_times_1pRR":
                    at["per_pass_N2_conversion"] * (1.0 + feed["RR"]),
                "NH3_formed_t_h": at["NH3_formed_mol_h"] * 17.0305e-6,
            },
            "volume_to_hold_design_conversion": {
                "target_X_pct": 100.0 * X_ref,
                "V_m3": None if V_need is None else round(V_need, 3),
                "GHSV_normal_h1": None if V_need is None else
                round(feed["Q"] / V_need, 1),
                "delta_V_pct": None if V_need is None else
                round(100.0 * (V_need / V_ref - 1.0), 1),
                "catalyst_mass_t": None if V_need is None else
                round(V_need * RHO_CAT / 1000.0, 1),
                "inventory_cost_USD": None if V_need is None else
                round(V_need * RHO_CAT * PRICES["catalyst_USD_per_kg"], -3),
                "vessel_scale_factor_capex_exponent_0p7": None if V_need is None
                else round((V_need / V_ref) ** 0.7, 4),
                **vinfo},
            "ceiling_remedy": {
                "T_in_common_K": ceil["T_in_K"], "T_peak_K": ceil["T_peak_K"],
                "feasible": ceil["feasible"], "ceiling_binding": ceil["binding"],
                "per_pass_N2_pct": 100.0 * ceil["out"]["per_pass_N2_conversion"],
                "outlet_NH3_molpct": ceil["out"]["outlet_NH3_molpct"],
                "interbed_cooling_duty_MW":
                    ceil["out"]["interbed_cooling_duty_MW"],
                "recycle_ratio_implied":
                    ceil["out"]["recycle_ratio_implied_by_kinetics"],
            },
            "recycle_compressor_at_this_activity": {
                "recycle_mol_h": recycle_mol_h,
                "power_by_loop_dP": pw,
            },
        }
        rows.append(row)

    def span(key, sub=None):
        vals = [((x[key][sub] if sub else x[key]) or float("nan")) for x in rows]
        vals = [v for v in vals if v == v]
        return (min(vals), max(vals)) if vals else (None, None)

    lo_fix, hi_fix = span("at_fixed_geometry", "per_pass_N2_pct")
    lo_vp, hi_vp = span("volume_to_hold_design_conversion", "V_m3")
    lo_pk, hi_pk = span("at_fixed_geometry", "T_peak_K")
    lo_ol, hi_ol = span("at_fixed_geometry", "outlet_NH3_molpct")
    by_dp = []
    for i, dp in enumerate(dp_loop_bar):
        vals = [x["recycle_compressor_at_this_activity"]["power_by_loop_dP"][i]
                ["power_MW"] for x in rows]
        by_dp.append({"dP_loop_bar": dp, "power_MW_min": min(vals),
                      "power_MW_max": max(vals),
                      "delta_power_MW": max(vals) - min(vals),
                      "delta_cost_USD_y": (max(vals) - min(vals)) * 1000.0 *
                      PRICES["operating_hours_per_year"] *
                      PRICES["electricity_USD_per_MWh"] / 1000.0})
    return {
        "what_this_is": ("corridor, not a point: the whole ammonia synthesis "
                         "reactor decision is re-evaluated across the activity "
                         "factor that the opened benchmarks leave unresolved"),
        "activity_band": {"k_scale_lo": k_lo, "k_scale_hi": k_hi,
                          "factor": factor,
                          "k0_published": float(
                              cfg.raw["kinetics"]["ammonia"]["k0_kmol_m3cat_h"]),
                          "source_of_band": (
                              "model/converter.py calibrate_k0: k_lo hits the opened "
                              "per-pass band midpoint, k_hi hits the opened 13 mol% "
                              "outlet benchmark; the two opened industrial data "
                              "disagree by this factor"),
                          "status": "[ЧАСТИЧНО] both anchors are opened literature "
                                    "values; the factor itself is a measured "
                                    "inconsistency of the sources, not a fitted "
                                    "spread"},
        "design_reference": {"k_scale": k_lo,
                             "catalyst_volume_m3": V_ref,
                             "per_pass_N2_pct": 100.0 * X_ref,
                             "outlet_NH3_molpct": ref["outlet_NH3_molpct"],
                             "T_peak_K": ref["T_peak_K"],
                             "assumed_bed_ceiling_K": feed["ceiling"],
                             "recycle_ratio_configured": feed["RR"],
                             "GHSV_normal_h1": feed["G"],
                             "p_bar": feed["p"],
                             "bed_inlet_T_K": feed["T_in"][0],
                             "n_beds": feed["n_beds"],
                             "note": ("the design sits at the LOW edge of the band, "
                                      "so its catalyst volume is the optimistic "
                                      "(small) end and its peak temperature is the "
                                      "pessimistic end of the physical corridor")},
        "rows": rows,
        "spans": {"per_pass_N2_pct": [lo_fix, hi_fix],
                  "catalyst_volume_to_hold_design_m3": [lo_vp, hi_vp],
                  "T_peak_K": [lo_pk, hi_pk],
                  "outlet_NH3_molpct": [lo_ol, hi_ol]},
        "production_is_not_activity_limited": {
            "argument": ("at fixed fresh syngas flow and fixed loop pressure the "
                         "net NH3 rate is set by the closure X*(1+RR) >= 1; the "
                         "activity changes what recycle ratio is needed, not the "
                         "stoichiometric ceiling on tonnage. A closure ABOVE 1.0 "
                         "does NOT mean more product: it means the configured "
                         "recycle is larger than this activity requires, and the "
                         "loop would settle at a lower RR (or with a different "
                         "inert balance) - so the corridor is reported as the RR "
                         "that the kinetics imply, with tonnage held at the loop "
                         "value"),
            "closure_at_low_edge": rows[0]["at_fixed_geometry"][
                "loop_closure_X_times_1pRR"],
            "closure_at_high_edge": rows[-1]["at_fixed_geometry"][
                "loop_closure_X_times_1pRR"],
            "NH3_design_t_h": r["synthesis"]["NH3_t_h"],
            "recycle_ratio_needed_corridor": [
                rows[-1]["at_fixed_geometry"]["recycle_ratio_implied"],
                rows[0]["at_fixed_geometry"]["recycle_ratio_implied"]],
        },
        "money": {
            "catalyst_inventory_corridor_USD": [
                x["volume_to_hold_design_conversion"]["inventory_cost_USD"]
                for x in (rows[0], rows[-1])],
            "price_used": PRICES["catalyst_USD_per_kg"],
            "price_status": ("[ДОПУЩЕНИЕ] PRICES['catalyst_USD_per_kg'] is the "
                             "project's screening price for Ni/MgAl2O4 reforming "
                             "catalyst; no promoted-iron ammonia-catalyst price was "
                             "opened (docs/28 asks for it), and no catalyst LIFE for "
                             "the NH3 bed was opened either, so annual replacement "
                             "cost is deliberately NOT computed"),
            "density_used_kg_m3": RHO_CAT,
            "density_status": ("[ЧАСТИЧНО] 1775 kg/m3 is the VBF Cu/ZnO bulk "
                               "density reused as a placeholder; the NH3 catalyst "
                               "value is exactly what docs/28 item 12 asks for"),
            "vessel_scaling": ("(V/V_ref)^[CAPEX_scale_exponent] with the project's "
                               "own exponent 0.7; the converter's SHARE of the "
                               "281.4 M USD screening CAPEX is not resolved by the "
                               "model, so only the relative factor is reported"),
            "recycle_compressor": {
                "power_by_loop_dP": by_dp,
                "note": ("estimate for the recycle loop only, at the assumed loop "
                         "pressure drops listed per row; the project's compressor "
                         "model is [ASSUMPTION] (k, eta; catalogue curves not "
                         "opened), so this is a bracket for a re-rating decision, "
                         "not a purchase figure")},
        },
        "not_covered": [
            "catalyst price and life for promoted iron (docs/28 p. 12-13) - so no "
            "annualised catalyst cost line",
            "converter vendor layout and quench control (docs/28 p. 14-18)",
            "real loop closure: purge rate, inert build-up, separator pressure - "
            "the ammonia loop in model/synthesis.py is stoichiometric",
            "deactivation over the run: no 200-1000 h series for this catalyst",
            "the band is an activity band only; feed/temperature uncertainty is "
            "quantified separately in model/uncertainty.py (docs/30)",
        ],
        "how_to_use": "\n".join([
            "report the corridor in every ammonia answer: catalyst volume, peak "
            "temperature and outlet NH3 as ranges over the factor; single numbers "
            "may be quoted only together with the k_scale they belong to",
            "the corridor is NOT plant validation and NOT a vendor guarantee; it "
            "stays a model band until docs/27 (activity at our conditions) and "
            "docs/28 (vendor layout, density, ceiling) are closed",
            "the band is activity-only: feed and temperature uncertainty is "
            "quantified separately in model/uncertainty.py (docs/30), where 0 of 6 "
            "pilot points fall inside the model band - that disagreement is NOT "
            "covered by this corridor and is not fixed by it"]),
    }


def main():
    out = band()
    os.makedirs(os.path.join(ROOT, "results_v2"), exist_ok=True)
    p = os.path.join(ROOT, "results_v2", "activity_uncertainty.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False, default=float)
    c = out["spans"]
    print(json.dumps({"factor": out["activity_band"]["factor"],
                      "V_m3": [out["design_reference"]["catalyst_volume_m3"],
                               c["catalyst_volume_to_hold_design_m3"][1]],
                      "per_pass_pct": c["per_pass_N2_pct"],
                      "T_peak_K": c["T_peak_K"],
                      "outlet_pct": c["outlet_NH3_molpct"]},
                     indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
