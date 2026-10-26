"""V2 product-variant engine: 5 target products + regulation/tuning.

User requirement #1: methanol, Fischer-Tropsch, oxo, hydrogen, ammonia.
User requirement #2/#7: every knob is adjustable (see cases/config.json and
model/control.py); utilities are derived from the chosen climate.
User requirement #3/#4: both normal-volume definitions are computed.
User requirement #9: PR EOS + IAPWS-IF97 + C3+ feed + 1-D tube/creep.
User requirement #12: catalyst/Ni inventory via model/catalyst_inventory.py.

This module is self-contained: it does not silently reuse the v1 L1 flowsheet
because the v1 flowsheet was hard-wired to a methanol base case.
"""
from __future__ import annotations
import copy, json, math
from .config import load_config
from .routes import make_feed, feed_carbon
from .equilibrium import equilibrate, adiabatic_temperature, REACTIONS
from .thermo import (h0, h_liquid_water, stream_enthalpy, water_dew_point,
                     R_J, SPECIES, GASES)
from .steam import (saturation_pressure_bar, vaporisation_enthalpy_kJ_per_mol,
                    steam_generation_dh_kJ_per_mol, available as iapws_available)
from .catalyst_inventory import inventory as catalyst_inventory
from .equipment_v2 import size_reformer
from .equipment import size_whb, compressor_power, asu_power

M = {"H2O": 18.0153, "CH4": 16.0425, "C2H6": 30.0690, "C3H8": 44.0956,
     "CO": 28.0101, "CO2": 44.0095, "H2": 2.01588, "N2": 28.0134,
     "O2": 31.9988, "C_GR": 12.011, "NH3": 17.0305}
LHV_CH4_KJ_PER_MOL = 802.305   # NIST-derived full oxidation to gaseous H2O
CP_WATER_KJ_KG_K = 4.18


def _reaction_dh(stoich, T):
    return sum(nu * h0(sp, T) for sp, nu in stoich.items() if sp != "C_GR")


WGS = {"CO": -1.0, "H2O": -1.0, "CO2": 1.0, "H2": 1.0}
METH_CO = {"CO": -1.0, "H2": -3.0, "CH4": 1.0, "H2O": 1.0}
METH_CO2 = {"CO2": -1.0, "H2": -4.0, "CH4": 1.0, "H2O": 2.0}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _dry(n):
    return sum(v for k, v in n.items() if k not in ("H2O", "C_GR"))


def _y_dry(n):
    d = _dry(n)
    return {k: v / d for k, v in n.items() if k not in ("H2O", "C_GR")} if d else {}


def _H(n, T, p, cfg):
    return stream_enthalpy(n, T, p_bar=p, eos_kset=cfg.eos_kset,
                           use_iapws_steam=cfg.use_iapws)


def build_feed(cfg, knobs):
    df = cfg.F["dry_mol_fraction"]
    carbon = feed_carbon(df)
    f = make_feed(SC=knobs["SC"], O2C=knobs["O2C"], CO2C=knobs["CO2C"],
                  h2_recycle=cfg.F["H2_recycle_mol_per_100"], dry_feed=df)
    return f, carbon


def reformer(cfg, knobs, secondary_air=0.0):
    """Return reactor model. Isothermal fired reformer or adiabatic ATR/POX.

    For ammonia the primary reformer is isothermal and a secondary adiabatic
    reformer with air is appended (EPA AP-42 flowsheet, opened).
    """
    f, carbon = build_feed(cfg, knobs)
    p = knobs["p_bar"]
    eos = cfg.eos_kset
    proc = cfg.process
    units = []
    if cfg.P["route"] == "SMR_air_secondary":
        # Stage 1: primary reformer at fixed outlet T.
        r1 = equilibrate(f, proc["T_primary_out_K"], p,
                         approach_K=knobs["approach_K"], eos_kset=eos)
        H1 = _H(r1["n_mol"], proc["T_primary_out_K"], p, cfg)
        H0 = _H(f, proc["T_feed_preheat_K"], p, cfg)
        Q_primary = H1 - H0
        n2 = {k: v for k, v in r1["n_mol"].items() if v > 0}
        n2["C_GR"] = r1["n_mol"].get("C_GR", 0.0)
        # air: 21 mol% O2 / 79 mol% N2, plus Ar rolled into N2
        air = secondary_air * carbon
        n2["O2"] = n2.get("O2", 0.0) + 0.21 * air
        n2["N2"] = n2.get("N2", 0.0) + 0.79 * air
        # mixed inlet temperature from enthalpy balance (air at preheat)
        H_air = _H({"O2": 0.21 * air, "N2": 0.79 * air},
                   proc["T_secondary_air_preheat_K"], p, cfg)
        a = adiabatic_temperature(n2, p, T_in=298.15, eos_kset=eos)
        # recompute H_in explicitly at the correct mixed inlet T
        # (adiabatic_temperature's internal T_in is replaced by a secant solve)
        if a["converged"]:
            Tad = a["T_ad_K"]
            r2 = equilibrate(n2, Tad, p, approach_K=knobs["approach_K"],
                             eos_kset=eos)
            H_in_mixed = H1 + H_air
            H2 = _H(r2["n_mol"], Tad, p, cfg)
            # bisect T until H_out(T) = H_in_mixed
            lo, hi = 700.0, 2200.0
            for _ in range(45):
                mid = 0.5 * (lo + hi)
                rr = equilibrate(n2, mid, p, approach_K=knobs["approach_K"],
                                 eos_kset=eos)
                if _H(rr["n_mol"], mid, p, cfg) < H_in_mixed:
                    lo = mid
                else:
                    hi = mid
            Tad = 0.5 * (lo + hi)
            r2 = equilibrate(n2, Tad, p, approach_K=knobs["approach_K"],
                             eos_kset=eos)
            H2 = _H(r2["n_mol"], Tad, p, cfg)
            units.append({"unit": "R-101 primary reformer", "T_out_K": proc["T_primary_out_K"],
                          "Q_kJ_per_100mol_NG": Q_primary, "equilibrium": r1})
            units.append({"unit": "R-102 secondary reformer (adiabatic, air)",
                          "air_mol_per_100mol_NG": air,
                          "O2_mol_per_100mol_NG": 0.21 * air,
                          "N2_mol_per_100mol_NG": 0.79 * air,
                          "T_out_K": Tad, "Q_kJ_per_100mol_NG": 0.0,
                          "H_balance_error_pct": abs(H2 - H_in_mixed) / max(abs(H_in_mixed), 1) * 100,
                          "equilibrium": r2})
            return {"feed": f, "feed_secondary": n2, "carbon_per_100mol_NG": carbon,
                    "T_out_K": Tad, "p_bar": p, "equilibrium": r2,
                    "Q_primary_kJ_per_100mol_NG": Q_primary,
                    "Q_total_kJ_per_100mol_NG": Q_primary,
                    "H_in_kJ_per_100mol_NG": H0 + H_air,
                    "H_out_kJ_per_100mol_NG": H2,
                    "units": units, "air_mol_per_100mol_NG": air}
        return {"converged": False, "adiabatic": a}
    if knobs["O2C"] > 0.0:
        # Adiabatic ATR/POX: enthalpy-consistent inlet at the configured preheat
        a = adiabatic_temperature(f, p, T_in=proc["T_feed_preheat_K"],
                                  eos_kset=eos)
        if not a.get("converged"):
            return {"converged": False, "adiabatic": a}
        r = a["equilibrium"]
        Tad = a["T_ad_K"]
        units.append({"unit": "R-101 autothermal / partial-oxidation reformer",
                      "T_out_K": Tad, "Q_kJ_per_100mol_NG": 0.0, "equilibrium": r})
        return {"feed": f, "carbon_per_100mol_NG": carbon, "T_out_K": Tad,
                "p_bar": p, "equilibrium": r,
                "Q_total_kJ_per_100mol_NG": 0.0,
                "H_in_kJ_per_100mol_NG": a["H_in_kJ"],
                "H_out_kJ_per_100mol_NG": a["H_out_kJ"],
                "units": units, "adiabatic_solve": {"converged": True, "T_ad_K": Tad}}
    T = knobs["T_K"]
    r = equilibrate(f, T, p, approach_K=knobs["approach_K"], eos_kset=eos)
    H_in = _H(f, proc["T_feed_preheat_K"], p, cfg)
    H_out = _H(r["n_mol"], T, p, cfg)
    Q = H_out - H_in
    units.append({"unit": "R-101 fired tubular / CO2 reformer", "T_out_K": T,
                  "Q_kJ_per_100mol_NG": Q, "equilibrium": r})
    return {"feed": f, "carbon_per_100mol_NG": carbon, "T_out_K": T, "p_bar": p,
            "equilibrium": r, "Q_total_kJ_per_100mol_NG": Q,
            "H_in_kJ_per_100mol_NG": H_in, "H_out_kJ_per_100mol_NG": H_out,
            "units": units}


# --------------------------------------------------------------------------
# downstream units
# --------------------------------------------------------------------------
def wgs(n, conversion, T):
    n = dict(n)
    ext = conversion * n.get("CO", 0.0)
    ext = min(ext, n.get("CO", 0.0), n.get("H2O", 0.0))
    for sp, nu in WGS.items():
        n[sp] = n.get(sp, 0.0) + nu * ext
    return n, ext, -ext * _reaction_dh(WGS, T)


def methanation(n, residual_ppm, T):
    n = dict(n)
    tot = sum(v for k, v in n.items() if k not in ("H2O", "C_GR"))
    target = residual_ppm * 1e-6 * tot
    x_co = max(n.get("CO", 0.0) - target / 2.0, 0.0)
    x_co2 = max(n.get("CO2", 0.0) - target / 2.0, 0.0)
    for sp, nu in METH_CO.items():
        n[sp] = n.get(sp, 0.0) + nu * x_co
    for sp, nu in METH_CO2.items():
        n[sp] = n.get(sp, 0.0) + nu * x_co2
    Q = -(x_co * _reaction_dh(METH_CO, T) + x_co2 * _reaction_dh(METH_CO2, T))
    return n, {"CO": x_co, "CO2": x_co2}, Q


def co2_removal(n, recovery, residual_ppm, q_GJ_per_t):
    n = dict(n)
    dry = _dry(n)
    residual = residual_ppm * 1e-6 * dry
    x = min(recovery * n.get("CO2", 0.0), max(n.get("CO2", 0.0) - residual, 0.0))
    n["CO2"] = n.get("CO2", 0.0) - x
    t_co2 = x * M["CO2"] / 1e6       # g -> t (x is mol)
    return n, x, t_co2, q_GJ_per_t * t_co2 * 1e6   # kJ


PSA_SLIP = {"CO": 0.05, "CO2": 0.05, "N2": 0.5, "CH4": 1.0, "H2O": 0.0}


def psa(n, recovery, purity, slip=None):
    """H2 PSA split. Impurity slip weights model selective adsorption: CO/CO2
    are strongly adsorbed (small slip), N2 less, CH4 passes most easily.
    Weights are [ASSUMPTION]; the >99.9% purity and 85-90% recovery are from
    opened open-access studies (see cases/config.json product sources)."""
    n = dict(n)
    w = {**PSA_SLIP, **(slip or {})}
    h2_prod = recovery * n.get("H2", 0.0)
    product_total = h2_prod / purity
    impurity = product_total - h2_prod
    others = {k: v for k, v in n.items() if k != "H2" and k != "C_GR"}
    weighted = {k: v * w.get(k, 0.3) for k, v in others.items()}
    tot_w = sum(weighted.values())
    product = {"H2": h2_prod}
    for k, v in others.items():
        product[k] = impurity * weighted[k] / tot_w if tot_w else 0.0
    tail = {k: max(v - product.get(k, 0.0), 0.0) for k, v in n.items() if k != "H2"}
    tail["H2"] = n.get("H2", 0.0) - h2_prod
    return product, tail


def cool_and_condense(n, T_hot, T_cold, p, cfg, name="E-101"):
    n = dict(n)
    H_hot = _H(n, T_hot, p, cfg)
    psat = saturation_pressure_bar(T_cold) if cfg.use_iapws else None
    if psat is None:
        from .thermo import water_psat_bar
        psat = water_psat_bar(T_cold)
    y_sat = min(psat / p, 0.999)
    dry = _dry(n)
    n_h2o_vap = dry * y_sat / (1.0 - y_sat)
    condensed = max(n.get("H2O", 0.0) - n_h2o_vap, 0.0)
    n["H2O"] = n.get("H2O", 0.0) - condensed
    H_cold = stream_enthalpy(n, T_cold, liquid_water_mol=condensed, p_bar=p,
                             eos_kset=cfg.eos_kset, use_iapws_steam=cfg.use_iapws)
    tot_gas = sum(v for k, v in n.items() if k != "C_GR")
    dew = water_dew_point(p, n.get("H2O", 0.0) / max(tot_gas, 1e-12),
                          use_iapws=cfg.use_iapws)
    return n, condensed, {"unit": name, "T_in_K": T_hot, "T_out_K": T_cold,
                          "Q_removed_kJ_per_100mol_NG": H_hot - H_cold,
                          "condensed_water_mol_per_100mol_NG": condensed,
                          "dew_point_K": dew, "psat_bar": psat}


def downstream(cfg, knobs, rx):
    """Return final n (per 100 mol dry NG) and a full unit-operation list.

    The sequence is: WHB (steam credit) -> [WGS] -> syngas cooler ->
    [MDEA] -> [methanation] -> [PSA] -> final cooler -> [dryer/compressor].
    Each thermal step is a real enthalpy difference (PR + IF97 aware), so the
    material and energy balances close before any costing is done.
    """
    n = dict(rx["equilibrium"]["n_mol"])
    p = rx["p_bar"]
    proc = cfg.process
    D = cfg.P["downstream"]
    units = []
    withdrawals = {}

    def withdraw(species, amount):
        if amount:
            withdrawals[species] = withdrawals.get(species, 0.0) + amount

    T_cur = rx["T_out_K"]
    # 1. WHB: high-temperature heat recovery -> steam credit
    T_whb_out = (proc["WGS_HTS_T_K"] if "WGS" in D else proc["T_WHB_out_K"])
    n, water1, u = cool_and_condense(n, T_cur, T_whb_out, p, cfg,
                                     "E-101 WHB / syngas cooler")
    u["steam_credit"] = True
    units.append(u)
    withdraw("H2O", water1)
    T_cur = T_whb_out
    # 2. WGS (HTS+LTS lumped extent)
    if "WGS" in D:
        n, ext, Q = wgs(n, knobs["WGS_CO_conversion"], proc["WGS_HTS_T_K"])
        units.append({"unit": "R-201 WGS (HTS+LTS lumped)",
                      "T_K": proc["WGS_HTS_T_K"],
                      "CO_conversion": knobs["WGS_CO_conversion"],
                      "extent_mol_per_100mol_NG": ext,
                      "Q_removed_kJ_per_100mol_NG": Q,
                      "status": "[ASSUMPTION] conversion set by knob, not a kinetic model"})
        T_cur = proc["WGS_HTS_T_K"]
    # 3. syngas cooler ahead of MDEA / PSA (condenses most of the steam)
    if "CO2_removal" in D or "PSA" in D:
        T_abs = max(proc["MDEA_T_K"], cfg.climate_T_product_K)
        n, water_c, u = cool_and_condense(n, T_cur, T_abs, p, cfg,
                                          "E-301 absorber-feed cooler / separator")
        if T_abs > proc["MDEA_T_K"] + 0.01:
            u["status"] = ("[PARTIAL] absorber temperature raised to the climate "
                           "cooling limit; a chiller/trim cooler may be needed")
        units.append(u)
        withdraw("H2O", water_c)
        T_cur = T_abs
    # 4. CO2 removal (MDEA)
    if "CO2_removal" in D:
        n, x, tco2, Q = co2_removal(n, knobs["MDEA_CO2_recovery"], 50.0,
                                   knobs["MDEA_reboiler_GJ_per_tCO2"])
        units.append({"unit": "A-301 MDEA CO2 removal",
                      "T_K": proc["MDEA_T_K"],
                      "CO2_removed_mol_per_100mol_NG": x,
                      "CO2_captured_t_per_100mol_NG": tco2,
                      "reboiler_duty_kJ_per_100mol_NG": Q,
                      "reboiler_GJ_per_tCO2": knobs["MDEA_reboiler_GJ_per_tCO2"]})
        withdraw("CO2", x)
    # 5. methanation (requires reheat - heat integration NOT modelled)
    if "methanation" in D:
        n, ext, Q = methanation(n, knobs["methanator_residual_ppm"],
                                proc["methanator_T_K"])
        units.append({"unit": "R-401 methanator", "T_K": proc["methanator_T_K"],
                      "extent_mol_per_100mol_NG": ext,
                      "Q_removed_kJ_per_100mol_NG": Q,
                      "residual_CO_CO2_ppm": knobs["methanator_residual_ppm"],
                      "status": "[NOT MODELLED] reheat duty from 313 K to 573 K"})
        T_cur = proc["methanator_T_K"]
    # 6. PSA
    psa_result = None
    if "PSA" in D:
        product, tail = psa(n, knobs["PSA_H2_recovery"], cfg.P["target"],
                            {k.replace("PSA_", "").replace("_slip", ""): v
                             for k, v in knobs.items() if k.startswith("PSA_") and k.endswith("_slip")})
        psa_result = {"product": product, "tail": tail}
        units.append({"unit": "A-501 PSA",
                      "H2_recovery": knobs["PSA_H2_recovery"],
                      "product_purity": cfg.P["target"],
                      "H2_product_mol_per_100mol_NG": product["H2"],
                      "tail_gas_mol_per_100mol_NG": sum(v for k, v in tail.items() if k != "C_GR")})
        n = product
        for sp, val in tail.items():
            withdraw(sp, val)
    # 7. final cooler to climate-dependent product temperature
    T_prod = cfg.climate_T_product_K
    T_from = max(T_cur, T_prod)
    n, water2, u2 = cool_and_condense(n, T_from, T_prod, p, cfg,
                                      "E-601 final cooler / knockout")
    units.append(u2)
    withdraw("H2O", water2)
    T_cur = T_prod
    if "drying" in D:
        n = dict(n)
        dry_tot = _dry(n)
        allowed = cfg.P["max_H2O_molpct"] / 100.0 * dry_tot
        removed = max(n.get("H2O", 0.0) - allowed, 0.0)
        n["H2O"] = n.get("H2O", 0.0) - removed
        units.append({"unit": "A-701 molecular-sieve dryer",
                      "H2O_spec_molpct": cfg.P["max_H2O_molpct"],
                      "water_removed_mol_per_100mol_NG": removed,
                      "status": "[NOT MODELLED] dryer regeneration duty",
                      "Q_removed_kJ_per_100mol_NG": 0.0})
        withdraw("H2O", removed)
    if "compression" in D:
        units.append({"unit": "K-801 syngas compression",
                      "p_out_bar": cfg.P["product_p_bar_abs"],
                      "status": "[NOT MODELLED] compression to ammonia-loop pressure"})
    return {"n": n, "y_dry": _y_dry(n), "dry_mol_per_100mol_NG": _dry(n),
            "T_K": T_cur, "p_bar": p, "units": units, "psa": psa_result,
            "withdrawals": withdrawals}


# --------------------------------------------------------------------------
# tuner
# --------------------------------------------------------------------------
def _evaluate(cfg, knobs, air=0.0):
    rx = reformer(cfg, knobs, secondary_air=air)
    if not rx.get("converged", True) or "equilibrium" not in rx:
        return None
    ds = downstream(cfg, knobs, rx)
    y = ds["y_dry"]
    metric = cfg.metric_of(y)
    return {"rx": rx, "ds": ds, "metric": metric,
            "carbon_stable": rx["equilibrium"]["carbon_stable"]}


def tune(cfg, verbose=False):
    """Find the process knobs that hit the product target.

    methanol    : bisect CO2/C on SN (with carbon-deposition guard on S/C)
    ft          : bisect O2/C on H2/CO in an adiabatic ATR (S/C fixed low)
    oxo         : bisect CO2/C on H2/CO (dry/steam reforming)
    hydrogen    : no tuning - WGS+PSA already maximises H2; check purity
    ammonia     : bisect air ratio on H2/N2 after WGS+MDEA+methanation
    """
    k = copy.deepcopy(cfg.knobs)
    product = cfg.product
    target = cfg.P["target"]
    trace = []
    if product == "methanol":
        lo, hi = 0.0, 0.6
        for i in range(22):
            mid = (lo + hi) / 2
            k["CO2C"] = mid
            r = _evaluate(cfg, k)
            if r is None: lo = mid; continue
            trace.append({"CO2C": mid, "SN": r["metric"]})
            if r["metric"] > target: lo = mid
            else: hi = mid
        k["CO2C"] = (lo + hi) / 2
        key = "CO2C"
    elif product == "ft":
        k["SC"] = 0.60
        lo, hi = 0.45, 0.90
        for i in range(10):
            mid = (lo + hi) / 2
            k["O2C"] = mid
            r = _evaluate(cfg, k)
            if r is None: hi = mid; continue
            trace.append({"O2C": mid, "H2_CO": r["metric"],
                          "T_ad_K": r["rx"]["T_out_K"]})
            if r["metric"] > target: lo = mid
            else: hi = mid
        k["O2C"] = (lo + hi) / 2
        key = "O2C"
    elif product == "oxo":
        k["SC"] = 0.60
        lo, hi = 0.4, 2.0
        for i in range(18):
            mid = (lo + hi) / 2
            k["CO2C"] = mid
            r = _evaluate(cfg, k)
            if r is None: lo = mid; continue
            trace.append({"CO2C": mid, "H2_CO": r["metric"]})
            if r["metric"] > target: lo = mid
            else: hi = mid
        k["CO2C"] = (lo + hi) / 2
        key = "CO2C"
    elif product == "hydrogen":
        key = "PSA_H2_recovery"
    elif product == "ammonia":
        lo, hi = 0.2, 1.6
        for i in range(10):
            mid = (lo + hi) / 2
            r = _evaluate(cfg, k, air=mid)
            if r is None or r["metric"] is None:
                hi = mid; continue
            trace.append({"air_ratio": mid, "H2_N2": r["metric"]})
            if r["metric"] > target: lo = mid
            else: hi = mid
        k["air_ratio"] = (lo + hi) / 2
        key = "air_ratio"
    else:
        raise KeyError(product)
    cfg2 = copy.copy(cfg)
    cfg2.P = copy.deepcopy(cfg.P)
    cfg2.P["knobs"] = k
    cfg2._knobs = k
    final = _evaluate(cfg2, k, air=k.get("air_ratio", 0.0))
    return {"cfg": cfg2, "knobs": k, "tuned_knob": key, "trace": trace,
            "final": final, "target": target,
            "tolerance": cfg.P["tolerance"],
            "hit": (final is not None and final["metric"] is not None and
                    abs(final["metric"] - target) <= cfg.P["tolerance"])}


# --------------------------------------------------------------------------
# full design
# --------------------------------------------------------------------------
def design(cfg, do_tune=True):
    if do_tune:
        tuned = tune(cfg)
        cfg = tuned["cfg"]
        ev = tuned["final"]
        air = cfg.knobs.get("air_ratio", 0.0)
    else:
        tuned = None
        ev = _evaluate(cfg, cfg.knobs, cfg.knobs.get("air_ratio", 0.0))
        air = cfg.knobs.get("air_ratio", 0.0)
    if ev is None:
        raise RuntimeError("equilibrium/downstream failed to converge")
    rx, ds = ev["rx"], ev["ds"]
    p = rx["p_bar"]
    proc = cfg.process
    # ---- basis: target capacity -> mol/h of product stream
    cap_mol_h = cfg.capacity_in_mol_h()
    basis = cap_mol_h
    if cfg.P["capacity_basis"] == "H2_product":
        n_basis = ds["psa"]["product"]["H2"]
    elif cfg.P["capacity_basis"] == "NH3":
        n_basis = ds["dry_mol_per_100mol_NG"]
    else:
        n_basis = ds["dry_mol_per_100mol_NG"]
    scale = basis / n_basis     # (mol/h)/(mol per 100 mol NG) -> 100 mol NG / h
    dry_feed_100 = 100.0
    feed_mol_per_100 = sum(rx["feed"].values())
    feed_normal_m3_per_100 = feed_mol_per_100 * cfg.Vm
    dry_gas_mol_per_100 = sum(v for k, v in cfg.F["dry_mol_fraction"].items())
    product_normal_m3_h = ds["dry_mol_per_100mol_NG"] * scale * cfg.Vm
    # ---- utilities (per 100 mol dry NG -> per hour)
    U = {}
    Q_fired_kJ_100 = rx["Q_total_kJ_per_100mol_NG"]
    U["Q_reformer_kW"] = Q_fired_kJ_100 * scale / 3600.0
    eta = proc["furnace_efficiency_LHV"]
    fuel_mol_h = max(Q_fired_kJ_100, 0.0) * scale / (eta * LHV_CH4_KJ_PER_MOL)
    U["fuel_Nm3_h"] = fuel_mol_h * cfg.Vm
    U["CO2_from_fuel_t_h"] = fuel_mol_h * M["CO2"] / 1e6
    whb = next((u for u in ds["units"] if u["unit"].startswith("E-101")), None)
    Q_whb_kJ_100 = whb["Q_removed_kJ_per_100mol_NG"] if whb else 0.0
    dh_steam = steam_generation_dh_kJ_per_mol(proc["steam_p_bar_abs"],
                                              proc["steam_T_K"],
                                              cfg.C["bfw_T_C"] + 273.15)
    steam_mol_h = max(Q_whb_kJ_100, 0.0) * scale / max(dh_steam, 1.0)
    U["steam_generated_t_h"] = steam_mol_h * M["H2O"] / 1e6
    mdea = next((u for u in ds["units"] if u["unit"].startswith("A-301")), None)
    Q_mdea_kJ_100 = mdea["reboiler_duty_kJ_per_100mol_NG"] if mdea else 0.0
    dh_vap = vaporisation_enthalpy_kJ_per_mol(2.0)   # MDEA reboiler ~2 bar(a) saturated steam
    U["MDEA_reboiler_steam_t_h"] = Q_mdea_kJ_100 * scale / max(dh_vap, 1.0) * M["H2O"] / 1e6
    U["steam_net_export_t_h"] = U["steam_generated_t_h"] - U["MDEA_reboiler_steam_t_h"]
    U["CO2_captured_t_h"] = (mdea["CO2_captured_t_per_100mol_NG"] * scale) if mdea else 0.0
    U["total_CO2_t_h"] = U["CO2_from_fuel_t_h"] + U["CO2_captured_t_h"]
    # cooling: final cooler + WGS + methanator + MDEA condenser (reboiler excluded)
    Q_cool_kJ_100 = 0.0
    for u in ds["units"]:
        if u["unit"].startswith(("E-301", "E-601", "R-201", "R-401")):
            Q_cool_kJ_100 += u.get("Q_removed_kJ_per_100mol_NG", 0.0)
    Q_cool_kW = Q_cool_kJ_100 * scale / 3600.0
    dT_cw = max(cfg.C["cooling_water_return_C"] - cfg.C["cooling_water_supply_C"], 5.0)
    U["cooling_duty_kW"] = Q_cool_kW
    U["cooling_water_m3_h"] = Q_cool_kW * 3600.0 / (CP_WATER_KJ_KG_K * dT_cw) / 1000.0
    U["air_cooler_outlet_C"] = cfg.C["ambient_dry_bulb_C"] + cfg.C["air_cooler_approach_K"]
    U["air_cooler_reaches_product_T"] = bool(U["air_cooler_outlet_C"] <= cfg.C["product_T_C"])
    U["trim_cooling_required"] = not U["air_cooler_reaches_product_T"]
    # power: ASU + PSA + pumps
    O2_mol_h = rx.get("feed", {}).get("O2", 0.0) * scale
    if rx.get("feed_secondary"):
        O2_mol_h = rx["feed_secondary"].get("O2", 0.0) * scale
    asu = asu_power(O2_mol_h / 1000.0)
    U["O2_t_h"] = asu["O2_t_h"]
    U["ASU_power_MW"] = asu["power_MW"]
    U["PSA_power_MW"] = (product_normal_m3_h * 0.05 / 1000.0) if "PSA" in cfg.P["downstream"] else 0.0
    U["pump_power_MW"] = 0.02 * (U["cooling_duty_kW"] / 1000.0)
    U["total_power_MW"] = (U["ASU_power_MW"] + U["PSA_power_MW"] + U["pump_power_MW"])
    # ---- equipment
    feed_mol_h = feed_mol_per_100 * scale
    E = size_reformer(cfg, U["Q_reformer_kW"], feed_mol_h,
                      rx["T_out_K"], p, eos_kset=cfg.eos_kset,
                      feed_for_dp=rx["feed"] if U["Q_reformer_kW"] > 0 else None)
    E["WHB"] = size_whb(max(Q_whb_kJ_100, 0.0) * scale / 3600.0,
                        rx["T_out_K"], proc["T_WHB_out_K"],
                        T_cold_in=cfg.C["bfw_T_C"] + 273.15,
                        T_cold_out=proc["steam_T_K"])
    # ---- catalyst / Ni
    cat = catalyst_inventory(cfg, feed_normal_m3_per_100 * scale,
                             dry_gas_mol_per_100 * cfg.Vm * scale,
                             product_normal_m3_h,
                             sulfur_ppmv=cfg.F["H2S_ppmv"],
                             feed_kmol_h=feed_mol_h / 1000.0)
    # ---- economics
    ec = cfg.economics
    hours = ec["operating_hours_per_year"]
    lhv_mmbtu = LHV_CH4_KJ_PER_MOL / cfg.Vm * 9.47817e-7
    feed_gas_Nm3_h = dry_gas_mol_per_100 * cfg.Vm * scale
    gas_cost = (feed_gas_Nm3_h + U["fuel_Nm3_h"]) * lhv_mmbtu * ec["gas_USD_per_MMBtu"] * hours
    co2_cost = U["total_CO2_t_h"] * ec["CO2_USD_per_t"] * hours
    power_cost = U["total_power_MW"] * 1000.0 * ec["electricity_USD_per_MWh"] / 1000.0 * hours
    steam_credit = max(U["steam_net_export_t_h"], 0.0) * ec["steam_USD_per_t"] * hours
    cw_cost = U["cooling_water_m3_h"] * ec["cooling_water_USD_per_m3"] * hours
    catalyst_cost = cat["catalyst_consumption_t_per_y"] * 1000.0 * (ec.get("catalyst_USD_per_t", 5000.0))
    opex = gas_cost + co2_cost + power_cost + cw_cost + catalyst_cost - steam_credit
    # CAPEX: scaled from opened H2 study (700 USD/kW at 300 MW LHV H2)
    h2_mol_h = ds["y_dry"].get("H2", 0.0) * ds["dry_mol_per_100mol_NG"] * scale
    mw_lhv = h2_mol_h * 241.826 / 3600.0 / 1000.0   # MW (LHV H2 = 241.826 kJ/mol)
    capex_ref = ec["CAPEX_USD_per_kW_H2_LHV"] * ec["CAPEX_ref_H2_MW_LHV"] * 1000.0
    capex = capex_ref * (max(mw_lhv, 1.0) / ec["CAPEX_ref_H2_MW_LHV"]) ** ec["CAPEX_scale_exponent"]
    if U["O2_t_h"] > 0:
        capex *= (1.0 + ec["ASU_CAPEX_share"])
    if mdea:
        capex *= (1.0 + ec["CO2_removal_CAPEX_share"])
    r = ec["discount_rate"]; ny = ec["plant_life_years"]
    ann = capex * r / (1.0 - (1.0 + r) ** (-ny))
    opex_total = opex + capex * ec["fixed_OPEX_pct_CAPEX"]
    if cfg.P["capacity_basis"] == "NH3":
        prod_per_y = cfg.P["capacity"] * 365.0
        unit = "USD/t NH3"
    elif cfg.P["capacity_basis"] == "H2_product":
        prod_per_y = cfg.P["capacity"] * hours
        unit = "USD/1000 Nm3 H2"
    else:
        prod_per_y = product_normal_m3_h * hours
        unit = "USD/1000 Nm3 dry syngas"
    lcop = (opex_total + ann) / (prod_per_y / 1000.0) if "NH3" not in unit else (opex_total + ann) / prod_per_y
    econ = {"gas_cost_USD_y": gas_cost, "CO2_cost_USD_y": co2_cost,
            "power_cost_USD_y": power_cost, "steam_credit_USD_y": steam_credit,
            "cooling_water_cost_USD_y": cw_cost, "catalyst_cost_USD_y": catalyst_cost,
            "fixed_OPEX_USD_y": capex * ec["fixed_OPEX_pct_CAPEX"],
            "total_OPEX_USD_y": opex_total,
            "CAPEX_USD": capex, "annualised_CAPEX_USD_y": ann,
            "H2_equivalent_MW_LHV": mw_lhv,
            "levelised_cost": lcop, "unit": unit,
            "status": "[PARTIAL] CAPEX scaled from opened H2 study to syngas; class-5 +/-50%"}
    # ---- spec check
    y = ds["y_dry"]
    spec = {"metric": cfg.P["metric"], "target": cfg.P["target"],
            "achieved": ev["metric"], "within_tolerance": tuned["hit"] if tuned else
            (ev["metric"] is not None and abs(ev["metric"] - cfg.P["target"]) <= cfg.P["tolerance"]),
            "carbon_stable": ev["carbon_stable"],
            "CO2_molpct": y.get("CO2", 0.0) * 100,
            "CH4_molpct": y.get("CH4", 0.0) * 100,
            "N2_molpct": y.get("N2", 0.0) * 100,
            "H2O_molpct": 100 * ds["n"].get("H2O", 0.0) /
                          max(sum(v for k, v in ds["n"].items() if k != "C_GR"), 1e-12),
            "H2_purity_molpct": y.get("H2", 0.0) * 100,
            "CO_ppm": y.get("CO", 0.0) * 1e6,
            "CO2_ppm": y.get("CO2", 0.0) * 1e6,
            "CH4_ppm": y.get("CH4", 0.0) * 1e6,
            "N2_ppm": y.get("N2", 0.0) * 1e6,
            "H2O_ppm": 1e6 * ds["n"].get("H2O", 0.0) /
                       max(sum(v for k, v in ds["n"].items() if k != "C_GR"), 1e-12),
            "non_H2_ppm": (1.0 - y.get("H2", 0.0)) * 1e6,
            "limit_checks": {}}
    for key, lim in (("max_CO2_molpct", "CO2_molpct"), ("max_CH4_molpct", "CH4_molpct"),
                     ("max_N2_molpct", "N2_molpct"), ("max_H2O_molpct", "H2O_molpct"),
                     ("max_CO_ppm", "CO_ppm"), ("max_CO2_ppm", "CO2_ppm"),
                     ("max_CH4_ppm", "CH4_ppm"), ("max_N2_ppm", "N2_ppm"),
                     ("max_H2O_ppm", "H2O_ppm"),
                     ("max_total_non_H2_ppm", "non_H2_ppm"),
                     ("max_CO_CO2_ppm", "CO_CO2_ppm")):
        if key in cfg.P:
            if lim == "CO_CO2_ppm":
                spec["CO_CO2_ppm"] = spec["CO_ppm"] + spec["CO2_ppm"]
            spec["limit_checks"][key] = {"limit": cfg.P[key],
                                          "value": spec[lim],
                                          "pass": spec[lim] <= cfg.P[key]}
    return {
        "config": cfg.describe(),
        "product": cfg.product, "normal": cfg.active["normal"],
        "climate": cfg.active["climate"], "feed": cfg.active["feed"],
        "Vm_m3_per_mol": cfg.Vm,
        "knobs": cfg.knobs, "tuning": ({"tuned_knob": tuned["tuned_knob"],
                                         "hit": tuned["hit"],
                                         "trace_last": tuned["trace"][-1] if tuned["trace"] else None}
                                        if tuned else None),
        "spec": spec,
        "reformer": {k: v for k, v in rx.items() if k not in ("units", "feed", "feed_secondary")},
        "reformer_feed_mol_per_100mol_NG": rx["feed"],
        "reformer_units": [{k: v for k, v in u.items() if k != "equilibrium"} for u in rx["units"]],
        "downstream": ds,
        "flows": {"scale_100mol_NG_per_h": scale,
                  "dry_feed_Nm3_h": feed_gas_Nm3_h,
                  "total_feed_Nm3_h": feed_normal_m3_per_100 * scale,
                  "product_Nm3_h": product_normal_m3_h,
                  "product_mol_h": ds["dry_mol_per_100mol_NG"] * scale,
                  "H2_product_Nm3_h": (ds["psa"]["product"]["H2"] * scale * cfg.Vm)
                                      if ds["psa"] else None},
        "utilities": U, "equipment": E, "catalyst": cat, "economics": econ,
        "steam": {"IAPWS_used": iapws_available() and cfg.use_iapws,
                  "dh_steam_kJ_per_mol": dh_steam,
                  "dh_vap_at_MDEA_kJ_per_mol": dh_vap},
        "eos": {"enabled": cfg.eos["enabled"], "kset": cfg.eos_kset,
                "Z": rx["equilibrium"]["eos"].get("Z"),
                "Q1_over_K1_real": rx["equilibrium"]["eos"].get("Q1_over_K1_real"),
                "Kphi_R1": rx["equilibrium"]["eos"].get("Kphi_R1")},
        "status": {"hysys": "NOT RUN - Python/DWSIM-equivalent (user confirmation #11)",
                   "validation": "no experimental campaign; see docs/13"},
    }
