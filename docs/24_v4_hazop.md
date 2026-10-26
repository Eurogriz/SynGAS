# 24. HAZOP worksheet (V4) — **НЕ СЕРТИФИЦИРОВАНО**

> **ЯВНОЕ ПРЕДУПРЕЖДЕНИЕ.** Сертифицированный HAZOP невозможен без
> междисциплинарной команды, независимого ведущего (facilitator),
> проверенных P&ID, подписанного технического задания, закрытия действий и
> подписи руководства. Ничего этого здесь НЕ было. Данный документ —
> автоматически сгенерированный **шаблон рабочей таблицы** по структуре
> IEC 61882 (полный текст стандарта НЕ открывался).
> Статус: **[НЕ ПОДТВЕРЖДЕНО] NOT A CERTIFIED HAZOP**.
> Не используйте его как обоснование безопасности или доказательство
> соответствия.

## 24.1 Объём

10 узлов × 11 направляющих слов =
**110 строк** рабочей таблицы, из них
**20** с риском ≥ 6 (матрица 3×3, приори — **[ДОПУЩЕНИЕ]**).
Полная таблица: `results_v2/hazop_worksheet.csv` и
`results_v2/hazop_worksheet.json`.

| узел | назначение |
|---|---|
| N01 | Natural-gas feed / HDS-ZnO guard — deliver S<0.02 ppmv gas at 30 bar |
| N02 | R-100 adiabatic pre-reformer — remove C2+ at 600-750 K, Q=0 |
| N03 | R-101 fired tubular reformer — 1123 K, 25 bar, SN=2.05 |
| N04 | WHB / syngas cooler — recover heat, raise 30 bar steam |
| N05 | A-302 CO2 trim / A-301 MDEA — CO2 to 4-8 mol% / <3 mol% |
| N06 | E-601 cooler + knockout + dryer — product at 40/55 C |
| N07 | PSA / methanator — ISO 14687 H2 / <10 ppm CO+CO2 |
| N08 | Synthesis loop + recycle compressor — MeOH/FT/oxo/NH3 product |
| N09 | SHUTDOWN / standby / Ni(CO)4 — CO<10 ppm before T<200 C |
| N10 | PSV / flare / relief network — protect against blocked outlet |

Направляющие слова: NO/LOW FLOW, HIGH FLOW, HIGH P, LOW P, HIGH T, LOW T, WRONG COMPOSITION, REVERSE FLOW, LEAK/RUPTURE, UTILITY FAILURE, STARTUP/SHUTDOWN.

## 24.2 Примеры строк с высоким риском

| узел | слово | причина | последствие | защита | риск |
|---|---|---|---|---|---|
| Natural-gas feed / HDS-ZnO guard | HIGH T | firing maldistribution, loss of quench, ex | tube creep rupture (LMP), Ni sintering, Ni | skin thermocouples, high-high T trip, LMP- | 6 |
| Natural-gas feed / HDS-ZnO guard | STARTUP/SHUTDOWN | incomplete purge, wrong sequence, CO prese | Ni(CO)4 formation, explosive mixture, resi | written purge procedure, CO<10 ppm permit, | 6 |
| R-100 adiabatic pre-reformer | HIGH T | firing maldistribution, loss of quench, ex | tube creep rupture (LMP), Ni sintering, Ni | skin thermocouples, high-high T trip, LMP- | 6 |
| R-100 adiabatic pre-reformer | STARTUP/SHUTDOWN | incomplete purge, wrong sequence, CO prese | Ni(CO)4 formation, explosive mixture, resi | written purge procedure, CO<10 ppm permit, | 6 |
| R-101 fired tubular reformer | HIGH T | firing maldistribution, loss of quench, ex | tube creep rupture (LMP), Ni sintering, Ni | skin thermocouples, high-high T trip, LMP- | 6 |
| R-101 fired tubular reformer | STARTUP/SHUTDOWN | incomplete purge, wrong sequence, CO prese | Ni(CO)4 formation, explosive mixture, resi | written purge procedure, CO<10 ppm permit, | 6 |
| WHB / syngas cooler | HIGH T | firing maldistribution, loss of quench, ex | tube creep rupture (LMP), Ni sintering, Ni | skin thermocouples, high-high T trip, LMP- | 6 |
| WHB / syngas cooler | STARTUP/SHUTDOWN | incomplete purge, wrong sequence, CO prese | Ni(CO)4 formation, explosive mixture, resi | written purge procedure, CO<10 ppm permit, | 6 |
| A-302 CO2 trim / A-301 MDEA | HIGH T | firing maldistribution, loss of quench, ex | tube creep rupture (LMP), Ni sintering, Ni | skin thermocouples, high-high T trip, LMP- | 6 |
| A-302 CO2 trim / A-301 MDEA | STARTUP/SHUTDOWN | incomplete purge, wrong sequence, CO prese | Ni(CO)4 formation, explosive mixture, resi | written purge procedure, CO<10 ppm permit, | 6 |
| E-601 cooler + knockout + dryer | HIGH T | firing maldistribution, loss of quench, ex | tube creep rupture (LMP), Ni sintering, Ni | skin thermocouples, high-high T trip, LMP- | 6 |
| E-601 cooler + knockout + dryer | STARTUP/SHUTDOWN | incomplete purge, wrong sequence, CO prese | Ni(CO)4 formation, explosive mixture, resi | written purge procedure, CO<10 ppm permit, | 6 |

## 24.3 Что требуется для сертификации

1. No chartered multi-disciplinary HAZOP team was convened (IEC 61882 requires a team).
2. No independent competent facilitator / scribe was appointed.
3. No reviewed and frozen P&IDs, cause-and-effect matrix or safeguard list existed.
4. No signed terms of reference, scope, node definition by a responsible engineer.
5. No LOPA / SIL verification (IEC 61508 / IEC 61511) of the proposed safeguards.
6. No action close-out, management sign-off or re-HAZOP after design change.
7. No consequence modelling (dispersion, fire, explosion, toxic Ni(CO)4 plume).
8. No ATEX/IECEx hazardous-area classification or detector layout study.
9. No MOC (management of change) record for the V2/V3 design modifications.

## 24.4 Связь с расчётом

- Ni(CO)₄: log₁₀K = 7430/T − 21,90 (OSTI 7349456, открыт); при работе
  0,0006 ppb, при останове нужна продувка CO < 10 ppm до охлаждения ниже
  200 °C — см. `docs/19`.
- PSV: только скрининг по критическому истечению, **не** сертификация
  API 520/521.
- Δp и LMP: `docs/20`; ЛОВЕР-сценарии здесь не заменяют SIL-верификацию.
