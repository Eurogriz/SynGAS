# 22. Pilot dataset for 15 wt% Ni/MgAl₂O₄ and commercial datasheets (V4)

**Ни одно число в этом реестре не выдумано.** `data/pilot_ni_mgal2o4.json`
содержит 30 записей из 7 открытых
источников; у каждой записи есть URL и статус. `value: null` означает, что
источник сообщает тенденцию, но не приводит табличного числа.

## 22.1 Что реально найдено

| источник | работа | что даёт | статус |
|---|---|---|---|
| S1 | Saavedra Lopez et al., Catalysts 2019, 9(10), 801, doi:10.3390 | Full text opened in chunks 2/5/6; Tables 1 and 4 are images in HTML | [ПОДТВЕРЖДЕНО] |
| S2 | A Short Review on Ni Based Catalysts and Related Engineering I | HTML opened; Table 1/2 numeric content retrieved via the searchable fu | [ЧАСТИЧНО] |
| S3 | PNNL-32738, Stable Catalysts for Combined Dry and Steam Reform | Figures 8-10 contain genuinely tabulated numeric time-on-stream data | [ПОДТВЕРЖДЕНО] |
| S4 | Shen, Reule, Semagina, Int. J. Hydrogen Energy 2019, 44(10), 4 | Abstract and highlights opened; full text paywalled | [ЧАСТИЧНО] |
| S5 | Kinetics of steam reforming of methane on Rh-Ni/MgAl2O4 cataly | Abstract only; no numeric conversion table retrieved | [ЧАСТИЧНО] |
| S6 | Rh-Ni/MgAl2O4 catalyst for steam reforming of methane (Appl. C | Table text retrieved via search index; PDF not directly fetched | [ЧАСТИЧНО] |
| S7 | Sehested, J. Catal. 2001 (Ni sintering, first 200 h) | Abstract only from v1 session | [ЧАСТИЧНО] |

Ключевые числа (все — из открытых текстов):

- 15 мас.% Ni/MgAl₂O₄ (Sasol Puralox 30/140), BET 86 м²/г, Ni 6,6 нм,
  восстановление 850 °C/16 ч, TPR-пик 725 °C, H/Ni(пов) = 0,2 при 600 °C
  (Catalysts 2019, 9, 801). [ПОДТВЕРЖДЕНО]
- Порядок по этану 0,76, по воде 0, Ea = 79,1 кДж/моль; 1 атм, 550–900 °C,
  GHSV 22 000–356 000 ч⁻¹, τ = 10–170 мс, типичный опыт 9 мг катализатора.
  [ПОДТВЕРЖДЕНО]
- 100 ч при 850 °C, S/C = 1,5, τ = 2,3 мс, симулянт природного газа:
  Ni сохраняет **53 %** активности (Ir 91 %, Rh 78 %). Причина — коксование
  C₂₊, а не спекание. [ПОДТВЕРЖДЕНО]
- X_CH₄ = 40–50 % при 1 бар, 35–45 % при 5 и 10 бар (600 °C, S/C = 5,
  15 мас.% Ni/MgAl₂O₄). 0Rh15Ni: 49,4 % → 40,0 % при 1 → 10 бар.
  [ЧАСТИЧНО]
- 10 %Ni/Mg₂Al₂O₄, сухой риформинг CH₄:CO₂ = 1:1: X_CH₄ 50,0 / 65,8 /
  78,4 / 83,2 % при 650 / 700 / 750 / 800 °C (10 мин) и 47,6 / 62,6 /
  76,0 / 81,4 % (200 мин). [ЧАСТИЧНО] — другой катализатор и другая реакция.
- 3,4 мас.% Ni/MgAl₂O₄, 9,8 нм, 100 ч без дезактивации, 500–700 °C,
  CO₂/CH₄ = 0,76, O₂/CH₄ = 0,12–0,47, H₂/CO = 1,5–2,1. [ЧАСТИЧНО]

## 22.2 Коммерческий даташит: честный ответ

**Даташит коммерческого Ni/MgAl₂O₄ КАТАЛИЗАТОРА не найден.**
Найдены даташиты коммерческих **порошков носителя MgAl₂O₄**:

| поставщик | продукт | BET м²/г | насыпная плотность | статус |
|---|---|---|---|---|
| Novotech LLC | Magnesium Aluminate spinel nanopowder  | 152.8 | 300.0 г/л | [ПОДТВЕРЖДЕНО] |
| Sigma-Aldrich (Merck) | Magnesium aluminate, spinel nanopowder | - | - | [ЧАСТИЧНО] |
| Baikowski (France) | S30CR / S25CR MgAl2O4 spinel powder | [26.0, 31.0] | - | [ЧАСТИЧНО] |
| Sasol | Puralox 30/140 MgAl2O4 support | - | - | [ЧАСТИЧНО] |

Novotech 2130RS: насыпная плотность 300 г/л = 300 кг/м³, истинная 3,64 г/мл,
BET 152,8 м²/г, Al₂O₃ 71,73 %, MgO 28,64 %, S < 0,07 %, Tпл 2130 °C.
**Это насыпная плотность нанопорошка, а не плотность загрузки гранул**, поэтому
прокси JM KATALCO (900 кг/м³, α-Al₂O₃ / Ca-алюминат) из `cases/config.json`
остаётся необходимым и по-прежнему явно помечен как PROXY. [НЕ ПОДТВЕРЖДЕНО]

## 22.3 Сравнение модели с внешними данными (фальсификация)

| запись | p бар | T K | X изм. | X модель (равновесие) | Δ | применимость |
|---|---|---|---|---|---|---|
| P16 | 1.0 | 873.1 | 0.45 | 0.911 | 0.461 | outside model design point ( |
| P17 | 5.0 | 873.1 | 0.4 | 0.623 | 0.223 | outside model design point ( |
| P18 | 10.0 | 873.1 | 0.4 | 0.495 | 0.095 | outside model design point ( |
| P19 | 1.0 | 873.1 | 0.48 | 0.911 | 0.431 | outside model design point ( |
| P28 | 1.0 | 873.1 | 0.494 | 0.911 | 0.417 | outside model design point ( |
| P29 | 10.0 | 873.1 | 0.4 | 0.495 | 0.095 | outside model design point ( |

- Среднее смещение **+0.287**, макс +0.461,
  мин +0.095 по 6 точкам.
- Тренд по давлению воспроизведён: измерено 0.050,
  модель 0.416 (модель завышает чувствительность).
- Смещение **ожидаемо**: модель решает РАВНОВЕСИЕ, лабораторные данные —
  КИНЕТИКА при 1–10 бар и коротком времени контакта. Это опровергает
  использование равновесной модели как кинетического предиктора, но не
  валидирует расчётную точку 25 бар.

## 22.4 Ресурс и спекание

Экстраполяция 100-часовой потери активности до 50 % даёт
109 ч против расчётного ресурса
32000 ч (отношение
293×). Это НИЖНЯЯ граница:
измеренная дезактивация вызвана коксованием при S/C = 1,5, а не спеканием при
S/C = 3. Серии 200–1000 ч для 15 мас.% Ni/MgAl₂O₄ не найдено.
[НЕ ПОДТВЕРЖДЕНО]

## 22.5 Не закрыто

- NO pilot dataset at 20-31 bar with 15 wt% Ni/MgAl2O4 and S/C=3, CO2/C=0.76 (the model's design point)
- NO measured packed-bed pressure drop for 15 wt% Ni/MgAl2O4 at design gas velocity; Ergun remains a correlation
- NO 200-1000 h sintering series (Ni particle size vs time) for 15 wt% Ni/MgAl2O4; the 500 h point is for Rh/MgAl2O4
- NO tabulated X_CH4 vs S/C and vs CO2/C at fixed T,p for the unpromoted 15 wt% Ni/MgAl2O4
- NO commercial Ni/MgAl2O4 reforming-catalyst datasheet (see data/commercial_mgal2o4.json)
- All retrieved conversion data are in the KINETIC regime at 1-10 bar; the model is an EQUILIBRIUM model. Loop 5 therefore compares model equilibrium conversion to measured kinetic conversion and is expected to show a systematic positive bias.
