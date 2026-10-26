# Журнал поиска (G1)

Дата: 26.10.2026. Инструменты сессии: `web_search` (полнотекстовый поиск по открытому
вебу, глубина 1–3) и `fetch_page` (чтение HTML/PDF, до 30 страниц PDF). Прямой сетевой
доступ из shell ограничен github.com / codeload / api.github.com / registry.npmjs.org /
pypi.org / files.pythonhosted.org.

## 1. Реально охваченное

| База / ресурс | Доступ | Что получено |
|---|---|---|
| NIST Chemistry WebBook (SRD 69) | **открыт, прочитан** | Shomate для CH₄, H₂O(g/l), CO, CO₂, H₂, O₂, N₂; Antoine H₂O; Ni и Al₂O₃ конденсированные фазы; Ni(CO)₄ термохимия |
| NIST-JANAF (через WebBook, Chase 1998) | **открыт** | те же данные, стандартное состояние 1 бар |
| JANAF tables (janaf.nist.gov) | открыт | проверка формата: `C-008.html` оказался B₄C, а не графит → графит взят из NASA TM-4513 |
| NASA TM-4513 / SP-273 (через Cantera 3.2.0 `nasa_condensed.yaml`, `graphite.yaml`) | **открыт (локальный файл с проверенным заголовком)** | T_пл Ni 1728 K, Al₂O₃ 2327 K, MgAl₂O₄ 2408 K, ZrO₂ 2950 K; NASA7 для графита |
| GRI-Mech 3.0 (`gri30.yaml`, `critical-properties.yaml`) | **открыт локально** | независимые NASA7 для газов, C₂H₆; Tc/pc/ω для Peng–Robinson. Верхний URL `combustion.berkeley.edu/.../text30.html` вернул 404 |
| Crossref API | **открыт** | проверка DOI 10.1002/aic.690350109 (Xu & Froment, 1989, 35(1) 88–96) |
| Google Patents | **открыт** | EP1013603A1, US3436358A, US7541005B2, US9393552B2, US4919844A, WO2019228797A1, EP0279389A1 — примеры, CPC, приоритет, правовой статус |
| ScienceDirect (абстракты и открытые фрагменты) | **открыты абстракты** | S0021951700930859 (Sehested 2001), S0021951714001109 (Mei 2014), S0263876217304173, S0926860X15002264, S0360544225001823 |
| MDPI (Catalysts, Processes, Energies, Carbon Capture Util.) | **открыты полностью** | 10.3390/catal9100801; 10.3390/pr8040408; 10.3390/en13112792; 10.3390/pr808? ; MDPI 2673-4141/6/4/94 |
| White Rose ePrints / SciELO / ResearchGateabstracts / UCLA / PNNL | **открыты PDF** | PNNL-23207; Abbas et al. 2017 (S0360319916333821); Fernandes & Soares 2006;tube-life PDF; IEAGHG/Linde ASU PDF |
| Wiley/ACS/RSC/Springer (полные тексты) | **закрыты** | только абстракты |
| eLibrary.ru, CNKI, J-PlatPat, KIPRIS, Espacenet, WIPO PATENTSCOPE, USPTO Patent Public Search, ФИПС, CNIPA, The Lens, Derwent | **недоступны из сессии** | пробел в патентном/FTO поиске |
| Scopus, Web of Science, ScienceDirect полные тексты, ACS, RSC | **недоступны** | пробел в полнотекстовом рецензируемом поиске |
| Aspen HYSYS / DWSIM / COCO | **не установлены** | см. docs/HYSYS_case_spec.md |

## 2. Запросы (журнал)

| # | Запрос (язык) | Результатов (оценка по выдаче) | Отобрано | Причина отбора/отбраковки |
|---|---|---|---|---|
| Q01 | `Xu Froment 1989 methane steam reforming intrinsic kinetics AIChE DOI` (en) | ~20 | 3 | DOI, библиография, кинетика; полный текст недоступен |
| Q02 | `Xu Froment kinetic parameters table preexponential activation energy adsorption constants PDF` (en) | ~18 | 2 | вторичные таблицы параметров |
| Q03 | `"Xu and Froment" "240100" OR "1.17" kinetic parameters ...` (en) | ~20 | 2 | COMSOL PDF и academia.edu; неполные таблицы |
| Q04 | `Ni/MgAl2O4 steam reforming catalyst Ni particle size after aging steam 800 °C sintering BET` (en) | ~15 | 4 | PNNL-23207, Mei 2014, Catalysts 2019, Sehested 2001 |
| Q05 | `gamma alumina to alpha phase transformation temperature ... surface area loss` (en) | ~19 | 3 | JACerS 2024, Bol. Soc. Esp. Ceram. 2017, Appl. Surf. Sci. 2015 |
| Q06 | `steam methane reforming industrial operating conditions outlet 850 C 20-30 bar S/C 3` (en) | ~20 | 4 | Energy 2025 (open access), MDPI 2025, Processes 2020, gasprocessingnews |
| Q07 | `site:patents.google.com/patent Ni MgAl2O4 steam reforming catalyst nickel spinel` (en) | ~17 | 6 | патентное семейство и CPC |
| Q08 | `nickel steam reforming catalyst sulfur poisoning feed sulfur limit ppbv ZnO` (en) | ~19 | 3 | JM webinar PDF, AFPM Q&A, Springer chapter |
| Q09 | `cryogenic air separation unit specific power kWh per tonne O2 99.5%` (en) | ~21 | 2 | IEAGHG/Linde 2009 PDF, Air Liquide PDF |
| Q10 | `nickel carbonyl Ni(CO)4 formation temperature CO reduced nickel shutdown` (en) | ~16 | 3 | NIST WebBook, Becht note, Mond-process техника |
| Q11 | `steam reformer tube wall temperature 900 C maximum design skin temperature` (en) | ~18 | 3 | S0263876217304173, NDT.net, Processes 2020 |
| Q12 | `"Xu and Froment" adsorption constants "K_CH4" ...` (en) | ~27 | 2 | SciELO 2006 (полный набор), uoc.gr PDF (не открылся), scirp/JCRA |
| Q13 | `"Xu and Froment" kinetic parameters table "k1" "k2" "k3" "K_CH4" ...` (en) | ~11 | 1 | White Rose PDF с Table 3 |
| Q14 | `site:patents.google.com/patent electrically heated steam reforming` (en, через Q07) | — | 1 | WO2019228797A1 |

Языки: фактически **только английский**. Русский, китайский, японский, корейский
запросы **не выполнялись** — это объявленный пробел (риск R-08). Числа из неанглоязычных
источников не использовались.

## 3. Патентный обзор (не юридическое заключение)

| Патент | Приоритет / заявитель | Статус (Google Patents) | CPC | Что использовано |
|---|---|---|---|---|
| US3436358A | 29.12.1962, Haldor Topsoe | Expired – Lifetime | B01J23/755, C01B3/38, C01B3/40 | исторический носитель MgAl₂O₄ ≥50–70 мас.%, прочность 600 кг/см² |
| EP1013603A1 | 22.12.1998, Haldor Topsoe AS | **Ceased** (семейство: ZA9907709A; US09/467,242 Expired – Fee Related; JP11363049A Pending; NO996376A Discontinuation) | B01J21/005, B01J23/755, B01J35/615, C01B3/38 | Ni 10–60 мас.%; промоторы Zr/Y/W/La/Ce 0,01–10 мас.%; шпинель 183–192 м²/г после 550 °C; критерий Asp > 400·exp(−Tc/400 °C) |
| US7541005B2 | 06.10.2005, Siemens Energy | Expired – Fee Related | F23C13/08 | T_пл MgAl₂O₄ = 2135 °C = 2408 K |
| US9393552B2 | — | см. Google Patents | B01J23/755 | 2–16 мас.% Ni + 0,01–0,5 мас.% Rh/Ir на MgAl₂O₄/Al₂O₃ |
| EP0279389A1 | — | см. Google Patents | B01J23/755 | Ni 2–20 мас.% на алюминате кальция |
| US4919844A | — | см. Google Patents | C01B3/38, C01B3/382, B01J8/067 | газонагреваемый реформер как альтернатива |
| WO2019228797A1 | Topsoe | см. Google Patents | C01B3/384, B01J15/005 | реформер с резистивным нагревом; max T стенки ≈1000 °C |

Проверка классификации CPC выполнена по открытым страницам: **C01B3/38, B01J23/755,
B01J21/005, B01J37/02, C01B3/384** актуальны. Цитирования вперёд/назад и география
прослежены только для EP1013603A1. Полноценный FTO не проводился; решение остаётся
за патентным поверенным.

## 4. Целенаправленный поиск опровержений

- Найдены отрицательные/ограничивающие данные: γ→α переход Al₂O₃ и потеря >80 % поверхности;
  рост Ni 7,7→27 нм за 700 ч; «большинство спекания за первые 200 ч»;
  коксование DRM (наша модель: графит стабилен при CO₂/C = 1 и S/C = 0);
  сравнение кинетических моделей, где Xu–Froment не лучшая (S0098135421001575).
- Обнаружено **внутреннее противоречие вторичного источника**: напечатанные параметры
  Xu–Froment не воспроизводят его же кривую конверсии (docs/11). Это зафиксировано,
  а не сглажено.

## 5. Объявленные пробелы

S35 платформы полнотекстового/патентного поиска; S36 стандарты API/ASME/TEMA/ASTM;
S37 HYSYS/DWSIM/COCO; S38 коммерческие спецификации катализаторов; S40 AACE 18R-97;
S45 Hou & Hughes (PDF найден, не открыт); полный текст Xu & Froment 1989 (S15/S16).
