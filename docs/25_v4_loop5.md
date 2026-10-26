# 25. Verification loop 5 after the V4 data acquisition (G8)

Контур 5 **перезапущен** с реальными внешними данными. Он остаётся
**НЕ ПРОЙДЕННЫМ**, но теперь это доказательный результат, а не просто
«нет данных».

**Вердикт:** FAILED (now evidence-based, not just absence-of-data)
**Причина:** External pilot data WERE found and compared. The model is an EQUILIBRIUM model; the lab data are KINETIC at 1-10 bar, so the mean bias is +0.287 X_CH4. A commercial Ni/MgAl2O4 catalyst datasheet, a design-point pilot campaign, a 200-1000 h sintering series and a certified HAZOP are still absent. The methanol kinetic model reproduces two opened benchmarks; the ammonia kinetic model does not.

## 25.1 Подпроверки: 4 из 13

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
6. Validated Xu-Froment kinetic parameter set (secondary set fails self-consistency)
7. Sintering model discrimination GPLE vs power-law (factor ~3.06, v1 finding)
8. PSA vendor breakthrough curve and MDEA vendor reboiler guarantee
9. Absolute rate scale of the Temkin-Pyzhev PFR (needs GHSV ~1000 1/h to match 13 mol% NH3)
10. Kinetic models for FT and oxo loops; external propylene cost
11. Certified HAZOP / LOPA / SIL verification, API 520/521 PSV full text, Ni(CO)4 kinetics
12. API 530 / ASME certified tube creep calculation; regional price quotes; GOST 5542 full text

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
