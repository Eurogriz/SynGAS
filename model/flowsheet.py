"""L1 material and heat balance for the base case (front-end level).

All balances are computed from the pure-Python equilibrium core. Every unit
has an explicit enthalpy balance; the plant-level closure is asserted.
"""
from __future__ import annotations
import json, math, os
from .thermo import (stream_enthalpy, h_liquid_water, water_psat_bar,
                     water_dew_point, h0, properties, R_KJ)
from .equilibrium import equilibrate, element_vector, adiabatic_temperature
from .routes import make_feed, DRY_FEED, HC_CARBON, find_co2_for_SN

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOLAR_VOLUME_NM3 = 0.02241397        # m3(normal)/mol, 273.15 K, 101325 Pa [ASSUMPTION]


def mix_temperature(streams, T_guess=600.0):
    """Adiabatic mixing temperature of several streams of known composition."""
    n = {}
    H = 0.0
    for comp, T in streams:
        for k, v in comp.items():
            n[k] = n.get(k, 0.0) + v
        H += stream_enthalpy(comp, T)
    def f(T):
        return stream_enthalpy(n, T) - H
    lo, hi = 250.0, 2000.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi), n


def condense(n_gas, T, p_bar):
    """Equilibrium condensation of water at T,p using NIST Antoine psat."""
    dry = sum(v for k, v in n_gas.items() if k not in ("H2O", "C_GR"))
    psat = water_psat_bar(T)
    y_eq = min(psat / p_bar, 0.95)
    n_h2o_gas = y_eq / (1 - y_eq) * dry
    n_cond = n_gas.get("H2O", 0.0) - n_h2o_gas
    if n_cond < 0:
        n_cond, n_h2o_gas = 0.0, n_gas.get("H2O", 0.0)
    out = dict(n_gas)
    out["H2O"] = n_h2o_gas
    H = stream_enthalpy(out, T) + n_cond * h_liquid_water(T)
    return {"gas_mol": out, "condensate_mol": n_cond, "H_kJ": H,
            "p_sat_bar": psat, "y_H2O_sat": y_eq, "dry_mol": dry}


def pinch_analysis(streams, dTmin=20.0):
    """Problem-table (interval) pinch targeting with constant cp per stream.

    streams: [{name, type 'hot'|'cold', T_in, T_out, Q>0 (kJ per basis)}]
    Returns utility targets, pinch temperature and the cascade table.
    """
    prep = []
    for s in streams:
        dT = abs(s["T_in"] - s["T_out"])
        cp = s["Q"] / dT if dT > 0 else 0.0
        sh = -dTmin / 2 if s["type"] == "hot" else dTmin / 2
        lo = min(s["T_in"], s["T_out"]) + sh
        hi = max(s["T_in"], s["T_out"]) + sh
        prep.append({**s, "cp": cp, "lo": lo, "hi": hi})
    temps = sorted({x for p in prep for x in (p["lo"], p["hi"])}, reverse=True)
    cascade, table = 0.0, []
    for i in range(len(temps) - 1):
        Th, Tl = temps[i], temps[i + 1]
        dT = Th - Tl
        hot = sum(p["cp"] * dT for p in prep if p["type"] == "hot" and p["hi"] >= Th and p["lo"] <= Tl)
        cold = sum(p["cp"] * dT for p in prep if p["type"] == "cold" and p["hi"] >= Th and p["lo"] <= Tl)
        net = hot - cold
        cascade += net
        table.append({"T_high_K": Th, "T_low_K": Tl, "Q_hot_kJ": hot,
                      "Q_cold_kJ": cold, "net_kJ": net, "cascade_kJ": cascade})
    cmin = min([0.0] + [r["cascade_kJ"] for r in table])
    QH = -cmin
    QC = cascade + QH
    acc = QH
    pinch_T = None
    prev = 0.0
    for r in table:
        prev = acc
        acc += r["net_kJ"]
        if pinch_T is None and ((prev > 0 >= acc) or (prev < 0 <= acc) or abs(acc) < 1e-6):
            pinch_T = r["T_low_K"]
    return {"dT_min_K": dTmin, "Q_hot_min_kJ": QH, "Q_cold_min_kJ": QC,
            "pinch_shifted_T_K": pinch_T, "cascade": table}


def build_base_case(case):
    P = case["process"]
    SC = P["S_C_molar_per_hydrocarbon_C"]
    T_sm = P["SMR_T_out_K"]
    p_sm = P["SMR_p_out_bar_abs"]
    appr = P["SMR_approach_to_equilibrium_K"]
    T_pre = P["T_feed_preheat_K"]
    T_whb = P["WHB_T_out_K"]
    T_cond = P["condenser_T_out_K"]
    p_cond = P["condenser_p_bar_abs"]
    T_feed = case["feed"]["T_C"] + 273.15

    tuned = find_co2_for_SN(case["target"]["SN_target"], SC=SC, T=T_sm,
                            p=p_sm, approach_K=appr)
    co2c = tuned["CO2_C_molar"] if tuned["converged"] else 0.4

    # ---- inlet streams (basis = 100 mol DRY natural gas, mol units) ----
    ng = dict(DRY_FEED)
    ng["H2"] = case["feed"]["H2_recycle_mol_per_100_mol_feed"]
    steam = {"H2O": SC * HC_CARBON}
    co2_imp = {"CO2": co2c * HC_CARBON}
    H_ng_in = stream_enthalpy(ng, T_feed)
    H_ng_out = stream_enthalpy(ng, T_pre)
    Q_preheat = H_ng_out - H_ng_in
    T_mix, mixed = mix_temperature([(ng, T_pre), (steam, T_pre), (co2_imp, T_feed)])
    H_mixed = stream_enthalpy(mixed, T_mix)

    # ---- R-101 adiabatic pre-reformer (true adiabatic solve) ----
    ad = adiabatic_temperature(mixed, p_sm, T_in=T_mix)
    if not ad["converged"]:
        raise RuntimeError("adiabatic pre-reformer did not converge: " + str(ad))
    pre = ad["equilibrium"]
    T_pre_out = ad["T_ad_K"]
    H_pre = stream_enthalpy(pre["n_mol"], T_pre_out)
    pre["T_out_K"] = T_pre_out
    pre["H_in_kJ"] = ad["H_in_kJ"]
    pre["H_out_kJ"] = H_pre
    pre["adiabatic_closure_kJ"] = H_pre - ad["H_in_kJ"]

    # ---- R-201 fired tubular SMR ----
    smr = equilibrate(pre["n_mol"], T_sm, p_sm, approach_K=appr)
    H_smr_out = stream_enthalpy(smr["n_mol"], T_sm)
    Q_smr = H_smr_out - H_pre

    # ---- E-201 waste-heat boiler (no reaction, no condensation allowed) ----
    y_h2o = smr["y_wet"]["H2O"]
    dew = water_dew_point(p_sm, y_h2o)
    n_hot = {k: v for k, v in smr["n_mol"].items() if k != "C_GR"}
    H_whb_in = stream_enthalpy(n_hot, T_sm)
    H_whb_out = stream_enthalpy(n_hot, T_whb)
    Q_whb = H_whb_out - H_whb_in          # negative: heat released
    no_condensation_in_WHB = (dew is None or dew < T_whb)

    # ---- E-202 cooler / condenser + V-201 separator ----
    cond = condense(n_hot, T_cond, p_cond)
    Q_cond = cond["H_kJ"] - H_whb_out

    # ---- scale to the specified production rate ----
    dry_mol_basis = sum(v for k, v in cond["gas_mol"].items() if k not in ("H2O", "C_GR"))
    target = case["target"]["capacity_dry_Nm3_per_h"]
    F = target / (dry_mol_basis * MOLAR_VOLUME_NM3)     # mol/h per (mol basis)
    kW = lambda Q: Q * F / 3600.0
    kmol_h = lambda n: n * F / 1000.0

    # ---- fuel, steam and emissions ----
    FULL_OX_GAS = {"CH4": -1, "O2": -2, "CO2": 1, "H2O": 2}
    dh_comb = sum(nu * h0(s, 298.15) for s, nu in FULL_OX_GAS.items())
    LHV_kJ_per_mol = -dh_comb                      # water stays as vapour -> LHV
    q_smr_kW = kW(Q_smr)
    eta = P["furnace_efficiency_LHV"]
    fuel_mol_h = q_smr_kW * 3600.0 / (eta * LHV_kJ_per_mol)
    dh_steam = h0("H2O", 673.15) - h_liquid_water(373.15)
    steam_gen_mol_h = -kW(Q_whb) * 3600.0 / dh_steam
    steam_demand_mol_h = SC * HC_CARBON * F
    cw_cp = 75.3        # J/mol/K [ASSUMPTION]
    cw_mol_h = -kW(Q_cond) * 3600.0 / (cw_cp * 10.0 / 1000.0)  # kJ/h / (kJ/mol)
    cw_m3_h = cw_mol_h * 0.018015 / 1000.0

    # ---- plant-level energy closure ----
    H_in_total = (H_ng_in + stream_enthalpy(steam, T_pre)
                  + stream_enthalpy(co2_imp, T_feed))
    H_out_total = cond["H_kJ"]
    Q_units = Q_preheat + 0.0 + Q_smr + Q_whb + Q_cond
    closure_pct = abs((H_in_total + Q_units - H_out_total) /
                      max(abs(H_out_total), 1e-9)) * 100

    # ---- pinch (screening level) ----
    flue_Q = (q_smr_kW / eta) * 3600.0 / F * 0.45   # kJ per basis [ASSUMPTION 45% of fired heat leaves with flue gas]
    streams = [
        {"name": "H1 WHB syngas", "type": "hot", "T_in": T_sm, "T_out": T_whb, "Q": -Q_whb},
        {"name": "H2 syngas cooler/condenser", "type": "hot", "T_in": T_whb, "T_out": T_cond, "Q": -Q_cond},
        {"name": "H3 flue gas", "type": "hot", "T_in": 1373.15, "T_out": 423.15, "Q": flue_Q},
        {"name": "C1 feed preheat", "type": "cold", "T_in": T_feed, "T_out": T_pre, "Q": Q_preheat},
        {"name": "C2 steam generation", "type": "cold", "T_in": 373.15, "T_out": 673.15,
         "Q": min(-Q_whb * 0.7, steam_demand_mol_h / F * dh_steam)},
        {"name": "C3 BFW heating", "type": "cold", "T_in": 298.15, "T_out": 373.15,
         "Q": steam_demand_mol_h / F * (h_liquid_water(373.15) - h_liquid_water(298.15))},
    ]
    pinch = pinch_analysis(streams, P["pinch_dT_min_K"])

    # ---- stream table ----
    def stream_row(tag, T, p, n, H, liquid=0.0, note=""):
        tot = sum(v for k, v in n.items() if k not in ("H2O", "C_GR")) + n.get("H2O", 0.0)
        return {"stream": tag, "T_K": T, "p_bar_abs": p,
                "total_mol_basis": tot, "kmol_h": sum(n.values()) * F / 1000.0,
                "H_kJ_per_basis": H, "H_MW_plant": H * F / 3.6e6,
                "liquid_mol_basis": liquid, "note": note,
                **{f"y_{k}": (v / tot if tot else 0.0) for k, v in n.items()
                   if k not in ("C_GR",)}}
    stream_rows = [
        stream_row("S-101 NG feed", T_feed, case["feed"]["p_bar_abs"], ng, H_ng_in,
                   note="after HDS/ZnO; sulfur removed"),
        stream_row("S-102 steam", T_pre, 30.0, steam, stream_enthalpy(steam, T_pre),
                   note="imported/raised steam [ASSUMPTION]"),
        stream_row("S-103 CO2 import", T_feed, 30.0, co2_imp, stream_enthalpy(co2_imp, T_feed),
                   note="CO2/C tuned to SN=2"),
        stream_row("S-104 mixed feed", T_mix, p_sm, mixed, H_mixed),
        stream_row("S-105 pre-reformer out", T_pre_out, p_sm, pre["n_mol"], H_pre),
        stream_row("S-106 SMR outlet", T_sm, p_sm, smr["n_mol"], H_smr_out),
        stream_row("S-107 WHB outlet", T_whb, p_sm, n_hot, H_whb_out),
        stream_row("S-108 dry syngas", T_cond, p_cond, cond["gas_mol"],
                   stream_enthalpy(cond["gas_mol"], T_cond)),
        stream_row("S-109 condensate", T_cond, p_cond, {"H2O": cond["condensate_mol"]},
                   cond["condensate_mol"] * h_liquid_water(T_cond), cond["condensate_mol"]),
    ]
    units = [
        {"unit": "E-101 feed preheat", "Q_kJ_per_basis": Q_preheat, "Q_kW": kW(Q_preheat)},
        {"unit": "R-101 pre-reformer (adiabatic)", "Q_kJ_per_basis": 0.0, "Q_kW": 0.0},
        {"unit": "R-201 SMR furnace (process side)", "Q_kJ_per_basis": Q_smr, "Q_kW": q_smr_kW},
        {"unit": "E-201 waste-heat boiler", "Q_kJ_per_basis": Q_whb, "Q_kW": kW(Q_whb)},
        {"unit": "E-202 cooler/condenser", "Q_kJ_per_basis": Q_cond, "Q_kW": kW(Q_cond)},
        {"unit": "V-201 separator", "Q_kJ_per_basis": 0.0, "Q_kW": 0.0},
    ]
    return {
        "CO2_C_molar": co2c, "SN_target": case["target"]["SN_target"],
        "SN_achieved": smr["stoichiometric_number_SN"],
        "scaling_factor_mol_h_per_mol_basis": F,
        "dry_syngas_Nm3_h": dry_mol_basis * MOLAR_VOLUME_NM3 * F,
        "streams": stream_rows, "units": units,
        "pre_reformer": pre, "SMR": smr,
        "pre_reformer_T_out_K": T_pre_out,
        "condensation": {k: v for k, v in cond.items() if k != "gas_mol"},
        "dew_point_K": dew, "no_condensation_in_WHB": no_condensation_in_WHB,
        "plant_energy_closure_pct": closure_pct,
        "element_balance_SMR_max_pct": smr["max_element_imbalance_pct"],
        "pinch": pinch,
        "utilities": {
            "LHV_CH4_kJ_per_mol_from_NIST": LHV_kJ_per_mol,
            "furnace_efficiency_LHV": eta,
            "fuel_mol_h": fuel_mol_h, "fuel_kmol_h": fuel_mol_h / 1000.0,
            "fuel_Nm3_h": fuel_mol_h * MOLAR_VOLUME_NM3,
            "fired_heat_kW": q_smr_kW / eta,
            "steam_generated_mol_h": steam_gen_mol_h,
            "steam_generated_t_h": steam_gen_mol_h * 0.018015 / 1000.0,
            "steam_demand_mol_h": steam_demand_mol_h,
            "steam_demand_t_h": steam_demand_mol_h * 0.018015 / 1000.0,
            "steam_net_export_t_h": (steam_gen_mol_h - steam_demand_mol_h) * 0.018015 / 1000.0,
            "cooling_water_m3_h": cw_m3_h,
            "CO2_from_fuel_t_h": fuel_mol_h * 0.0440095 / 1000.0,
            "CO2_in_product_mol_h": cond["gas_mol"]["CO2"] * F,
            "CO_in_product_mol_h": cond["gas_mol"]["CO"] * F,
        },
    }
