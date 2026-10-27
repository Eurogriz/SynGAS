# 13. V2 maximum-accuracy verification (five loops, G8)

HYSYS status: **NOT RUN**. User answer 11 = "otherwise confirm" -> the
Python/DWSIM-equivalent plus `docs/HYSYS_case_spec.md` is CONFIRMED as the
accepted equivalent. No claim of a HYSYS run is made.

## 13.1 Loop summary

| loop | passed | key number |
|---|---|---|
| 1_sources | YES | 90 claims |
| 2_arithmetic | YES | max rel error 1.84e-16 |
| 3_conservation | YES | max error 1.6e-12% |
| 4_thermo | YES | Q*Kphi/K dev 2.376e-12% |
| 5_validation_falsification | NO | FAILED (now evidence-based, not just absence-of-data) |

Overall: **FAIL (loop 5 open by design)**.

## 13.2 Loop 1 - sources and claims

90 registered claims: {'[ПОДТВЕРЖДЕНО]': 31, '[ЧАСТИЧНО]': 40, '[ДОПУЩЕНИЕ]': 14, '[НЕ ПОДТВЕРЖДЕНО]': 5}.
Problems: []. Full registry: `data/v2_claims.json`,
`docs/v2_claims_register.md`.

## 13.3 Loop 2 - arithmetic

40 independent recomputations, worst relative
error 1.84e-16
({'product': 'oxo', 'name': 'Ni_inventory'}).

## 13.4 Loop 3 - conservation

Worst element/enthalpy imbalance 1.6e-12%.
The full-flowsheet check explicitly includes condensed water, MDEA CO2 product,
PSA tail gas and dryer water.

## 13.5 Loop 4 - thermodynamic consistency

- Real-gas equilibrium: worst |Q*Kphi/K - 1| = 2.376e-12%.
- Compressibility factors by product:
| product | Z | Kphi_R1 | Q1/K1 (real) |
|---|---|---|---|
| methanol | 1.00313 | 1.01622 | 1.00000000 |
| ft | 1.00339 | 1.00701 | 1.00000000 |
| oxo | 1.00318 | 1.00757 | 1.00000000 |
| hydrogen | 1.00288 | 1.01626 | 1.00000000 |
| ammonia | 1.00434 | 1.01560 | 1.00000000 |
- Shomate vs NASA7 reaction enthalpies at 1123 K:
| reaction | Shomate kJ/mol | NASA7 kJ/mol | difference |
|---|---|---|---|
| SMR | 226.785 | 225.787 | 0.997 |
| WGS | -33.565 | -33.556 | -0.009 |
| DRM | 260.349 | 259.343 | 1.006 |
| H2OX | -248.590 | -248.585 | -0.004 |
- IAPWS-IF97: h(30 bar, 673.15 K) = 3231.571 kJ/kg
  (reference 3231.571), Tsat(30 bar) = 507.008 K
  (reference 507.008). Status [ЧАСТИЧНО]: the IF97 revision guide was NOT opened;
  the installed package version is pinned.
- Dew point IF97 313.15 K vs NIST Antoine
  313.17 K; difference
  0.02 K. This is why IF97 is the primary
  water/steam property source in V2.
- PR vs ideal X_CH4: 0.80884 -> 0.80730 (delta -0.00155); k_ij spread in X_CH4 = 0.001779.
- **Independent SciPy SLSQP** real-gas minimisation: success = True, max |Δy_wet| = 1.0949905260293491e-08, X_CH4 SciPy 0.807295 vs model 0.807295. [ПОДТВЕРЖДЕНО] numerical cross-check.
- Extra V3 checks: {'scipy': True, 'prereformer': True, 'synthesis': True, 'safety': True, 'dP': True, 'NH3_Ka_vs_NIST': True, 'NH3_layout_scan': True, 'NH3_activity_band': True}. Pre-reformer C2+ conversion >0,99; saleable product >0; Ni(CO)4 in normal operation <1 ppb; Ergun Δp ≤ 3 bar after tube-count sizing.
| продукт | C2+ конверсия | продукт т/ч | Ni(CO)4 ppb | Δp бар | труб |
|---|---|---|---|---|---|
| methanol | 0.9994 | 40.24 | 0.00057 | 2.828 | 509 |
| ft | n/a | 12.90 | 4.36e-05 | 0.226 | 1 |
| oxo | n/a | 65.99 | 0.000434 | 0.185 | 1 |
| hydrogen | 0.9997 | 8.99 | 9.04e-29 | 2.830 | 512 |
| ammonia | 0.9997 | 47.39 | 7.54e-24 | 2.830 | 411 |

## 13.6 Loop 5 - validation / falsification

**FAILED (now evidence-based, not just absence-of-data)**.
External pilot data WERE found and compared. The model is an EQUILIBRIUM model; the lab data are KINETIC at 1-10 bar, so the mean bias is +0.287 X_CH4. A commercial Ni/MgAl2O4 catalyst datasheet, a design-point pilot campaign, a 200-1000 h sintering series and a certified HAZOP are still absent. The methanol kinetic model reproduces two opened benchmarks. The ammonia model was rebuilt as a multi-bed adiabatic converter and now needs ONE documented activity scalar (k_scale=0.213) to sit on the opened per-pass benchmark; the two opened ammonia benchmarks themselves disagree by a factor of 2.36 on that scalar, so this is calibration, not validation.

Unchecked items:
1. HYSYS / DWSIM / COCO steady-state run (not installed; user answer 11 confirms Python equivalent)
2. Pilot campaign at 20-31 bar with 15 wt% Ni/MgAl2O4: X_CH4 vs T, p, S/C, CO2/C
3. Measured packed-bed pressure drop at design velocity (Ergun is a correlation)
4. 200-1000 h Ni particle-size / sintering series for 15 wt% Ni/MgAl2O4
5. Commercial Ni/MgAl2O4 reforming CATALYST datasheet (Ni wt%, loaded density, crush strength, life)
6. Ammonia converter vendor data: bed-T ceiling, GHSV basis, pressure drop, catalyst size distribution (docs/28_v5_vendor_rfi.md items 12-18)
7. Certified HAZOP team / facilitator for the worksheet in docs/29 (terms of reference issued, no team convened)
8. Measured NH3 converter per-pass data on THIS catalyst at 150-250 bar (k_scale is fitted to a literature plant benchmark, not to our pilot)
9. Validated Xu-Froment kinetic parameter set (secondary set fails self-consistency)
10. Sintering model discrimination GPLE vs power-law (factor ~3.06, v1 finding)
11. PSA vendor breakthrough curve and MDEA vendor reboiler guarantee
12. Absolute Temkin-Pyzhev activity scale: V4's 'GHSV ~1000 1/h' figure was an ARTIFACT of using the actual-basis volumetric flow; on the normal basis the 3-bed converter sits 20-40% ABOVE the opened band with published k0, and the remaining k_scale=0.213 cannot be separated from the vendor's own activity/packing definition without plant or pilot converter data
13. Kinetic models for FT and oxo loops; external propylene cost
14. Certified HAZOP / LOPA / SIL verification, API 520/521 PSV full text, Ni(CO)4 kinetics
15. API 530 / ASME certified tube creep calculation; regional price quotes; GOST 5542 full text

## 13.7 Equipment accuracy upgrades

- 1-D tube thermal profile with local equilibrium composition;
  T_wall,max for methanol = 1271.2 K
  (998.0 C),
  consistent with the ~1000 C wall reported in the opened electrified-SMR study.
- LMP creep: C = 22.4, one opened HP-Nb point (11 MPa at LMP 35.2),
  API 530 thin-cylinder equation t = P*Do/(2S+P) + corrosion allowance.
  Required thickness 0.01427 m
  vs specified 0.01500 m
  -> PASS.
  The master-curve slope is an [ДОПУЩЕНИЕ]; this is NOT an API 530 certification.
- Ergun dP for the packed tubes: 2.828 bar
  (limit 3.00 bar).
