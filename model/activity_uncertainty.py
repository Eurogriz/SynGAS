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
from .operator_data import activity_overrides

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


def band(n_grid=5, designs=None, cfg=None, dp_loop_bar=(1.0, 2.0, 3.0),
         overrides=None, use_operator_data=True, n_steps=None):
    """The ammonia activity corridor, recomputed with whatever the operators supplied.

    `use_operator_data` pulls `data/operator_inputs.json` through
    model/operator_data.activity_overrides(): an entered activity pins the centre
    of the band, an entered guaranteed spread shrinks it, an entered density /
    price / life / ceiling / loop dP replace the project placeholders. Nothing
    is ever dropped silently: the V5.2 literature band stays in the output as
    `literature_reference_rows`, because one operator number from a vendor sheet
    is still ONE source.
    """
    cfg = cfg or load_config(product="ammonia")
    if designs is None:
        from .products import design
        r = design(cfg)
    else:
        r = designs["ammonia"] if isinstance(designs, dict) and "ammonia" in designs \
            else designs
    cal = calibrate_k0(cfg)
    k_lit_lo = float(cal["k_scale"])
    alt = cal.get("alternative_objective") or {}
    k_lit_hi = float(alt.get("k_scale_needed", k_lit_lo))
    lit_factor = k_lit_hi / k_lit_lo if k_lit_lo else 1.0

    ov = dict(activity_overrides() if use_operator_data else (overrides or {}))
    if overrides is not None:
        ov = dict(overrides)
    rho = float(ov.get("rho_kg_m3") or RHO_CAT)
    price = float(ov.get("price_USD_per_kg") or PRICES["catalyst_USD_per_kg"])
    life = ov.get("life_years")
    dp_loop_bar = tuple(ov.get("dp_loop_bar") or dp_loop_bar)
    inlet_T_lo = float(ov.get("inlet_T_min_K") or 600.0)

    feed = _design_feed(r, cfg)
    if n_steps:
        feed["kw"]["n_steps"] = int(n_steps)      # tests use a coarse march
    ghub_status = "[ДОПУЩЕНИЕ] проектное GHSV, базис normal задан моделью"
    if ov.get("ceiling_K"):
        feed["ceiling"] = float(ov["ceiling_K"])
    if ov.get("GHSV_h1"):
        g_entered = float(ov["GHSV_h1"])
        if str(ov.get("GHSV_basis") or "normal") == "actual":
            # ideal-gas conversion actual -> normal at the first bed inlet; Z is
            # NOT applied here, so the number keeps a [ЧАСТИЧНО] label
            g_use = (g_entered * (273.15 / feed["T_in"][0]) *
                     (feed["p"] / 1.01325))
            ghub_status = ("[ЧАСТИЧНО] поставщик указал фактический базис; перевод "
                           "в нормальный выполнен идеальным газом при %.1f K / %.0f "
                           "бар без поправки на Z: %.0f -> %.0f 1/h"
                           % (feed["T_in"][0], feed["p"], g_entered, g_use))
        else:
            g_use = g_entered
            ghub_status = ("[ЧАСТИЧНО] GHSV введена оператором из даташита "
                           "(провенанс в data_entry), базис normal")
        feed["G"] = g_use
    # ---- activity band: pinned by the operator, or the literature disagreement
    if ov.get("k_center"):
        k_c = float(ov["k_center"])
        f = max(1.0, float(ov.get("k_factor") or 1.0))
        k_lo, k_hi = k_c / f, k_c * f
        factor = (k_hi / k_lo) if k_lo else 1.0
        pinned = {"by_operator": True, "k_center": k_c, "guaranteed_factor": f,
                  "width_factor": factor,
                  "single_source": not (f > 1.0 or "nh3_activity_k_scale" in
                                        ov.get("verified_ids", []))}
    else:
        k_lo, k_hi, factor = k_lit_lo, k_lit_hi, lit_factor
        pinned = {"by_operator": False, "k_center": None,
                  "guaranteed_factor": None, "width_factor": factor,
                  "single_source": False}
    n_grid = 1 if factor <= 1.0 + 1e-12 else int(n_grid)
    grid = [k_lo * (factor ** (i / (n_grid - 1.0)) if n_grid > 1 else 1.0)
            for i in range(n_grid)]
    # literature edges stay in the report as reference points when they lie
    # outside what the operator just pinned
    extra_edges = ([] if not pinned["by_operator"] else
                   [k for k in (k_lit_lo, k_lit_hi)
                    if k < k_lo * (1.0 - 1e-9) or k > k_hi * (1.0 + 1e-9)])
    ref = _run(feed, grid[0])                   # the design as configured
    V_ref = ref["catalyst_volume_m3"]
    X_ref = ref["per_pass_N2_conversion"]
    rows = []
    for k in list(grid) + list(extra_edges):
        at = _run(feed, k)
        V_need, vinfo = _volume_for_conversion(feed, k, X_ref, V_ref / 8.0,
                                               V_ref * 8.0, tol=1e-3)
        ceil = _ceiling_inlet(feed, k, T_lo=inlet_T_lo)
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
            "row_kind": ("literature_reference" if k in extra_edges else
                         "operator_point" if (pinned["by_operator"] and factor <= 1.0 + 1e-12)
                         else "operator_corridor" if pinned["by_operator"]
                         else "literature_corridor"),
            "position_in_band": (
                "ссылка: край литературной полосы V5.2 (не данные оператора)"
                if k in extra_edges else
                "точка оператора (один источник)" if n_grid == 1 else
                "нижний край полосы" if abs(k - k_lo) < 1e-12 else
                "верхний край полосы" if abs(k - k_hi) < 1e-12 else
                "внутренняя точка полосы"),
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
                round(V_need * rho / 1000.0, 1),
                "inventory_cost_USD": None if V_need is None else
                round(V_need * rho * price, -3),
                "annual_replacement_cost_USD_y": None if (V_need is None or not life)
                else round(V_need * rho * price / float(life), -3),
                "bed_volume_m3_if_basis_is_bed":
                    None if V_need is None else
                    round(V_need / max(1e-6, 1.0 - float(
                        (cfg.raw.get("equipment") or {}).get("bed_voidage", 0.5))), 2),
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

    main_rows = [x for x in rows if x["row_kind"] != "literature_reference"]
    lit_rows = [x for x in rows if x["row_kind"] == "literature_reference"]

    def span(key, sub=None, src=None):
        vals = [((x[key][sub] if sub else x[key]) or float("nan"))
                for x in (src if src is not None else main_rows)]
        vals = [v for v in vals if v == v]
        return (min(vals), max(vals)) if vals else (None, None)

    lo_fix, hi_fix = span("at_fixed_geometry", "per_pass_N2_pct")
    lo_vp, hi_vp = span("volume_to_hold_design_conversion", "V_m3")
    lo_pk, hi_pk = span("at_fixed_geometry", "T_peak_K")
    lo_ol, hi_ol = span("at_fixed_geometry", "outlet_NH3_molpct")
    spans_lit = {k: [span("at_fixed_geometry", f, src=lit_rows)[0] if lit_rows else None,
                      span("at_fixed_geometry", f, src=lit_rows)[1] if lit_rows else None]
                 for k, f in (("per_pass_N2_pct", "per_pass_N2_pct"),
                              ("T_peak_K", "T_peak_K"),
                              ("outlet_NH3_molpct", "outlet_NH3_molpct"))}
    spans_lit["catalyst_volume_to_hold_design_m3"] = [
        (min(x["volume_to_hold_design_conversion"]["V_m3"] for x in rows
             if x["volume_to_hold_design_conversion"]["V_m3"]) if lit_rows else None),
        (max(x["volume_to_hold_design_conversion"]["V_m3"] for x in rows
             if x["volume_to_hold_design_conversion"]["V_m3"]) if lit_rows else None)]
    by_dp = []
    for i, dp in enumerate(dp_loop_bar):
        vals = [x["recycle_compressor_at_this_activity"]["power_by_loop_dP"][i]
                ["power_MW"] for x in main_rows]
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
                          "literature_band": [k_lit_lo, k_lit_hi, lit_factor],
                          "pinned_by_operator": pinned["by_operator"],
                          "single_source_pin": pinned["single_source"],
                          "k_center_entered": pinned["k_center"],
                          "guaranteed_factor_entered": pinned["guaranteed_factor"],
                          "GHSV_status": ghub_status,
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
        "design_reference": {"k_scale": grid[0],
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
                             "volume_basis": str(ov.get("volume_basis")
                                                 or "catalyst"),
                             "note": ("the design sits at the LOW edge of the band, "
                                      "so its catalyst volume is the optimistic "
                                      "(small) end and its peak temperature is the "
                                      "pessimistic end of the physical corridor"
                                      if not pinned["by_operator"] else
                                      "reference row = the design recomputed at the "
                                      "activity the operator entered; the literature "
                                      "band is kept in literature_reference_rows")},
        "literature_reference_rows": [
            {"k_scale": x["k_scale"], "per_pass_N2_pct":
             x["at_fixed_geometry"]["per_pass_N2_pct"],
             "outlet_NH3_molpct": x["at_fixed_geometry"]["outlet_NH3_molpct"],
             "T_peak_K": x["at_fixed_geometry"]["T_peak_K"],
             "V_to_hold_design_m3": x["volume_to_hold_design_conversion"]["V_m3"],
             "kind": "литературный край полосы V5.2 (не данные оператора)"}
            for x in lit_rows],
        "rows": rows,
        "spans_literature_reference": dict(spans_lit, note=(
            "края литературной полосы V5.2, пересчитанные при ТОМ ЖЕ целевом X, "
            "которое задал оператор: это сравнение 'насколько оптимистичен ввод', а "
            "не новый коридор проекта")),
        "band_kind": ("point_from_operator_data" if pinned["by_operator"] and
                      factor <= 1.0 + 1e-12 else
                      "operator_corridor" if pinned["by_operator"] else
                      "literature_corridor (recommended form)"),
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
            "closure_at_low_edge": main_rows[0]["at_fixed_geometry"][
                "loop_closure_X_times_1pRR"],
            "closure_at_high_edge": main_rows[-1]["at_fixed_geometry"][
                "loop_closure_X_times_1pRR"],
            "NH3_design_t_h": r["synthesis"]["NH3_t_h"],
            "recycle_ratio_needed_corridor": [
                main_rows[-1]["at_fixed_geometry"]["recycle_ratio_implied"],
                main_rows[0]["at_fixed_geometry"]["recycle_ratio_implied"]],
        },
        "money": {
            "catalyst_inventory_corridor_USD": [
                x["volume_to_hold_design_conversion"]["inventory_cost_USD"]
                for x in (main_rows[0], main_rows[-1])],
            "price_used": price,
            "price_status": ("[ЧАСТИЧНО] цена введена оператором из даташита "
                             "(провенанс в data_entry); независимого подтверждения "
                             "нет" if ov.get("price_USD_per_kg") else
                             "[ДОПУЩЕНИЕ] PRICES['catalyst_USD_per_kg'] is the "
                             "project's screening price; no promoted-iron "
                             "ammonia-catalyst price was opened (docs/28 asks for "
                             "it) - it can be entered in data/operator_inputs.json"),
            "life_years_used": life,
            "annual_replacement_cost_USD_y": (None if not life else round(
                sum(x["volume_to_hold_design_conversion"]["annual_replacement_cost_USD_y"]
                    or 0.0 for x in main_rows) / max(1, len(main_rows)), -3)),
            "density_used_kg_m3": rho,
            "density_status": ("[ЧАСТИЧНО] насыпная плотность введена оператором из "
                               "даташита; пересчёт объём->масса линеен"
                               if ov.get("rho_kg_m3") else
                               "[ЧАСТИЧНО] 1775 kg/m3 is the VBF Cu/ZnO bulk "
                               "density reused as a placeholder; the NH3 catalyst "
                               "value is exactly what docs/28 item 12 asks for "
                               "(field nh3_rho_bulk in the operator form)"),
            "capex_share_pct_used": ov.get("capex_share_pct"),
            "converter_CAPEX_delta_USD": (None if not ov.get("capex_share_pct") else
                round(((lo_vp / V_ref) ** 0.7 - 1.0) *
                      float(ov["capex_share_pct"]) / 100.0 *
                      float((r.get("economics") or {}).get("CAPEX_USD") or 0.0), -4)),
            "vessel_scaling": ("(V/V_ref)^0.7 с долей конвертора из ввода оператора "
                               "-> абсолютная дельта CAPEX посчитана"
                               if ov.get("capex_share_pct") else
                               "(V/V_ref)^[CAPEX_scale_exponent] with the project's "
                               "own exponent 0.7; the converter's SHARE of the "
                               "281.4 M USD screening CAPEX is not resolved by the "
                               "model, so only the relative factor is reported "
                               "(field converter_capex_share in the form)"),
            "recycle_compressor": {
                "power_by_loop_dP": by_dp,
                "note": ("estimate for the recycle loop only, at the assumed loop "
                         "pressure drops listed per row; the project's compressor "
                         "model is [ASSUMPTION] (k, eta; catalogue curves not "
                         "opened), so this is a bracket for a re-rating decision, "
                         "not a purchase figure")},
        },
        "data_entry": {
            "overrides_used": {k: v for k, v in ov.items()
                              if not str(k).startswith("_") and k not in
                              ("provenance", "verified_ids")},
            "provenance": ov.get("provenance", {}),
            "verified_ids": ov.get("verified_ids", []),
            "corridor_recommended": (not ov.get("k_center")) or pinned["single_source"],
            "rule": ("коридор остаётся рекомендованной формой отчёта, пока размер "
                     "не введён с провенансом; одиночный ввод фиксирует точку, но "
                     "литературная полоса показана рядом"),
        },
        "not_covered": ([
            "catalyst price and life for promoted iron (docs/28 p. 12-13) - so no "
            "annualised catalyst cost line" if not life else
            "цена/ресурс взяты из ввода оператора (один источник) — годовая замена "
            "посчитана как масса/ресурс×цена, без независимого подтверждения",
        ] + [
            "converter vendor layout and quench control (docs/28 p. 14-18)",
            "real loop closure: purge rate, inert build-up, separator pressure - "
            "the ammonia loop in model/synthesis.py is stoichiometric",
            "deactivation over the run: no 200-1000 h series for this catalyst",
            "the band is an activity band only; feed/temperature uncertainty is "
            "quantified separately in model/uncertainty.py (docs/30)",
        ]),
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
            "covered by this corridor and is not fixed by it",
            ("операторский ввод фиксирует точку, но не закрывает контур 5: данные "
             "без второй подписи остаются [ЧАСТИЧНО]" if pinned["by_operator"] else
             "введите недостающие числа через data/operator_inputs.json (или "
             "вкладку «Ручной ввод данных» панели) - тогда коридор сузится ровно "
             "на столько, на сколько позволяет провенанс")]),
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
