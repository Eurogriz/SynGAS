# 25. Verification loop 5 after the V4 data acquisition (G8)

Контур 5 **перезапущен** с реальными внешними данными. Он остаётся
**НЕ ПРОЙДЕННЫМ**, но теперь это доказательный результат, а не просто
«нет данных».

**Вердикт:** FAILED (now evidence-based, not just absence-of-data)
**Причина:** External pilot data WERE found and compared. The model is an EQUILIBRIUM model; the lab data are KINETIC at 1-10 bar, so the mean bias is +0.287 X_CH4. A commercial Ni/MgAl2O4 catalyst datasheet, a design-point pilot campaign, a 200-1000 h sintering series and a certified HAZOP are still absent. The methanol kinetic model reproduces two opened benchmarks. The ammonia model was rebuilt as a multi-bed adiabatic converter and now needs ONE documented activity scalar (k_scale=0.213) to sit on the opened per-pass benchmark; the two opened ammonia benchmarks themselves disagree by a factor of 2.36 on that scalar, so this is calibration, not validation.

## 25.1 Подпроверки: 14 из 30

| статус | проверка | примечание |
|---|---|---|
| ПРОВЕРЕНО | external numeric pilot comparisons | 6 genuinely sourced X_CH4 points at 1-10 bar |
| ПРОВЕРЕНО | pressure trend reproduced | both measured and modelled X_CH4 fall from 1 to 10 bar |
| НЕ ПРОЙДЕНО | equilibrium model matches lab KINETIC conversion | mean bias = 0.287 (equilibrium overpredicts kinetic regime) |
| НЕ ПРОЙДЕНО | pilot data at model design point (20-31 bar, 15 wt% Ni/MgAl2O4) | no such dataset was found |
| НЕ ПРОЙДЕНО | measured packed-bed dP | no measured Ni/MgAl2O4 dP; Ergun correlation only |
| НЕ ПРОЙДЕНО | 200-1000 h sintering series | 100 h coking data and 500 h Rh data only |
| НЕ ПРОЙДЕНО | commercial Ni/MgAl2O4 CATALYST datasheet | 4 commercial MgAl2O4 SUPPORT powders found instead |
| ПРОВЕРЕНО | methanol VBF per-pass conversion in opened 25-30% (+0.2 pp) |  |
| ПРОВЕРЕНО | methanol VBF reproduces Arzew 3.4 mol% MeOH within 10% |  |
| НЕ ПРОЙДЕНО | NH3 Temkin-Pyzhev per-pass conversion in opened 15-25% |  |
| НЕ ПРОЙДЕНО | NH3 benchmark matched at an OPENED GHSV |  |
| НЕ ПРОЙДЕНО | NH3 adiabatic converter reaches the opened per-pass band at an OPENED GHSV with the PUBLISHED k0 | 0 of 6 grid rows inside the band; the single-bed rows sit at the adiabatic equilibrium |
| ПРОВЕРЕНО | k_scale calibration reproduces the opened benchmark AT THE BENCHMARK POINT | true BY CONSTRUCTION (the fit target is that number) - it validates the calibration pr |
| НЕ ПРОЙДЕНО | converter design point inside the wider opened 15-25% band | 200 bar design point sits slightly above the opened band; the band belongs to another  |
| НЕ ПРОЙДЕНО | the two opened NH3 benchmarks are mutually consistent | matching 17.5% per-pass needs k_scale=0.213, matching 13 mol% NH3 needs k_scale=0.504  |
| ПРОВЕРЕНО | the two opened NH3 benchmarks agree once BOTH are reduced to a per-pass conversion at one loop closure (tolerance = the opened band, fixed before the run) | matching the outlet figure needs a per-pass conversion of 22.30 %, which is outside th |
| ПРОВЕРЕНО | activity corridor (x2.362 on k_scale) propagated through catalyst volume, peak T, duty and recycle - as corridors, not points | model/activity_uncertainty.py + docs/32_v5_activity_band.md; T_peak turns out activity |
| ПРОВЕРЕНО | converter bed enthalpy balance closes (H=const per bed) | relative residual of the per-bed adiabatic invariant; the profile is written to result |
| НЕ ПРОЙДЕНО | converter peak bed T within the catalyst ceiling at the design inlet temperature | peak 845 K vs assumed ceiling 803 K; remedy (cooler inlets or more beds with cold shot |
| ПРОВЕРЕНО | converter recycle closure X*(1+RR) >= 1 at the configured RR |  |
| ПРОВЕРЕНО | converter NH3 formation consistent with loop stoichiometry within 5% |  |
| НЕ ПРОЙДЕНО | ammonia converter geometry / ceiling confirmed by vendor datasheet | no vendor converter datasheet; bed-T ceiling is an assumption (docs/28_v5_vendor_rfi.m |
| НЕ ПРОЙДЕНО | catalyst ACTIVITY pinned by operator data (corridor collapses to a point only with provenance; the V5.2 literature band is still printed next to it) | не введено - отчёт обязан оставаться коридорным (docs/32) |
| ПРОВЕРЕНО | operator data entry validated and consistently applied (docs/33; a rejected form is a FAILURE, not a silent no-op) |  |
| ПРОВЕРЕНО | operator form <-> docs/28 cross-reference resolves (every '28 п.N' in the form maps to a real RFI item and every RFI item is either linked or declared out of reach) | сопоставление построено разборкой таблицы docs/28: форма ссылается на номера пунктов,  |
| НЕ ПРОЙДЕНО | pilot campaign file ingested and validated against the contract | contract data/pilot_schema.json + harness model/data_ingest.py are in place and self-t |
| ПРОВЕРЕНО | model input-uncertainty envelope computed; it is shown NOT to explain the pilot/model bias (band <= |gap| at every point, and each design band reproduces the reported conversion) |  |
| ПРОВЕРЕНО | methanol ADIABATIC march reproduces the opened non-isothermal worked case of the rate law's own paper (VBF Table 3 / Fig. 5) |  |
| НЕ ПРОЙДЕНО | certified HAZOP (IEC 61882) | worksheet with 110 rows generated, but NOT certified |
| НЕ ПРОЙДЕНО | independent HYSYS / DWSIM run | not installed; Python equivalent confirmed by user answer 11 |

## 25.2 Ключевые внешние числа

- Питонных записей: 30, из них численных сравнений
  X_CH₄: **6**, качественных:
  4.
- Смещение равновесной модели относительно кинетических измерений:
  среднее **+0.287**, макс +0.461.
- Коммерческий даташит Ni/MgAl₂O₄ катализатора:
  **НЕ НАЙДЕН**;
  найдено даташитов носителя: 4.
- Экстраполированный t₅₀ = 109 ч
  против расчётных 32000 ч.
- HAZOP: 110 строк, сертификация = **НЕТ**.

## 25.3 Кинетика синтеза

| продукт | модель | за проход | диапазон из источника | бенчмарк | статус |
|---|---|---|---|---|---|
| methanol | VBF/Graaf LHHW | 30.2% | [0.25, 0.31] | 3.09 мол.% MeOH | [ДОПУЩЕНИЕ] effective GHSV=100000 1/h  |
| ammonia | Temkin-Pyzhev / Dyson-Simon | 8.8% | [0.15, 0.25] | 12.59 мол.% NH3 | [НЕ ПОДТВЕРЖДЕНО] absolute rate scale: |

## 25.4 Не проверено

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

## 25.5 Итог пяти контуров

| контур | статус |
|---|---|
| 1_sources | PASS |
| 2_arithmetic | PASS |
| 3_conservation | PASS |
| 4_thermo | PASS |
| 5_validation_falsification | FAIL |

Общий результат: **FAIL (контур 5 открыт)**.
Модель не объявляется завершённой.
