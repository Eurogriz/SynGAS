"""G6: Ni/MgAl2O4 catalyst volumes, service life, consumption and Ni balance.

User requirement #10/#12: the catalyst database MUST contain nickel on
magnesium-aluminate spinel and give an understanding of volumes, service life,
consumption and nickel requirements. Data provenance is explicit: the
Ni/MgAl2O4 chemistry (15 wt% Ni, 86 m2/g, 6.6 nm) is from an opened peer-
reviewed lab study; the bulk density / life / NiO loading are from an opened
commercial steam-reforming-catalyst brochure whose SUPPORT IS NOT MgAl2O4 and
are therefore marked as a PROXY, not as a MgAl2O4 datasheet.
"""
from __future__ import annotations
from .equipment import size_zno

M_NI = 58.6934          # g/mol
M_NIO = 74.6924         # g/mol
NI_FRACTION_IN_NIO = M_NI / M_NIO


def nio_to_ni_wt_pct(nio_wt_pct):
    return nio_wt_pct * NI_FRACTION_IN_NIO


def inventory(cfg, feed_Nm3_h, dry_gas_Nm3_h, product_Nm3_h,
              sulfur_ppmv=5.0, feed_kmol_h=None):
    c = cfg.catalyst
    Vm = cfg.Vm
    g_r = c["GHSV_reformer_Nm3_per_m3cat_h"]
    g_p = c["GHSV_pre_reformer_Nm3_per_m3cat_h"]
    rho = c["commercial_proxy_loaded_density_kg_m3"]
    ni_wt = c["Ni_wt_pct_metal"] / 100.0
    V_reformer = feed_Nm3_h / g_r
    V_pre = feed_Nm3_h / g_p
    m_reformer = V_reformer * rho
    m_pre = V_pre * rho
    ni_reformer = m_reformer * ni_wt
    ni_pre = m_pre * ni_wt
    mass_total = m_reformer + m_pre
    ni_total = ni_reformer + ni_pre
    life = c["life_years"]
    hours = cfg.economics["operating_hours_per_year"]
    # ZnO guard (v1 sizing function, opened formula)
    z = size_zno(sulfur_ppmv, feed_kmol_h if feed_kmol_h is not None else dry_gas_Nm3_h / Vm / 1000.0,
                 life_years=2.0)
    sens = []
    for ly in c["life_range_years"]:
        sens.append({
            "life_years": ly,
            "catalyst_consumption_t_per_y": mass_total / 1000.0 / ly,
            "Ni_consumption_t_per_y": ni_total / 1000.0 / ly,
            # kg of annual Ni make-up per 1000 Nm3 of annual product. The two
            # /1000 factors used to cancel each other (V5.2 unit fix: the value
            # was kg per Nm3 while the key says kg per 1000 Nm3, i.e. 1000x low).
            "Ni_consumption_kg_per_1000Nm3": (ni_total / ly /
                                              (product_Nm3_h * hours) * 1000.0),
        })
    return {
        "basis": "Ni/MgAl2O4",
        "Ni_wt_pct_metal_used": c["Ni_wt_pct_metal"],
        "proxy_NiO_wt_pct": c["commercial_proxy_NiO_wt_pct"],
        "proxy_NiO_as_Ni_metal_wt_pct": nio_to_ni_wt_pct(c["commercial_proxy_NiO_wt_pct"]),
        "proxy_loaded_density_kg_m3": rho,
        "GHSV_reformer_Nm3_per_m3cat_h": g_r,
        "GHSV_pre_reformer_Nm3_per_m3cat_h": g_p,
        "reformer_catalyst_volume_m3": V_reformer,
        "pre_reformer_catalyst_volume_m3": V_pre,
        "total_catalyst_volume_m3": V_reformer + V_pre,
        "reformer_catalyst_mass_t": m_reformer / 1000.0,
        "pre_reformer_catalyst_mass_t": m_pre / 1000.0,
        "total_catalyst_mass_t": mass_total / 1000.0,
        "Ni_in_reformer_t": ni_reformer / 1000.0,
        "Ni_in_pre_reformer_t": ni_pre / 1000.0,
        "total_Ni_inventory_t": ni_total / 1000.0,
        # kg of installed Ni per 1000 Nm3 of ANNUAL product (inventory
        # intensity, not consumption - see Ni_consumption_kg_per_1000Nm3 in
        # life_sensitivity for the make-up rate). V5.2 unit fix: the previous
        # "/1000 /1000" cancelled and returned kg per Nm3.
        "Ni_per_1000Nm3_product_kg": (ni_total / (product_Nm3_h * hours) * 1000.0)
                                     if product_Nm3_h else None,
        "design_life_years": life,
        "catalyst_consumption_t_per_y": mass_total / 1000.0 / life,
        "Ni_consumption_t_per_y": ni_total / 1000.0 / life,
        "ZnO_guard_mass_kg": z["ZnO_mass_kg"],
        "ZnO_guard_life_years": 2.0,
        "life_sensitivity": sens,
        "source": c["source"], "status": c["status"],
        "NiO_to_Ni_conversion": "Ni wt% = NiO wt% * 58.6934/74.6924 = 0.78575",
    }
