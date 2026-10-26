"""G7: screening-class (AACE-like class 5) economics. ALL prices are assumptions."""
from __future__ import annotations

PRICES = {
    "natural_gas_USD_per_MMBtu": 8.0,
    "electricity_USD_per_MWh": 80.0,
    "CO2_USD_per_t": 80.0,
    "steam_USD_per_t": 25.0,
    "cooling_water_USD_per_m3": 0.05,
    "catalyst_USD_per_kg": 40.0,
    "operating_hours_per_year": 8000.0,
    "CAPEX_USD": 120e6,
    "CAPEX_class": "screening / AACE-like class 5, +/-50% [ASSUMPTION]; AACE 18R-97 text was NOT opened",
    "discount_rate": 0.10,
    "plant_life_years": 20.0,
}
STATUS = "[ASSUMPTION] no cost database, vendor quote or licence fee was opened in this session"


def lhv_mmbtu_per_nm3(LHV_kJ_per_mol, molar_volume_Nm3=0.02241397):
    return LHV_kJ_per_mol / molar_volume_Nm3 * 9.47817e-7  # kJ/Nm3 -> MMBtu/Nm3 (1 MMBtu = 1.055056e6 kJ)


def economics_report(case, fs):
    u = fs["utilities"]
    p = PRICES
    hours = p["operating_hours_per_year"]
    lhv = lhv_mmbtu_per_nm3(u["LHV_CH4_kJ_per_mol_from_NIST"])
    feed_nm3_h = fs["dry_syngas_Nm3_h"] * 0.6     # [ASSUMPTION] feed/syngas ratio
    fuel_nm3_h = u["fuel_Nm3_h"]
    gas_cost = (feed_nm3_h + fuel_nm3_h) * lhv * p["natural_gas_USD_per_MMBtu"] * hours
    co2_cost = u["CO2_from_fuel_t_h"] * p["CO2_USD_per_t"] * hours
    steam_credit = max(u["steam_net_export_t_h"], 0) * p["steam_USD_per_t"] * hours
    cw_cost = u["cooling_water_m3_h"] * p["cooling_water_USD_per_m3"] * hours
    power_cost = 0.0    # SMR base case; ASU/compression handled in route comparison
    opex = gas_cost + co2_cost + cw_cost + power_cost - steam_credit
    ann = p["CAPEX_USD"] * p["discount_rate"] / (1 - (1 + p["discount_rate"]) ** (-p["plant_life_years"]))
    prod_nm3_y = fs["dry_syngas_Nm3_h"] * hours
    lcos = (opex + ann) / prod_nm3_y
    sens = []
    for key, vals in {"natural_gas_USD_per_MMBtu": (4, 8, 12, 16),
                      "CO2_USD_per_t": (0, 40, 80, 160),
                      "CAPEX_USD": (60e6, 120e6, 240e6)}.items():
        for v in vals:
            pp = dict(p); pp[key] = v
            gc = (feed_nm3_h + fuel_nm3_h) * lhv * pp["natural_gas_USD_per_MMBtu"] * hours
            cc = u["CO2_from_fuel_t_h"] * pp["CO2_USD_per_t"] * hours
            an = pp["CAPEX_USD"] * pp["discount_rate"] / (1 - (1 + pp["discount_rate"]) ** (-pp["plant_life_years"]))
            sens.append({"parameter": key, "value": v,
                         "USD_per_1000Nm3_syngas": (gc + cc + cw_cost - steam_credit + an) / prod_nm3_y * 1000})
    return {"prices": p, "status": STATUS,
            "LHV_CH4_MMBtu_per_Nm3": lhv,
            "annual": {"feed_plus_fuel_Nm3_h": feed_nm3_h + fuel_nm3_h,
                       "gas_cost_USD_y": gas_cost, "CO2_cost_USD_y": co2_cost,
                       "cooling_water_cost_USD_y": cw_cost,
                       "steam_credit_USD_y": steam_credit,
                       "annualised_CAPEX_USD_y": ann,
                       "total_OPEX_plus_annual_CAPEX_USD_y": opex + ann},
            "levelised_cost_USD_per_1000Nm3_dry_syngas": lcos * 1000,
            "sensitivity": sens,
            "warning": "This is NOT a project cost estimate. No vendor quotes, no licence fees, no location factors, no AACE class definition was opened."}
