# 19. Safety screening: Ni(CO)₄, HAZOP, PSV (V3 continuation)

**Статус: скрининг, НЕ сертифицированный HAZOP / API 520/521.**
Полный текст API 520/521 в сессии открыт не был.

## 19.1 Ni(CO)₄

Ni(т) + 4CO(г) ⇌ Ni(CO)₄(г); log₁₀K = 7430/T − 21,90,
K = p(Ni(CO)₄)/p(CO)⁴ (OSTI 7349456, opened: ΔH = −142,3 кДж/моль,
ΔS = −419,2 Дж/моль/К). NIST WebBook по Ni(CO)₄ (opened).

- При нормальной работе T = 1123 K:
  0.00057 ppb — пренебрежимо мало.
- При остановке ниже 200 °C и **непродутом CO**
  равновесие предсказывает заметный Ni(CO)₄ (см. таблицу). Продувка до
  CO < 10 ppm перед охлаждением удерживает
  Ni(CO)₄ ниже 1 ppb — это совпадает с рекомендацией Becht (opened).
- **[ЧАСТИЧНО]** равновесный скрининг; кинетика на 15 мас.% Ni/MgAl₂O₄
  и активность поверхности Ni не моделировались.

| T C | Ni(CO)4 ppb без продувки | Ni(CO)4 ppb после продувки |
|---|---|---|
| 27 | 1.44e+09 | 0.00287 |
| 50 | 1.44e+09 | 4.83e-05 |
| 75 | 1.44e+09 | 1.08e-06 |
| 100 | 1.44e+09 | 4.01e-08 |
| 125 | 6.33e+08 | 2.25e-09 |
| 150 | 5e+07 | 1.78e-10 |
| 200 | 6.98e+05 | 2.48e-12 |
| 227 | 1e+05 | 3.56e-13 |

## 19.2 Предохранительный клапан (скрининг)

Заблокированный выход на линии питания реформера:
расход 34.03 кг/с,
p_уст = 27.5 бар,
поток 2752 кг/(м²·с),
требуемое отверстие 125.5 мм.
[ДОПУЩЕНИЕ] screening choked-flow estimate, not a certified PSV size

## 19.3 HAZOP-узлы (скрининг)

| узел | отклонение | защита |
|---|---|---|
| Feed desulfurization / ZnO guard | High H2S | lead-lag ZnO + online H2S analyser; <0.02 ppmv after guard [ЧАСТИЧНО] |
| R-100 pre-reformer | Low S/C / low T | S/C low-low trip, high Δp trip, carbon boundary check in model |
| R-101 fired reformer tubes | High tube-wall T | T_wall monitoring, 100000 h LMP design, Δp<=3 bar, skin thermocouples [ЧАСТИЧНО] |
| WHB / syngas cooler | Low level / high T | low-low level trip, PSV, IF97 dew-point margin |
| CO2 trim / MDEA | High CO2 slip | online SN analyser, reboiler steam ratio control |
| PSA / H2 product | CO/CO2 breakthrough | product GC, automatic product diversion |
| R-401 methanator (ammonia) | High T runaway | high-high T trip, feed analyser, <10 ppm spec |
| Synthesis loop (all products) | Inert accumulation | purge ratio control, recycle compressor trip |
| SHUTDOWN / standby | Low T + CO present | keep T>200 C until CO<10 ppm; N2 purge; Ni(CO)4 monitoring [ПОДТВЕРЖДЕНО] per Becht guidan |

## 19.4 Сера

H₂S на входе 5.0 ppmv → после ZnO
0.020 ppmv;
масса ZnO 65538 кг (lead-lag, [ЧАСТИЧНО]).

## 19.5 Не проверено

- certified HAZOP / LOPA
- API 520/521 PSV full text
- Ni(CO)4 kinetic rate on 15 wt% Ni/MgAl2O4
- toxic gas dispersion and detector layout
- ATEX/IECEx zoning
- SIS SIL verification
