"""G5/G7 extension: downstream synthesis loops -> saleable product tonnages.

Stoichiometric + recycle material balances only. NOT a kinetic reactor model.
Every conversion/selectivity value is user-adjustable in cases/config.json and
is traceable to an opened source (see the config "source" strings).

Products:
  methanol : CO + 2H2 -> CH3OH ; CO2 + 3H2 -> CH3OH + H2O
  ft       : CO + 2H2 -> -CH2- + H2O ; ASF chain-growth distribution
  oxo      : C3H6 + CO + H2 -> C4H8O (butyraldehyde), external propylene
  hydrogen : H2 product compressed to a delivery pressure
  ammonia  : N2 + 3H2 -> 2NH3
"""
from __future__ import annotations
import math
from .equipment import compressor_power

MW = {"CH3OH": 32.042, "H2O": 18.0153, "NH3": 17.0305,
      "H2": 2.01588, "C4H8O": 72.107, "C3H6": 42.081}


def _mol_h(r):
    scale = r["flows"]["scale_100mol_NG_per_h"]
    return {sp: v * scale for sp, v in r["downstream"]["n"].items()}


def _common(r, cfg, S):
    return {"product": r["product"], "p_synthesis_bar": S.get("p_bar"),
            "T_synthesis_C": S.get("T_C"), "source": S.get("source"),
            "status": S.get("status"),
            "method": "stoichiometric loop balance, NOT a kinetic simulation"}


def synthesis_report(r, cfg):
    prod = r["product"]
    S = cfg.raw.get("synthesis", {}).get(prod, {})
    n = _mol_h(r)
    y = r["downstream"]["y_dry"]
    hours = cfg.economics["operating_hours_per_year"]
    out = _common(r, cfg, S)
    dry = sum(v for sp, v in n.items() if sp not in ("H2O", "C_GR"))
    co, co2, h2, n2 = (n.get(k, 0.0) for k in ("CO", "CO2", "H2", "N2"))
    inert = sum(n.get(k, 0.0) for k in ("CH4", "C2H6", "C3H8", "N2", "O2"))
    out["dry_syngas_mol_h"] = dry
    out["inert_mol_h"] = inert
    out["inert_molpct"] = 100 * inert / dry if dry else None

    if prod == "methanol":
        X = S.get("overall_C_conversion", 0.97)
        C = co + co2
        fco = co / C if C else 0.0
        fco2 = co2 / C if C else 0.0
        meoh = C * X
        h2_used = meoh * (2 * fco + 3 * fco2)
        out.update({
            "reaction": "CO + 2H2 -> CH3OH ; CO2 + 3H2 -> CH3OH + H2O",
            "COx_in_mol_h": C, "CO_mol_h": co, "CO2_mol_h": co2,
            "H2_in_mol_h": h2, "H2_stoichiometric_mol_h": h2_used,
            "H2_utilisation": h2_used / h2 if h2 else None,
            "overall_C_conversion": X,
            "per_pass_COx_conversion": S.get("per_pass_COx_conversion"),
            "recycle_ratio": S.get("recycle_ratio"),
            "recycle_mol_h": S.get("recycle_ratio", 0) * C,
            "methanol_mol_h": meoh,
            "methanol_t_h": meoh * MW["CH3OH"] / 1e6,
            "methanol_t_y": meoh * MW["CH3OH"] / 1e6 * hours,
            "water_formed_t_h": meoh * fco2 * MW["H2O"] / 1e6,
            "CO2_feed_molpct": 100 * y.get("CO2", 0.0),
            "CO2_window_molpct": S.get("CO2_feed_molpct_range"),
            "heat_released_MW": -(S.get("dH_CO_kJ_mol", -90.7) * fco +
                                  S.get("dH_CO2_kJ_mol", -49.7) * fco2) *
                                 meoh / 3600.0 / 1000.0,
        })
        # synthesis-loop compression from the reformer pressure
        pw = compressor_power(dry / 1000.0, 313.15,
                              r["reformer"]["p_bar"], S.get("p_bar", 75.0),
                              k=1.35, MW=12.0)
        out["compression_power_MW"] = pw["power_kW"] / 1000.0
        out["compression_status"] = pw["status"]

    elif prod == "ft":
        X = S.get("CO_conversion", 0.70)
        a = S.get("alpha", 0.90)
        co_conv = co * X
        h2_need = 2 * co_conv
        if h2 < h2_need:
            co_conv = h2 / 2.0
            X = co_conv / co if co else 0.0
        ch2 = co_conv
        hc_t_h = ch2 * S.get("CH2_MW", 14.027) / 1e6
        c5 = a ** 4 * (5 - 4 * a)          # ASF mass fraction C5+
        asf = [{"n": i,
                "mass_fraction": (i * (1 - a) ** 2 * a ** (i - 1)) /
                                 (1.0 / (1 - a) ** 2) * (1 - a) ** 2}
               for i in range(1, 13)]
        # normalise the truncated distribution for reporting
        tot = sum(x["mass_fraction"] for x in asf)
        for x in asf:
            x["mass_fraction_norm"] = x["mass_fraction"] / tot if tot else 0.0
        out.update({
            "reaction": "CO + 2H2 -> -CH2- + H2O",
            "CO_in_mol_h": co, "H2_in_mol_h": h2,
            "CO_conversion": X, "CO_converted_mol_h": co_conv,
            "alpha": a, "ASF_C5plus_mass_fraction": c5,
            "hydrocarbons_t_h": hc_t_h,
            "C5plus_t_h": hc_t_h * c5,
            "C5plus_t_y": hc_t_h * c5 * hours,
            "water_t_h": co_conv * MW["H2O"] / 1e6,
            "heat_released_MW": -S.get("dH_kJ_per_mol_CO", -165.0) *
                                 co_conv / 3600.0 / 1000.0,
            "ASF_first_12": asf,
            "note": "CH4 in the fresh syngas is counted as inert, not FT product",
        })

    elif prod == "oxo":
        olefin = min(co, h2)   # external propylene fed stoichiometrically
        conv = S.get("olefin_conversion", 0.90)
        sel = S.get("aldehyde_selectivity", 0.95)
        ald = olefin * conv * sel
        out.update({
            "reaction": "C3H6 + CO + H2 -> C4H8O (n-/iso-butyraldehyde)",
            "olefin": S.get("olefin"), "CO_in_mol_h": co, "H2_in_mol_h": h2,
            "external_olefin_mol_h": olefin,
            "external_olefin_t_h": olefin * S.get("olefin_MW", 42.081) / 1e6,
            "olefin_conversion": conv, "aldehyde_selectivity": sel,
            "n_iso_ratio": S.get("n_iso_ratio"),
            "aldehyde_mol_h": ald,
            "aldehyde_t_h": ald * S.get("aldehyde_MW", 72.107) / 1e6,
            "aldehyde_t_y": ald * S.get("aldehyde_MW", 72.107) / 1e6 * hours,
            "heat_released_MW": None,
            "note": "hydroformylation heat of reaction [NOT MODELLED] - no "
                    "opened dH for C3H6/C4H8O in this session; external "
                    "propylene feed cost is NOT in the OPEX",
        })

    elif prod == "hydrogen":
        h2p = r["flows"].get("H2_product_Nm3_h") or (h2 * r["Vm_m3_per_mol"])
        pw = compressor_power(h2 / 1000.0, S.get("T_in_K", 313.15),
                              r["reformer"]["p_bar"],
                              S.get("delivery_p_bar", 200.0),
                              k=S.get("k", 1.41), MW=S.get("MW", 2.016))
        out.update({
            "reaction": "no synthesis reaction - H2 is the product",
            "H2_mol_h": h2, "H2_Nm3_h": h2p,
            "H2_t_h": h2 * MW["H2"] / 1e6,
            "H2_kg_h": h2 * MW["H2"] / 1000.0,
            "delivery_p_bar": S.get("delivery_p_bar", 200.0),
            "compression_power_MW": pw["power_kW"] / 1000.0,
            "compression_status": pw["status"],
            "note": "compression duty is an ADDITIONAL utility, not in the "
                    "base utility balance (documented separately)",
        })

    elif prod == "ammonia":
        X = S.get("overall_conversion", 0.97)
        n2_conv = n2 * X
        nh3 = 2 * n2_conv
        out.update({
            "reaction": "N2 + 3H2 -> 2NH3",
            "N2_in_mol_h": n2, "H2_in_mol_h": h2,
            "H2_N2_ratio": h2 / n2 if n2 else None,
            "per_pass_conversion": S.get("per_pass_conversion", 0.18),
            "overall_conversion": X,
            "N2_converted_mol_h": n2_conv,
            "NH3_mol_h": nh3,
            "NH3_t_h": nh3 * MW["NH3"] / 1e6,
            "NH3_t_day": nh3 * MW["NH3"] / 1e6 * 24.0,
            "NH3_t_y": nh3 * MW["NH3"] / 1e6 * hours,
            "nominal_capacity_t_day": cfg.P["capacity"],
            "heat_released_MW": -S.get("dH_kJ_per_mol_NH3", -46.0) *
                                 nh3 / 3600.0 / 1000.0,
        })
        pw = compressor_power(dry / 1000.0, 313.15,
                              r["reformer"]["p_bar"], S.get("p_bar", 200.0),
                              k=1.40, MW=8.5)
        out["compression_power_MW"] = pw["power_kW"] / 1000.0
        out["compression_status"] = pw["status"]
        out["note"] = ("compression to the NH3 loop pressure is an ADDITIONAL "
                       "utility shown here, not in the base utility balance")

    else:
        out["error"] = f"no synthesis model for {prod}"
    return out
