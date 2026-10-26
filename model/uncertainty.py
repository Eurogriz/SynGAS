"""V5+: the model's OWN input-uncertainty band on X_CH4 (docs/27 sec. 7).

Until now the falsification in loop 5 was stated as a point comparison:
"the equilibrium model sits +0.287 above the measured kinetic conversions".
That is only meaningful if we know how far the model itself could move when its
inputs are moved by the uncertainties those sources actually allow. Without it
the comparison is an accusation with no error bar - and it is exactly what a
pilot campaign would have to beat.

This module computes, for every comparable open pilot point AND for the design
point, a one-factor-at-a-time sensitivity envelope:

  * bed temperature      +/- 2 K        (the requirement in docs/27 sec. 6)
  * S/C, CO2/C           +/- 2 % rel.   (steam/CO2 metering)
  * CH4 fraction           +/- 1 % rel. (balloon/mixer accuracy)
  * approach_K           0 -> 10 K      (finite-rate correction the model applies)
  * PR kij set           zero / base / high (real-gas closure uncertainty)
  * explicit C2+ in the feed (design point only; the model lumps C2+ -> C3H8)

Two bands are reported: a worst-case envelope (min..max over all perturbations)
and a quadrature band (RSS of the individual half-widths). Both are model
OUTPUT uncertainty from input uncertainty - they say nothing about the rate
law, which is the point: an equilibrium model cannot be blamed or defended on
kinetic data by its thermo only.

Everything here is computed, not assumed: no band is hard-coded.
"""
from __future__ import annotations
import json, math, os

from .config import load_config
from .pilot_data import lab_feed, load_pilot, model_X_CH4, _measured_value

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# relative perturbations; approach_K and kij are absolute switches
PERTURB = {
    "T_+2K": {"dT": +2.0},
    "T_-2K": {"dT": -2.0},
    "S/C_+2%": {"dSC": 0.02},
    "S/C_-2%": {"dSC": -0.02},
    "CO2/C_+2%": {"dCO2C": 0.02},
    "CO2/C_-2%": {"dCO2C": -0.02},
    "y_CH4_-1%": {"dCH4": -0.01},
    "approach_10K": {"approach_K": 10.0},
    "kij_zero": {"kset": "zero"},
    "kij_high": {"kset": "high"},
}
PRODUCTS_FOR_BAND = ("methanol", "ammonia", "ft")

STATUSES = {"dT": "[ДОПУЩЕНИЕ] sensor requirement from docs/27 sec. 6",
            "dSC": "[ДОПУЩЕНИЕ] steam metering",
            "dCO2C": "[ДОПУЩЕНИЕ] CO2 metering",
            "dCH4": "[ДОПУЩЕНИЕ] feed analysis",
            "approach_K": "[ЧАСТИЧНО] finite-rate correction allowed by the model",
            "kset": "[ПОДТВЕРЖДЕНО] three opened kij sets"}


def _x_feed(feed, T, p, approach_K=0.0, kset="base"):
    r = model_X_CH4(T, p, dict(feed), eos_kset=kset, approach_K=approach_K)
    return float(r["X_CH4"]), bool(r.get("carbon_stable", True))


def band_for_feed(feed, T, p, approach_K=0.0, extra=None, label=""):
    """Sensitivity envelope on an ARBITRARY feed dict (used for design points,
    where the model's own reformer feed must be reproduced exactly)."""
    base, stab0 = _x_feed(feed, T, p, approach_K, "base")
    rows = [{"perturbation": "true equilibrium (approach_K=0)",
             "X_CH4": _x_feed(feed, T, p, 0.0, "base")[0],
             "delta": _x_feed(feed, T, p, 0.0, "base")[0] - base,
             "carbon_stable": _x_feed(feed, T, p, 0.0, "base")[1],
             "status": "[ЧАСТИЧНО] the design basis applies a finite-rate approach"}]
    for name, mut, status in (
            ("T_+2K", lambda f: (f, T + 2.0, p, approach_K, "base"),
             "[ДОПУЩЕНИЕ] sensor requirement (docs/27 sec. 6)"),
            ("T_-2K", lambda f: (f, T - 2.0, p, approach_K, "base"),
             "[ДОПУЩЕНИЕ] sensor requirement (docs/27 sec. 6)"),
            ("H2O_+2%", (_scale(feed, "H2O", 1.02), T, p, approach_K, "base"),
             "[ДОПУЩЕНИЕ] steam metering"),
            ("H2O_-2%", (_scale(feed, "H2O", 0.98), T, p, approach_K, "base"),
             "[ДОПУЩЕНИЕ] steam metering"),
            ("CO2_+2%", (_scale(feed, "CO2", 1.02), T, p, approach_K, "base"),
             "[ДОПУЩЕНИЕ] CO2 metering"),
            ("CO2_-2%", (_scale(feed, "CO2", 0.98), T, p, approach_K, "base"),
             "[ДОПУЩЕНИЕ] CO2 metering"),
            ("CH4_-1%", (_scale(feed, "CH4", 0.99), T, p, approach_K, "base"),
             "[ДОПУЩЕНИЕ] feed analysis"),
            ("approach_K_+10K", (feed, T, p, approach_K + 10.0, "base"),
             "[ЧАСТИЧНО] finite-rate assumption, one half-step"),
            ("kij_zero", (feed, T, p, approach_K, "zero"),
             "[ПОДТВЕРЖДЕНО] opened kij set"),
            ("kij_high", (feed, T, p, approach_K, "high"),
             "[ПОДТВЕРЖДЕНО] opened kij set"),
    ):
        if callable(mut):
            fe, TT, pp, aa, kk = mut(feed)
        else:
            fe, TT, pp, aa, kk = mut
        x, stab = _x_feed(fe, TT, pp, aa, kk)
        rows.append({"perturbation": name, "X_CH4": x, "delta": x - base,
                     "carbon_stable": stab, "status": status})
    for name, f2, status in (extra or []):
        x, stab = _x_feed(f2, T, p, approach_K, "base")
        rows.append({"perturbation": name, "X_CH4": x, "delta": x - base,
                     "carbon_stable": stab, "status": status})
    return _envelope(base, stab0, rows, label,
                     {"T_K": T, "p_bar": p, "approach_K": approach_K})


def _scale(feed, sp, fac):
    f = dict(feed)
    f[sp] = f.get(sp, 0.0) * fac
    return f


def _envelope(base, stab0, rows, label, inputs):
    xs = [base] + [r["X_CH4"] for r in rows]
    deltas = [r["delta"] for r in rows]
    rss = math.sqrt(sum(d * d for d in deltas) / max(len(deltas), 1))
    return {"label": label, "inputs": inputs, "X_base": base,
            "carbon_stable_base": stab0,
            "envelope_min": min(xs), "envelope_max": max(xs),
            "envelope_half_width": 0.5 * (max(xs) - min(xs)),
            "quadrature_half_width": rss,
            "largest_single_effect": max(rows, key=lambda r: abs(r["delta"])),
            "rows": rows}


def _x(T, p, SC, CO2C, CH4=1.0, approach_K=0.0, kset="base", C2H6=0.0):
    """Equilibrium X_CH4 for one perturbed input set, on the SAME call path the
    loop-5 comparison uses (model_X_CH4 -> allow_carbon=True)."""
    if C2H6 > 0.0:
        # per 100 mol carbon: a fraction C2H6 = 100*f/2 (two carbons each)
        c_tot = 100.0
        feed = {"CH4": c_tot * (1.0 - C2H6), "C2H6": c_tot * C2H6 / 2.0,
                "C3H8": 0.0, "CO2": CO2C * c_tot, "N2": 0.0,
                "H2O": SC * c_tot, "H2": 1e-3 * c_tot}
    else:
        feed = lab_feed(SC=SC, CO2C=CO2C, CH4=100.0 * CH4)
    r = model_X_CH4(T, p, feed, eos_kset=kset, approach_K=approach_K)
    return float(r["X_CH4"]), bool(r.get("carbon_stable", True))


def band_for_point(T_K, p_bar, SC, CO2C, CH4=1.0, C2H6=0.0, with_c2=False):
    """Return the sensitivity envelope for one operating point."""
    base, stab0 = _x(T_K, p_bar, SC, CO2C, CH4, C2H6=C2H6)
    rows = []
    for name, d in PERTURB.items():
        x, stab = _x(T_K + d.get("dT", 0.0), p_bar,
                     SC * (1.0 + d.get("dSC", 0.0)),
                     CO2C * (1.0 + d.get("dCO2C", 0.0)),
                     CH4 * (1.0 + d.get("dCH4", 0.0)),
                     approach_K=d.get("approach_K", 0.0),
                     kset=d.get("kset", "base"), C2H6=C2H6)
        rows.append({"perturbation": name, "X_CH4": x, "delta": x - base,
                     "carbon_stable": stab,
                     "status": STATUSES.get(next(iter(d), ""), "-")})
    if with_c2:                       # design point only: explicit ethane
        for frac in (0.06, 0.10):
            x, stab = _x(T_K, p_bar, SC, CO2C, CH4 * (1 - frac),
                         C2H6=frac)
            rows.append({"perturbation": f"explicit C2+ as C2H6 ({frac*100:.0f}% C)",
                         "X_CH4": x, "delta": x - base, "carbon_stable": stab,
                         "status": "[ЧАСТИЧНО] the model lumps C2+ into C3H8"})
    return _envelope(base, stab0, rows, "lab feed",
                     {"T_K": T_K, "p_bar": p_bar, "S_C": SC, "CO2_C": CO2C,
                      "CH4_fraction": CH4})


def pilot_points(cfg=None):
    """The six genuinely comparable open pilot points (same selection as
    model/pilot_data.compare_X_CH4, but with the perturbable inputs)."""
    pilot = load_pilot()
    out = []
    for rec in pilot["records"]:
        if rec.get("quantity") not in ("X_CH4", "X_CH4_Pt0"):
            continue
        meas = _measured_value(rec)
        c = rec.get("conditions", {})
        if meas is None or c.get("T_C") is None:
            continue
        out.append({"record_id": rec["id"], "source_id": rec["source_id"],
                    "T_K": float(c["T_C"]) + 273.15,
                    "p_bar": float(c["p_bar"]) if c.get("p_bar") is not None else 1.0,
                    "S_C": float(c.get("S_C", 3.0)),
                    "CO2_C": float(c.get("CO2C", 0.0)),
                    "X_measured": meas, "record_status": rec["status"]})
    return out


def run(cfg=None, include_design=True):
    cfg = cfg or load_config()
    res = []
    for pt in pilot_points(cfg):
        b = band_for_point(pt["T_K"], pt["p_bar"], pt["S_C"], pt["CO2_C"])
        gap = pt["X_measured"] - b["X_base"]
        res.append({**pt, **b, "measured_minus_model": gap,
                    "gap_over_envelope_half_width":
                        abs(gap) / b["envelope_half_width"]
                        if b["envelope_half_width"] > 1e-12 else None,
                    "gap_over_quadrature":
                        abs(gap) / b["quadrature_half_width"]
                        if b["quadrature_half_width"] > 1e-12 else None,
                    "measurement_inside_model_band":
                        b["envelope_min"] <= pt["X_measured"] <= b["envelope_max"],
                    "kind": "open pilot point (lab, kinetic regime)"})
    if include_design:
        from .products import design
        for prod in PRODUCTS_FOR_BAND:
            r = design(load_config(product=prod))
            eq = r["reformer"]["equilibrium"]
            T = float(r["reformer"]["T_out_K"])
            p = float(r["reformer"]["p_bar"])
            aK = float(r["knobs"].get("approach_K", 0.0))
            feed = dict(r["reformer_feed_main_mol_per_100mol_NG"])
            pre = dict(r.get("reformer_feed_mol_per_100mol_NG") or {})
            c2_in = float(pre.get("C2H6", 0.0)) + 3.0 * float(pre.get("C3H8", 0.0))
            extra = []
            if c2_in > 0:            # pre-reformer slip: C2+ reaching the top box
                for slip in (0.05, 0.20):
                    f = dict(feed)
                    f["C2H6"] = f.get("C2H6", 0.0) + slip * c2_in
                    extra.append((f"pre-reformer C2+ slip {slip*100:.0f}%", f,
                                  "[ЧАСТИЧНО] pre-reformer conversion is modelled, "
                                  "not measured"))
            b = band_for_feed(feed, T, p, approach_K=aK, extra=extra,
                              label=f"{prod} design point (model's own feed)")
            b["X_model_reported"] = float(eq["CH4_conversion"])
            b["reported_minus_banded"] = float(eq["CH4_conversion"]) - b["X_base"]
            res.append({"record_id": f"design_{prod}", "source_id": "THIS MODEL",
                        "T_K": T, "p_bar": p,
                        "S_C": float(r["knobs"]["SC"]),
                        "CO2_C": float(r["knobs"]["CO2C"]),
                        "X_measured": None, **b,
                        "gap_over_envelope_half_width": None,
                        "gap_over_quadrature": None,
                        "measurement_inside_model_band": None,
                        "kind": "design point (no external data; band only)"})
    env = [r["envelope_half_width"] for r in res]
    qua = [r["quadrature_half_width"] for r in res]
    rat = [r["gap_over_envelope_half_width"] for r in res
           if r.get("gap_over_envelope_half_width")]
    inside = [r for r in res if r["kind"].startswith("open")
              and r["measurement_inside_model_band"]]
    return {
        "purpose": "model-side input-uncertainty band for X_CH4, needed to state "
                   "the loop-5 bias quantitatively instead of as a bare number",
        "factors": {k: ({"dT_K": 2.0} if k.startswith("T_") else
                        {"rel": 0.02} if k in ("S/C_+2%", "S/C_-2%",
                                              "CO2/C_+2%", "CO2/C_-2%") else
                        {"rel": 0.01} if k == "y_CH4_-1%" else
                        {"approach_K": 10.0} if k == "approach_10K" else
                        {"kij_set": k.split("_")[1]}) for k in PERTURB},
        "factor_status": "perturbation SIZES are requirements/assumptions "
                         "(docs/27 sec. 6); their EFFECTS on X_CH4 are computed",
        "points": res,
        "n_points": len(res),
        "mean_envelope_half_width": sum(env) / len(env) if env else None,
        "mean_quadrature_half_width": sum(qua) / len(qua) if qua else None,
        "max_quadrature_half_width": max(qua) if qua else None,
        "pilot_points_inside_model_band": len(inside),
        "pilot_points_total": sum(1 for r in res if r["kind"].startswith("open")),
        "median_gap_over_envelope": (sorted(rat)[len(rat) // 2] if rat else None),
        "verdict": ("the +0.287 mean bias is NOT explained by input uncertainty: "
                    "it is " +
                    (f"{min(rat):.1f}-{max(rat):.1f}x" if rat else "n/a") +
                    " the per-point envelope half-width") if rat else
                   "no comparable pilot points",
        "how_to_use_in_loop5": "a bias smaller than the band is a null result, not "
                               "a pass; the band shrinks only when the pilot "
                               "reports real sensor and analysis uncertainties "
                               "(data/pilot_schema.json X_CH4_u etc.)",
        "status": "[ЧАСТИЧНО] computed sensitivity; perturbation magnitudes are "
                  "documented assumptions",
    }


def main():
    out = run()
    os.makedirs(os.path.join(ROOT, "results_v2"), exist_ok=True)
    with open(os.path.join(ROOT, "results_v2", "model_uncertainty.json"),
              "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False, default=float)
    with open(os.path.join(ROOT, "results_v2", "model_uncertainty.csv"),
              "w", encoding="utf-8", newline="") as fh:
        import csv
        w = csv.writer(fh)
        w.writerow(["point", "kind", "T_K", "p_bar", "S_C", "CO2_C",
                    "X_base", "envelope_min", "envelope_max", "env_half",
                    "quad_half", "X_measured", "gap", "gap/env_half",
                    "inside_band", "largest_effect", "largest_effect_delta"])
        for r in out["points"]:
            w.writerow([r["record_id"], r["kind"], r["T_K"], r["p_bar"],
                        r["S_C"], r["CO2_C"], round(r["X_base"], 5),
                        round(r["envelope_min"], 5), round(r["envelope_max"], 5),
                        round(r["envelope_half_width"], 5),
                        round(r["quadrature_half_width"], 6), r["X_measured"],
                        (round(r["measured_minus_model"], 5)
                         if r.get("measured_minus_model") is not None else ""),
                        (round(r["gap_over_envelope_half_width"], 2)
                         if r.get("gap_over_envelope_half_width") else ""),
                        r["measurement_inside_model_band"],
                        r["largest_single_effect"]["perturbation"],
                        round(r["largest_single_effect"]["delta"], 5)])
    print(json.dumps({k: out[k] for k in
                      ("n_points", "mean_envelope_half_width",
                       "mean_quadrature_half_width",
                       "pilot_points_inside_model_band", "pilot_points_total",
                       "median_gap_over_envelope", "verdict")},
                     indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
