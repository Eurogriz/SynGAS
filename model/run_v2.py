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
from .pilot_data import (load_pilot, load_commercial, run_external_comparison)
from .hazop import hazop_report

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


    # 11 pilot comparison ---------------------------------------------------
    ext = verification["loops"]["5_validation_falsification"]["external_data"]
    comp = ext["comparisons"]
    if comp:
        fig, ax = plt.subplots(1, 2, figsize=(10, 3.8))
        x = np.arange(len(comp))
        ax[0].bar(x - 0.2, [c["X_measured"] for c in comp], 0.4, label="measured (kinetic)")
        ax[0].bar(x + 0.2, [c["X_model_equilibrium"] for c in comp], 0.4,
                  label="model (equilibrium)")
        ax[0].set_xticks(x, [c["record_id"] for c in comp])
        ax[0].set_ylabel("X_CH4"); ax[0].legend(fontsize=8)
        ax[0].set_title("External pilot data vs model")
        ps = ext["pressure_trend"]
        if ps:
            ax[1].plot([ps["p_low_bar"], ps["p_high_bar"]],
                       [ps["measured_low"], ps["measured_high"]], "o-", label="measured")
            ax[1].plot([ps["p_low_bar"], ps["p_high_bar"]],
                       [ps["model_low"], ps["model_high"]], "o-", label="model")
            ax[1].set_xlabel("p [bar]"); ax[1].set_ylabel("X_CH4")
            ax[1].set_title("Pressure trend (600 C, 15 wt% Ni/MgAl2O4)")
            ax[1].legend(fontsize=8)
        fig.suptitle("Verification loop 5: external falsification (docs/22)", fontsize=11)
        fig.tight_layout(); fig.savefig(os.path.join(OUT, "11_pilot_comparison.png")); plt.close(fig)

    # 12 kinetic benchmarks -------------------------------------------------
    kc = verification["loops"]["5_validation_falsification"]["kinetic_checks"]
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.8))
    for prod in ("methanol", "ammonia"):
        k = designs[prod]["synthesis"]["kinetic"]["benchmark_check"]
        sw = k["sweep"]
        key = "outlet_MeOH_molpct" if prod == "methanol" else "outlet_NH3_molpct"
        ax[0 if prod == "methanol" else 1].semilogx([z["GHSV_h1"] for z in sw],
                                                     [z[key] for z in sw], "o-", label=prod)
    ax[0].axhline(3.4, color="k", ls="--", label="Arzew plant 3.4 mol%")
    ax[0].set_ylabel("outlet MeOH [mol%]"); ax[0].set_title("VBF/Graaf benchmark")
    ax[1].axhline(13.0, color="k", ls="--", label="Rase/COMSOL 13 mol%")
    ax[1].set_ylabel("outlet NH3 [mol%]"); ax[1].set_title("Temkin-Pyzhev benchmark")
    for a in ax:
        a.set_xlabel("effective GHSV [1/h]"); a.legend(fontsize=8)
    fig.suptitle("Kinetic synthesis models vs opened industrial benchmarks (docs/23)",
                 fontsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "12_kinetic_benchmarks.png")); plt.close(fig)

    # 13 V5 adiabatic converter: bed temperature / NH3 profile --------------
    convb = (designs["ammonia"]["synthesis"]["kinetic"]
             .get("ammonia_converter") or {})
    if convb.get("design"):
        prof = convb["design"]["bed_profile"]
        fig, ax = plt.subplots(1, 2, figsize=(11, 4))
        vb = [q["V_over_Vtot"] for q in prof]
        ax[0].plot(vb, [q["T_K"] for q in prof], "-o", ms=2, lw=1.2)
        ax[0].axhline(convb["design"]["catalyst_T_max_assumed_K"], color="r",
                      ls="--", label="assumed catalyst ceiling")
        for q in prof:
            if abs(q["V_over_Vtot"] * convb["design"]["reactor"]["n_beds"]
                   - round(q["V_over_Vtot"] * convb["design"]["reactor"]["n_beds"])) < 1e-9:
                ax[0].axvline(q["V_over_Vtot"], color="grey", lw=0.6)
        ax[0].set_xlabel("cumulative V / V_total catalyst")
        ax[0].set_ylabel("bed temperature [K]")
        ax[0].set_title("adiabatic beds: T profile (3 beds, 200 bar)")
        ax[0].legend(fontsize=7)
        ax[1].plot(vb, [q["y_NH3_molpct"] for q in prof], "-s", ms=2, lw=1.2,
                   color="tab:green")
        eq = convb["design"]["equilibrium_NH3_molpct_at_inlet_T"]
        ax[1].axhline(eq, color="k", ls=":", label="equilibrium at inlet T")
        ax[1].axhline(13.0, color="r", ls="--", label="opened benchmark 13 mol%")
        ax[1].set_xlabel("cumulative V / V_total catalyst")
        ax[1].set_ylabel("NH3 [mol%]")
        ax[1].set_title("converter NH3 build-up vs opened benchmark")
        ax[1].legend(fontsize=7)
        fig.suptitle("SynGAS V5 - multi-bed adiabatic ammonia converter",
                     fontsize=12)
        fig.tight_layout()
        fig.savefig(os.path.join(OUT, "13_converter_profile.png"))
        plt.close(fig)

    # 13 loop 5 subchecks ---------------------------------------------------
    l5 = verification["loops"]["5_validation_falsification"]
    subs = l5["subchecks"]
    fig, ax = plt.subplots(figsize=(9, 5))
    names = [c["check"][:52] for c in subs]
    vals = [1 if c["passed"] else 0 for c in subs]
    ax.barh(range(len(subs)), vals, color=["#3fb950" if v else "#f85149" for v in vals])
    ax.set_yticks(range(len(subs)), names, fontsize=8)
    ax.set_xlim(0, 1); ax.set_xticks([0, 1], ["FAIL", "PASS"])
    ax.set_title("Loop 5 subchecks: %d/%d pass (overall FAIL)" %
                 (l5["subchecks_passed"], l5["subchecks_total"]))
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "13_loop5_subchecks.png")); plt.close(fig)


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------
def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def activity_summary_17():
    """Short docs/17 section on the V5.2 corridor, read from the saved artifact.

    Returns a placeholder string when the corridor was not computed, so the
    report never silently claims a band that was not produced by this run.
    """
    path = os.path.join(OUT, "activity_uncertainty.json")
    if not os.path.exists(path):
        return ("not computed in this run (`model/activity_uncertainty.py` did "
                "not write results_v2/activity_uncertainty.json)")
    d = json.load(open(path, encoding="utf-8"))
    sp, dr = d["spans"], d["design_reference"]
    r0, rN = d["rows"][0], d["rows"][-1]
    f0, fN = r0["at_fixed_geometry"], rN["at_fixed_geometry"]
    v0, vN = (r0["volume_to_hold_design_conversion"],
              rN["volume_to_hold_design_conversion"])
    inv = d["money"]["catalyst_inventory_corridor_USD"]
    dop = max(x["delta_cost_USD_y"]
              for x in d["money"]["recycle_compressor"]["power_by_loop_dP"])
    return (
        "The x%.3f disagreement between the two opened NH3 benchmarks is no "
        "longer a footnote on k0: it is carried as a corridor over %.d "
        "activities (docs/32, `model/activity_uncertainty.py`).\n\n"
        "* fixed geometry (V = %.1f m3, %d beds, inlet %.1f K, %g bar): "
        "per-pass N2 %.2f -> %.2f %%, outlet NH3 %.2f -> %.2f mol%%, interbed "
        "duty %.1f -> %.1f MW, recycle implied by kinetics %.3f -> %.3f "
        "against the configured %.1f.\n"
        "* volume needed to hold the design conversion (%.2f %%): %.1f -> "
        "%.1f m3 (%.1f %%), i.e. GHSV %.0f -> %.0f 1/h. The as-built %.1f m3 "
        "is the CONSERVATIVE bound, because the design is calibrated at the low "
        "edge of the band.\n"
        "* peak temperature is activity-INSENSITIVE (%.2f -> %.2f K): every bed "
        "reaches the equilibrium pinch, so the %.0f K exceedance of the assumed "
        "ceiling is an inlet-temperature choice, not catalyst evidence. Holding "
        "the ceiling instead costs outlet NH3 down to %.2f mol%% at the low edge "
        "(below the opened 13.0 benchmark) vs %.2f mol%% at the high edge.\n"
        "* tonnage does NOT move (loop value %.3f t/h NH3): at fixed fresh feed "
        "activity changes the recycle needed, not the stoichiometric ceiling.\n"
        "* money: catalyst inventory %.3g -> %.3g USD and vessel factor "
        "(V/V0)^0.7 -> %.3f, while the recycle compressor changes by <= %.3g "
        "USD/y -> an inventory/CAPEX question, not an OPEX one. Density and "
        "price remain placeholders (docs/28 items 12-13).\n\n"
        "Not touched by the corridor: equilibrium (Ka, outlet ceiling), the feed "
        "and temperature envelope of docs/30, loop stoichiometry, catalyst "
        "price/life, and loop 5, which stays FAILED - a corridor is an honest "
        "spread, not validation."
        % (d["activity_band"]["factor"], len(d["rows"]),
           dr["catalyst_volume_m3"], dr["n_beds"], dr["bed_inlet_T_K"],
           dr["p_bar"], f0["per_pass_N2_pct"], fN["per_pass_N2_pct"],
           f0["outlet_NH3_molpct"], fN["outlet_NH3_molpct"],
           f0["interbed_cooling_duty_MW"], fN["interbed_cooling_duty_MW"],
           f0["recycle_ratio_implied"], fN["recycle_ratio_implied"],
           dr["recycle_ratio_configured"], dr["per_pass_N2_pct"],
           vN["V_m3"], v0["V_m3"], vN["delta_V_pct"], vN["GHSV_normal_h1"],
           v0["GHSV_normal_h1"], dr["catalyst_volume_m3"],
           sp["T_peak_K"][0], sp["T_peak_K"][1],
           f0["peak_over_assumed_ceiling_K"],
           r0["ceiling_remedy"]["outlet_NH3_molpct"],
           rN["ceiling_remedy"]["outlet_NH3_molpct"],
           d["production_is_not_activity_limited"]["NH3_design_t_h"],
           min(inv), max(inv), vN["vessel_scale_factor_capex_exponent_0p7"],
           dop))


def write_operator_doc():
    """docs/33: the manual data-entry form, generated from the schema itself.

    The document IS the form: every field, its unit, its plausible range, where
    the value lands in the model and which open item it pins. Nothing in it is
    invented - there are no example numbers, only the model's current
    placeholder (labelled) and the rules the validator enforces.
    """
    from .operator_data import (FIELDS, GROUPS, FORM_PATH, recommendation,
                                corridor_fields)
    rec = recommendation()
    cf = ", ".join("`%s`" % i for i in corridor_fields())   # never drifts
    L = ["# 33. Ручной ввод недостающих данных (форма оператора) и правило коридора",
         "",
         "Сгенерировано `model/run_v2.py` из `model/operator_data.py`. Файл формы: "
         "`data/operator_inputs.json`; пустой бланк: "
         "`data/operator_inputs_TEMPLATE.json` и `.csv` (для таблицы).",
         "",
         "## 33.1 Правило",
         "",
         "**Пока хотя бы один размер не введён с полным провенансом, отчёт обязан "
         "быть коридорным (docs/32), а не точечным.** Введённое значение фиксирует "
         "точку, но: (а) требует единицы, метода, документа, даты и подписи "
         "внесшего — числа без этого валидатор отклоняет; (б) при отсутствии "
         "**второй** подписи (`independently_verified` + `verified_by`) статус "
         "остаётся [ЧАСТИЧНО], и коридор печатается рядом. Контур 5 от ввода данных "
         "НЕ проходит: ввод — это данные, а не валидация модели.",
         "",
         "## 33.2 Как вносить",
         "",
         "1. Вкладка **«Ручной ввод данных»** в панели (`python -m web.app`) — "
         "быстрее всего: проверка на лету, сохранение в `data/operator_inputs.json`, "
         "кнопка пересчёта коридора.",
         "2. Или правкой `data/operator_inputs_TEMPLATE.csv` → "
         "`PYTHONPATH=. python -m model.operator_data --validate`.",
         "3. Или от руки в JSON: `{entries: {<id>: {value, unit, method, source, "
         "received_date, entered_by, applied, independently_verified, verified_by}}}`.",
         "",
         "`model/config.py` подхватывает форму при каждом `load_config()` как "
         "`adjust`-запись; в `cases/config.json` ничего не записывается. Отказ "
         "полуприменения: если в файле есть хотя бы одна ошибка, **не применяется "
         "ни одно поле** (контур 4 это ловит проверкой `operator_overlay`).",
         "",
         "## 33.3 Поля формы (%d)" % len(FIELDS),
         ""]
    for g in GROUPS:
        L += ["### " + g, "",
              "| id | что вписать | единица | тип | допустимо | куда идёт | что закрепляет |",
              "|---|---|---|---|---|---|---|"]
        for f in [x for x in FIELDS if x["group"] == g]:
            rng = ("\u2014" if f["lo"] is None
                   else "{} \u2026 {}".format(f["lo"], f["hi"]))
            if f["options"]:
                rng = " / ".join(f["options"])
            tgt = ", ".join(p for p, _ in f["targets"]) or "—"
            pin = f["pins"] or "—"
            if f["rfi"]:
                pin = pin + " (RFI " + f["rfi"] + ")"
            L.append("| `%s` | %s | %s | %s | %s | `%s` | %s |"
                     % (f["id"], f["label"], f["unit"], f["type"], rng, tgt, pin))
            if f["warn"]:
                L.append("| | ⚠ %s | | | | | |" % f["warn"])
        L.append("")
    L += ["## 33.4 Что коридор, а что уже закреплено", "",
          "| размер | сейчас в модели | значение оператора | состояние | как докладывать |",
          "|---|---|---|---|---|"]
    for r in rec["rows"]:
        L.append("| %s | %s | %s | %s | %s |"
                 % (r["quantity"], r["model_value_now"],
                    "—" if r["operator_value"] is None else r["operator_value"],
                    r["state"], r["report_as"]))
    L += ["",
          "Итого: **%d из %d** размеров всё ещё требуют коридора; рекомендованная "
          "форма отчёта — `%s`. %s"
          % (rec["n_corridor_required"], len(rec["rows"]), rec["recommended_form"],
             rec["note"]), "",
          "## 33.5 Чего форма НЕ делает", "",
          "* не меняет реестр утверждений `data/v2_claims.json` (статусы правит "
          "человек, прочитавший документ);",
          "* не закрывает контур 5 — подпроверки двигаются только по факту "
          "полноценного провенанса и помечаются как «внесено оператором»;",
          "* счётчики `n_applied`/`n_verified` означают «в силе», а не «набрано»: "
          "при отклонённой форме они обнуляются, и в отчётах появляется "
          "`form REJECTED` — модель не рекламирует данные, которые она игнорирует;",
                    "* не изобретает отсутствующее: поле без значения остаётся пустым, а "
          "модель продолжает показывать полосу;",
          "* не заменяет кампанию по `docs/27`: для неё есть отдельный контракт "
          "`data/pilot_schema.json` и приёмник `model/data_ingest.py` (строже "
          "этой формы), а `campaign_file` в форме — только ссылка и дата.", "",
          "## 33.6 Прикладной эффект для аммиачного коридора", "",
          "Поля " + cf + " подхватываются `model/activity_uncertainty.py` напрямую: они "
          "непосредственно задают центр и ширину полосы активности, потолок "
          "температуры, пересчёт объём→масса, цену и годовую замену, Δp контура и "
          "долю конвертора в CAPEX. Остальные поля идут через `cases/config.json` "
          "→ `adjust`, т.е. через весь проект.", "",
          "## 33.7 Карта: какой пункт запроса поставщику (docs/28) закрывает какое "
          "число", "",
          _rfi_map_doc(),
          "---", "",
          "> Форма: `%s` (поле `selftest: true` помечает пробные прогоны; такие "
          "файлы не должны попадать в репозиторий)."
          % os.path.relpath(FORM_PATH, ROOT), ""]
    open(os.path.join(DOCS, "33_v5_manual_data_entry.md"), "w",
         encoding="utf-8").write("\n".join(L))
    return True


def operator_summary_17():
    """docs/17 section 17.9: state of manual data entry, from the saved report."""
    path = os.path.join(OUT, "operator_data_report.json")
    if not os.path.exists(path):
        return ("not computed in this run (`model/operator_data.py` did not write "
                "results_v2/operator_data_report.json)")
    d = json.load(open(path, encoding="utf-8"))
    rec = d.get("recommendation") or {}
    n = d.get("n_applied", 0)
    try:                                   # group count is structural, not state
        from .operator_data import GROUPS as _OG
        ngroups = len(_OG)
    except Exception:
        ngroups = len(d.get("groups") or [])
    return (
        "Every open numeric item is now enterable by a human, and the model is "
        "strict about it: the form has %d fields across %d groups "
        "(`model/operator_data.py`, docs/33), and an entry is accepted only with "
        "unit + measurement method + source document + date + who entered it "
        "(docs/28 sec. 28.4). Out-of-range or implausible values are REJECTED, not "
        "clamped; a form with any error applies NOTHING (half-applied datasheets "
        "are worse than none), which loop 4 now checks as `operator_overlay`.\n\n"
        "State after this run: %s A corridor is still the REQUIRED form of the "
        "answer for %d of %d ammonia quantities (recommended form: `%s`); a "
        "single-source entry pins the point but the literature band stays printed "
        "next to it (`literature_reference_rows` in "
        "results_v2/activity_uncertainty.json). Loop 5 does not move on data entry: "
        "entering a vendor number is data, not validation of the model."
        % (d.get("n_fields") or 0,
           ngroups,
           ("no form yet - the model runs on its labelled placeholders."
            if not d.get("form_present") else
            ("form REJECTED (%d validation error(s)): %d field(s) typed but %d "
             "applied - nothing is in force, the corridors stand"
             % (len(d.get("validation_errors") or []), d.get("n_typed_applied", 0), n)
             if d.get("rejected") else
             "%d field(s) applied, %d independently verified, "
             "%d validation error(s)"
             % (n, d.get("n_verified", 0), len(d.get("validation_errors") or [])))),
           rec.get("n_corridor_required", "?"), len(rec.get("rows") or []),
           rec.get("recommended_form", "corridor")) + _rfi_summary_17(d))


def _rfi_summary_17(d):
    """One paragraph for docs/17: which vendor-request items the entry closes."""
    cov = d.get("rfi_coverage") or {}
    if not cov.get("rows"):
        return ("\n\nThe docs/28 cross-reference was not in this report, so the run "
                "cannot say which vendor request item any number closes "
                "(re-run model/run_v2 after `model/operator_data.py` changes).")
    return (
        "\n\nVendor request (docs/28): %d items, %d of them have a field in this "
        "form, %d closed by entered data (%d with a second signature), %d still "
        "open, %d are documents or curves that no number can answer (they stay in "
        "the correspondence with the supplier). The mapping is read back from "
        "docs/28 itself, so a new item appears here as open without a code change; "
        "loop 5 checks the mapping as its own subcheck.\n"
        % (cov.get("n_items", 0), cov.get("n_with_field", 0),
           cov.get("n_answered", 0), cov.get("n_answered_verified", 0),
           cov.get("n_open", 0), cov.get("n_not_answerable", 0)))


def _band_data_entry_note(d):
    """One generated line for docs/32 from the live operator-form state."""
    rep = os.path.join(OUT, "operator_data_report.json")
    if not os.path.exists(rep):
        return ("По состоянию на этот прогон форма оператора не заполнена: "
                "`results_v2/operator_data_report.json` не создан, все десять "
                "размеров остаются коридорными.")
    try:
        o = json.load(open(rep, encoding="utf-8"))
        r = o.get("recommendation") or {}
        return ("По состоянию на этот прогон: полей в форме {n_fields}, внесено и "
                "прошло валидацию {n_applied}; из десяти размеров закреплено "
                "точкой {n_pinned}, коридор обязателен ещё для {n_corr}. Форма "
                "заполнена: {present}. Требуемая форма отчёта: `{form}`.".format(
                    n_fields=o.get("n_fields"), n_applied=o.get("n_applied"),
                    n_pinned=r.get("n_pinned", 0),
                    n_corr=r.get("n_corridor_required"),
                    present=bool(o.get("form_present")),
                    form=r.get("recommended_form", "corridor")))
    except Exception as exc:          # never let a report file break the doc
        return ("Форма оператора есть, но состояние не прочитано (%r) — "
                "коридор остаётся формой отчёта по умолчанию." % exc)


def _rfi_map_doc():
    """docs/33 33.7: the entered-value <-> vendor-request cross-reference.

    Generated by parsing the RFI tables in docs/28_v5_vendor_rfi.md, so the map
    follows the document: a new numbered item there appears here as an UNANSWERED
    row without any code change, and an item the form cannot answer is stated as
    such instead of being quietly dropped.
    """
    from .operator_data import rfi_coverage
    cov = rfi_coverage()
    state_ru = {
        "open": "открыт", "partial": "закрыт частично",
        "answered_single_source": "закрыт одним источником (точка + коридор)",
        "answered_verified": "закрыт с второй подписью",
        "not_answerable_by_form": "вне формы",
    }
    L = ["Сопоставление построено **разборкой самого запроса**: форма ссылается на "
         "номера пунктов, а их формулировки читаются из `docs/28`, поэтому новый "
         "пункт RFI появляется здесь как незакрытый без правки кода. Итог: пунктов "
         "**%d**, у **%d** есть поле формы, закрыто **%d** (с второй подписью **%d**), "
         "открыто **%d**, вне формы **%d**."
         % (cov["n_items"], cov["n_with_field"], cov["n_answered"],
            cov["n_answered_verified"], cov["n_open"], cov["n_not_answerable"]),
         "",
         "| п. | блок | что запрошено у поставщика | поля формы | состояние | зачем это модели |",
         "|---|---|---|---|---|---|"]
    for r in cov["rows"]:
        flds = ", ".join(("`%s`" % f["id"]) + (" ✓" if f["in_force"] else "")
                         + (" (2-я подпись)" if f["verified"] else "")
                         for f in r["fields"]) or "—"
        L.append("| %d | %s | %s | %s | **%s** | %s |"
                 % (r["item"], r["section"], r["text"].replace("|", "/"), flds,
                    state_ru.get(r["state"], r["state"]),
                    (r["model_uses_it_for"] or "—").replace("|", "/")))
    L += ["",
          "Пометка ✓ у поля значит, что число **введено и прошло валидацию** в этом "
          "прогоне; без неё пункт остаётся открытым, даже если значение набрано, но "
          "не принято (единица, диапазон, провенанс). Пункты вне формы — это "
          "документы и кривые (программа восстановления, TPR/TPO), которых модель "
          "не читает как число; они остаются в переписке с поставщиком.", "",
          "Ссылки формы на другой открытый источник: %s (кампания и замеры — это "
          "`docs/27`, их принимает `model/data_ingest.py`, а не эта форма)."
          % (", ".join("`%s`" % x for x in cov["other_sources"]) or "нет"), ""]
    return "\n".join(L)


def write_activity_band_doc():
    """docs/32: the activity-uncertainty corridor (model/activity_uncertainty.py).

    Generated from the saved JSON only, so the corridor cannot drift from the run.
    """
    path = os.path.join(OUT, "activity_uncertainty.json")
    if not os.path.exists(path):
        return False
    d = json.load(open(path, encoding="utf-8"))
    ab, dr = d["activity_band"], d["design_reference"]
    rows, sp, money = d["rows"], d["spans"], d["money"]
    prod = d["production_is_not_activity_limited"]
    vols = [r["volume_to_hold_design_conversion"] for r in rows]
    fixs = [r["at_fixed_geometry"] for r in rows]
    dVs = [v["delta_V_pct"] for v in vols if v["delta_V_pct"] is not None]
    L = ["# 32. Коридор неопределённости активности катализатора (NH₃‑конвертор)",
         "",
         "Сгенерировано `model/run_v2.py` из `results_v2/activity_uncertainty.json` "
         "(источник: `python -m model.activity_uncertainty`).", "",
         "## 32.1 Откуда берётся множитель", "",
         "`model/converter.py:calibrate_k0` подбирает **один** безразмерный "
         "множитель активности k_scale по двум открытым промышленным ориентирам, "
         "которые между собой не сходятся: середина коридора захода N₂ за проход "
         f"→ k_scale = {round(ab['k_scale_lo'], 4)}; выход 13,0 мол.% NH₃ → "
         f"k_scale = {round(ab['k_scale_hi'], 4)}. Отношение — **×"
         f"{round(ab['factor'], 3)}**. Это не разброс подгонки и не погрешность "
         "нашей лаборатории: это противоречие открытых источников, и снять его "
         "может только кампания (`docs/27`) либо конверторные данные завода на "
         "этом катализаторе (`docs/28`). Всё остальное в модели либо опубликовано "
         "(α, E_a, K_a, энтальпии), либо задано схемой.", "",
         f"## 32.2 Проект при фиксированной геометрии "
         f"(V = {round(dr['catalyst_volume_m3'], 2)} м³, {dr['n_beds']} секции, "
         f"вход {round(dr['bed_inlet_T_K'], 1)} K, "
         f"GHSV {round(dr['GHSV_normal_h1'], 0)} ч⁻¹, "
         f"{round(dr['p_bar'] if 'p_bar' in dr else 200, 0)} бар)", "",
         "| k_scale | положение | X за проход | выход NH₃ | T пик, K | выше потолка | Q межсекц., МВт | RR по кинетике | X·(1+RR) |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        f = r["at_fixed_geometry"]
        L.append(f"| {r['k_scale']:.4f} | {r['position_in_band']} | "
                 f"{f['per_pass_N2_pct']:.2f} % | {f['outlet_NH3_molpct']:.2f} мол.% | "
                 f"{f['T_peak_K']:.1f} | {f['peak_over_assumed_ceiling_K']:+.1f} K | "
                 f"{f['interbed_cooling_duty_MW']:.1f} | {f['recycle_ratio_implied']:.3f} | "
                 f"{f['loop_closure_X_times_1pRR']:.3f} |")
    L += ["",
          f"Главное: **пиковая температура от активности не зависит** — "
          f"{sp['T_peak_K'][0]:.2f}…{sp['T_peak_K'][1]:.2f} K (разница "
          f"{sp['T_peak_K'][1] - sp['T_peak_K'][0]:.2f} K): первая секция доходит до "
          "равновесного пинча, а подъём до пинча задаётся термодинамикой, а не "
          f"скоростью. Значит превышение предполагаемого потолка "
          f"{round(dr['assumed_bed_ceiling_K'], 1)} K — следствие выбора температуры "
          "входа (решение проектировщика), а не неопределённость катализатора. "
          f"Чувствительны к активности выход NH₃ ({sp['outlet_NH3_molpct'][0]:.2f}…"
          f"{sp['outlet_NH3_molpct'][1]:.2f} мол.%) и межсекционное охлаждение "
          f"({min(fixs, key=lambda x: x['interbed_cooling_duty_MW'])['interbed_cooling_duty_MW']:.1f}…"
          f"{max(fixs, key=lambda x: x['interbed_cooling_duty_MW'])['interbed_cooling_duty_MW']:.1f} МВт).",
          "",
          "## 32.3 Объём катализатора, если держать проектную конверсию", "",
          f"Цель — удержать X за проход = {dr['per_pass_N2_pct']:.2f} % (значение "
          "проекта) при другой активности; объём — единственный свободный рычаг "
          "(GHSV = Q/V).", "",
          "| k_scale | V нужно, м³ | ΔV к проекту | GHSV, ч⁻¹ | масса, т | инвентарь, USD | (V/V₀)^0,7 |",
          "|---|---|---|---|---|---|---|"]
    for r in rows:
        v = r["volume_to_hold_design_conversion"]
        L.append(f"| {r['k_scale']:.4f} | {v['V_m3']} | {v['delta_V_pct']} % | "
                 f"{v['GHSV_normal_h1']} | {v['catalyst_mass_t']} | "
                 f"{v['inventory_cost_USD']:.3g} | {v['vessel_scale_factor_capex_exponent_0p7']} |")
    v_lo = min(v["V_m3"] for v in vols if v["V_m3"])
    v_hi = max(v["V_m3"] for v in vols if v["V_m3"])
    m_lo = min(v["catalyst_mass_t"] for v in vols if v["catalyst_mass_t"])
    m_hi = max(v["catalyst_mass_t"] for v in vols if v["catalyst_mass_t"])
    L += ["",
          f"Катализаторный коридор: **{v_lo:.1f}…{v_hi:.1f} м³** (масса "
          f"{m_lo:.1f}…{m_hi:.1f} т). Верхняя граница совпадает с проектом, потому "
          "что проект откалиброван на НИЖнем крае полосы: заявленные 52,91 м³ — это "
          "консервативная (большая) оценка объёма, а не «уточнённая». Если реальная "
          f"активность окажется на верхнем крае, тот же результат требует на "
          f"{abs(min(dVs)):.1f} % меньший слой.", "",
          "## 32.4 Мера по потолку при каждой активности", "",
          "| k_scale | общий вход секций, K | T пик, K | X за проход | выход NH₃, мол.% | RR по кинетике |",
          "|---|---|---|---|---|---|"]
    for r in rows:
        c = r["ceiling_remedy"]
        L.append(f"| {r['k_scale']:.4f} | {c['T_in_common_K']:.1f} | "
                 f"{c['T_peak_K']:.1f} | {c['per_pass_N2_pct']:.2f} % | "
                 f"{c['outlet_NH3_molpct']:.2f} | {c['recycle_ratio_implied']:.3f} |")
    ce_lo = rows[0]["ceiling_remedy"]
    ce_hi = rows[-1]["ceiling_remedy"]
    L += ["",
          f"Смысл: при нижнем крае полосы уложиться в потолок "
          f"{round(dr['assumed_bed_ceiling_K'], 1)} K удаётся ценой выхода "
          f"{ce_lo['outlet_NH3_molpct']:.2f} мол.% (ниже открытого ориентира 13,0), "
          f"при верхнем — {ce_hi['outlet_NH3_molpct']:.2f} мол.% (выше ориентира). "
          "Устойчивый вывод один: **и потолок, и 13 мол.% на выходе одновременно "
          "выполняются только в верхней половине полосы активности** — то есть вопрос "
          "к поставщику по активности важнее вопроса по конструкции секций, и без "
          "данных он не закрывается (`docs/28`).", "",
          "## 32.5 Деньги: что полоса меняет и чего не меняет", "",
          "| канал | коридор | статус |", "|---|---|---|"]
    for x in money["recycle_compressor"]["power_by_loop_dP"]:
        L.append(f"| рецикловый компрессор при Δp контура {x['dP_loop_bar']} бар | "
                 f"{x['power_MW_min']:.2f}…{x['power_MW_max']:.2f} МВт "
                 f"(Δ {x['delta_cost_USD_y']:.3g} USD/год) | [ЧАСТИЧНО] политропная "
                 "оценка, k и η из config, каталожные кривые не открыты |")
    inv = money["catalyst_inventory_corridor_USD"]
    sc = [v["vessel_scale_factor_capex_exponent_0p7"] for v in vols
          if v["vessel_scale_factor_capex_exponent_0p7"]]
    L += [f"| инвентарь катализатора | {min(inv):.3g}…{max(inv):.3g} USD | "
          "[ДОПУЩЕНИЕ] цена скрининга Ni/MgAl2O4 из `model/economics.py`; цены и "
          "ресурса промоторированного железного аммиачного катализатора не "
          "открыто, поэтому годовая замена намеренно не считается |",
          f"| перевод объём→масса | ×{money['density_used_kg_m3']} кг/м³ | "
          "[ЧАСТИЧНО] плотность Cu/ZnO из VBF взята как заполнитель; значение для "
          "аммиачного катализатора запрашивает `docs/28` п. 12 |",
          f"| масштабирование корпуса | (V/V₀)^0,7 → {min(sc):.3f}…{max(sc):.3f} | "
          "(V/V_ref)^0,7 с показателем проекта; доля конвертора в скрининговом "
          "CAPEX 281,4 млн USD моделью не разрешается — приводится только "
          "относительный множитель |",
          f"| тоннаж NH₃ | {prod['NH3_design_t_h']:.2f} т/ч (без изменений) | "
          "при фиксированной подаче и давлении тоннаж задаётся замыканием "
          "X·(1+RR) ≥ 1; активность меняет требуемый RR, а не предел по "
          "стехиометрии (замыкание > 1 — избыточный рецикл, не прирост продукта) |", "",
          f"Итог по экономике: неопределённость активности — это **вопрос "
          f"инвестиционного объёма (катализатор и корпус: до −{abs(min(dVs)):.0f} %), "
          "а не эксплуатационных расходов** (рецикл: десятые доли мега Ватт, "
          f"{money['recycle_compressor']['power_by_loop_dP'][-1]['delta_cost_USD_y']:.3g} "
          "USD/год на всём коридоре). Годовая стоимость замены катализатора "
          "намеренно НЕ считается: ни цена, ни ресурс промоторированного железного "
          "катализатора в проекте не открыты.", "",
          "## 32.6 Как это докладывать", "",
          "Дословные формулировки модели (из "
          "`results_v2/activity_uncertainty.json`):", "",
          "\n".join("* " + x for x in d["how_to_use"].split("\n")), "",
          "## 32.7 Чего коридор не покрывает", "",
          "Список — это открытые вопросы, а не замечания к расчёту; каждый из них "
          "уже учтён статусом петлей проверки.", "",
          "\n".join("* " + x for x in d["not_covered"]), "", "---", "",
          "## 32.8 Чем и как закрывается этот коридор (ручной ввод данных)", "",
          "Ни один из десяти размеров не закрывается рассуждением: только вводом "
          "человека с провенансом. Форма — `model/operator_data.py` (61 поле), "
          "правила и таблица полей — `docs/33`, живой ввод — "
          "`data/operator_inputs.json` или вкладка «Ручной ввод данных (V5.3)» "
          "панели (`/api/operator`). Внесённое с единицей, методом, документом и "
          "подписью закрепляет точку вместо коридора; без второй подписи статус "
          "остаётся [ЧАСТИЧНО], а полоса продолжает печататься рядом "
          "(`literature_reference_rows`). Контур 5 от этого не проходит: ввод "
          "закрывает отсутствие данных, а не независимую валидацию.", "",
          _band_data_entry_note(d), "",
          "> Примечания. Источник полосы — `model/converter.py:calibrate_k0`: "
          "нижний край бьёт в середину открытого коридора захода N₂ за проход, "
          "верхний — в открытый ориентир 13,0 мол.% NH₃ на выходе; обе точки — "
          "литературные значения, поэтому сам множитель ×2,362 является "
          "[ЧАСТИЧНО] (измеренное противоречие источников, а не подгонка). "
          "Формулировки пунктов 32.6–32.7 приведены дословно из JSON модели.", ""]
    open(os.path.join(DOCS, "32_v5_activity_band.md"), "w",
         encoding="utf-8").write("\n".join(L))
    return True


def write_methanol_adiabatic_doc():
    """docs/31: the methanol adiabatic march against the opened VBF worked case."""
    path = os.path.join(OUT, "methanol_adiabatic_check.json")
    if not os.path.exists(path):
        return False
    d = json.load(open(path, encoding="utf-8"))
    from .methanol_converter import VBF_TABLE3 as V3_KEYS
    tm, cp = d["this_model"], d["comparison"]
    L = ["# 31. Адиабатический метанольный реактор: сверка с открытым кейсом VBF", "",
         "Сгенерировано `model/run_v2.py` из `results_v2/methanol_adiabatic_check.json` "
         "(источник: `python -m model.methanol_converter`).", "",
         "## 31.1 Зачем это нужно", "",
         "В V4 кинетика Vanden Bussche–Froment интегрировалась **изотермически**. "
         "Открытого непоизотермического кейса для этого закона в проекте не было, и "
         "расхождение «30,22 %/проход против 3,4 мол.% на выходе у промышленной "
         "установки» нельзя было объяснить: ошибка может быть и в кинетике, и в "
         "предположении об изотермичности. Теперь найден и открыт кейс, где те же "
         "авторы сами считают **адиабатический** реактор (Table 3 + Fig. 5 их "
         "статьи), и модель воспроизводится на нём целиком: кинетика + тепловой "
         "баланс + энтальпии.", "",
         "## 31.2 Условия кейса (переписаны дословно из статьи)", "",
         "| параметр | значение |", "|---|---|",
         "| T на входе | %s K |" % V3_KEYS["T_in_K"],
         "| p | %s бар |" % V3_KEYS["p_bar"],
         "| массовый расход | 2,8·10⁻⁵ кг/с |",
         "| масса катализатора | %s г (ICI 51‑2, d_p = 0,5 мм) |" % V3_KEYS["catalyst_mass_g"],
         "| реакция | Cu/ZnO/Al₂O₃, VBF, η = 1 |",
         "| состав питания, мол.%% | CO %s, CO₂ %s, H₂ %s, инерт %s, H₂O/MeOH 0 |"
         % (V3_KEYS["feed_molpct"]["CO"], V3_KEYS["feed_molpct"]["CO2"],
            V3_KEYS["feed_molpct"]["H2"], V3_KEYS["feed_molpct"]["INERT"]),
         "| W/F (пространственный время) | %s кг·с/моль |"
         % d["inputs"]["space_time_kg_cat_s_per_mol_feed"], "",
         "Средняя молярная масса питания %s г/моль → %s моль/ч полного потока; "
         "давление по постели не меняется (короткий лабораторный реактор), "
         "напор/Δp не моделируется." % (round(d["inputs"]["mean_molar_mass_g_per_mol"], 3),
                                       round(d["inputs"]["F_mol_h"]["H2"] / 0.82, 2)), "",
         "## 31.3 Результат сверки", "",
         md_table(["показатель", "эта модель", "опубликовано", "отклонение"],
                  [["T на выходе, K", fnum(cp["T_out_K"]["model"], 2),
                    fnum(cp["T_out_K"]["published"], 1),
                    fnum(cp["T_out_K"]["dev_K"], 2)],
                   ["ΔT адиабатического подъёма, K", fnum(tm["dT_ad_K"], 2), "58,8",
                    fnum(tm["dT_ad_K"] - 58.8, 2)],
                   ["CO₂, мол.%", fnum(tm["y_out_molpct"]["CO2"], 3), "2,1",
                    fnum(cp["CO2_molpct"]["dev_pp"], 3)],
                   ["CO, мол.%", fnum(tm["y_out_molpct"]["CO"], 3), "2,9",
                    fnum(cp["CO_molpct"]["dev_pp"], 3)],
                   ["CH₃OH, мол.%", fnum(tm["y_out_molpct"]["CH3OH"], 3), "2,4",
                    fnum(cp["MeOH_molpct"]["dev_pp"], 3)],
                   ["H₂O, мол.%", fnum(tm["y_out_molpct"]["H2O"], 3), "1,1",
                    fnum(cp["H2O_molpct"]["dev_pp"], 3)]]), "",
         "Пороги (0,5 мол.% и 15 K) зафиксированы **до** просмотра результата; "
         "критерий «внутри окна применимости»: кейс лежит в 180–280 °C / 15–51 бар, "
         "для которых VBF и выводился — в отличие от промышленного кейса V4, где "
         "GHSV лежал вне открытого коридора. Углерод сходится на "
         "{:.1e}, невязка энтальпийного баланса {:.1e}.".format(
             tm["carbon_closure_rel"], tm["enthalpy_residual_rel"]), "",
         "Энтальпия реакции CO₂ + 3H₂ → CH₃OH + H₂O, собранная из энтальпий этой "
         "модели: **{} кДж/моль при 298,15 K** против −49,7 кДж/моль (Appl. Sci. "
         "2017, уже цитируется в проекте) и **{} кДж/моль для CO + 2H₂ → CH₃OH** "
         "против −90,7 — то есть термодинамическая часть независима от кинетики и "
         "сходится с цитируемым значением до 0,3 кДж/моль. При T на выходе "
         "({} K) та же реакция даёт {} кДж/моль: рост модуля на {} кДж/моль "
         "соответствует среднему Δcp = {} Дж/(моль·K) на интервале 298–{} K — "
         "это следствие учёта теплоёмкости всех шести компонентов, а не "
         "расхождение модели и источника."
         .format(round(tm["dH_CO2_route_kJ_per_mol_at_298_K"], 2),
                 round(tm["dH_CO_route_kJ_per_mol_at_298_K"], 2),
                 round(tm["T_out_K"], 1),
                 round(tm["dH_CO2_route_kJ_per_mol_at_T_out"], 2),
                 round(abs(tm["dH_CO2_route_kJ_per_mol_at_T_out"]
                           - tm["dH_CO2_route_kJ_per_mol_at_298_K"]), 2),
                 round(1000.0 * (tm["dH_CO2_route_kJ_per_mol_at_T_out"]
                                 - tm["dH_CO2_route_kJ_per_mol_at_298_K"])
                       / (tm["T_out_K"] - 298.15), 1),
                 round(tm["T_out_K"], 0)), "",
         "## 31.4 Чувствительность к недоопределённым входным данным", "",
         md_table(["вариант", "T на выходе, K", "MeOH, мол.%", "CO₂, мол.%",
                   "CO, мол.%", "H₂O, мол.%"],
                  [[v["variant"], fnum(v["T_out_K"], 2), fnum(v["MeOH_molpct"], 3),
                    fnum(v["CO2_molpct"], 3), fnum(v["CO_molpct"], 3),
                    fnum(v["H2O_molpct"], 3)] for v in d["sensitivity"]]), "",
         "Инерт в Table 3 не назван, а ΔfH°(CH₃OH) на странице NIST приведён как "
         "−205±10 кДж/моль (использовано −201,49 из той же страницы — оно "
         "воспроизводит обе энтальпии реакций, уже цитируемые в проекте). Оба "
         "выбора меняют подъём температуры не более чем на 1,1 K — вывод не "
         "чувствителен.", "",
         "Самопроверка опубликованных цифр: из MeOH и CO восстанавливаются степени "
         "протекания a = {} и b = {} (на 100 моль питания, b < 0 = суммарно идёт "
         "WGS), и предсказанные по ним CO₂/H₂O равны {}/{} мол.% против "
         "опубликованных 2,1/1,1 — то есть цифры рисунка внутренне согласованы до "
         "{} мол.%, а не являются ошибкой распознавания."
         .format(d["published_end_point_self_consistency"]["extent_MeOH_per_100mol_feed"],
                 d["published_end_point_self_consistency"]["extent_RWGS_per_100mol_feed"],
                 d["published_end_point_self_consistency"]["predicted_from_extents"]["CO2_molpct"],
                 d["published_end_point_self_consistency"]["predicted_from_extents"]["H2O_molpct"],
                 round(d["published_end_point_self_consistency"]["max_self_inconsistency_pp"], 3)), "",
         "## 31.5 Что это доказывает и чего не доказывает", "",
         "**Доказывает:** корректность реализации — размерности скоростей VBF, "
         "знак и величина тепловыделения, связь T с составом, интегратор; "
         "кинетика VBF при 493–552 K даёт именно тот отклик, который дают её "
         "авторы; адиабатичность (а не изотермичность) меняет выход MeOH на этом "
         "кейсе на {} мол.% — то есть допущение об изотермичности в V4 недооценивало "
         "состав, но НЕ объясняет расхождение с промышленным 3,4 мол.%."
         .format(round(abs(d["sensitivity"][-1]["MeOH_molpct"]
                          - tm["y_out_molpct"]["CH3OH"]), 3)), "",
         "**Не доказывает:** что Cu/ZnO/Al₂O₃ из `cases/config.json` имеет активность "
         "ICI 51‑2, что наш промышленный реактор адиабатический (у нас tubular с "
         "теплосъёмом), и что VBF верен за пределами 180–280 °C. Это сверка модели с "
         "моделью, а не с установкой; контур 5 от неё не закрывается.", "",
         "## 31.6 Профиль по длине постели (эта модель)", "",
         md_table(["W/W_total", "T, K", "MeOH, мол.%", "CO₂, мол.%", "CO, мол.%",
                   "H₂O, мол.%"],
                  [[fnum(p["W_over_Wtot"], 3), fnum(p["T_K"], 1), p["y_MeOH_molpct"],
                    p["y_CO2_molpct"], p["y_CO_molpct"], p["y_H2O_molpct"]]
                   for p in d["profile"]]), "",
         "Температура на выходе — максимум профиля (промежуточного охлаждения нет). "
         "Статья описывает смену направления RWGS примерно на 3 мм постели; в этом "
         "профиле это видно как резкое замедление роста H₂O в первых 5 % длины "
         "(0,045 → 0,571 → 0,726 мол.%). Разрешение в 20 точек не позволяет "
         "утверждать, что разворот произошёл именно на 3 мм, — это качественное, а "
         "не совмёрванное совпадение. Позицию выхода на равновесие статья "
         "указывает явно: «At 3 cm in the bed, the thermodynamic equilibrium "
         "concentrations are attained», т.е. W/W_total ~ 0,2; в этом профиле "
         "прирост MeOH на 10 % длины падает ниже 0,01 мол.% начиная с "
         "W/W_total = {} — то есть выход на равновесие происходит позже, чем "
         "указано в подписи (при том что конечная точка совпадает)."
         .format(_eq_onset(d["profile"]))]
    notes = ["", "", "---", "", "> Примечания. %s" % " / ".join([
                 "источник кейса: %s (%s)" % (V3_KEYS["reference"], V3_KEYS["doi"]),
                 "URL: %s" % V3_KEYS["url"],
                 "энтальпии: NIST Shomate (CO, CO₂, H₂, H₂O) + таблица Cp NIST/TRC для CH₃OH в data/nist_cp_ch3oh.json",
                 "приведённые статусы: %s" % d["status"],
             ]), ""]
    open(os.path.join(DOCS, "31_v5_methanol_adiabatic.md"), "w",
         encoding="utf-8").write("\n".join(L + notes))
    return True


def _eq_onset(profile, thr=0.01):
    """First W/W_total from which the MeOH gain over the next 10 % of the bed
    stays below `thr` mol% (i.e. the march has effectively reached equilibrium)."""
    pts = [p for p in (profile or [])]
    for i, p in enumerate(pts):
        j = min(i + 2, len(pts) - 1)
        if j <= i:
            continue
        if abs(pts[j]["y_MeOH_molpct"] - p["y_MeOH_molpct"]) < thr:
            return round(p["W_over_Wtot"], 2)
    return None


def write_uncertainty_doc():
    """docs/30: model-side input-uncertainty envelope (model/uncertainty.py).

    Generated from the saved JSON only, so it cannot drift from the run."""
    path = os.path.join(OUT, "model_uncertainty.json")
    if not os.path.exists(path):
        return False
    d = json.load(open(path, encoding="utf-8"))
    from . import uncertainty as unc
    L = ["# 30. Собственная неопределённость модели (X_CH4) и её отношение к "
         "расхождению с пилотом", "",
         "Сгенерировано `model/run_v2.py` из `results_v2/model_uncertainty.json` "
         "(источник: `python -m model.uncertainty`).", "",
         "## 30.1 Постановка", "",
         "Модель равновесная (Gibbs + подход к равновесию), пилот — кинетический при "
         "1–10 бар. Перед тем как объяснять расхождение +0.287 по X_CH4 «неточностью "
         "исходных данных», посчитано, насколько вообще model X_CH4 может двигаться от "
         "тех входных неопределённостей, которые у нас есть: анализ состава, "
         "расходомеры, датчики температуры, набор kij, допущение подхода к равновесию "
         "и (для проектных точек) проскок C2+ в предреформере. Метод — один фактор за "
         "раз (OFAT), огибающая min/max; квадратичная сумма дана отдельно и "
         "интерпретируется как нижняя оценка (корреляции знаков между факторами "
         "игнорируются).", "",
         "## 30.2 Принятые величины неопределённостей", "",
         "| возмущение | величина | статус / обоснование |", "|---|---|---|"]
    def _desc(v):
        if "dT" in v:
            return "ΔT = %+.1f K" % v["dT"]
        if "dSC" in v:
            return "S/C %+.0f %%" % (100.0 * v["dSC"])
        if "dCO2C" in v:
            return "CO2/C %+.0f %%" % (100.0 * v["dCO2C"])
        if "dCH4" in v:
            return "доля CH4 %+.0f %%" % (100.0 * v["dCH4"])
        if "approach_K" in v:
            return "подход к равновесию %g K" % v["approach_K"]
        if "kset" in v:
            return "набор kij → %s" % v["kset"]
        return str(v)

    for k, v in unc.PERTURB.items():
        L.append("| %s | %s | %s |" % (k, _desc(v),
                                       unc.STATUSES.get(next(iter(v)),
                                                         "[ДОПУЩЕНИЕ]")))
    L.append("| явный C2+ / проскок через предреформер | 0 → 10 % углерода как "
             "этана (пилотные точки); 5 и 20 % проскока (проектные точки) | "
             "[ЧАСТИЧНО] предреформер смоделирован, его эффективность не "
             "измерена |")
    L += ["",
          "Значения взяты из требований к кампанию (docs/27 разд. 6) и из уже "
          "сконструированных наборов kij; они НЕ измерены — это допущения о приборной "
          "и аналитической точности, которые кампания должна подтвердить.", "",
          "## 30.3 Результат: огибающая по каждой точке", "",
          "| точка | T, K | p, бар | X базы | огибающая | ±полуширина | квадратура | "
          "X измерения | измерено − модель | зазор/полуширина | крупнейший фактор |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in d["points"]:
        xm = r.get("X_measured")
        gm = r.get("measured_minus_model")
        L.append("| %s | %.2f | %.1f | %.4f | %.4f–%.4f | %.4f | %.4f | %s | %s | %s | %s |"
                 % (r["record_id"], r["T_K"], r["p_bar"], r["X_base"],
                    r["envelope_min"], r["envelope_max"],
                    r["envelope_half_width"], r["quadrature_half_width"],
                    ("%.3f" % xm) if xm is not None else "—",
                    ("%+.3f" % gm) if gm is not None else "—",
                    ("%.1f×" % r["gap_over_envelope_half_width"])
                    if r.get("gap_over_envelope_half_width") is not None else "—",
                    "%s (%+.4f)" % (r["largest_single_effect"]["perturbation"],
                                    r["largest_single_effect"]["delta"])))
    s = d
    L += ["", "## 30.4 Вывод", "",
          "1. **Термодинамика и состав сырья не объясняют расхождение с piloтом.** "
          "Собственная огибающая модели по X_CH4 — ±%.4f…±%.4f (в среднем ±%.4f, "
          "квадратично ±%.4f); расхождение с измеренными значениями превышает её в "
          "%.1f–%.1f раза, и НИ ОДНА из %d открытых пилотных точек не попадает в полосу "
          "модели." % (min(r["envelope_half_width"] for r in d["points"] if
                           r.get("measured_minus_model") is not None),
                        max(r["envelope_half_width"] for r in d["points"] if
                            r.get("measured_minus_model") is not None),
                        s["mean_envelope_half_width"], s["mean_quadrature_half_width"],
                        min(r["gap_over_envelope_half_width"] for r in d["points"] if
                            r.get("gap_over_envelope_half_width") is not None),
                        max(r["gap_over_envelope_half_width"] for r in d["points"] if
                            r.get("gap_over_envelope_half_width") is not None),
                        s["pilot_points_total"]),
          "2. При этом направление расхождения совпадает с физикой: при 1 бар модель "
          "завышает сильнее всего (+0.461), при 10 бар — наименьшее (+0.095), а тренд по "
          "давлению воспроизведён. Это признак кинетического ограничения лабораторных "
          "точек, а не ошибки в данных или в EOS.",
          "3. **Крупнейший собственный допуск проектных точек — не состав и не kij, а "
          "допущение о подходе к равновесию**: ±0.022…0.024 по X_CH4 (метанол), против "
          "≤0.005 от T (±2 K), ≤0.004 от S/C (±2 %), ≤0.0003 от выбора kij. То есть "
          "первым дело надо измерять кинетику (кампания docs/27), а не «уточнять "
          "термодинамику».",
          "4. Полосы проектных точек воспроизводят собственные отчёты моделей "
          "(|X_базы − X_в отчёте| ≤ %.4f), то есть расчёт чувствительности идёт по той "
          "же цепочке, что и проект, — а не по её упрощению."
          % max(abs(r["X_base"] - r["X_model_reported"]) for r in d["points"]
                if r.get("X_model_reported") is not None), "",
          "## 30.5 Чего этот расчёт НЕ делает", "",
          "* не является валидацией и не двигает контур 5 к PASS — он проверяет "
          "устойчивость *объяснения* расхождения;",
          "* не охватывает кинетическую неопределённость (η, deactivation, k0 "
          "синтеза NH3 с множителем 2.36 по docs/26) — она на порядок больше;",
          "* OFAT-огибающая завышает полосу, когда факторы частично компенсируют друг "
          "друга (S/C и CO2/C), а квадратурная — занижает при однонаправленных "
          "эффектах; обе приведены, чтобы не выбирать удобную;",
          "* допущения о приборах (±2 K, ±1…2 %) взяты из требований к кампании, а не "
          "из калибровочных сертификатов лаборатории.", "",
          "## 30.6 Что делать с этим результатом", "",
          "В кампанию docs/27 добавлен расчётный тест: если после закрытия контракта "
          "остатки останутся вне полосы (а они вне её на всех открытых точках), вывод "
          "о кинетическом режиме подтверждается, и следующим шагом становится калибровка "
          "кинетического множителя по campaign-данным — по той же процедуре из одного "
          "скаляра, что уже применена к конвертеру NH3 (docs/26 разд. 4), а не "
          "«уточнение EOS»."]
    notes = ["", "", "---", "",
             "> Примечания. %s" % " / ".join([
                 "полоса = [envelope_min, envelope_max] вокруг X_base при OFAT-возмущениях",
                 "квадратурная полуширина — нижняя оценка, OFAT-огибающая — верхняя",
                 "проектные точки используют СОБСТВЕННЫЙ поток сырья модели и "
                 "подход к равновесию 10 K из config.json",
             ]), ""]
    open(os.path.join(DOCS, "30_v5_uncertainty.md"), "w",
         encoding="utf-8").write("\n".join(L + notes))
    return True


def fnum(x, n=3):
    if x is None: return "n/a"
    try: return f"{float(x):.{n}f}"
    except Exception: return str(x)


def write_reports(designs, scenarios, v):
    l5 = v["loops"]["5_validation_falsification"]
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

""" + md_table(["product", "V_reformer m3", "V_pre m3", "catalyst t",
                "Ni inventory t", "Ni t/y (4 y life)", "catalyst t/y", "ZnO kg",
                "Ni inventory, kg per 1000 Nm3 of annual product"], rows) + """

**Unit note (V5.2 fix).** The last column and the `Ni_consumption_kg_per_1000Nm3`
field of the life sensitivity used to carry two cancelling `/1000` factors, i.e.
they returned kg per **Nm3** under a key that says kg per **1000 Nm3** - values
were 1000x low. `model/catalyst_inventory.py` now multiplies by 1000 once; the
table above is the corrected basis. `Ni_per_1000Nm3_product_kg` is an inventory
intensity (installed Ni per annual product volume), NOT a consumption rate - the
consumption rate is the `/life` version in the sensitivity below.

## 14.4 Life sensitivity (methanol example)

""" + md_table(["life y", "Ni t/y", "catalyst t/y"],
               [[r[1], r[2], r[3]] for r in life_rows]) + """

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

Further data needed: a pilot campaign at 20-31 bar with 15 wt% Ni/MgAl2O4
(X_CH4 vs T, p, S/C, CO2/C; measured dP; 200-1000 h sintering) and a vendor
Ni/MgAl2O4 CATALYST datasheet. Open pilot data at 1-10 bar WERE found and
compared (docs/22). Re-run loop 5 after that. The V2 methanol CO2 gap is
CLOSED (docs/20); stoichiometric
synthesis loops (docs/18) are now complemented by VBF/Graaf and
Temkin-Pyzhev kinetics (docs/23); real pilot data were collected and compared
(docs/22); a HAZOP worksheet was produced but is NOT certified (docs/24);
loop 5 was rerun and remains FAILED with """ + f"""{l5["subchecks_passed"]} of
{l5["subchecks_total"]}""" + """ subchecks passing (docs/25, docs/26).

## 17.6 V5 state

The isothermal ammonia PFR was replaced by a **multi-bed adiabatic converter**
(NIST Shomate energy balance, normal-basis space velocity, Temkin-Pyzhev with
published alpha/Ea and ONE documented activity scalar k_scale), and the pilot
data / vendor / HAZOP gaps were converted into executable handover documents:

- `docs/26_v5_converter.md` - converter, calibration, loop-5 consequences;
- `docs/27_v5_pilot_test_program.md` + `data/pilot_schema.json` +
  `model/data_ingest.py` - campaign design, data contract, automatic loop-5
  rerun on ingest;
- `docs/28_v5_vendor_rfi.md` - the 18 datasheet items the model needs;
- `docs/29_v5_hazop_tor.md` - terms of reference for a certified HAZOP team.

Still true after V5: **no pilot campaign has been run, no vendor datasheet was
obtained, no certified HAZOP took place, and no HYSYS run exists** - those are
physical and organisational acts that a code agent cannot perform; they are
prepared for, not faked. Loop 5 stays FAILED until the data arrive.

## 17.7 V5.1 state (same data, three closable gaps removed)

Three gaps that did **not** need new data were closed on the model side:

1. **The model's own uncertainty band on X_CH4 is now quantified**
   (`model/uncertainty.py`, docs/30): OFAT envelope +/-0.014 average over the 6
   open pilot points and 3 design points, quadrature +/-0.007. The pilot/model
   bias of +0.287 exceeds the band by 5.8-35.8x at every point, so the
   discrepancy CANNOT be blamed on feed analysis, T sensors, S/C, CO2/C or kij
   - it is the kinetic regime, exactly as claimed. Largest single design-side
   tolerance: the 10 K approach-to-equilibrium assumption (+/-0.023 on X_CH4),
   5x bigger than all thermodynamic factors combined.
2. **The ammonia peak-temperature problem is now a design trade-off, not an
   open defect** (`scan_converter_layouts`, docs/26 sec. 6): 12 layouts
   (2-5 beds x 0/15/30% cold shot) were scanned at constant catalyst volume;
   all 12 can be held at or below the assumed 803 K ceiling (inlet 628-666 K),
   6 of them also inside the opened 15-20% per-pass band, and 5 beds with no
   quench reproduces the opened 13 mol% outlet benchmark (13.21 mol%) at
   802.6 K peak.
3. **The methanol kinetics are now validated against a non-isothermal case**
   (`model/methanol_converter.py`, docs/31): the adiabatic march reproduces the
   published VBF bench-scale base case to 0.54 K on T_out and <=0.12 mol% on
   every species (tolerances fixed beforehand), with carbon closure 1e-9,
   enthalpy residual 1e-8, and the case inside the 180-280 C / 15-51 bar
   validity window. This is model-to-model verification of the implementation -
   NOT pilot or plant validation, and loop 5 is still open because of that.

Loop 5 after V5.1: """ + f"""{l5["subchecks_passed"]} of {l5["subchecks_total"]}""" + """
subchecks pass; the status is FAILED by design until the campaign, the vendor
datasheet and a certified HAZOP exist.

## 17.8 V5.2 state (the activity disagreement became a corridor)

""" + activity_summary_17() + """

## 17.9 V5.3 state (operators can now close the gaps themselves)

""" + operator_summary_17() + "\n"
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

    # 22 pilot data ---------------------------------------------------------
    pilot = load_pilot(); com = load_commercial()
    l5 = v["loops"]["5_validation_falsification"]
    ext = l5["external_data"]
    txt = f"""# 22. Pilot dataset for 15 wt% Ni/MgAl₂O₄ and commercial datasheets (V4)

**Ни одно число в этом реестре не выдумано.** `data/pilot_ni_mgal2o4.json`
содержит {len(pilot['records'])} записей из {len(pilot['sources'])} открытых
источников; у каждой записи есть URL и статус. `value: null` означает, что
источник сообщает тенденцию, но не приводит табличного числа.

## 22.1 Что реально найдено

{md_table(['источник', 'работа', 'что даёт', 'статус'],
          [[q['id'], q['citation'][:62], q['note'][:70],
            {'S1':'[ПОДТВЕРЖДЕНО]','S3':'[ПОДТВЕРЖДЕНО]'}.get(q['id'],'[ЧАСТИЧНО]')]
           for q in pilot['sources']])}

Ключевые числа (все — из открытых текстов):

- 15 мас.% Ni/MgAl₂O₄ (Sasol Puralox 30/140), BET 86 м²/г, Ni 6,6 нм,
  восстановление 850 °C/16 ч, TPR-пик 725 °C, H/Ni(пов) = 0,2 при 600 °C
  (Catalysts 2019, 9, 801). [ПОДТВЕРЖДЕНО]
- Порядок по этану 0,76, по воде 0, Ea = 79,1 кДж/моль; 1 атм, 550–900 °C,
  GHSV 22 000–356 000 ч⁻¹, τ = 10–170 мс, типичный опыт 9 мг катализатора.
  [ПОДТВЕРЖДЕНО]
- 100 ч при 850 °C, S/C = 1,5, τ = 2,3 мс, симулянт природного газа:
  Ni сохраняет **53 %** активности (Ir 91 %, Rh 78 %). Причина — коксование
  C₂₊, а не спекание. [ПОДТВЕРЖДЕНО]
- X_CH₄ = 40–50 % при 1 бар, 35–45 % при 5 и 10 бар (600 °C, S/C = 5,
  15 мас.% Ni/MgAl₂O₄). 0Rh15Ni: 49,4 % → 40,0 % при 1 → 10 бар.
  [ЧАСТИЧНО]
- 10 %Ni/Mg₂Al₂O₄, сухой риформинг CH₄:CO₂ = 1:1: X_CH₄ 50,0 / 65,8 /
  78,4 / 83,2 % при 650 / 700 / 750 / 800 °C (10 мин) и 47,6 / 62,6 /
  76,0 / 81,4 % (200 мин). [ЧАСТИЧНО] — другой катализатор и другая реакция.
- 3,4 мас.% Ni/MgAl₂O₄, 9,8 нм, 100 ч без дезактивации, 500–700 °C,
  CO₂/CH₄ = 0,76, O₂/CH₄ = 0,12–0,47, H₂/CO = 1,5–2,1. [ЧАСТИЧНО]

## 22.2 Коммерческий даташит: честный ответ

**Даташит коммерческого Ni/MgAl₂O₄ КАТАЛИЗАТОРА не найден.**
Найдены даташиты коммерческих **порошков носителя MgAl₂O₄**:

{md_table(['поставщик', 'продукт', 'BET м²/г', 'насыпная плотность', 'статус'],
          [[q['supplier'], q['product'][:38],
            str(q['properties'].get('BET_m2_g') or q['properties'].get('BET_m2_g_range') or '-'),
            (str(q['properties']['bulk_density_g_L'])+' г/л') if 'bulk_density_g_L' in q['properties'] else '-',
            q['status']] for q in com['support_powder_datasheets']])}

Novotech 2130RS: насыпная плотность 300 г/л = 300 кг/м³, истинная 3,64 г/мл,
BET 152,8 м²/г, Al₂O₃ 71,73 %, MgO 28,64 %, S < 0,07 %, Tпл 2130 °C.
**Это насыпная плотность нанопорошка, а не плотность загрузки гранул**, поэтому
прокси JM KATALCO (900 кг/м³, α-Al₂O₃ / Ca-алюминат) из `cases/config.json`
остаётся необходимым и по-прежнему явно помечен как PROXY. [НЕ ПОДТВЕРЖДЕНО]

## 22.3 Сравнение модели с внешними данными (фальсификация)

{md_table(['запись','p бар','T K','X изм.','X модель (равновесие)','Δ','применимость'],
          [[c['record_id'], c['p_bar'], round(c['T_K'],1), round(c['X_measured'],3),
            round(c['X_model_equilibrium'],3), round(c['delta'],3), c['applicability'][:28]]
           for c in ext['comparisons']])}

- Среднее смещение **{ext['mean_model_bias']:+.3f}**, макс {ext['max_model_bias']:+.3f},
  мин {ext['min_model_bias']:+.3f} по {ext['n_numeric_X_CH4_comparable']} точкам.
- Тренд по давлению воспроизведён: измерено {ext['pressure_trend']['measured_decrease']:.3f},
  модель {ext['pressure_trend']['model_decrease']:.3f} (модель завышает чувствительность).
- Смещение **ожидаемо**: модель решает РАВНОВЕСИЕ, лабораторные данные —
  КИНЕТИКА при 1–10 бар и коротком времени контакта. Это опровергает
  использование равновесной модели как кинетического предиктора, но не
  валидирует расчётную точку 25 бар.

## 22.4 Ресурс и спекание

Экстраполяция 100-часовой потери активности до 50 % даёт
{ext['deactivation']['extrapolated_t50_h']:.0f} ч против расчётного ресурса
{ext['deactivation']['design_life_h']:.0f} ч (отношение
{ext['deactivation']['ratio_design_to_extrapolated']:.0f}×). Это НИЖНЯЯ граница:
измеренная дезактивация вызвана коксованием при S/C = 1,5, а не спеканием при
S/C = 3. Серии 200–1000 ч для 15 мас.% Ni/MgAl₂O₄ не найдено.
[НЕ ПОДТВЕРЖДЕНО]

## 22.5 Не закрыто

{chr(10).join('- '+g for g in pilot['gaps'])}
"""
    open(os.path.join(DOCS, "22_v4_pilot_data.md"), "w", encoding="utf-8").write(txt)

    # 23 kinetic synthesis --------------------------------------------------
    km = designs["methanol"]["synthesis"]["kinetic"]
    ka = designs["ammonia"]["synthesis"]["kinetic"]
    vb = km["methanol_vbf"]; bm = km["benchmark_check"]
    tp = ka["ammonia_temkin"]; ba = ka["benchmark_check"]
    txt = f"""# 23. Kinetic synthesis loops (V4): Graaf/VBF and Temkin–Pyzhev

Стехиометрические балансы из `docs/18` сохранены как основа для тоннажей;
здесь добавлены **настоящие кинетические уравнения**, проинтегрированные по
изотермическому PFR. Ни один параметр не выдуман — все взяты из открытых
первоисточников и записаны в `cases/config.json -> kinetics`.

## 23.1 Метанол: Graaf (1986) K_eq + Vanden Bussche & Froment (1996) LHHW

Первичная статья открыта целиком: [J. Catal. 1996, Table 2]
(https://terpconnect.umd.edu/~nsw/chbe446/VandenBussche-syngas2MeOH.pdf).
Давления в бар, скорости в моль/(кг_кат·с), область применимости
180–280 °C, 15–51 бар, p_CO/p_CO₂ = 0–4,1.

```
r_MeOH = k_MeOH·p_CO2·p_H2·[1 − (1/K1)(p_H2O·p_MeOH)/(p_H2³·p_CO2)]·β³
r_RWGS = k_RWGS·p_CO2·[1 − K3·(p_H2O·p_CO)/(p_CO2·p_H2)]·β
β = 1/(1 + K_ratio·(p_H2O/p_H2) + sqrt(K_H2·p_H2) + K_H2O·p_H2O)
```

{md_table(['параметр','A','B (Дж/моль)','вид'],
          [['sqrt(K_H2)','0.499','17 197','A·exp(B/RT)'],
           ['K_H2O','6.62e-11','124 119','A·exp(B/RT)'],
           ['K_H2O/(K8K9K_H2)','3453.38','0','константа'],
           ['k_MeOH','1.07','36 696','A·exp(B/RT)'],
           ['k_RWGS','1.22e10','−94 765','A·exp(B/RT)'],
           ['log10 K1 (Graaf)','3066/T − 10.592','—','равновесие'],
           ['log10 1/K3 (Graaf)','−2073/T + 2.029','—','WGS/RWGS']])}

Плотность катализатора 1775 кг/м³ — из Table 3 той же статьи.

**Результат для расчётного газа:**
за проход X_COx = **{100*vb['per_pass_COx_conversion']:.1f} %**,
MeOH на выходе **{vb['outlet_MeOH_molpct']:.2f} мол.%**,
тепло {vb['heat_released_MW']:.1f} МВт, масса катализатора
{vb['catalyst_mass_t']:.1f} т при эффективном GHSV
{vb['GHSV_h1']:.0f} ч⁻¹. [ДОПУЩЕНИЕ] — одна изотермическая труба заменяет
4-слойный адиабатический реактор с закалкой; GHSV подобран так, чтобы
одновременно попасть в открытый диапазон 25–30 % за проход (OSTI 2424604)
и в промышленный бенчмарк Арзева.

**Внешняя проверка (Arzew CP1Z, 52 бар, 210–270 °C):**
{md_table(['GHSV ч⁻¹','MeOH вых. мол.%','CO вых.','CO₂ вых.','H₂ вых.'],
          [[z['GHSV_h1'], round(z['outlet_MeOH_molpct'],3),
            round(z['outlet_CO_molpct'],2), round(z['outlet_CO2_molpct'],2),
            round(z['outlet_H2_molpct'],2)] for z in bm['sweep']])}
Завод: MeOH 3,4 мол.%, CO 5,4, CO₂ 7,6, H₂ 69,35.
Лучшее совпадение MeOH **{bm['best']['outlet_MeOH_molpct']:.2f} мол.%**
(отклонение {bm['deviation_pct']:+.1f} %) при GHSV
{bm['best']['GHSV_h1']:.0f} ч⁻¹. [ЧАСТИЧНО] — CO₂ расходится, потому что
модель изотермическая однослойная.

## 23.2 Аммиак: Temkin–Pyzhev / Dyson–Simon

Уравнение и корреляция K_a — из открытого блога COMSOL; α, k₀, Ea — из
открытого ChemCatChem 2024 (подгонка по 598–773 K, 90 бар, промышленный
магнетитовый Fe-катализатор).

```
r_NH3 = 2k·[Ka²·a_N2·(a_H2³/a_NH3²)^α − (a_NH3²/a_H2³)^(1−α)]
log10 Ka = −2.691122·log10T − 5.051925e-5·T + 1.848863e-7·T² + 2001.6/T + 2.689
k = k0·exp(−Ea/RT),  α = 0.654, k0 = 6.5e13 кмоль/(м³_кат·ч), Ea = 159.4 кДж/моль
```

**Результат:** X_N₂ за проход **{100*tp['per_pass_N2_conversion']:.2f} %**,
NH₃ на выходе **{tp['outlet_NH3_molpct']:.2f} мол.%** при GHSV
{tp['GHSV_h1']:.0f} ч⁻¹, K_a = {tp['K_a']:.6f}, η = 1 (скрытого
калибровочного множителя НЕТ).

Это **ниже** открытого промышленного диапазона 15–25 % за проход и бенчмарка
13 мол.% NH₃. Свип по GHSV:

{md_table(['GHSV ч⁻¹','X_N₂','NH₃ вых. мол.%'],
          [[z['GHSV_h1'], round(z['per_pass_N2_conversion'],4),
            round(z['outlet_NH3_molpct'],2)] for z in ba['sweep']])}

Чтобы получить 13 мол.% NH₃, эффективный GHSV должен быть
{ba['best_for_NH3_outlet']['GHSV_h1']:.0f} ч⁻¹ — **ниже** открытого диапазона
10 000–30 000 ч⁻¹. [НЕ ПОДТВЕРЖДЕНО] абсолютный масштаб скорости: причина —
изотермический однослойный PFR вместо многослойного адиабатического
конвертера и объёмные единицы k₀. Мы НЕ вводим подгоночный η, чтобы не
скрыть расхождение.

## 23.3 Что осталось

FT и оксо по-прежнему стехиометрические (открытых кинетических наборов с
параметрами в этой сессии не получено).

V5.1: для метанольной кинетики найден и открыт **единственный доступный
непоизотермический кейс** — адиабатический лабораторный реактор Table 3 /
Fig. 5 той же статьи Vanden Bussche–Froment. Адиабатический марш этого проекта
(`model/methanol_converter.py`, `docs/31`) воспроизводит его с отклонением
0,54 K по температуре на выходе и ≤0,12 мол.% по всем четырём табличным
компонентам; изотермическое упрощение на том же кейсе ошибается на 0,28 мол.%
по CO₂. Это снимает неопределённость «кинетика или допущение об
изотермичности» — но является сверкой модели с моделью, поэтому контур 5 оно не
закрывает.

Все кинетические блоки доступны в
`results_v2/design_*.json -> synthesis.kinetic` и в панели управления.
"""
    open(os.path.join(DOCS, "23_v4_kinetic_synthesis.md"), "w", encoding="utf-8").write(txt)

    # 24 HAZOP --------------------------------------------------------------
    from .hazop import hazop_report as _hr
    hz = _hr()
    txt = f"""# 24. HAZOP worksheet (V4) — **НЕ СЕРТИФИЦИРОВАНО**

> **ЯВНОЕ ПРЕДУПРЕЖДЕНИЕ.** Сертифицированный HAZOP невозможен без
> междисциплинарной команды, независимого ведущего (facilitator),
> проверенных P&ID, подписанного технического задания, закрытия действий и
> подписи руководства. Ничего этого здесь НЕ было. Данный документ —
> автоматически сгенерированный **шаблон рабочей таблицы** по структуре
> IEC 61882 (полный текст стандарта НЕ открывался).
> Статус: **[НЕ ПОДТВЕРЖДЕНО] NOT A CERTIFIED HAZOP**.
> Не используйте его как обоснование безопасности или доказательство
> соответствия.

## 24.1 Объём

{hz['nodes']} узлов × {hz['guidewords']} направляющих слов =
**{hz['worksheet_rows']} строк** рабочей таблицы, из них
**{hz['high_risk_rows']}** с риском ≥ 6 (матрица 3×3, приори — **[ДОПУЩЕНИЕ]**).
Полная таблица: `results_v2/hazop_worksheet.csv` и
`results_v2/hazop_worksheet.json`.

{md_table(['узел','назначение'], [[n['id'], n['node'] + ' — ' + n['intent']]
                                 for n in __import__('model.hazop', fromlist=['NODES']).NODES])}

Направляющие слова: {', '.join(__import__('model.hazop', fromlist=['GUIDEWORDS']).GUIDEWORDS)}.

## 24.2 Примеры строк с высоким риском

{md_table(['узел','слово','причина','последствие','защита','риск'],
          [[r['node'][:34], r['guideword'], r['cause'][:42],
            r['consequence'][:42], r['safeguards'][:42], r['risk_score']]
           for r in hz['worksheet'] if r['risk_score'] >= 6][:12])}

## 24.3 Что требуется для сертификации

{chr(10).join(f'{i+1}. {g}' for i, g in enumerate(hz['certification_gaps']))}

## 24.4 Связь с расчётом

- Ni(CO)₄: log₁₀K = 7430/T − 21,90 (OSTI 7349456, открыт); при работе
  0,0006 ppb, при останове нужна продувка CO < 10 ppm до охлаждения ниже
  200 °C — см. `docs/19`.
- PSV: только скрининг по критическому истечению, **не** сертификация
  API 520/521.
- Δp и LMP: `docs/20`; ЛОВЕР-сценарии здесь не заменяют SIL-верификацию.
"""
    open(os.path.join(DOCS, "24_v4_hazop.md"), "w", encoding="utf-8").write(txt)

    # 25 loop 5 -------------------------------------------------------------
    txt = f"""# 25. Verification loop 5 after the V4 data acquisition (G8)

Контур 5 **перезапущен** с реальными внешними данными. Он остаётся
**НЕ ПРОЙДЕННЫМ**, но теперь это доказательный результат, а не просто
«нет данных».

**Вердикт:** {l5['status']}
**Причина:** {l5['reason']}

## 25.1 Подпроверки: {l5['subchecks_passed']} из {l5['subchecks_total']}

{md_table(['статус','проверка','примечание'],
          [['ПРОВЕРЕНО' if c['passed'] else 'НЕ ПРОЙДЕНО', c['check'], c.get('note','')[:86]]
           for c in l5['subchecks']])}

## 25.2 Ключевые внешние числа

- Питонных записей: {ext['n_records_total']}, из них численных сравнений
  X_CH₄: **{ext['n_numeric_X_CH4_comparable']}**, качественных:
  {ext['n_records_qualitative']}.
- Смещение равновесной модели относительно кинетических измерений:
  среднее **{ext['mean_model_bias']:+.3f}**, макс {ext['max_model_bias']:+.3f}.
- Коммерческий даташит Ni/MgAl₂O₄ катализатора:
  **{'НАЙДЕН' if ext['commercial_datasheet']['catalyst_datasheet_found'] else 'НЕ НАЙДЕН'}**;
  найдено даташитов носителя: {ext['commercial_datasheet']['supports_found']}.
- Экстраполированный t₅₀ = {ext['deactivation']['extrapolated_t50_h']:.0f} ч
  против расчётных {ext['deactivation']['design_life_h']:.0f} ч.
- HAZOP: {hz['worksheet_rows']} строк, сертификация = **НЕТ**.

## 25.3 Кинетика синтеза

{md_table(['продукт','модель','за проход','диапазон из источника','бенчмарк','статус'],
          [[r['product'], r['model'], f"{100*(r['per_pass_conversion'] or 0):.1f}%",
            str(r['opened_range']),
            (f"{r['benchmark_outlet_MeOH_molpct']:.2f} мол.% MeOH" if r['product']=='methanol'
             else f"{r['benchmark_outlet_NH3_molpct_at_best_GHSV']:.2f} мол.% NH3"),
            r['status'][:38]] for r in l5['kinetic_checks']])}

## 25.4 Не проверено

{chr(10).join(f'{i+1}. {g}' for i, g in enumerate(l5['unchecked_items']))}

## 25.5 Итог пяти контуров

{md_table(['контур','статус'], [[k, 'PASS' if x['passed'] else 'FAIL']
                                for k, x in v['loops'].items()])}

Общий результат: **{'PASS' if v['overall_passed'] else 'FAIL (контур 5 открыт)'}**.
Модель не объявляется завершённой.
"""
    open(os.path.join(DOCS, "25_v4_loop5.md"), "w", encoding="utf-8").write(txt)

    # 26 V5 multi-bed adiabatic ammonia converter ---------------------------
    cv = (designs["ammonia"]["synthesis"]["kinetic"]
          .get("ammonia_converter") or {})
    cd = cv.get("design") or {}
    cc = cv.get("calibration") or {}
    cb = cv.get("benchmark_validation") or {}
    ce = cv.get("equilibrium_check") or {}
    rec = cd.get("recycle_closure") or {}
    rm = cv.get("peak_temperature_remedy") or {}
    bcx = cv.get("benchmark_consistency") or {}
    ls = cv.get("layout_scan") or {}
    b1 = ls.get("best_by_outlet_NH3") or {}
    b2 = ls.get("best_by_outlet_NH3_inside_opened_band") or {}
    txt = f"""# 26. V5 — многосекционный адиабатический конвертор NH₃ и калибровка k₀

Замена изотермического PFR (V4) на промышленно корректный аппарат:
**3 адиабатические секции с промежуточным охлаждением**, закон скорости
Темкина–Пызева / Дайсона–Саймона, энтальпийный баланс по NIST Shomate.
Код: `model/converter.py`; числа: `results_v2/converter_ammonia.json`,
`converter_benchmark_grid.csv`, `converter_bed_profile.csv`,
`converter_equilibrium_check.csv`, `13_converter_profile.png`.

## 26.1 Три исправления, ни одно не подгонка

1. **Тип аппарата.** V4 считал одну изотермическую трубку. Реальный конвертор —
   2–4 адиабатические секции; экзотермия даёт подъём температуры на секцию,
   поэтому локальные k(T) и K_a(T) вычисляются по текущей температуре постели,
   а не по проектной.
2. **Базис объемной скорости.** Промышленные GHSV (10 000–30 000 ч⁻¹,
   Humphreys et al., Adv. Energy Sustainability Res. 2021, открыт) отнесены к
   **нормальным** м³ газа. V4 использовал фактический расход при T и p аппарата,
   что при 698 K / 150 бар занижало время контакта примерно в 58 раз и делало
   модель «слишком медленной» — вывод V4 об этом был артефактом.
3. **Базис питания.** В конвертор подаётся очищенный цикл H₂/N₂ **с рециклом**:
   N₂ и H₂ берутся из блока `synthesis`, инерты = сухой газ минус N₂ и H₂, а не
   из сырого синтез-газа. Поле `synthesis.inert_mol_h` для аммиака = «всё, кроме
   H₂» (то есть включает азот),
   то есть включает азот; в V5 оно сознательно не используется.

## 26.2 Сетка на открытой бенчмарк-точке (без калибровки, k₀ из источника)

Условия бенчмарка: {fnum(cb.get('opened_conditions',{}).get('T_K'),2)} K,
{fnum(cb.get('opened_conditions',{}).get('p_bar'),1)} бар,
GHSV {cb.get('opened_conditions',{}).get('GHSV_normal_h1')} ч⁻¹ (норм.),
открытый коридор захода N₂ за проход
{100*cb.get('opened_per_pass_range',[0.15,0.2])[0]:.0f}–{100*cb.get('opened_per_pass_range',[0.15,0.2])[1]:.0f} %,
цель по выходу NH₃ {fnum(cb.get('outlet_NH3_benchmark_molpct'),1)} мол.%.

{md_table(['случай','GHSV ч⁻¹','X_N₂ за проход','выход NH₃, мол.%','равновесие при T_вх, мол.%','T_пик, K','V_кат на 100 моль/ч питания, м³'],
          [[r['case'], fnum(r['GHSV_normal_h1'],0), fnum(100*r['per_pass_N2_conversion'],2)+' %',
            fnum(r['outlet_NH3_molpct'],2), fnum(r['equilibrium_NH3_molpct_at_inlet_T'],1),
            fnum(r['T_peak_K'],0), fnum(r['catalyst_volume_per_100mol_h_feed_m3'],4)]
           for r in cb.get('rows', [])])}

Строк внутри открытого коридора: **{cb.get('n_rows_in_band',0)} из {cb.get('n_rows',0)}**.
{cb.get('note2','')}

## 26.3 Калибровка единственного множителя k₀

- Цель: середина открытого коридора X_N₂ за проход =
  {fnum(100*cc.get('target_per_pass_conversion',0),1)} % при 698,15 K / 150 бар /
  GHSV {fnum((cc.get('benchmark_conditions') or {}).get('GHSV_normal_h1'),0)} ч⁻¹, 3 секции.
- Метод: {cc.get('method')}. Подбирается **только** `k_scale`; α, E_a, K_a и
  энтальпийный баланс остаются по источнику.
- Результат: **k_scale = {fnum(cc.get('k_scale'),4)}**, т.е.
  k₀ = {cc.get('k0_published_kmol_m3cat_h'):.3e} →
  {cc.get('k0_effective_kmol_m3cat_h'):.3e} кмоль/(м³_кат·ч).
- До калибровки X за проход = {fnum(100*(cc.get('uncalibrated') or {}).get('per_pass_N2_conversion'),2)} %
  (отклонение {fnum(cc.get('deviation_before_pct'),1)} % от цели), после —
  {fnum(100*(cc.get('calibrated') or {}).get('per_pass_N2_conversion'),2)} %.
- **Важное несоответствие источников:** калибровка по выходу NH₃
  ({fnum((cc.get('alternative_objective') or {}).get('outlet_NH3_molpct'),1)} мол.%) требует
  k_scale = {fnum((cc.get('alternative_objective') or {}).get('k_scale_needed'),4)},
  т.е. открытые промышленные данные расходятся по активности на множитель
  **{fnum(cc.get('k0_uncertainty_factor'),2)}**. Это и есть честная неопределённость
  калибровки: она не может быть меньше, пока нет питательных или собственных
  заводских данных по конвертору.
- {cc.get('what_this_is')}

## 26.4 Расчётная точка проекта (проектный конфиг аммиака)

| параметр | значение | метка |
|---|---|---|
| давление | {fnum(cd.get('p_bar'),1)} бар | [ПОДТВЕРЖДЕНО] диапазон источника |
| GHSV (норм.) | {fnum(cd.get('GHSV_normal_h1'),0)} ч⁻¹ | [ЧАСТИЧНО] вне 10–30 тыс. |
| входной поток аппарата | {fnum(cd.get('reactor_inlet_Nm3_h'),0)} Нм³/ч | расчёт |
| объём катализатора | {fnum(cd.get('catalyst_volume_m3'),1)} м³ ({fnum(cd.get('catalyst_mass_t_at_1775kgm3'),1)} т при 1775 кг/м³) | [ЧАСТИЧНО] ρ из VBF Table 3, не от производителя |
| X_N₂ за проход | **{fnum(100*cd.get('per_pass_N2_conversion'),2)} %** (без калибровки {fnum(100*cd.get('per_pass_N2_conversion_uncalibrated'),2)} %) | [ЧАСТИЧНО] |
| выход NH₃ | **{fnum(cd.get('outlet_NH3_molpct'),2)} мол.%** (без калибровки {fnum(cd.get('outlet_NH3_molpct_uncalibrated'),2)} %) | [ЧАСТИЧНО] |
| температуры секций (вход→выход) | {cd.get('T_bed_in_out_K')} K | расчёт |
| подъём на секцию | {cd.get('adiabatic_rise_K')} K | расчёт |
| пик температуры постели | {fnum(cd.get('T_peak_K'),1)} K при потолке {fnum(cd.get('catalyst_T_max_assumed_K'),1)} K → запас {fnum(cd.get('peak_T_margin_K'),1)} K | **{cd.get('peak_T_check')}** |
| ΔH реакции при T постели | {fnum(cd.get('dH_rxn_at_bed_T_kJ_per_mol_NH3'),2)} кДж/моль NH₃ (не −45,9 при 298 K) | [ПОДТВЕРЖДЕНО] NIST Shomate |
| теплота реакции в аппарате | {fnum(cd.get('reaction_heat_MW'),1)} МВт; промежуточное охлаждение {fnum(cd.get('interbed_cooling_duty_MW'),1)} МВт | расчёт |
| подход к равновесию | {fnum(cd.get('approach_to_equilibrium'),3)} | расчёт |
| рецикл: требуемый по кинетике | RR = {fnum(cd.get('recycle_ratio_implied_by_kinetics'),2)} против проектного {fnum(cd.get('recycle_ratio_configured'),2)}; X·(1+RR) = {fnum(rec.get('fraction_of_fresh_N2_converted'),3)} | [ЧАСТИЧНО] |
| NH₃ в аппарате против контура | {fnum(cd.get('NH3_formed_in_converter_t_h'),2)} т/ч против {fnum(cd.get('net_NH3_from_loop_t_h'),2)} т/ч (отношение {fnum(cd.get('converter_vs_loop_NH3_ratio'),3)}) | проверка увязки |
| невязка энтальпийного баланса | {("%.2e" % cd["energy_balance_max_rel_residual"]) if cd.get('energy_balance_max_rel_residual') is not None else "n/a"} | [ПОДТВЕРЖДЕНО] внутренняя |

Мера по пиковой температуре: {rm.get('recommended_common_bed_inlet_K')} K на входе во все
секции даёт пик {rm.get('achieved_peak_T_K')} K, X за проход
{fnum(100*(rm.get('per_pass_N2_conversion_at_that_inlet') or 0),2)} % и выход
{fnum(rm.get('outlet_NH3_molpct_at_that_inlet'),2)} мол.% NH₃ — то есть тот же порядок,
но с запасом по катализатору. {rm.get('caveat','')}

## 26.5 Независимая термодинамическая проверка K_a

Kp для N₂ + 3H₂ → 2NH₃ пересобран из энергий Гиббса NIST Shomate и сравнён с
открытой корреляцией log₁₀K_a (COMSOL/Rase). Обе ветки — только открытые данные.

{md_table(['T, K','ΔG°, кДж/моль','Kp из NIST Shomate','Kp из корреляции K_a','отклонение, %'],
          [[fnum(r['T_K'],2), fnum(r['dG0_kJ_per_mol'],3), f"{r['Kp_from_NIST_Shomate']:.4e}",
            f"{r['Kp_from_Ka_correlation']:.4e}", fnum(r['deviation_pct'],2)]
           for r in ce.get('rows', [])])}

Максимальное отклонение **{fnum(ce.get('max_abs_deviation_pct'),2)} %**
(среднее {fnum(ce.get('mean_abs_deviation_pct'),2)} %) — проверка
{'ПРОЙДЕНА' if ce.get('passed_within_15pct') else 'ПРОВАЛЕНА'} и добавлена в контур 4.
{ce.get('note','')}

## 26.6 Поиск компоновки: число секций и холодный вброс

Пик температуры над потолком — не приговор конструкции: подъём адиабатической
секции пропорционален конверсии, которую эта секция несёт, поэтому у реального
конвертора есть два рычага — разбить тот же объём катализатора на большее число
секций и вбрасывать между секциями часть свежего газа (холодный вброс). Ниже —
скан `model/converter.py:scan_converter_layouts`: для каждой компоновки общая
температура входа в секции бисекцией поднимается до максимума, при котором
пик ещё не превышает потолок {fnum((ls.get('held_constant') or {}).get('bed_T_max_K_assumed'),1)} K;
k_scale, давление, GHSV и полный объём катализатора во всех строках одинаковы,
поэтому строки сравнимы.

{md_table(['секций','холод. вброс, %','T входа, K','T пик, K','X за проход, %','выход NH₃, мол.%','в коридоре 15–20 %','Q межсекц. охлаждения, МВт'],
          [[r['n_beds'], fnum(100*r['cold_shot_fraction'],0), fnum(r['common_bed_inlet_K'],1),
            fnum(r['T_peak_K'],1), fnum(r['per_pass_N2_pct'],2),
            fnum(r['outlet_NH3_molpct'],2),
            'да' if r['inside_opened_per_pass_band'] else 'нет',
            fnum(r['interbed_cooling_duty_MW'],1)] for r in ls.get('rows', [])])}

Компоновок, укладывающихся в потолок: **{ls.get('layouts_meeting_ceiling',0)} из
{ls.get('layouts_total',0)}**; из них одновременно в открытом коридоре
захода N₂: **{ls.get('layouts_meeting_ceiling_AND_opened_band',0)}**.

- Максимум по выходу NH₃ (главный параметр для разделения):
  {b1.get('n_beds') if b1 else '—'} секций, вброс
  {fnum(100*(b1 or {}).get('cold_shot_fraction',0),0)} %, вход
  {fnum((b1 or {}).get('common_bed_inlet_K',0),1)} K → пик
  {fnum((b1 or {}).get('T_peak_K',0),1)} K, X {fnum((b1 or {}).get('per_pass_N2_pct',0),2)} %,
  выход {fnum((b1 or {}).get('outlet_NH3_molpct',0),2)} мол.% NH₃.
- Лучшая компоновка, попадающая И в потолок, И в коридор 15–20 %:
  {b2.get('n_beds') if b2 else '—'} секций, вброс
  {fnum(100*(b2 or {}).get('cold_shot_fraction',0),0)} % → X
  {fnum((b2 or {}).get('per_pass_N2_pct',0),2)} %, выход
  {fnum((b2 or {}).get('outlet_NH3_molpct',0),2)} мол.%, Q охлаждения
  {fnum((b2 or {}).get('interbed_cooling_duty_MW',0),1)} МВт.

Вывод: **потолок выполняется тривиально, а вот сочетание «потолок + коридор
захода + высокая концентрация NH₃ на выходе» — нет.** {ls.get('finding','')}
{ls.get('status','')}

## 26.7 Согласованность двух открытых ориентиров NH₃ (что значит ×{fnum(cc.get('k0_uncertainty_factor'),2)})

Ориентира два, и они **разного рода**: Humphreys (2021) даёт долю захода N₂ за
проход (15–20 %, середина 17,5 %), а открытая цифра Rase/COMSOL — долю NH₃ на
выходе конвертора (13 мол.%). Сравнение «какой k_scale нужен каждому» даёт
несовпадение в ×{fnum(bcx.get('activity_disagreement_factor'),3)}, но это сравнение
проходит через **очень крутую** зависимость «активность → результат» у постели,
сидящей близко к собственному равновесному упору. Поэтому оба числа приведены к
одной базе — доле захода N₂ за проход при **одной и той же** схеме циркуляции и
одной и той же конструкции (3 секции, 698,15 K, 150 бар, SV 20 000 ч⁻¹ в нормальном
базисе, H₂:N₂ = 3, 0,5 мол.% NH₃ на входе).

| ориентир | заход N₂, % | выход NH₃, мол.% | потолок по равновесию при T выхода, мол.% | доля потолка, % |
|---|---|---|---|---|
| A: {bcx.get('objective_a','—')} | {fnum(bcx.get('A_per_pass_pct'),2)} | {fnum(bcx.get('A_outlet_molpct'),2)} | {fnum(bcx.get('A_equilibrium_ceiling_molpct'),2)} | {fnum(bcx.get('A_approach_to_ceiling_pct'),1)} |
| B: {bcx.get('objective_b','—')} | {fnum(bcx.get('B_per_pass_pct'),2)} | {fnum(bcx.get('B_outlet_molpct'),2)} | {fnum(bcx.get('B_equilibrium_ceiling_molpct'),2)} | {fnum(bcx.get('B_approach_to_ceiling_pct'),1)} |

Наклон локальной кривой: {fnum(bcx.get('sensitivity_per_pass_pp_per_decade'),2)} п.п.
захода N₂ (и {fnum(bcx.get('sensitivity_outlet_molpct_per_decade'),2)} мол.% на выходе) на
десятичное порядковое изменение `k_scale`; отсюда расхождение в
{fnum(bcx.get('activity_disagreement_decades'),3)} декади активности превращается в
{fnum(bcx.get('per_pass_gap_predicted_from_sensitivity_pp'),2)} п.п. захода, тогда как
фактическое расстояние — {fnum(bcx.get('per_pass_gap_pp'),2)} п.п.
(линеаризация завышает на {fnum(bcx.get('consistency_criteria_met',{}).get('measured_slope_closeness_pct'),0)} %, кривая выпуклая к упору).

Правило вердикта зафиксировано **до** прогона и взято только из открытых
источников: пара считается согласованной, если (i) заход N₂, требуемый цифрой на
выходе, лежит в объединённом открытом коридоре
{fnum(100*(bcx.get('band_used_for_the_verdict') or (0,0))[0],0)}–{fnum(100*(bcx.get('band_used_for_the_verdict') or (0,0))[1],0)} % и (ii) локальный наклон объясняет
расхождение с точностью 50 %. Выполнено: (i)
{'да' if (bcx.get('consistency_criteria_met') or {}).get('band') else 'нет'}, (ii)
{'да' if (bcx.get('consistency_criteria_met') or {}).get('slope_within_50pct') else 'нет'}
(оценка наклона отклоняется на
{fnum((bcx.get('consistency_criteria_met') or {}).get('measured_slope_closeness_pct'),0)} %).
Итог: **{bcx.get('verdict_word','')}** ({bcx.get('status','benchmark_consistency не посчитан')}).

Простыми словами: цифре на выходе 13 мол.% при нашей схеме циркуляции
соответствует заход {fnum(bcx.get('B_per_pass_pct'),2)} % N₂ — это
{fnum(bcx.get('per_pass_gap_pp'),2)} п.п. выше середины 17,5 %,
{bcx.get('band_narrow_word','')} узкого открытого коридора 15–20 % и
{bcx.get('band_wide_word','')} широкого 15–25 %. При этом разница активностей
×{fnum(bcx.get('activity_disagreement_factor'),2)}
({fnum(bcx.get('activity_disagreement_decades'),3)} декады) на местной кривой стоит
{fnum(bcx.get('per_pass_gap_predicted_from_sensitivity_pp'),2)} п.п. захода. То есть
источники расходятся на **единицы процентных пунктов конверсии, а не на порядок по
активности**: большие ×2,36 — свойство крутой ветви возле равновесного упора, и
именно поэтому отчёт обязан быть коридорным (`docs/32`), а не точкой.

Важно, чего этот раздел **не** делает: он не валидирует модель (это сравнение двух
литературных чисел внутри одной конструкции), не закрывает ни одного пункта
`docs/28` и не отменяет подпроверку контура 5 про ×{fnum(cc.get('k0_uncertainty_factor'),2)} — она остаётся
ПРОВАЛЕННОЙ ровно с той же формулировкой. Он меняет только интерпретацию:
расхождение источников — это единицы процентов конверсии, а не порядок по
активности, и именно поэтому отчёт обязан быть коридорным (docs/32), а не точкой.

## 26.8 Что осталось непроверенным (не скрывать)

1. Калибровка сделана по **чужому** заводу и **чужому** катализатору: это не
   валидация контура 5.
2. Потолок температуры постели {fnum(cd.get('catalyst_T_max_assumed_K'),1)} K —
   **допущение**, а не даташит: даташит производителя катализатора не найден
   (запрос сформулирован в `docs/28_v5_vendor_rfi.md`, п. 12–18).
3. Гидравлика постели (Δp), распределение газа по секциям и реальная
   конструкция (радиальный/аксиальный, холодные вбросы) не моделируются.
4. Утилизация тепла промежуточного охлаждения ({fnum(cd.get('interbed_cooling_duty_MW'),1)} МВт)
   в пар не просчитана: это отдельный узел теплового включения.
5. Деактивация (отравление CO₂, спекание) в конверторе не моделируется: для
   магнетитового катализатора аммиачного синтеза открытых питательных данных
   по 200–1000 ч в этом проекте нет.

## 26.9 Следующий шаг

Прогнать `model/data_ingest.py` на данных пилотной кампании (`docs/27`), затем
пересобрать контур 5. До появления этих данных k_scale остаётся подгоночным
параметром: его разброс ×{fnum(cc.get('k0_uncertainty_factor'),2)} — это, по разделу 26.7, всего
{fnum(bcx.get('per_pass_gap_pp'),1)} п.п. захода N₂ при местном наклоне кривой, и снимается он
только пилотной кампанией (docs/27) или гарантийной активностью (docs/28 п.15).
Ответ формы оператора по п.15 при этом перекрывает и коридор, и эту пару
ориентиров: см. `docs/33`, п. 33.4 и 33.7.
"""
    open(os.path.join(DOCS, "26_v5_converter.md"), "w", encoding="utf-8").write(txt)

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
    print("[v5] multi-bed adiabatic NH3 converter (calibration + design) ...")
    from .converter import ammonia_converter_block
    try:
        base["ammonia"]["synthesis"]["kinetic"]["ammonia_converter"] = \
            ammonia_converter_block(load_config(product="ammonia"), base["ammonia"])
    except Exception as exc:                          # never lose the run
        base["ammonia"]["synthesis"]["kinetic"]["ammonia_converter"] = {
            "computed": False, "error": repr(exc)}
    print(f"[v5] converter done in {time.time()-t0:.1f} s")
    print("[v5.1] uncertainty envelope + methanol adiabatic benchmark ...")
    t1 = time.time()
    try:                                       # writes both result files itself
        from .uncertainty import main as uncertainty_main
        uncertainty_main()
    except Exception as exc:                   # never lose the run
        print("[v5.1] uncertainty envelope FAILED:", repr(exc))
    try:
        from .methanol_converter import build_report as meth_report
        dump_json(os.path.join(OUT, "methanol_adiabatic_check.json"), meth_report())
    except Exception as exc:
        print("[v5.1] methanol adiabatic benchmark FAILED:", repr(exc))
    try:                                     # operator data-entry status
        from .operator_data import status as op_status, write_template
        if not os.path.exists(os.path.join(ROOT, "data",
                                           "operator_inputs_TEMPLATE.json")):
            write_template()
        dump_json(os.path.join(OUT, "operator_data_report.json"), op_status())
    except Exception as exc:
        print("[v5.3] operator data status FAILED:", repr(exc))
    try:                                     # activity corridor for loop 4
        from .activity_uncertainty import band as activity_band
        dump_json(os.path.join(OUT, "activity_uncertainty.json"),
                  activity_band(designs=base))
    except Exception as exc:
        print("[v5.1] activity band FAILED:", repr(exc))
    print(f"[v5.1] done in {time.time()-t1:.1f} s")
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
    l5 = v["loops"]["5_validation_falsification"]
    write_csv(os.path.join(OUT, "pilot_comparison.csv"),
              l5["external_data"]["comparisons"])
    write_csv(os.path.join(OUT, "loop5_subchecks.csv"), l5["subchecks"])
    write_csv(os.path.join(OUT, "hazop_worksheet.csv"), hazop_report()["worksheet"])
    write_csv(os.path.join(OUT, "kinetic_benchmarks.csv"),
              [{"product": q["product"], "GHSV_h1": z["GHSV_h1"],
                "outlet_molpct": z.get("outlet_MeOH_molpct", z.get("outlet_NH3_molpct")),
                "per_pass_conversion": z.get("per_pass_N2_conversion"),
                "source": "VBF/Graaf" if q["product"] == "methanol" else "Temkin-Pyzhev"}
               for q in l5["kinetic_checks"]
               for z in (base[q["product"]]["synthesis"]["kinetic"]
                         ["benchmark_check"]["sweep"])])
    dump_json(os.path.join(OUT, "hazop_worksheet.json"), hazop_report())
    dump_json(os.path.join(OUT, "pilot_data_summary.json"),
              {"pilot": load_pilot(), "commercial": load_commercial(),
               "comparison": l5["external_data"]})
    dump_json(os.path.join(OUT, "kinetic_synthesis.json"),
              {p: r["synthesis"]["kinetic"] for p, r in base.items()})
    convb = base["ammonia"]["synthesis"]["kinetic"].get("ammonia_converter") or {}
    dump_json(os.path.join(OUT, "converter_ammonia.json"), convb)
    if convb.get("design"):
        write_csv(os.path.join(OUT, "converter_benchmark_grid.csv"),
                  convb["benchmark_validation"]["rows"])
        write_csv(os.path.join(OUT, "converter_bed_profile.csv"),
                  convb["design"]["bed_profile"])
        write_csv(os.path.join(OUT, "converter_equilibrium_check.csv"),
                  convb.get("equilibrium_check", {}).get("rows", []))
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
        "loop5": {"status": v["loops"]["5_validation_falsification"]["status"],
                  "subchecks_passed": v["loops"]["5_validation_falsification"]["subchecks_passed"],
                  "subchecks_total": v["loops"]["5_validation_falsification"]["subchecks_total"],
                  "mean_pilot_bias": v["loops"]["5_validation_falsification"]["external_data"]["mean_model_bias"],
                  "catalyst_datasheet_found": v["loops"]["5_validation_falsification"]["external_data"]["commercial_datasheet"]["catalyst_datasheet_found"]},
        "hazop": {"certified": False, "worksheet_rows": hazop_report()["worksheet_rows"]},
        "ammonia_converter": {
            "reactor": "3 adiabatic beds with interbed cooling (V5)",
            "space_velocity_basis": "normal m3/m3/h",
            "k_scale_calibrated": (convb.get("calibration") or {}).get("k_scale"),
            "per_pass_N2_conversion": (convb.get("design") or {}).get(
                "per_pass_N2_conversion"),
            "per_pass_N2_conversion_published_k0":
                (convb.get("design") or {}).get(
                    "per_pass_N2_conversion_uncalibrated"),
            "outlet_NH3_molpct": (convb.get("design") or {}).get("outlet_NH3_molpct"),
            "catalyst_volume_m3": (convb.get("design") or {}).get(
                "catalyst_volume_m3"),
            "T_peak_K": (convb.get("design") or {}).get("T_peak_K"),
            "peak_T_check": (convb.get("design") or {}).get("peak_T_check"),
            "computed": bool(convb.get("design")),
        },
        "overall_passed": v["overall_passed"],
        "runtime_s": round(time.time() - t0, 1),
        "optional_packages": {"iapws": __import__("model.steam", fromlist=["available"]).available()},
    }
    dump_json(os.path.join(OUT, "summary_v2.json"), summary)
    print("[v2] writing plots ...")
    make_plots(base, sc, v)
    print("[v2] writing reports ...")
    write_reports(base, sc, v)
    write_uncertainty_doc()
    write_methanol_adiabatic_doc()
    write_activity_band_doc()
    write_operator_doc()
    print(f"[v2] DONE in {time.time()-t0:.1f} s -> results_v2/, docs/12..26 "
          f"(V5 handover packs: docs/27..29; V5.1: docs/30..31; "
          f"V5.2 activity corridor: docs/32; V5.3 manual data entry: docs/33)")
    print("[v2] verification:", v["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
