# 17. V2 final report - synthesis gas from Russian natural gas on Ni/MgAl2O4

**Краткое заключение:** создана воспроизводимая модель (Python / DWSIM-эквивалент,
HYSYS не запускался) для пяти целевых продуктов - метанол, Фишер-Тропш,
оксо-синтез, водород, аммиак. Все пять вариантов выводятся на целевые
показатели настраиваемыми параметрами; обеспечены оба определения нормального
кубометра, площадки России и Ближнего Востока, расчёт объёмов катализатора
Ni/MgAl2O4 и потребности в никеле. Проверка: циклы 1-4 пройдены, цикл 5
(валидация/фальсификация) **не пройден** - нет экспериментальных данных и
коммерческого даташита Ni/MgAl2O4. Модель не объявляется «завершённой».

## 17.1 Key numbers (methanol base, Russia, 0 C/101325 Pa)

| value | number | unit | confidence |
|---|---|---|---|
| dry syngas | 100000 | Nm3/h | [ЧАСТИЧНО] - design basis |
| SN | 2.0500 | - | [ПОДТВЕРЖДЕНО] target range |
| X_CH4 | 0.7852 | - | [ЧАСТИЧНО] equilibrium + approach |
| T_out | 1123.2 | K | [ДОПУЩЕНИЕ] |
| p | 25.0 | bar(a) | [ДОПУЩЕНИЕ] |
| Z (PR) | 1.00295 | - | [ЧАСТИЧНО] k_ij |
| fired duty | 75008 | kW | [ЧАСТИЧНО] |
| fuel | 8875 | Nm3/h | [ЧАСТИЧНО] |
| total CO2 | 17.43 | t/h | [ЧАСТИЧНО] |
| cooling water | 6550 | m3/h | [ЧАСТИЧНО] |
| catalyst volume | 67.05 | m3 | [ЧАСТИЧНО] proxy density |
| Ni inventory | 9.052 | t | [ЧАСТИЧНО] |
| Ni make-up | 2.263 | t/y | [НЕ ПОДТВЕРЖДЕНО] life |
| T_wall,max | 1271.2 | K | [ЧАСТИЧНО] |
| levelised cost | 225.06 | USD/1000 Nm3 dry syngas | [ЧАСТИЧНО] class 5 |

## 17.2 All five variants

| product | metric | achieved | cost | unit | Ni t | CO2 t/h |
|---|---|---|---|---|---|---|
| methanol | SN | 2.0500 | 225.06 | USD/1000 Nm3 dry syngas | 9.05 | 17.43 |
| ft | H2_CO | 2.1000 | 214.39 | USD/1000 Nm3 dry syngas | 6.79 | 9.77 |
| oxo | H2_CO | 1.0500 | 249.50 | USD/1000 Nm3 dry syngas | 3.30 | 23.85 |
| hydrogen | H2_purity | 0.9997 | 364.98 | USD/1000 Nm3 H2 | 11.86 | 75.77 |
| ammonia | H2_N2 | 3.0012 | 600.09 | USD/t NH3 | 10.18 | 71.21 |

## 17.3 Five verification loops

| loop | status |
|---|---|
| 1_sources | PASS |
| 2_arithmetic | PASS |
| 3_conservation | PASS |
| 4_thermo | PASS |
| 5_validation_falsification | FAIL |

## 17.4 Not checked (see 13.6 for the full list)

- HYSYS / DWSIM / COCO steady-state run (not installed; user answer 11 confirms Python equivalent)
- Experimental pilot campaign for Ni/MgAl2O4 conversion, pressure drop and catalyst life
- Vendor Ni/MgAl2O4 catalyst datasheet: bulk density, Ni loading, crush strength, life
- Validated Xu-Froment kinetic parameter set (full primary text not opened; secondary set fails self-consistency)
- Sintering model discrimination: GPLE vs power-law life differ by factor ~3.06 (v1 finding)
- PSA vendor impurity-breakthrough curve (slip weights are calibrated assumptions)

## 17.5 Next step

Obtain an experimental/pilot dataset for 15 wt% Ni/MgAl2O4 (conversion vs T,
p, S/C, CO2/C; pressure drop; 200-1000 h sintering) and a vendor MgAl2O4
catalyst datasheet (bulk density, Ni loading, crush strength, life). Re-run
loop 5, then close the methanol CO2 trim and the downstream synthesis loops.
