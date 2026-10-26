"""V5: ingest + validation of pilot-campaign data, and automatic loop-5 rerun.

This module is the machine-readable counterpart of docs/27_v5_pilot_test_program.md.
It exists for one reason: the campaign is run by other people, in another
building, possibly years from now, and the model must be able to consume
whatever comes back WITHOUT silently accepting data it cannot use.

Everything here is deliberately strict and stdlib-only:

* `validate()` refuses records with wrong units, missing fields, out-of-range
  values, unknown columns, ambiguous conversion basis, and temperatures that
  look like degrees Celsius entered in a kelvin column.
* `compare()` computes the model's equilibrium X_CH4 at each record's own
  conditions and reports the bias together with the *measured* uncertainty only
  - there is deliberately no invented model-side uncertainty.
* `dP_check()`, `sintering_check()` and `regime_screening()` address the three
  specific loop-5 blockers (measured pressure drop, 200-1000 h sintering,
  kinetic-vs-equilibrium regime).
* `rerun_loop5()` returns the updated subcheck statuses, and `main()` writes
  `results_v2/pilot_ingest_report.json` plus `pilot_ingest_records.csv`.

Run it on a file as soon as data exist:

    PYTHONPATH=. .venv/bin/python -m model.data_ingest --file data/my_campaign.csv
    PYTHONPATH=. .venv/bin/python -m model.data_ingest --selftest
"""
from __future__ import annotations
import csv, json, math, os, sys

from .config import load_config
from .equipment import ergun_dp_bar
from .pilot_data import lab_feed, model_X_CH4

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(ROOT, "data", "pilot_schema.json")
R_GAS = 8.314462618


# --------------------------------------------------------------------------
# schema + file reading
# --------------------------------------------------------------------------
def load_schema(path=SCHEMA_PATH):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_records(path):
    """Read a campaign file: .json (list or {'records': [...]}) or .csv."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if path.lower().endswith(".json"):
        with open(path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        if isinstance(obj, dict):
            for key in ("records", "data", "rows", "campaign"):
                if key in obj:
                    meta = {k: v for k, v in obj.items() if k != key}
                    return list(obj[key]), meta
            raise ValueError("JSON object has no 'records' list")
        return list(obj), {}
    rows = []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        for raw in csv.DictReader(fh):
            rec = {}
            for k, v in raw.items():
                if k is None or str(k).startswith("#"):
                    continue
                k = k.strip()
                v = (v or "").strip()
                if v == "":
                    continue
                rec[k] = v
            rows.append(rec)
    return rows, {}


def _coerce(value, typ, field):
    if typ == "float":
        try:
            return float(value), None
        except (TypeError, ValueError):
            return None, f"{field}: {value!r} is not a number"
    if typ == "int":
        try:
            return int(float(value)), None
        except (TypeError, ValueError):
            return None, f"{field}: {value!r} is not an integer"
    return str(value), None


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------
def validate(records, schema=None):
    """Return (clean_records, issues). issues is a list of {run_id, level, msg}."""
    schema = schema or load_schema()
    F = schema["fields"]
    known = set(F) | {"series_id", "u_C2H6", "u_H2O", "regime"} | set(
        schema.get("regime_block", {}).get("fields", {}))
    required = schema["required_for_model_use"]
    clean, issues = [], []
    seen_ids = set()
    for i, src in enumerate(records):
        rid = str(src.get("run_id") or f"row{i+1}")
        rec, bad = {}, False
        for k, v in src.items():
            if k in known:
                rec[k] = v
            else:
                issues.append({"run_id": rid, "level": "warn",
                               "msg": f"unknown column '{k}' ignored "
                                      "(add it to the schema if it is real data)"})
        for k in required:
            if k not in rec:
                issues.append({"run_id": rid, "level": "error",
                               "msg": f"required field '{k}' missing"})
                bad = True
        if rec.get("date"):
            d = str(rec["date"])
            if not (len(d) >= 8 and d[:4].isdigit()):
                issues.append({"run_id": rid, "level": "warn",
                               "msg": f"date {d!r} is not ISO-8601"})
        if rid in seen_ids:
            issues.append({"run_id": rid, "level": "error",
                           "msg": "duplicate run_id"})
        seen_ids.add(rid)
        for k, spec in F.items():
            if k not in rec:
                continue
            typ = spec.get("type")
            if typ in ("float", "int"):
                val, err = _coerce(rec[k], typ, k)
                if err:
                    issues.append({"run_id": rid, "level": "error", "msg": err})
                    bad = True
                    continue
                lo, hi = spec.get("range"), None
                if isinstance(lo, list) and len(lo) == 2:
                    hi = lo[1]
                    lo = lo[0]
                    if val < lo or val > hi:
                        issues.append({"run_id": rid, "level": "error",
                                       "msg": f"{k}={val} outside the schema "
                                              f"range [{lo}, {hi}] "
                                              f"({spec.get('unit','')})"})
                        bad = True
                    rec[k] = val
                else:
                    rec[k] = val
            elif typ == "enum":
                allowed = spec.get("values", [])
                if str(rec[k]) not in allowed:
                    issues.append({"run_id": rid, "level": "error",
                                   "msg": f"{k}={rec[k]!r} not in the allowed set "
                                          f"{allowed}"})
                    bad = True
        # unit-sanity hints, independent of the range check: the two most common
        # entry mistakes in lab data are Celsius in a kelvin column and kPa in a
        # bar column. Both are refused rather than guessed at.
        tv = rec.get("T_K")
        if isinstance(tv, float) and 300.0 <= tv < 773.15:
            issues.append({"run_id": rid, "level": "error",
                           "msg": "T_K=%.1f looks like a Celsius value; these beds "
                                  "run 1023-1223 K (750-950 C) - convert to kelvin"
                                  % tv})
            bad = True
        pv = rec.get("p_bar")
        if isinstance(pv, float) and pv > 50.0:
            issues.append({"run_id": rid, "level": "error",
                           "msg": "p_bar=%.1f looks like kPa or psi; the contract "
                                  "wants bar ABSOLUTE" % pv})
            bad = True
        # cross-field logic
        if "X_CH4" not in rec and "y_CH4_out_dry" in rec and "y_CH4_in_dry" in rec:
            try:
                xin = float(rec["y_CH4_in_dry"])
                rec["X_CH4"] = max(0.0, (xin - float(rec["y_CH4_out_dry"])) / xin)
                rec["X_CH4_derived"] = True
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        if rec.get("X_CH4") is not None and rec.get("X_CH4_u") is None:
            issues.append({"run_id": rid, "level": "error",
                           "msg": "X_CH4 without X_CH4_u: the loop-5 acceptance "
                                  "test needs a stated uncertainty"})
            bad = True
        if "dP_bed_bar" in rec and "dP_bed_bar_u" not in rec:
            issues.append({"run_id": rid, "level": "warn",
                           "msg": "dP_bed_bar without dP_bed_bar_u"})
        if not bad:
            clean.append(rec)
    return clean, issues


# --------------------------------------------------------------------------
# model comparison
# --------------------------------------------------------------------------
def compare_one(rec, cfg=None, eos_kset="base"):
    """Model X_CH4 at the record's own conditions + the measured gap."""
    feed = lab_feed(SC=float(rec.get("S_C", 3.0)),
                    CO2C=float(rec.get("CO2_C", 0.0)),
                    O2C=float(rec.get("O2_C", 0.0)),
                    N2_per_100C=float(rec.get("N2_C", 0.0)) * 100.0,
                    CH4=float(rec.get("y_CH4_in_dry", 1.0)) * 100.0)
    T, p = float(rec["T_K"]), float(rec["p_bar"])
    mres = model_X_CH4(T, p, feed, eos_kset=eos_kset)
    Xm = float(mres["X_CH4"])
    meas = float(rec["X_CH4"])
    u = float(rec.get("X_CH4_u") or 0.0)
    out = {"run_id": rec["run_id"], "T_K": T, "p_bar": p,
           "S_C": float(rec.get("S_C", 3.0)),
           "CO2_C": float(rec.get("CO2_C", 0.0)),
           "GHSV_h1_normal": rec.get("GHSV_h1_normal"),
           "X_measured": meas, "X_model_equilibrium": Xm,
           "delta": Xm - meas, "u_meas_2sigma": 2.0 * u,
           "agreement_within_2u_meas": abs(Xm - meas) <= 2.0 * u if u > 0 else None,
           "model_carbon_stable": mres.get("carbon_stable"),
           "model_Z": mres.get("Z"),
           "contact_time_regime": rec.get("contact_time_regime"),
           "catalyst_id": rec.get("catalyst_id"),
           "time_on_stream_h": rec.get("time_on_stream_h"),
           "note": "the model is an EQUILIBRIUM model: agreement is only expected "
                   "for near-equilibrium / equilibrium points"}
    if rec.get("contact_time_regime") in ("kinetic", "unknown"):
        out["note"] += "; this point is kinetic-regime, so a positive bias is " \
                       "expected and does not falsify the equilibrium model"
    return out


def compare(records, cfg=None, eos_kset="base"):
    rows = [compare_one(r, cfg, eos_kset) for r in records]
    d = [r["delta"] for r in rows]
    eq_rows = [r for r in rows
               if r.get("contact_time_regime") in ("near-equilibrium", "equilibrium")]
    return {
        "n_points": len(rows), "rows": rows,
        "mean_bias": sum(d) / len(d) if d else None,
        "max_abs_bias": max((abs(x) for x in d), default=None),
        "mean_bias_equilibrium_regime_only":
            (sum(r["delta"] for r in eq_rows) / len(eq_rows)) if eq_rows else None,
        "n_equilibrium_regime_points": len(eq_rows),
        "n_agreements_within_2u": sum(1 for r in rows
                                      if r["agreement_within_2u_meas"]),
        "model_side_uncertainty": None,
        "model_side_uncertainty_note": "left empty ON PURPOSE. An equilibrium model "
                                       "has no defensible a-priori X_CH4 "
                                       "uncertainty until the sensitivity study of "
                                       "docs/27 sec. 7 (feed composition, T sensor "
                                       "bias, kij set, approach_K) is run on the "
                                       "measured points.",
        "interpretation": "bias > 0 means the equilibrium model is ABOVE the "
                          "measurement, i.e. the pilot point was kinetically "
                          "limited or poisoned; bias <= 0 at an equilibrium-regime "
                          "point would mean the model overpredicts conversion, "
                          "which is a thermodynamic problem, not a rate problem",
    }


# --------------------------------------------------------------------------
# the three loop-5 blockers
# --------------------------------------------------------------------------
def dP_check(records, schema=None):
    """Measured bed pressure drop vs Ergun recomputed from the record itself."""
    rows = []
    for r in records:
        if r.get("dP_bed_bar") is None:
            continue
        need = ("bed_height_mm", "pellet_d_eq_mm", "bed_voidage", "T_K", "p_bar")
        if any(r.get(k) is None for k in need):
            rows.append({"run_id": r["run_id"], "usable": False,
                         "why": "missing " + ",".join(k for k in need
                                                       if r.get(k) is None)})
            continue
        L = float(r["bed_height_mm"]) / 1000.0
        dp = float(r["pellet_d_eq_mm"]) / 1000.0
        eps = float(r["bed_voidage"])
        T, p = float(r["T_K"]), float(r["p_bar"])
        mw = (0.16 * float(r.get("y_CH4_in_dry", 1.0))
              + 0.018 * (1.0 - float(r.get("y_CH4_in_dry", 1.0))))
        rho = p * 1e5 * mw / (R_GAS * T)
        Q_norm = float(r.get("flow_total_NmL_min", 0.0)) / 1e6 / 60.0 * 0.0224140
        # superficial velocity from GHSV and bed height (bed-volume basis)
        ghsv = r.get("GHSV_h1_normal")
        v = None
        if ghsv:
            v = float(ghsv) * L / 3600.0 * (T / 273.15) * (1.01325 / p)
        mu = float(r.get("gas_viscosity_Pa_s", 2.6e-5))
        row = {"run_id": r["run_id"], "usable": v is not None,
               "dP_measured_bar": float(r["dP_bed_bar"]),
               "dP_u_bar": r.get("dP_bed_bar_u"), "L_m": L, "d_p_m": dp,
               "voidage": eps, "T_K": T, "p_bar": p, "rho_kg_m3": rho,
               "v_superficial_m_s": v, "mu_Pa_s_assumed": mu,
               "mw_assumed_kg_mol": mw}
        if v is not None:
            pa = ergun_dp_bar(L, dp, eps, dp, mu, rho, v)
            row["dP_ergun_bar"] = pa / 1e5
            row["ratio_measured_over_ergun"] = (float(r["dP_bed_bar"])
                                                / max(row["dP_ergun_bar"], 1e-12))
            row["note"] = ("sphericity, wall effects and inlet/exit losses are NOT "
                           "in the Ergun form used here; a ratio outside 0.7-1.4 "
                           "means the model's bed hydraulics must be re-fitted")
        rows.append(row)
    good = [x for x in rows if x.get("usable")]
    rat = [x["ratio_measured_over_ergun"] for x in good
           if x.get("ratio_measured_over_ergun")]
    return {"n_dP_points": len(rows), "n_usable": len(good),
            "rows": rows,
            "mean_ratio_measured_over_ergun": (sum(rat) / len(rat)) if rat else None,
            "ergun_confirmed": bool(rat) and all(0.7 <= x <= 1.4 for x in rat),
            "status": ("[ЧАСТИЧНО] measured dP available" if rat else
                       "[НЕ ПОДТВЕРЖДЕНО] no usable measured dP yet")}


def sintering_check(records):
    """Group time-on-stream points into sintering series and test the two
    candidate laws (generalised power law vs cubic / d^3 power law) - the v1
    open question, which today disagrees by a factor of ~3 in predicted life."""
    series = {}
    for r in records:
        if r.get("time_on_stream_h") is None or r.get("Ni_size_nm") is None:
            continue
        key = str(r.get("series_id") or (r.get("catalyst_id", "?") + "@"
                                         + str(r.get("T_K", 0)) + "K"))
        series.setdefault(key, []).append(r)
    out = []
    for key, pts in series.items():
        pts = sorted(pts, key=lambda x: float(x["time_on_stream_h"]))
        t = [float(x["time_on_stream_h"]) for x in pts]
        d = [float(x["Ni_size_nm"]) for x in pts]
        row = {"series_id": key, "n_points": len(pts),
               "t_h": [round(x, 1) for x in t], "d_Ni_nm": d,
               "usable": len(pts) >= 3 and t[-1] >= 200.0}
        if row["usable"]:
            n0 = max(t[0], 1e-6)
            d0 = d[0]
            dt = t[-1] - n0
            if dt > 0 and d[-1] > d0:
                row["cubic_k_d3_per_h"] = (d[-1] ** 3 - d0 ** 3) / dt
                row["GPLE_like_exponent_n"] = (
                    math.log((d[-1] ** 3 - d0 ** 3) / max(d0 ** 3, 1e-9))
                    / math.log(max(t[-1], 1.0001) / n0) if n0 > 0 else None)
                row["extrapolated_t50_cubic_h"] = (
                    (10 * d0) ** 3 / max(row["cubic_k_d3_per_h"], 1e-12))
                row["activity_loss_pct_per_1000h"] = (
                    100.0 * (float(pts[0].get("X_CH4", 0.0))
                             - float(pts[-1].get("X_CH4", 0.0))) / dt
                    * 1000.0 if all(x.get("X_CH4") is not None for x in (pts[0], pts[-1]))
                    else None)
                row["note"] = ("t50 defined as doubling of the mean Ni diameter; "
                               "the design-basis life in cases/config.json is a "
                               "different quantity (activity loss + changeout)")
        else:
            row["why_not_usable"] = "a sintering series needs >= 3 points and a " \
                                    "final time >= 200 h"
        out.append(row)
    good = [x for x in out if x["usable"]]
    return {"n_series": len(out), "n_usable_series": len(good), "series": out,
            "design_life_h": 32000.0,
            "worst_extrapolated_t50_h": min((x.get("extrapolated_t50_cubic_h") or
                                             float("inf") for x in good),
                                            default=None),
            "meets_200_1000h_requirement": bool(good),
            "status": ("[ЧАСТИЧНО] sintering series present; law discrimination "
                       "still needs >= 2 independent series" if good else
                       "[НЕ ПОДТВЕРЖДЕНО] no 200-1000 h sintering series")}


def regime_screening(records, tau=3.5, r_pore_nm=50.0, eps_p=0.5):
    """Screening check of internal transport - documented inputs, no fitting.

    D_eff is built from kinetic theory only: Knudsen diffusivity in a cylinder of
    radius r_pore plus a parallel tortuosity/porosity factor eps_p/tau. The
    Weisz-Prater modulus is then compared with 1. If it exceeds 1 the point is
    NOT equilibrium-limited and must not be used to falsify the equilibrium model.
    tau=3.5, pore radius 50 nm and porosity 0.5 are ASSUMPTIONS to be replaced by
    the vendor datasheet (docs/28_v5_vendor_rfi.md items 5-8).
    """
    rows = []
    M = 0.016
    for r in records:
        if r.get("W_cat_g") is None or r.get("X_CH4") is None:
            continue
        T, p = float(r["T_K"]), float(r["p_bar"])
        W = float(r["W_cat_g"]) / 1000.0
        F_CH4 = float(r.get("flow_total_NmL_min", 0.0)) * 60.0 * \
            float(r.get("y_CH4_in_dry", 1.0)) / 22414.0   # mol/h CH4 fed
        rate = F_CH4 * float(r["X_CH4"])                   # mol/h
        rate_kg_s = rate / max(W, 1e-9) / 3600.0           # mol/(kg s)
        C_s = p * 1e5 * float(r.get("y_CH4_out_dry", 0.05)) / (R_GAS * T)
        D_K = (2.0 / 3.0) * (r_pore_nm * 1e-9) * math.sqrt(
            8.0 * R_GAS * T / (math.pi * M))
        D_eff = max(D_K * eps_p / tau, 1e-12)
        R_p = float(r.get("pellet_d_eq_mm", 2.0)) * 1e-3 / 2.0
        rho_p = float(r.get("rho_loaded_kg_m3", 900.0))
        Phi = rate_kg_s * rho_p * R_p ** 2 / max(D_eff * C_s, 1e-30)
        rows.append({"run_id": r["run_id"], "rate_mol_per_kg_s": rate_kg_s,
                     "D_Knudsen_m2_s": D_K, "D_eff_m2_s": D_eff,
                     "Weisz_Prater": Phi,
                     "internal_gradients_negligible": Phi < 1.0,
                     "assumptions": {"tau": tau, "r_pore_nm": r_pore_nm,
                                     "eps_p": eps_p}})
    return {"rows": rows, "n": len(rows),
            "all_kinetic_clean": bool(rows) and all(
                x["internal_gradients_negligible"] for x in rows),
            "status": "[ДОПУЩЕНИЕ] screening only: tau, pore radius and porosity "
                      "are assumed, not vendor data",
            "note": "a modulus above 1 means the measured point is transport-"
                    "limited, so neither the equilibrium nor the intrinsic-"
                    "kinetic model should be compared with it without a corrected "
                    "effectiveness factor"}


# --------------------------------------------------------------------------
# loop-5 rerun
# --------------------------------------------------------------------------
def rerun_loop5(cfg=None, records=(), cmp=None, dp=None, sinter=None):
    """Status of the three pilot-data subchecks of loop 5, given ingested data.

    Loop 5 as a whole CANNOT pass from these three alone: the catalyst
    datasheet, the certified HAZOP and the independent flowsheet run are
    separate subchecks owned by other people (docs/28, docs/29).
    """
    cfg = cfg or load_config()
    cmp = cmp or {"n_points": 0, "mean_bias": None}
    dp = dp or {"n_usable": 0, "ergun_confirmed": False}
    sinter = sinter or {"n_usable_series": 0}
    design_pts = [r for r in records
                  if 20.0 <= float(r.get("p_bar", 0.0)) <= 31.0
                  and 1023.15 <= float(r.get("T_K", 0.0)) <= 1173.15]
    mb = cmp.get("mean_bias")
    eq_mb = cmp.get("mean_bias_equilibrium_regime_only")
    used = eq_mb if eq_mb is not None else mb
    return [
        {"check": "pilot data at model design point (20-31 bar, 15 wt% Ni/MgAl2O4)",
         "passed": len(design_pts) >= 12 and used is not None and abs(used) <= 0.05,
         "value": {"n_design_point_records": len(design_pts),
                   "mean_bias": used},
         "note": "needs >= 12 points inside the design window and |mean bias| "
                 "<= 0.05 (on equilibrium-regime points only when flagged)"},
        {"check": "measured packed-bed dP",
         "passed": dp.get("n_usable", 0) >= 6 and dp.get("ergun_confirmed", False),
         "value": {"n_usable": dp.get("n_usable"),
                   "mean_ratio": dp.get("mean_ratio_measured_over_ergun")},
         "note": ">= 6 usable points and measured/Ergun within 0.7-1.4"},
        {"check": "200-1000 h sintering series",
         "passed": sinter.get("n_usable_series", 0) >= 2,
         "value": sinter.get("n_usable_series"),
         "note": ">= 2 independent series with >= 3 points reaching >= 200 h, so "
                 "that the GPLE vs cubic-law disagreement can be decided"},
    ]


def report(records_path=None, records=None, cfg=None, write=True):
    schema = load_schema()
    meta = {}
    if records_path:
        records, meta = read_records(records_path)
    records = list(records or [])
    clean, issues = validate(records, schema)
    cmp = compare(clean, cfg) if clean else {"n_points": 0, "rows": [],
                                            "mean_bias": None,
                                            "mean_bias_equilibrium_regime_only": None,
                                            "n_agreements_within_2u": 0}
    dp = dP_check(clean) if clean else {"n_usable": 0, "rows": [],
                                        "ergun_confirmed": False,
                                        "status": "[НЕ ПОДТВЕРЖДЕНО] no file given"}
    sinter = sintering_check(clean) if clean else {
        "n_usable_series": 0, "series": [],
        "status": "[НЕ ПОДТВЕРЖДЕНО] no file given"}
    reg = regime_screening(clean) if clean else {"rows": [], "n": 0}
    subs = rerun_loop5(cfg, clean, cmp, dp, sinter)
    out = {
        "contract": {"name": schema["name"], "version": schema["version"],
                     "schema_file": "data/pilot_schema.json"},
        "input_file": records_path, "input_meta": meta,
        "n_records_read": len(records), "n_records_usable": len(clean),
        "issues": issues,
        "n_errors": sum(1 for i in issues if i["level"] == "error"),
        "n_warnings": sum(1 for i in issues if i["level"] == "warn"),
        "comparison": cmp, "dP": dp, "sintering": sinter, "regime": reg,
        "loop5_subcheck_status": subs,
        "loop5_subchecks_passed_from_this_data": sum(1 for s in subs if s["passed"]),
        "loop5_overall": "cannot pass from this data alone: catalyst datasheet, "
                         "certified HAZOP and independent flowsheet run are "
                         "separate subchecks",
        "status": ("[ЧАСТИЧНО] campaign data ingested and compared" if clean else
                   "[НЕ ПОДТВЕРЖДЕНО] no usable campaign data"),
    }
    if write and records_path:
        os.makedirs(os.path.join(ROOT, "results_v2"), exist_ok=True)
        with open(os.path.join(ROOT, "results_v2", "pilot_ingest_report.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, ensure_ascii=False, default=float)
        if cmp.get("rows"):
            with open(os.path.join(ROOT, "results_v2",
                                    "pilot_ingest_records.csv"),
                      "w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                keys = list(cmp["rows"][0])
                w.writerow(keys)
                for rr in cmp["rows"]:
                    w.writerow([rr.get(k) for k in keys])
    return out


def selftest():
    """Round-trip: build 3 synthetic-but-sourced-shaped records from the EXISTING
    pilot registry, translate them into the contract, validate, compare.

    The records are the registry's own numbers (already opened sources); the
    point of the self-test is that the contract and the ingest path work, NOT
    that new data exist - so loop-5 statuses are expected to stay failed.
    """
    from .pilot_data import _measured_value
    pilot = json.load(open(os.path.join(ROOT, "data", "pilot_ni_mgal2o4.json"),
                           encoding="utf-8"))
    recs = []
    for r in pilot["records"]:
        if r.get("quantity") not in ("X_CH4", "X_CH4_Pt0"):
            continue
        meas = _measured_value(r)
        c = r.get("conditions", {})
        if meas is None or c.get("T_C") is None:
            continue
        # CH4 fraction from the feed string when the paper gives one
        y_ch4, y_h2o = 1.0, float(c.get("S_C", 3.0)) / (1.0 + float(c.get("S_C", 3.0)))
        feed = str(c.get("feed", ""))
        if "/" in feed.replace(" ", ""):
            try:
                parts = [float(x) for x in feed.replace(" ", "").split("=")[-1].split("/")]
                if len(parts) == 3:
                    ch4, h2o, inert = parts
                    y_ch4 = ch4 / (ch4 + inert)
                    y_h2o = h2o / (ch4 + h2o + inert)
            except ValueError:
                pass
        pm = c.get("particle_mm")
        recs.append({
            "run_id": "ST-" + str(r.get("id")), "date": "2020-01-01",
            "lab": str(r.get("source_id")),
            "catalyst_id": "15wt-Ni/MgAl2O4 (registry record)",
            "Ni_wt_pct": c.get("Ni_wt_pct", 15.0),
            "support": c.get("support", "MgAl2O4"),
            "T_K": float(c["T_C"]) + 273.15,
            "p_bar": float(c["p_bar"]) if c.get("p_bar") is not None else 1.013,
            "S_C": float(c.get("S_C", 3.0)), "CO2_C": float(c.get("CO2_C", 0.0)),
            "y_CH4_in_dry": y_ch4, "y_H2O_in": y_h2o,
            "GHSV_h1_normal": float(c.get("GHSV_h1", 10000.0)),
            "flow_total_NmL_min": 220.0, "conversion_basis": "dry",
            "X_CH4": meas, "X_CH4_u": 0.02,
            "contact_time_regime": "kinetic",
            "pellet_d_eq_mm": (0.5 * (pm[0] + pm[1]) if isinstance(pm, list)
                               else 0.5),
            "bed_height_mm": 5.0, "bed_voidage": 0.4, "W_cat_g": 0.009,
            "time_on_stream_h": 1.0,
            "notes": "translated from data/pilot_ni_mgal2o4.json for the ingest "
                     "self-test; X_CH4_u=0.02 is a PLACEHOLDER because the papers "
                     "do not state an uncertainty, and bed geometry values are "
                     "placeholders too - this self-test validates the CONTRACT and "
                     "the ingest path, not the data",
        })
    clean, issues = validate(recs, load_schema())
    cmp = compare(clean) if clean else None
    return {"n_built": len(recs), "n_usable": len(clean), "issues": issues,
            "comparison": cmp, "dP": dP_check(clean),
            "sintering": sintering_check(clean),
            "regime": regime_screening(clean),
            "loop5_subcheck_status": rerun_loop5(None, clean, cmp,
                                                 dP_check(clean),
                                                 sintering_check(clean))}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="validate a pilot campaign file "
                                             "against data/pilot_schema.json and "
                                             "rerun the loop-5 pilot checks")
    ap.add_argument("--file", help="CSV or JSON campaign file")
    ap.add_argument("--selftest", action="store_true",
                    help="round-trip the existing pilot registry instead")
    a = ap.parse_args(argv)
    if a.selftest:
        st = selftest()
        print(json.dumps({k: v for k, v in st.items() if k != "comparison"},
                         indent=1, default=float)[:2500])
        if st.get("comparison"):
            print("mean bias %.3f over %d points" % (
                st["comparison"]["mean_bias"], st["comparison"]["n_points"]))
        return 0
    if not a.file:
        ap.error("--file or --selftest is required")
    rep = report(a.file)
    print(json.dumps({k: rep[k] for k in ("n_records_read", "n_records_usable",
                                          "n_errors", "n_warnings", "status",
                                          "loop5_subchecks_passed_from_this_data")},
                     indent=1))
    for i in rep["issues"][:20]:
        print(f"  {i['level'].upper():5} {i['run_id']}: {i['msg'][:110]}")
    for s in rep["loop5_subcheck_status"]:
        print(("  PASS " if s["passed"] else "  FAIL ") + s["check"])
    print("-> results_v2/pilot_ingest_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
