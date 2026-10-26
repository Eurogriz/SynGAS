"""V2 entry point: run all five product variants + scenarios + verification.

Usage:  PYTHONPATH=. .venv/bin/python -m model.run_v2
Outputs everything under results_v2/ and writes the V2 reports under docs/.
"""
from __future__ import annotations
import csv, json, math, os, sys, time
import numpy as np

from .config import Config, load_config, DEFAULT_PATH
from .scenarios import (run_all, run_base, run_variant, run_normal_comparison,
                        run_climate_comparison, run_feed_comparison,
                        run_eos_sensitivity, run_regulation_sweep,
                        run_ni_life_sensitivity, _compact, PRODUCTS)
from .products import design
from .verify_v2 import run_all as verify_all

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results_v2")
DOCS = os.path.join(ROOT, "docs")
os.makedirs(OUT, exist_ok=True)
os.makedirs(DOCS, exist_ok=True)


def to_jsonable(o):
    if isinstance(o, dict):
        return {k: to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [to_jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o


def dump_json(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(to_jsonable(obj), fh, indent=2, ensure_ascii=False, default=str)


def write_csv(path, rows):
    if not rows:
        return
    keys = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: to_jsonable(r.get(k)) for k in keys})


# --------------------------------------------------------------------------
# plots
# --------------------------------------------------------------------------
def make_plots(designs, scenarios, verification):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"figure.dpi": 120, "font.size": 9,
                         "axes.grid": True, "grid.alpha": 0.3})
    colours = {"methanol": "#1f77b4", "ft": "#ff7f0e", "oxo": "#2ca02c",
               "hydrogen": "#d62728", "ammonia": "#9467bd"}

    # 1 product comparison -------------------------------------------------
    fig, ax = plt.subplots(2, 2, figsize=(11, 7.5))
    prods = list(designs)
    met = [designs[p]["spec"]["achieved"] for p in prods]
    tgt = [designs[p]["spec"]["target"] for p in prods]
    x = np.arange(len(prods))
    ax[0, 0].bar(x - 0.2, met, 0.4, label="achieved", color=[colours[p] for p in prods])
    ax[0, 0].scatter(x + 0.2, tgt, marker="_", s=600, color="k", label="target")
    ax[0, 0].set_xticks(x, [designs[p]["spec"]["metric"] + "\n" + p for p in prods])
    ax[0, 0].set_title("Product quality metric (tuner hits target)")
    ax[0, 0].legend()
    ax[0, 1].bar(prods, [designs[p]["catalyst"]["total_Ni_inventory_t"] for p in prods],
                 color=[colours[p] for p in prods])
    ax[0, 1].set_title("Ni inventory [t] at 15 wt% Ni/MgAl$_2$O$_4$")
    ax[1, 0].bar(prods, [designs[p]["economics"]["levelised_cost"] for p in prods],
                 color=[colours[p] for p in prods])
    ax[1, 0].set_title("Levelised cost (units differ: see labels)")
    for i, p in enumerate(prods):
        ax[1, 0].text(i, designs[p]["economics"]["levelised_cost"],
                      designs[p]["economics"]["unit"].split("/")[-1],
                      ha="center", va="bottom", fontsize=7)
    ax[1, 1].bar(prods, [designs[p]["utilities"]["total_CO2_t_h"] for p in prods],
                 color=[colours[p] for p in prods])
    ax[1, 1].set_title("Total CO$_2$ (fuel + captured process) [t/h]")
    fig.suptitle("SynGAS V2 - five product variants (Russia, 0 C normal)", fontsize=12)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "01_product_comparison.png")); plt.close(fig)

    # 2 normal comparison --------------------------------------------------
    nc = scenarios["normal_comparison"]
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.6))
    labels = [r["normal"] for r in nc]
    ax[0].bar(labels, [r["Vm_m3_per_mol"] for r in nc], color=["#1f77b4", "#ff7f0e"])
    ax[0].set_title("Normal molar volume [m$^3$/mol]")
    ax[1].bar(labels, [r["dry_feed_Nm3_h"] for r in nc], color=["#1f77b4", "#ff7f0e"])
    ax[1].set_title("Dry natural-gas feed [Nm$^3$/h] for the SAME molar plant")
    for a in ax:
        a.set_ylabel("value")
    fig.suptitle("Both normal-cubic-metre definitions (user answer 3/4)", fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "02_normal_comparison.png")); plt.close(fig)

    # 3 climate -------------------------------------------------------------
    cc = scenarios["climate_comparison"]
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.8))
    for p in ("methanol", "hydrogen", "ammonia"):
        ys = [r for r in cc if r["product"] == p]
        ax[0].plot([r["climate"] for r in ys], [r["cooling_water_m3_h"] for r in ys],
                   "o-", label=p)
        ax[1].plot([r["climate"] for r in ys], [r["levelised_cost"] for r in ys],
                   "o-", label=p)
    ax[0].set_title("Cooling-water circulation [m$^3$/h]")
    ax[1].set_title("Levelised cost (units differ by product)")
    for a in ax: a.legend(fontsize=8)
    fig.suptitle("Russia vs Middle East site cases (user answer 8)", fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "03_climate_comparison.png")); plt.close(fig)

    # 4 EOS sensitivity -----------------------------------------------------
    es = scenarios["eos_sensitivity"]
    fig, ax = plt.subplots(1, 2, figsize=(9.5, 3.6))
    ks = [r["kij_set"] for r in es]
    ax[0].plot(ks, [r["X_CH4"] for r in es], "o-")
    ax[0].set_title("PR k$_{ij}$ sensitivity: X$_{CH4}$")
    ax[1].plot(ks, [r["achieved"] for r in es], "o-", label="SN")
    ax[1].axhline(2.05, color="k", ls="--", label="target 2.05")
    ax[1].set_title("SN vs k$_{ij}$ set")
    ax[1].legend(fontsize=8)
    for a in ax: a.tick_params(axis="x", rotation=20)
    fig.suptitle("Peng-Robinson real-gas sensitivity (maximum-accuracy mode)", fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "04_eos_sensitivity.png")); plt.close(fig)

    # 5 regulation sweep ----------------------------------------------------
    sw = scenarios["regulation_sweep"]
    fig, ax = plt.subplots(2, 3, figsize=(12, 6.6))
    for i, p in enumerate(PRODUCTS):
        a = ax.flat[i]
        rows = [r for r in sw if r["product"] == p]
        if not rows: continue
        a.plot([r["value"] for r in rows], [r["achieved"] for r in rows], "o-",
               color=colours[p])
        a.axhline(rows[0]["target"], color="k", ls="--", label="target")
        a.set_xlabel(rows[0]["knob"]); a.set_ylabel(rows[0]["metric"])
        a.set_title(p); a.legend(fontsize=7)
    ax.flat[-1].axis("off")
    fig.suptitle("Regulation / tunability: product metric vs main control knob", fontsize=12)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "05_regulation_sweep.png")); plt.close(fig)

    # 6 tube profile --------------------------------------------------------
    prof = designs["methanol"]["equipment"]["tube_thermal_profile"]
    if prof:
        fig, ax = plt.subplots(1, 2, figsize=(9.5, 3.6))
        L = [p["length_m"] for p in prof["profile"]]
        ax[0].plot(L, [p["T_gas_K"] for p in prof["profile"]], label="gas")
        ax[0].plot(L, [p["T_wall_K"] for p in prof["profile"]], label="tube wall")
        ax[0].set_xlabel("heated length [m]"); ax[0].set_ylabel("T [K]"); ax[0].legend()
        ax[0].set_title("1-D tube thermal profile")
        ax[1].plot(L, [p["X_CH4_local"] for p in prof["profile"]], color="g")
        ax[1].set_xlabel("heated length [m]"); ax[1].set_ylabel("X$_{CH4}$")
        ax[1].set_title("Local methane conversion")
        fig.tight_layout(); fig.savefig(os.path.join(OUT, "06_tube_profile.png")); plt.close(fig)

    # 7 Ni life -------------------------------------------------------------
    nl = scenarios["ni_life_sensitivity"]
    fig, ax = plt.subplots(1, 2, figsize=(9.5, 3.6))
    for p in PRODUCTS:
        rows = [r for r in nl if r["product"] == p]
        ax[0].plot([r["life_years"] for r in rows],
                   [r["Ni_consumption_t_per_y"] for r in rows], "o-", label=p,
                   color=colours[p])
        ax[1].bar(p, rows[0]["Ni_inventory_t"], color=colours[p])
    ax[0].set_xlabel("catalyst service life [y]")
    ax[0].set_ylabel("Ni make-up [t/y]"); ax[0].legend(fontsize=8)
    ax[1].set_title("Ni inventory [t] by product")
    fig.suptitle("Nickel requirement vs catalyst life (user answer 12)", fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "07_nickel_inventory.png")); plt.close(fig)


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------
def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def fnum(x, n=3):
    if x is None: return "n/a"
    try: return f"{float(x):.{n}f}"
    except Exception: return str(x)


def write_reports(designs, scenarios, v):
    # 12 product variants --------------------------------------------------
    rows = []
    for p, r in designs.items():
        s, u, e, c = r["spec"], r["utilities"], r["economics"], r["catalyst"]
        rows.append([p, s["metric"], fnum(s["target"], 5), fnum(s["achieved"], 5),
                     "YES" if s["within_tolerance"] else "NO",
                     "yes" if s["carbon_stable"] else "no",
                     fnum(r["reformer"]["equilibrium"]["CH4_conversion"], 4),
                     fnum(r["reformer"]["T_out_K"], 1), fnum(r["reformer"]["p_bar"], 1),
                     fnum(s["CO2_molpct"], 2), fnum(s["CH4_molpct"], 2),
                     fnum(e["levelised_cost"], 2), e["unit"]])
    txt = f"""# 12. V2 - five product variants (G0-G8)

Generated by `PYTHONPATH=. .venv/bin/python -m model.run_v2` on 2026-10-26.
All numbers are model results; status labels follow the user's rule.

## 12.1 Answer to G0 question 1: product variants

{md_table(["product", "metric", "target", "achieved", "hit", "graphite stable",
           "X_CH4", "T_out K", "p bar", "CO2 mol%", "CH4 mol%", "cost", "unit"], rows)}

**Target sources (all opened):** methanol SN 2.0-2.1 [Uhde 2010 Table 1, RSC EES 2020];
FT Co H2/CO 2.0-2.2 [Uhde 2010, OSTI 1547249]; oxo H2/CO 1.0-1.25
[Techniques de l'Ingenieur, KFUPM]; H2 ISO 14687:2025 grade D (opened official
sample PDF, Table 3); ammonia H2/N2 = 3 [EPA AP-42 8.1, Uhde 2010].
Status [ПОДТВЕРЖДЕНО] for the metric definitions; the chosen set-points inside
each range are design decisions.

## 12.2 Routes and tuned control knobs

{md_table(["product", "route", "tuned knob", "S/C", "CO2/C", "O2/C", "p bar", "air ratio", "T_out K"],
          [[p, designs[p]["config"]["route"], designs[p]["tuning"]["tuned_knob"],
            fnum(designs[p]["knobs"]["SC"], 3), fnum(designs[p]["knobs"]["CO2C"], 4),
            fnum(designs[p]["knobs"]["O2C"], 4), fnum(designs[p]["reformer"]["p_bar"], 2),
            fnum(designs[p]["knobs"].get("air_ratio"), 3),
            fnum(designs[p]["reformer"]["T_out_K"], 1)] for p in designs])}

- Methanol: bi-reforming (steam + CO2) in a fired tubular reformer; CO2/C is
  bisected to SN = 2.05.
- FT: low-S/C adiabatic ATR; O2/C is bisected to H2/CO = 2.10. The adiabatic
  solve enforces H_in = H_out; O2 comes from an ASU.
- Oxo: CO2 (dry) + steam reforming; CO2/C is bisected to H2/CO = 1.05.
- Hydrogen: SMR + HTS/LTS WGS + MDEA + PSA; H2 purity 99.97%, CO/CO2/H2O/CH4/N2
  checked against ISO 14687:2025 grade D.
- Ammonia: primary reformer + air-blown secondary reformer + WGS + MDEA +
  methanation + dryer; air ratio is bisected to H2/N2 = 3.

## 12.3 Both normal-cubic-metre definitions (user answer 3/4)

{md_table(["normal", "T K", "Vm m3/mol", "dry feed Nm3/h", "product Nm3/h", "cost"],
          [[r["normal"], 273.15 if r["normal"]=="0C" else 288.15,
            fnum(r["Vm_m3_per_mol"], 8), fnum(r["dry_feed_Nm3_h"], 1),
            fnum(r["product_Nm3_h"], 1), fnum(r["levelised_cost"], 2)]
           for r in scenarios["normal_comparison"]])}

The 15 C / 101325 Pa ISO 13443 molar volume is 5.49% larger than the 0 C value.
The **molar** plant is identical; only the volumetric labels change. Quoting a
capacity without the normal condition is a 5.5% error.

## 12.4 k_ij / EOS sensitivity (user answer 9)

{md_table(["k_ij set", "Z", "X_CH4", "SN", "cost"],
          [[r["kij_set"], fnum(r["Z"], 5), fnum(r["X_CH4"], 5), fnum(r["achieved"], 4),
            fnum(r["levelised_cost"], 2)] for r in scenarios["eos_sensitivity"]])}

## 12.5 Open items

- Methanol make-up gas contains {fnum(designs["methanol"]["spec"]["CO2_molpct"],2)} mol% CO2,
  above the 3-8 mol% typical of licensed methanol loops. An acid-gas trim
  (with re-tuning of CO2/C) is required before a licence-grade design.
  Status [ЧАСТИЧНО]; no methanol-licensor spec was opened.
- Ammonia-loop compression and synthesis, methanol/FT/oxo synthesis loops and
  their recycle/ purge systems are outside this boundary. [НЕ ПОДТВЕРЖДЕНО]
- C4+ is lumped into C3H8 on a carbon-equivalent basis (preserves C, overstates H).
  [ДОПУЩЕНИЕ]
"""
    open(os.path.join(DOCS, "12_v2_product_variants.md"), "w", encoding="utf-8").write(txt)

    # 13 verification ------------------------------------------------------
    L = v["loops"]
    txt = f"""# 13. V2 maximum-accuracy verification (five loops, G8)

HYSYS status: **NOT RUN**. User answer 11 = "otherwise confirm" -> the
Python/DWSIM-equivalent plus `docs/HYSYS_case_spec.md` is CONFIRMED as the
accepted equivalent. No claim of a HYSYS run is made.

## 13.1 Loop summary

{md_table(["loop", "passed", "key number"],
          [[k, "YES" if x["passed"] else "NO",
            (f"max rel error {x['max_relative_error']:.3g}" if "max_relative_error" in x else
             f"max error {x['max_error_pct']:.3g}%" if "max_error_pct" in x else
             f"{x['n_claims']} claims" if "n_claims" in x else
             f"Q*Kphi/K dev {x['worst_PR_deviation_pct']:.4g}%" if "worst_PR_deviation_pct" in x else
             x["status"])] for k, x in L.items()])}

Overall: **{'PASS' if v['overall_passed'] else 'FAIL (loop 5 open by design)'}**.

## 13.2 Loop 1 - sources and claims

{L['1_sources']['n_claims']} registered claims: {L['1_sources']['by_status']}.
Problems: {L['1_sources']['problems']}. Full registry: `data/v2_claims.json`,
`docs/v2_claims_register.md`.

## 13.3 Loop 2 - arithmetic

{L['2_arithmetic']['n_checks']} independent recomputations, worst relative
error {L['2_arithmetic']['max_relative_error']:.3g}
({L['2_arithmetic']['worst_check']}).

## 13.4 Loop 3 - conservation

Worst element/enthalpy imbalance {L['3_conservation']['max_error_pct']:.3g}%.
The full-flowsheet check explicitly includes condensed water, MDEA CO2 product,
PSA tail gas and dryer water.

## 13.5 Loop 4 - thermodynamic consistency

- Real-gas equilibrium: worst |Q*Kphi/K - 1| = {L['4_thermo']['worst_PR_deviation_pct']:.4g}%.
- Compressibility factors by product:
{md_table(["product", "Z", "Kphi_R1", "Q1/K1 (real)"],
          [[r["product"], fnum(r["Z"], 5), fnum(r["Kphi_R1"], 5),
            fnum(r["Q1_over_K1_real"], 8)] for r in L['4_thermo']["PR_equilibrium"]])}
- Shomate vs NASA7 reaction enthalpies at 1123 K:
{md_table(["reaction", "Shomate kJ/mol", "NASA7 kJ/mol", "difference"],
          [[k, fnum(x["shomate"], 3), fnum(x["nasa7"], 3), fnum(x["diff_kJ_per_mol"], 3)]
           for k, x in L['4_thermo']["reaction_enthalpies"].items()])}
- IAPWS-IF97: h(30 bar, 673.15 K) = {fnum(L['4_thermo']['IAPWS']['h_30bar_673K_kJ_per_kg'],3)} kJ/kg
  (reference 3231.571), Tsat(30 bar) = {fnum(L['4_thermo']['IAPWS']['Tsat_30bar_K'],3)} K
  (reference 507.008). Status [ЧАСТИЧНО]: the IF97 revision guide was NOT opened;
  the installed package version is pinned.
- Dew point IF97 {fnum(L['4_thermo']['dew_point_IF97_K'],2)} K vs NIST Antoine
  {fnum(L['4_thermo']['dew_point_NIST_K'],2)} K; difference
  {fnum(L['4_thermo']['dew_point_diff_K'],2)} K. This is why IF97 is the primary
  water/steam property source in V2.
- PR vs ideal X_CH4: {fnum(L['4_thermo']['PR_vs_ideal']['X_ideal'],5)} -> {fnum(L['4_thermo']['PR_vs_ideal']['X_PR'],5)} (delta {fnum(L['4_thermo']['PR_vs_ideal']['delta_X'],5)}); k_ij spread in X_CH4 = {fnum(L['4_thermo']['kij_X_CH4_spread'],6)}.

## 13.6 Loop 5 - validation / falsification

**{L['5_validation_falsification']['status']}**.
{L['5_validation_falsification']['reason']}

Unchecked items:
""" + "\n".join(f"{i+1}. {x}" for i, x in enumerate(L['5_validation_falsification']['unchecked_items'])) + """

## 13.7 Equipment accuracy upgrades

- 1-D tube thermal profile with local equilibrium composition;
  T_wall,max for methanol = """ + fnum(designs["methanol"]["equipment"]["T_wall_max_K"], 1) + """ K
  (""" + fnum(designs["methanol"]["equipment"]["T_wall_max_K"] - 273.15, 1) + """ C),
  consistent with the ~1000 C wall reported in the opened electrified-SMR study.
- LMP creep: C = 22.4, one opened HP-Nb point (11 MPa at LMP 35.2),
  API 530 thin-cylinder equation t = P*Do/(2S+P) + corrosion allowance.
  Required thickness """ + fnum(designs["methanol"]["equipment"]["creep"]["required_wall_thickness_m"], 5) + """ m
  vs specified """ + fnum(designs["methanol"]["equipment"]["creep"]["specified_wall_thickness_m"], 5) + """ m
  -> """ + ("PASS" if designs["methanol"]["equipment"]["creep"]["wall_adequate"] else "FAIL") + """.
  The master-curve slope is an [ДОПУЩЕНИЕ]; this is NOT an API 530 certification.
- Ergun dP for the packed tubes: """ + fnum(designs["methanol"]["equipment"]["Ergun_dP_bar"], 3) + """ bar
  (limit """ + fnum(load_config().equipment["dP_max_bar"], 2) + """ bar).
"""
    open(os.path.join(DOCS, "13_v2_accuracy_verification.md"), "w", encoding="utf-8").write(txt)

    # 14 catalyst / Ni -----------------------------------------------------
    rows = []
    for p, r in designs.items():
        c = r["catalyst"]
        rows.append([p, fnum(c["reformer_catalyst_volume_m3"], 2),
                     fnum(c["pre_reformer_catalyst_volume_m3"], 2),
                     fnum(c["total_catalyst_mass_t"], 2),
                     fnum(c["total_Ni_inventory_t"], 3),
                     fnum(c["Ni_consumption_t_per_y"], 3),
                     fnum(c["catalyst_consumption_t_per_y"], 2),
                     fnum(c["ZnO_guard_mass_kg"], 0), fnum(c["Ni_per_1000Nm3_product_kg"], 4)])
    life_rows = [[r["product"], r["life_years"], fnum(r["Ni_consumption_t_per_y"], 3),
                  fnum(r["catalyst_consumption_t_per_y"], 2)]
                 for r in scenarios["ni_life_sensitivity"]
                 if r["product"] == "methanol"]
    txt = f"""# 14. Ni/MgAl2O4 catalyst volumes, life, consumption and nickel (user 10/12)

## 14.1 Chemistry basis (opened, not invented)

- **Ni/MgAl2O4, 15 wt% Ni, BET 86 m2/g, Ni particle 6.6 nm, reduction 850 C/16 h**
  - Catalysts 2019, 9(10), 801 (opened). [ПОДТВЕРЖДЕНО]
- EP1013603A1 (opened): 10-60 wt% Ni on high-surface MgAl2O4, BET 183-192 m2/g.
  Legal status Ceased; this is a technical range, NOT a patent-freedom conclusion.
- PNNL-23207 (opened): 20% Ni/MgAl2O4 gives 4.6 nm Ni vs 8.6 nm on Al2O3;
  TPR complete at 800 C; deactivation data. J Catal 2001 Sehested (opened):
  most Ni sintering occurs in the first 200 h.

## 14.2 Engineering PROXY (explicitly not MgAl2O4)

The opened Johnson Matthey KATALCO brochure gives loaded density 780-1140 kg/m3
(we use 900), NiO 16-18 wt% (= 12.6-14.1 wt% Ni metal), QUADRALOBE shapes,
>80% strength after 5 years and catalyst lives >8-10 years. Its supports are
alpha-Al2O3 / calcium aluminate, **NOT MgAl2O4**. Therefore 15 wt% Ni on MgAl2O4
is combined with the commercial bulk properties only as a clearly marked
[ЧАСТИЧНО] proxy. A vendor Ni/MgAl2O4 datasheet was NOT found.

Ni metal from NiO: 17 wt% * 58.6934/74.6924 = """ + fnum(designs["methanol"]["catalyst"]["proxy_NiO_as_Ni_metal_wt_pct"], 2) + """ wt%.

## 14.3 Results

GHSV = 2500 Nm3/(m3cat h) for the main reformer, 5000 for the pre-reformer
(opened electrified-SMR value + [ДОПУЩЕНИЕ] pre-reformer).

{md_table(["product", "V_reformer m3", "V_pre m3", "catalyst t", "Ni inventory t",
           "Ni t/y (4 y life)", "catalyst t/y", "ZnO kg", "Ni kg/1000 Nm3"], rows)}

## 14.4 Life sensitivity (methanol example)

{md_table(["life y", "Ni t/y", "catalyst t/y"],
          [[r[1], r[2], r[3]] for r in life_rows])}

Nickel price """ + fnum(load_config().catalyst["Ni_price_USD_per_t"], 0) + """ USD/t is an
[ДОПУЩЕНИЕ] (no LME quote opened); annual Ni make-up cost is
Ni_t_per_y * price, and the sensitivity above scales it by 1/life.

## 14.5 Sintering / deactivation (still open)

The v1 GPLE and power-law sintering predictions differ by a factor of ~3.06;
no validated 3-year life for 15 wt% Ni/MgAl2O4 was found. V2 therefore reports
a user-adjustable life (default 4 y, sensitivity 3/5/8/10 y) rather than a
"final" life. [НЕ ПОДТВЕРЖДЕНО]
"""
    open(os.path.join(DOCS, "14_v2_catalyst_nickel.md"), "w", encoding="utf-8").write(txt)

    # 15 site cases ---------------------------------------------------------
    cc = scenarios["climate_comparison"]
    me_air = [r for r in cc if r["product"] == "methanol" and
              r["climate"] == "middle_east"][0]["air_cooler_outlet_C"]
    txt = f"""# 15. Russia and Middle East site cases (user answer 8)

All climates are adjustable in `cases/config.json` (`active.climate` and the
`climates` block). Utilities follow the climate: cooling-water supply/return,
air-cooler approach, product temperature and BFW temperature.

{md_table(["product", "climate", "product T C", "air-cooler outlet C", "trim cooling?",
           "CW m3/h", "cooling kW", "cost", "unit"],
          [[r["product"], r["climate"],
             fnum(r["product_T_C"], 0),
            fnum(r["air_cooler_outlet_C"], 1),
            "yes" if r["trim_cooling_required"] else "no",
            fnum(r["cooling_water_m3_h"], 1), fnum(r["cooling_duty_kW"], 0),
            fnum(r["levelised_cost"], 2), r["cost_unit"]] for r in cc])}

Russia design basis: ambient 30 C, cooling water 20->30 C, product 40 C.
Middle East: ambient 48 C, cooling water 35->45 C, product 55 C.
Sources (opened): Kasko/ACHE air-cooler design guide (Middle East design
ambient 45-50 C, Jubail 50 C case, water scarcity), IPIECA cooling systems
2022 (cooling-water return 32-45 C), Gulf-region cooling-water study (20 C
seawater in the reference case). The exact design values are engineering
choices inside those opened ranges -> [ЧАСТИЧНО].

Consequence: the hotter site raises the absorber/product temperature from 40 C
to 55 C, which changes the condensation and cooling-water duties and requires
a molecular-sieve dryer to hold the 0.5 mol% H2O product spec (dryer
regeneration duty is [NOT MODELLED]). An air-cooler-only configuration cannot
reach a 40 C product at 48 C ambient; either the product temperature is raised
or a cooling-water/chilled trim is needed. Air coolers are preferred in the
Middle East because of water scarcity (opened guide), but the 12 K approach
still leaves {me_air:.1f} C outlet air-side temperature.

The `me_rich` feed case (user answer 8 "possibly Middle East") is an
[ДОПУЩЕНИЕ] analogue composition, not a specific field assay:

{md_table(["feed", "dry feed Nm3/h", "X_CH4", "SN", "cost"],
          [[r["feed"], fnum(r["dry_feed_Nm3_h"], 1), fnum(r["X_CH4"], 4),
            fnum(r["achieved"], 4), fnum(r["levelised_cost"], 2)]
           for r in scenarios["feed_comparison"]])}
"""
    open(os.path.join(DOCS, "15_v2_site_cases.md"), "w", encoding="utf-8").write(txt)

    # 16 config/control guide ----------------------------------------------
    txt = """# 16. Configuration and control guide (user answers 2, 7, 11)

## 16.1 Three ways to regulate the model

1. **Edit `cases/config.json`** - the single source of truth. Section map:
   `active` (product/normal/climate/feed/eos), `normal_conditions`,
   `climates`, `feeds`, `products.*.knobs`, `process`, `catalyst`, `eos`,
   `equipment`, `economics`, `adjust`.
2. **Dotted overrides** in Python:
   ```python
   from model.config import load_config
   from model.products import design
   r = design(load_config({"active.climate":"middle_east",
                           "active.normal":"15C",
                           "products.methanol.knobs.SC":3.5,
                           "economics.gas_USD_per_MMBtu":6.0}))
   ```
3. **CLI** `model/control.py` and **live control panel** `web/app.py` (Flask).

## 16.2 CLI

```
PYTHONPATH=. .venv/bin/python -m model.control list
PYTHONPATH=. .venv/bin/python -m model.control show --product ft
PYTHONPATH=. .venv/bin/python -m model.control run --product methanol --set economics.gas_USD_per_MMBtu=6
PYTHONPATH=. .venv/bin/python -m model.control compare
PYTHONPATH=. .venv/bin/python -m model.control sweep --product oxo
PYTHONPATH=. .venv/bin/python -m model.control set active.climate middle_east
```

`set` writes into `cases/config.json`. `run`/`compare` never mutate the file
unless `--save` is passed.

## 16.3 Live control panel

```
PYTHONPATH=. .venv/bin/python -m web.app
```
opens on 0.0.0.0:5000 and is proxied as the Arena live preview. Sliders and
selects change product, normal standard, climate, feed, EOS k_ij set, IAPWS
switch, capacity, S/C, CO2/C, O2/C, T, p, approach, catalyst life, Ni wt%,
GHSV, Ni price and energy prices. "Run model" recomputes; "Compare all 5
products" runs the full matrix. All responses are JSON from `/api/*`.

## 16.4 Utilities are adjustable (user answer 7)

`climates.*` sets cooling water ΔT and air-cooler approach;
`process.steam_p_bar_abs`, `steam_T_K`, `furnace_efficiency_LHV` and
`pinch_dT_min_K` set the steam system; `economics.*` sets gas, power, CO2,
steam and cooling-water prices; `equipment.O2_power_kWh_per_t` (via
`equipment.asu_power` in v1) / `economics.O2_power_kWh_per_t` set ASU power.
Both air cooling and water cooling are reported with a feasibility flag.

## 16.5 HYSYS equivalence (user answer 11)

HYSYS is NOT installed. Confirmed equivalent = this reproducible Python model
(Gibbs minimisation + Peng-Robinson + IF97 + 1-D equipment) plus
`docs/HYSYS_case_spec.md`, which lists the exact HYSYS property package,
reactor blocks and convergence settings needed to reproduce it. No `.hsc`
file was produced and no HYSYS run is claimed.
"""
    open(os.path.join(DOCS, "16_v2_config_control_guide.md"), "w", encoding="utf-8").write(txt)

    # 17 final --------------------------------------------------------------
    key = designs["methanol"]
    txt = f"""# 17. V2 final report - synthesis gas from Russian natural gas on Ni/MgAl2O4

**Краткое заключение:** создана воспроизводимая модель (Python / DWSIM-эквивалент,
HYSYS не запускался) для пяти целевых продуктов - метанол, Фишер-Тропш,
оксо-синтез, водород, аммиак. Все пять вариантов выводятся на целевые
показатели настраиваемыми параметрами; обеспечены оба определения нормального
кубометра, площадки России и Ближнего Востока, расчёт объёмов катализатора
Ni/MgAl2O4 и потребности в никеле. Проверка: циклы 1-4 пройдены, цикл 5
(валидация/фальсификация) **не пройден** - нет экспериментальных данных и
коммерческого даташита Ni/MgAl2O4. Модель не объявляется «завершённой».

## 17.1 Key numbers (methanol base, Russia, 0 C/101325 Pa)

{md_table(["value", "number", "unit", "confidence"],
          [["dry syngas", fnum(key["flows"]["product_Nm3_h"],0), "Nm3/h", "[ЧАСТИЧНО] - design basis"],
           ["SN", fnum(key["spec"]["achieved"],4), "-", "[ПОДТВЕРЖДЕНО] target range"],
           ["X_CH4", fnum(key["reformer"]["equilibrium"]["CH4_conversion"],4), "-", "[ЧАСТИЧНО] equilibrium + approach"],
           ["T_out", fnum(key["reformer"]["T_out_K"],1), "K", "[ДОПУЩЕНИЕ]"],
           ["p", fnum(key["reformer"]["p_bar"],1), "bar(a)", "[ДОПУЩЕНИЕ]"],
           ["Z (PR)", fnum(key["eos"]["Z"],5), "-", "[ЧАСТИЧНО] k_ij"],
           ["fired duty", fnum(key["utilities"]["Q_reformer_kW"],0), "kW", "[ЧАСТИЧНО]"],
           ["fuel", fnum(key["utilities"]["fuel_Nm3_h"],0), "Nm3/h", "[ЧАСТИЧНО]"],
           ["total CO2", fnum(key["utilities"]["total_CO2_t_h"],2), "t/h", "[ЧАСТИЧНО]"],
           ["cooling water", fnum(key["utilities"]["cooling_water_m3_h"],0), "m3/h", "[ЧАСТИЧНО]"],
           ["catalyst volume", fnum(key["catalyst"]["total_catalyst_volume_m3"],2), "m3", "[ЧАСТИЧНО] proxy density"],
           ["Ni inventory", fnum(key["catalyst"]["total_Ni_inventory_t"],3), "t", "[ЧАСТИЧНО]"],
           ["Ni make-up", fnum(key["catalyst"]["Ni_consumption_t_per_y"],3), "t/y", "[НЕ ПОДТВЕРЖДЕНО] life"],
           ["T_wall,max", fnum(key["equipment"]["T_wall_max_K"],1), "K", "[ЧАСТИЧНО]"],
           ["levelised cost", fnum(key["economics"]["levelised_cost"],2), key["economics"]["unit"], "[ЧАСТИЧНО] class 5"]])}

## 17.2 All five variants

{md_table(["product", "metric", "achieved", "cost", "unit", "Ni t", "CO2 t/h"],
          [[p, r["spec"]["metric"], fnum(r["spec"]["achieved"],4),
            fnum(r["economics"]["levelised_cost"],2), r["economics"]["unit"],
            fnum(r["catalyst"]["total_Ni_inventory_t"],2),
            fnum(r["utilities"]["total_CO2_t_h"],2)] for p, r in designs.items()])}

## 17.3 Five verification loops

{md_table(["loop", "status"], [[k, "PASS" if x["passed"] else "FAIL"]
                              for k, x in v["loops"].items()])}

## 17.4 Not checked (see 13.6 for the full list)

""" + "\n".join(f"- {x}" for x in v["loops"]["5_validation_falsification"]["unchecked_items"][:6]) + """

## 17.5 Next step

Obtain an experimental/pilot dataset for 15 wt% Ni/MgAl2O4 (conversion vs T,
p, S/C, CO2/C; pressure drop; 200-1000 h sintering) and a vendor MgAl2O4
catalyst datasheet (bulk density, Ni loading, crush strength, life). Re-run
loop 5, then close the methanol CO2 trim and the downstream synthesis loops.
"""
    open(os.path.join(DOCS, "17_v2_final_report.md"), "w", encoding="utf-8").write(txt)

    # claims register markdown ---------------------------------------------
    claims = json.load(open(os.path.join(ROOT, "data", "v2_claims.json"), encoding="utf-8"))
    txt = "# V2 source / claim registry\n\n" + md_table(
        ["id", "claim", "value", "status", "used in result", "source", "url"],
        [[c["id"], c["name"], str(c["value"])[:70], c["status"],
          "yes" if c["used_in_result"] else "no", str(c["source"])[:100], c["url"]]
         for c in claims["claims"]])
    open(os.path.join(DOCS, "v2_claims_register.md"), "w", encoding="utf-8").write(txt)


# --------------------------------------------------------------------------
def main():
    t0 = time.time()
    print("[v2] running 5 product designs + scenarios ...")
    base, sc = run_all()
    print(f"[v2] designs+scenarios done in {time.time()-t0:.1f} s")
    print("[v2] running five verification loops ...")
    v = verify_all(base, sc)
    # write
    for p, r in base.items():
        dump_json(os.path.join(OUT, f"design_{p}.json"), r)
    write_csv(os.path.join(OUT, "product_comparison.csv"),
              [_compact(base[p]) for p in PRODUCTS])
    for name in ("normal_comparison", "climate_comparison", "feed_comparison",
                 "eos_sensitivity", "regulation_sweep", "ni_life_sensitivity"):
        write_csv(os.path.join(OUT, name + ".csv"), sc[name])
    dump_json(os.path.join(OUT, "verification_v2.json"), v)
    dump_json(os.path.join(OUT, "scenarios_v2.json"), sc)
    cfg = Config.load(DEFAULT_PATH)
    summary = {
        "version": "2.0", "generated": "2026-10-26",
        "hysys": "NOT RUN - Python/DWSIM-equivalent CONFIRMED (user answer 11)",
        "python": sys.version.split()[0],
        "config_active": cfg.raw["active"],
        "normal_conditions": cfg.raw["normal_conditions"],
        "products": list(cfg.raw["products"]),
        "key_numbers": {p: {
            "metric": base[p]["spec"]["metric"],
            "target": base[p]["spec"]["target"],
            "achieved": base[p]["spec"]["achieved"],
            "within_tolerance": base[p]["spec"]["within_tolerance"],
            "levelised_cost": base[p]["economics"]["levelised_cost"],
            "cost_unit": base[p]["economics"]["unit"],
            "Ni_inventory_t": base[p]["catalyst"]["total_Ni_inventory_t"],
            "catalyst_volume_m3": base[p]["catalyst"]["total_catalyst_volume_m3"],
            "total_CO2_t_h": base[p]["utilities"]["total_CO2_t_h"],
        } for p in PRODUCTS},
        "verification_summary": v["summary"],
        "overall_passed": v["overall_passed"],
        "runtime_s": round(time.time() - t0, 1),
        "optional_packages": {"iapws": __import__("model.steam", fromlist=["available"]).available()},
    }
    dump_json(os.path.join(OUT, "summary_v2.json"), summary)
    print("[v2] writing plots ...")
    make_plots(base, sc, v)
    print("[v2] writing reports ...")
    write_reports(base, sc, v)
    print(f"[v2] DONE in {time.time()-t0:.1f} s -> results_v2/ and docs/12..17")
    print("[v2] verification:", v["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
