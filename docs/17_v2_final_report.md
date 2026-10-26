# 17. V2 final report - synthesis gas from Russian natural gas on Ni/MgAl2O4

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

| value | number | unit | confidence |
|---|---|---|---|
| dry syngas | 100000 | Nm3/h | [ЧАСТИЧНО] - design basis |
| SN | 2.0500 | - | [ПОДТВЕРЖДЕНО] target range |
| X_CH4 | 0.8053 | - | [ЧАСТИЧНО] equilibrium + approach |
| T_out | 1123.2 | K | [ДОПУЩЕНИЕ] |
| p | 25.0 | bar(a) | [ДОПУЩЕНИЕ] |
| Z (PR) | 1.00313 | - | [ЧАСТИЧНО] k_ij |
| fired duty | 90254 | kW | [ЧАСТИЧНО] |
| fuel | 10679 | Nm3/h | [ЧАСТИЧНО] |
| CO2 in make-up gas | 6.00 | mol% | [ПОДТВЕРЖДЕНО] 4-8 window |
| total CO2 handled | 48.88 | t/h | [ЧАСТИЧНО] |
| net CO2 to atmosphere | 20.97 | t/h | [ЧАСТИЧНО] recycle assumption |
| methanol product | 40.24 | t/h | [ЧАСТИЧНО] stoichiometry |
| pre-reformer T_out | 615.0 | K | [ЧАСТИЧНО] equilibrium |
| Ergun dP | 2.828 | bar | [ЧАСТИЧНО] sized to <=3 bar |
| Ni(CO)4 at operation | 0.00057 | ppb | [ЧАСТИЧНО] equilibrium |
| cooling water | 7325 | m3/h | [ЧАСТИЧНО] |
| catalyst volume | 78.45 | m3 | [ЧАСТИЧНО] proxy density |
| Ni inventory | 10.590 | t | [ЧАСТИЧНО] |
| Ni make-up | 2.648 | t/y | [НЕ ПОДТВЕРЖДЕНО] life |
| T_wall,max | 1271.2 | K | [ЧАСТИЧНО] |
| levelised cost | 261.60 | USD/1000 Nm3 dry syngas | [ЧАСТИЧНО] class 5 |

## 17.2 All five variants

| product | metric | achieved | saleable t/h | cost | unit | Ni t | net CO2 t/h |
|---|---|---|---|---|---|---|---|
| methanol | SN | 2.0500 | 40.24 | 261.60 | USD/1000 Nm3 dry syngas | 10.59 | 20.97 |
| ft | H2_CO | 2.1000 | 12.90 | 214.39 | USD/1000 Nm3 dry syngas | 6.79 | 9.77 |
| oxo | H2_CO | 1.0500 | 65.99 | 253.97 | USD/1000 Nm3 dry syngas | 4.95 | 0.00 |
| hydrogen | H2_purity | 0.9997 | 8.99 | 364.98 | USD/1000 Nm3 H2 | 11.86 | 75.77 |
| ammonia | H2_N2 | 3.0012 | 47.39 | 600.09 | USD/t NH3 | 10.18 | 71.21 |

Detail: `docs/18` (synthesis), `docs/19` (safety), `docs/20` (pre-reformer /
CO2 trim / hydraulics), `docs/21` (15-case matrix).

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
- Pilot campaign at 20-31 bar with 15 wt% Ni/MgAl2O4: X_CH4 vs T, p, S/C, CO2/C
- Measured packed-bed pressure drop at design velocity (Ergun is a correlation)
- 200-1000 h Ni particle-size / sintering series for 15 wt% Ni/MgAl2O4
- Commercial Ni/MgAl2O4 reforming CATALYST datasheet (Ni wt%, loaded density, crush strength, life)
- Validated Xu-Froment kinetic parameter set (secondary set fails self-consistency)

## 17.5 Next step

Further data needed: a pilot campaign at 20-31 bar with 15 wt% Ni/MgAl2O4
(X_CH4 vs T, p, S/C, CO2/C; measured dP; 200-1000 h sintering) and a vendor
Ni/MgAl2O4 CATALYST datasheet. Open pilot data at 1-10 bar WERE found and
compared (docs/22). Re-run loop 5 after that. The V2 methanol CO2 gap is
CLOSED (docs/20); stoichiometric
synthesis loops (docs/18) are now complemented by VBF/Graaf and
Temkin-Pyzhev kinetics (docs/23); real pilot data were collected and compared
(docs/22); a HAZOP worksheet was produced but is NOT certified (docs/24);
loop 5 was rerun and remains FAILED with 4/13 subchecks passing (docs/25).
