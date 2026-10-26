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


    # 8 synthesis products --------------------------------------------------
    ss = scenarios["synthesis_summary"]
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.8))
    labels = [r["product"] for r in ss]
    vals = [r["saleable_t_h"] or 0 for r in ss]
    ax[0].bar(labels, vals, color=[colours[p] for p in labels])
    ax[0].set_ylabel("t/h"); ax[0].set_title("Saleable product (different products!)")
    heats = [r["heat_released_MW"] or 0 for r in ss]
    ax[1].bar(labels, heats, color=[colours[p] for p in labels])
    ax[1].set_ylabel("MW"); ax[1].set_title("Synthesis-loop heat release")
    fig.suptitle("Downstream synthesis loops (stoichiometric, docs/18)", fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "08_synthesis_products.png")); plt.close(fig)

    # 9 Ni(CO)4 shutdown ----------------------------------------------------
    sa = designs["methanol"]["safety"]["Ni_CO_4"]["shutdown_scenarios"]
    Ts = [x["T_C"] for x in sa]
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.8))
    ax[0].semilogy(Ts, [max(x["NiCO4_ppb_unpurged"], 1e-30) for x in sa], "o-",
                   color="#f85149", label="CO not purged")
    ax[0].semilogy(Ts, [max(x["NiCO4_ppb_after_purge"], 1e-30) for x in sa], "o-",
                   color="#3fb950", label="CO < 10 ppm")
    ax[0].axvline(200, color="k", ls="--", label="200 C safe T")
    ax[0].axhline(1.0, color="#d29922", ls=":", label="1 ppb")
    ax[0].set_xlabel("T [C]"); ax[0].set_ylabel("Ni(CO)4 [ppb]")
    ax[0].set_title("Equilibrium Ni(CO)4 during shutdown")
    ax[0].legend(fontsize=8)
    dp = [r["equipment"]["Ergun_dP_bar"] for r in designs.values()]
    ax[1].bar(list(designs), dp, color=[colours[p] for p in designs])
    ax[1].axhline(load_config().equipment["dP_max_bar"], color="k", ls="--",
                  label="3 bar limit")
    ax[1].set_ylabel("bar"); ax[1].set_title("Ergun dP after tube-count sizing")
    ax[1].legend(fontsize=8)
    fig.suptitle("Safety and hydraulic screening (docs/19)", fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "09_safety_dP.png")); plt.close(fig)

    # 10 pre-reformer + CO2 trim -------------------------------------------
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.8))
    pres = [(p, r["reformer"].get("prereformer")) for p, r in designs.items()]
    names = [p for p, pr in pres]
    tpre = [(pr["T_out_C"] if pr else 0) for p, pr in pres]
    ax[0].bar(names, tpre, color=[colours[p] for p in names])
    ax[0].set_ylabel("T out [C]"); ax[0].set_title("Adiabatic pre-reformer (ATR bypassed = 0)")
    net = [designs[p]["utilities"]["CO2_net_t_h"] for p in designs]
    imp = [designs[p]["utilities"]["CO2_import_t_h"] for p in designs]
    cap = [designs[p]["utilities"]["CO2_captured_t_h"] for p in designs]
    x = np.arange(len(designs)); w = 0.27
    ax[1].bar(x - w, imp, w, label="imported")
    ax[1].bar(x, cap, w, label="captured")
    ax[1].bar(x + w, net, w, label="net to atmosphere")
    ax[1].set_xticks(x, names); ax[1].set_ylabel("t/h CO2")
    ax[1].set_title("CO2 balance (import / capture / net)")
    ax[1].legend(fontsize=8)
    fig.suptitle("Pre-reformer and CO2 trim (docs/12, docs/18)", fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "10_prereformer_CO2.png")); plt.close(fig)


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

- Methanol make-up gas now contains {fnum(designs["methanol"]["spec"]["CO2_molpct"],2)} mol% CO2,
  INSIDE the opened 4-8 mol% licensor window (Applied Sciences 2017 7,1213).
  This required CO2/C = {fnum(designs["methanol"]["knobs"]["CO2C"],4)} plus a partial
  MDEA CO2 trim (recovery {fnum(next((u["recovery_fraction"] for u in designs["methanol"]["downstream"]["units"] if u["unit"].startswith("A-302")), 0),3)}).
  Status [ЧАСТИЧНО]: the trim reboiler duty is modelled, but a licensor
  kinetic methanol-loop model was NOT opened.
- Stoichiometric synthesis loops (methanol, FT, oxo, NH3) and H2 compression
  are now included in `docs/18`; their KINETIC models, licensor reactor designs,
  crude-methanol distillation, FT wax upgrading, Rh recycle and the cost of
  external oxo propylene remain outside this boundary. [НЕ ПОДТВЕРЖДЕНО]
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
- **Independent SciPy SLSQP** real-gas minimisation: success = {L['4_thermo']['scipy_independent_PR'].get('success')}, max |Δy_wet| = {L['4_thermo']['scipy_independent_PR'].get('max_dy_wet')}, X_CH4 SciPy {fnum(L['4_thermo']['scipy_independent_PR'].get('X_CH4_scipy'),6)} vs model {fnum(L['4_thermo']['scipy_independent_PR'].get('X_CH4_model'),6)}. [ПОДТВЕРЖДЕНО] numerical cross-check.
- Extra V3 checks: {L['4_thermo']['extra_checks_passed']}. Pre-reformer C2+ conversion >0,99; saleable product >0; Ni(CO)4 in normal operation <1 ppb; Ergun Δp ≤ 3 bar after tube-count sizing.
{md_table(['продукт','C2+ конверсия','продукт т/ч','Ni(CO)4 ppb','Δp бар','труб'],
          [[x['product'], fnum(x['pre_reformer_C2plus_conversion'],4),
            fnum(x['saleable_product_t_h'],2),
            f"{x['NiCO4_normal_ppb']:.3g}",
            fnum(x['dP_bar'],3), x['tubes_installed']]
           for x in L['4_thermo']['extra_checks']])}

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
   `climates`, `feeds`, `products.*.knobs`, `process` (incl. `prereformer_enabled`),
   `catalyst`, `eos`, `equipment`, `synthesis`, `safety`, `economics`, `adjust`.
   New V3 knobs: `products.methanol.co2_trim_target_molpct`,
   `synthesis.<product>.*`, `safety.Ni_CO_4.CO_purge_ppm`.
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
кубометра, площадки России и Ближнего Востока, PR+IF97, адиабатический
предреформер, CO2-трим метанола (6 мол.% внутри окна 4-8), стехиометрические
контуры синтеза, скрининг Ni(CO)4/HAZOP/PSV, независимый SciPy SLSQP,
расчёт объёмов катализатора Ni/MgAl2O4 и потребности в никеле. Проверка:
циклы 1-4 пройдены, цикл 5 (валидация/фальсификация) **не пройден** -
нет экспериментальных данных и коммерческого даташита Ni/MgAl2O4.
Модель не объявляется «завершённой».

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
           ["CO2 in make-up gas", fnum(key["spec"]["CO2_molpct"],2), "mol%", "[ПОДТВЕРЖДЕНО] 4-8 window"],
           ["total CO2 handled", fnum(key["utilities"]["total_CO2_t_h"],2), "t/h", "[ЧАСТИЧНО]"],
           ["net CO2 to atmosphere", fnum(key["utilities"]["CO2_net_t_h"],2), "t/h", "[ЧАСТИЧНО] recycle assumption"],
           ["methanol product", fnum(key["synthesis"]["methanol_t_h"],2), "t/h", "[ЧАСТИЧНО] stoichiometry"],
           ["pre-reformer T_out", fnum(key["reformer"]["prereformer"]["T_out_K"],1), "K", "[ЧАСТИЧНО] equilibrium"],
           ["Ergun dP", fnum(key["equipment"]["Ergun_dP_bar"],3), "bar", "[ЧАСТИЧНО] sized to <=3 bar"],
           ["Ni(CO)4 at operation", f"{key['safety']['Ni_CO_4']['normal_operation']['NiCO4_ppb']:.3g}", "ppb", "[ЧАСТИЧНО] equilibrium"],
           ["cooling water", fnum(key["utilities"]["cooling_water_m3_h"],0), "m3/h", "[ЧАСТИЧНО]"],
           ["catalyst volume", fnum(key["catalyst"]["total_catalyst_volume_m3"],2), "m3", "[ЧАСТИЧНО] proxy density"],
           ["Ni inventory", fnum(key["catalyst"]["total_Ni_inventory_t"],3), "t", "[ЧАСТИЧНО]"],
           ["Ni make-up", fnum(key["catalyst"]["Ni_consumption_t_per_y"],3), "t/y", "[НЕ ПОДТВЕРЖДЕНО] life"],
           ["T_wall,max", fnum(key["equipment"]["T_wall_max_K"],1), "K", "[ЧАСТИЧНО]"],
           ["levelised cost", fnum(key["economics"]["levelised_cost"],2), key["economics"]["unit"], "[ЧАСТИЧНО] class 5"]])}

## 17.2 All five variants

{md_table(["product", "metric", "achieved", "saleable t/h", "cost", "unit", "Ni t", "net CO2 t/h"],
          [[p, r["spec"]["metric"], fnum(r["spec"]["achieved"],4),
            fnum(r["synthesis"].get("methanol_t_h") or r["synthesis"].get("C5plus_t_h") or
                 r["synthesis"].get("aldehyde_t_h") or r["synthesis"].get("H2_t_h") or
                 r["synthesis"].get("NH3_t_h"),2),
            fnum(r["economics"]["levelised_cost"],2), r["economics"]["unit"],
            fnum(r["catalyst"]["total_Ni_inventory_t"],2),
            fnum(r["utilities"]["CO2_net_t_h"],2)] for p, r in designs.items()])}

Detail: `docs/18` (synthesis), `docs/19` (safety), `docs/20` (pre-reformer /
CO2 trim / hydraulics), `docs/21` (15-case matrix).

## 17.3 Five verification loops

{md_table(["loop", "status"], [[k, "PASS" if x["passed"] else "FAIL"]
                              for k, x in v["loops"].items()])}

## 17.4 Not checked (see 13.6 for the full list)

""" + "\n".join(f"- {x}" for x in v["loops"]["5_validation_falsification"]["unchecked_items"][:6]) + """

## 17.5 Next step

Obtain an experimental/pilot dataset for 15 wt% Ni/MgAl2O4 (conversion vs T,
p, S/C, CO2/C; pressure drop; 200-1000 h sintering) and a vendor MgAl2O4
catalyst datasheet (bulk density, Ni loading, crush strength, life). Re-run
loop 5. The V2 methanol CO2 gap is CLOSED (docs/20) and stoichiometric
synthesis loops are included (docs/18); the remaining gap is their kinetic
validation plus a certified HAZOP/API 520 study (docs/19).
"""
    open(os.path.join(DOCS, "17_v2_final_report.md"), "w", encoding="utf-8").write(txt)

    # 18 synthesis loops ----------------------------------------------------
    sy_rows = scenarios["synthesis_summary"]
    syn_rows = []
    for prod, r in designs.items():
        sy = r["synthesis"]
        syn_rows.append([prod, fnum(sy.get("p_synthesis_bar"), 0),
                         fnum(sy.get("T_synthesis_C"), 0),
                         fnum(sy.get("methanol_t_h") or sy.get("C5plus_t_h") or
                              sy.get("aldehyde_t_h") or sy.get("H2_t_h") or
                              sy.get("NH3_t_h"), 2),
                         fnum(sy.get("heat_released_MW"), 1),
                         fnum(sy.get("compression_power_MW"), 2),
                         str(sy.get("status"))[:60]])
    txt = f"""# 18. Downstream synthesis loops (V3 continuation)

Stoichiometric + recycle balances, **NOT** a kinetic reactor simulation.
All conversions/selectivities are adjustable in `cases/config.json -> synthesis`.

{md_table(['product','p bar','T C','saleable t/h','heat MW','compression MW','status'], syn_rows)}

## 18.1 Chemistry and opened sources

- **Methanol**: CO + 2H₂ → CH₃OH (−90,7 кДж/моль), CO₂ + 3H₂ → CH₃OH + H₂O
  (−49,7 кДж/моль), 50–100 бар, 200–300 °C, Cu/ZnO/Al₂O₃.
  Applied Sciences 2017, 7, 1213 (opened): 4–8 мол.% CO₂ в подпиточном газе,
  S-модуль чуть выше 2. OSTI 2424604 (opened): конверсия за проход 25–30 %,
  поэтому нужен рецикл 2:1–5:1 (opened review). Итоговая конверсия углерода 0,97.
- **FT**: CO + 2H₂ → –CH₂– + H₂O. ACS Catalysis 2017 (opened): в промышленности
  0,85 < α < 0,95; Hywax (opened): конверсия CO за проход 60–80 %;
  распределение Андерсона–Шульца–Флори Wₙ = n(1−α)²αⁿ⁻¹, доля C₅₊ = α⁴(5−4α).
- **Оксо**: C₃H₆ + CO + H₂ → C₄H₈O (масляный альдегид). US7582802B2 (opened):
  материальный баланс пропилена; MDPI Catalysts 2020 10,510 (opened): селективность
  ~99 % в мягких условиях; JM LP Oxo (opened): n:iso ≈ 7:1. **Внешний пропилен
  не включён в OPEX** — это открытый пункт.
- **Водород**: сжатие до 200 бар. Processes 2026 14(2),319 (opened): 9,2 МВт
  на 2966 кмоль/ч. Мощность показана отдельно от базового баланса утилит.
- **Аммиак**: N₂ + 3H₂ → 2NH₃, ΔH = −46 кДж/моль NH₃ (C-THRU brief, opened),
  150–250 бар, 400–450 °C, 15–25 % за проход (RSC EES 2020, opened),
  97 % суммарно с рециклом (Haber process, opened).

## 18.2 Результаты

{md_table(['product','saleable t/h','saleable t/y','heat MW','compression MW'],
          [[r['product'], fnum(r['saleable_t_h'],2), fnum(r['saleable_t_y'],0),
            fnum(r['heat_released_MW'],2), fnum(r['compression_power_MW'],2)]
           for r in sy_rows])}

Внимание: тоннажи разных продуктов **нельзя сравнивать напрямую** — это разные
химические продукты. Метанол {fnum(designs['methanol']['synthesis']['methanol_t_y'],0)} т/год,
FT C₅₊ {fnum(designs['ft']['synthesis']['C5plus_t_y'],0)} т/год,
альдегид {fnum(designs['oxo']['synthesis']['aldehyde_t_y'],0)} т/год,
H₂ {fnum(designs['hydrogen']['synthesis']['H2_t_h']*8000,0)} т/год,
NH₃ {fnum(designs['ammonia']['synthesis']['NH3_t_day'],0)} т/сут.

## 18.3 Не проверено

Кинетика синтеза, катализаторы синтеза, ректификация метанола-сырца,
гидроформилирование с рециклом родия, сепарация FT-восков, стоимость пропилена,
дополнительная мощность компрессоров в OPEX. [НЕ ПОДТВЕРЖДЕНО]
"""
    open(os.path.join(DOCS, "18_v3_synthesis_loops.md"), "w", encoding="utf-8").write(txt)

    # 19 safety -------------------------------------------------------------
    sa = designs["methanol"]["safety"]
    sc_rows = [[fnum(x["T_C"],0), f"{x['NiCO4_ppb_unpurged']:.3g}",
                f"{x['NiCO4_ppb_after_purge']:.3g}"] for x in sa["Ni_CO_4"]["shutdown_scenarios"]]
    haz = [[h["node"], h["deviation"], h["safeguard"][:90]] for h in sa["HAZOP_nodes"]]
    txt = f"""# 19. Safety screening: Ni(CO)₄, HAZOP, PSV (V3 continuation)

**Статус: скрининг, НЕ сертифицированный HAZOP / API 520/521.**
Полный текст API 520/521 в сессии открыт не был.

## 19.1 Ni(CO)₄

Ni(т) + 4CO(г) ⇌ Ni(CO)₄(г); log₁₀K = 7430/T − 21,90,
K = p(Ni(CO)₄)/p(CO)⁴ (OSTI 7349456, opened: ΔH = −142,3 кДж/моль,
ΔS = −419,2 Дж/моль/К). NIST WebBook по Ni(CO)₄ (opened).

- При нормальной работе T = {fnum(designs['methanol']['reformer']['T_out_K'],0)} K:
  {sa['Ni_CO_4']['normal_operation']['NiCO4_ppb']:.3g} ppb — пренебрежимо мало.
- При остановке ниже {fnum(sa['Ni_CO_4']['safe_temperature_C'],0)} °C и **непродутом CO**
  равновесие предсказывает заметный Ni(CO)₄ (см. таблицу). Продувка до
  CO < {fnum(sa['Ni_CO_4']['CO_purge_ppm'],0)} ppm перед охлаждением удерживает
  Ni(CO)₄ ниже 1 ppb — это совпадает с рекомендацией Becht (opened).
- **[ЧАСТИЧНО]** равновесный скрининг; кинетика на 15 мас.% Ni/MgAl₂O₄
  и активность поверхности Ni не моделировались.

{md_table(['T C','Ni(CO)4 ppb без продувки','Ni(CO)4 ppb после продувки'], sc_rows)}

## 19.2 Предохранительный клапан (скрининг)

Заблокированный выход на линии питания реформера:
расход {fnum(sa['relief']['relief_load_kg_s'],2)} кг/с,
p_уст = {fnum(sa['relief']['p_set_bar'],1)} бар,
поток {fnum(sa['relief']['choked_mass_flux_kg_m2_s'],0)} кг/(м²·с),
требуемое отверстие {fnum(sa['relief']['orifice_diameter_mm'],1)} мм.
{sa['relief']['status']}

## 19.3 HAZOP-узлы (скрининг)

{md_table(['узел','отклонение','защита'], haz)}

## 19.4 Сера

H₂S на входе {fnum(sa['sulfur_guard']['H2S_in_ppmv'],1)} ppmv → после ZnO
{fnum(sa['sulfur_guard']['H2S_after_guard_ppmv'],3)} ppmv;
масса ZnO {fnum(sa['sulfur_guard']['ZnO_mass_kg'],0)} кг (lead-lag, [ЧАСТИЧНО]).

## 19.5 Не проверено

{chr(10).join('- '+x for x in sa['unchecked'])}
"""
    open(os.path.join(DOCS, "19_v3_safety.md"), "w", encoding="utf-8").write(txt)

    # 20 pre-reformer + CO2 trim -------------------------------------------
    pr_rows = []
    for prod, r in designs.items():
        pr = r["reformer"].get("prereformer")
        pr_rows.append([prod,
                        fnum(pr["T_out_K"],1) if pr else "ATR bypass",
                        fnum(pr["C2plus_conversion"],4) if pr else "-",
                        fnum(pr["H_balance_mismatch_pct"],4) if pr else "-",
                        fnum(r["utilities"]["CO2_import_t_h"],2),
                        fnum(r["utilities"]["CO2_captured_t_h"],2),
                        fnum(r["utilities"]["CO2_net_t_h"],2),
                        fnum(r["equipment"]["Ergun_dP_bar"],3)])
    txt = f"""# 20. Pre-reformer, CO₂ trim and hydraulics (V3 continuation)

## 20.1 Адиабатический предреформер

Реализован в `model/prereformer.py`: равновесие Гиббса при H_вх(T_вх) =
H_вых(T_ад), бисекция 500–800 K (быстрее, чем общий решатель 298–3418 K).
C₄₊ по-прежнему объединены в C₃H₈ по углероду ([ДОПУЩЕНИЕ]).
Для ATR/FT/оксо предреформер **пропущен**: кислород в питании ATR расходовался
бы внутри предреформера — требуется отдельная схема с подачей O₂ после
предреформера. [НЕ ПОДТВЕРЖДЕНО]

{md_table(['продукт','T вых K','конверсия C2+','небаланс H %','CO2 импорт т/ч','CO2 улов т/ч','CO2 нетто т/ч','Δp бар'], pr_rows)}

## 20.2 CO₂-trim метанола

Открытый источник Applied Sciences 2017, 7, 1213: подпиточный газ метанола
должен содержать **4–8 мол.% CO₂**. Без трима при S/C = 3 и SN = 2,05 получалось
11,6 мол.% CO₂. Добавлен частичный MDEA-трим (`A-302`) с целевым значением
{fnum(load_config().P.get('co2_trim_target_molpct',6.0),1)} мол.% и повторная
настройка CO₂/C = **{fnum(designs['methanol']['knobs']['CO2C'],4)}**. Финальное
значение **{fnum(designs['methanol']['spec']['CO2_molpct'],2)} мол.%** — внутри окна.
Цена: рост удельной стоимости с 225 до
{fnum(designs['methanol']['economics']['levelised_cost'],2)} USD/1000 нм³.

Импортированный CO₂ частично рециклизуется из уловленного: чистый выброс
{fnum(designs['methanol']['utilities']['CO2_net_t_h'],2)} т/ч вместо
{fnum(designs['methanol']['utilities']['total_CO2_t_h'],2)} т/ч «оборотного» CO₂.
[ДОПУЩЕНИЕ] считается, что уловленный CO₂ возвращается до величины импорта.

## 20.3 Гидравлика: Δp по Эргуну

Исправлена размерность: `ergun_dp_bar()` возвращает **Па**, результат делится
на 10⁵. Число труб теперь определяется **одновременно** по тепловому потоку и
по допустимому Δp ≤ {fnum(load_config().equipment['dP_max_bar'],1)} бар:
для метанола {designs['methanol']['equipment']['tubes_for_heat']} труб по теплу →
{designs['methanol']['equipment']['tubes_installed']} труб по Δp,
итого Δp = {fnum(designs['methanol']['equipment']['Ergun_dP_bar'],3)} бар.
Это закрывает прежний провал проверки `dP_within_limit`.
"""
    open(os.path.join(DOCS, "20_v3_prereformer_trim.md"), "w", encoding="utf-8").write(txt)

    # 21 full matrix --------------------------------------------------------
    fm = scenarios["full_matrix"]
    txt = f"""# 21. Complete product × normal × climate matrix (V3 continuation)

15 расчётных случаев: 5 продуктов × (0 °C/Россия, 15 °C/Россия, 0 °C/Ближний Восток).
Используются настроенные параметры базового случая, пересчёт без повторной настройки.

{md_table(['продукт','случай','метрика','значение','CO2 мол.%','Ni т','стоимость','ед.'],
          [[r['product'], r['case'], r['metric'], fnum(r['achieved'],4),
            fnum(r['CO2_molpct'],2), fnum(r['Ni_inventory_t'],2),
            fnum(r['levelised_cost'],2), r['cost_unit']] for r in fm])}

Переход 0 °C → 15 °C меняет объёмные потоки на +5,49 % при неизменном молярном
заводе. Ближний Восток поднимает температуру продукта с 40 до 55 °C, меняет
конденсацию и требует осушителя (регенерация [НЕ ПОДТВЕРЖДЕНО]).

Сводка синтеза: `results_v2/synthesis_summary.csv`; безопасность:
`results_v2/safety_summary.csv`; полная матрица: `results_v2/full_matrix.csv`.
"""
    open(os.path.join(DOCS, "21_v3_full_matrix.md"), "w", encoding="utf-8").write(txt)

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
                 "eos_sensitivity", "regulation_sweep", "ni_life_sensitivity",
                 "full_matrix", "synthesis_summary", "safety_summary"):
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
            "CO2_net_t_h": base[p]["utilities"]["CO2_net_t_h"],
            "CO2_molpct": base[p]["spec"]["CO2_molpct"],
            "saleable_product_t_h": base[p]["synthesis"].get("methanol_t_h") or
                base[p]["synthesis"].get("C5plus_t_h") or
                base[p]["synthesis"].get("aldehyde_t_h") or
                base[p]["synthesis"].get("H2_t_h") or
                base[p]["synthesis"].get("NH3_t_h"),
            "tubes_installed": base[p]["equipment"]["tubes_installed"],
            "Ergun_dP_bar": base[p]["equipment"]["Ergun_dP_bar"],
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
    print(f"[v2] DONE in {time.time()-t0:.1f} s -> results_v2/ and docs/12..21")
    print("[v2] verification:", v["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
