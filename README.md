# SynGAS — модель синтез-газа из природного газа на Ni/MgAl₂O₄

**Статус (26.10.2026):** V2 (ответы на 12 вопросов G0) реализована и запущена.
Пять целевых продуктов, оба определения нормального м³, две площадки,
регулируемая конфигурация, Peng–Robinson + IAPWS-IF97, инвентаризация
Ni/MgAl₂O₄. **Aspen HYSYS не запускался** — его нет в среде; пользователь
подтвердил Python/DWSIM-эквивалент (вопрос 11). Пять контуров проверки:
1–4 **пройдены**, контур 5 (валидация/фальсификация) **не пройден** —
нет экспериментальных/пилотных данных и коммерческого даташита Ni/MgAl₂O₄.
Работа **не объявляется завершённой**.

## Быстрый запуск

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt       # ядро — чистый stdlib; пакеты нужны для IF97/PR-проверок, графиков, панели
PYTHONPATH=. .venv/bin/python -m model.run_v2  # ~100 с -> results_v2/ + docs/12..17
PYTHONPATH=. .venv/bin/python -m pytest -q     # 22 теста
PYTHONPATH=. .venv/bin/python -m model.run     # V1 (метанол, ~10 с) -> results/
```

Если `iapws` не установлен, модель автоматически переходит на NIST Shomate +
Antoine и явно помечает это в `results_v2/summary_v2.json`.

## Живая панель управления (регулировка, вопросы 2/7)

```bash
PYTHONPATH=. .venv/bin/python -m web.app        # 0.0.0.0:5000, Arena live preview
```

В браузере: выбор продукта / нормального м³ / площадки / сырья / набора kᵢⱼ /
таблицы пара, ползунки S/C, CO₂/C, O₂/C, T, p, approach, срока службы и
содержания Ni, GHSV, плотности, цен газа/электроэнергии/CO₂/пара. Кнопки:
расчёт, сравнение 5 продуктов, регулировочная кривая, 5 циклов проверки,
скачивание конфигурации. Браузер обращается только к относительным `/api/*` —
никаких `localhost`.

CLI (без браузера):

```bash
PYTHONPATH=. .venv/bin/python -m model.control list
PYTHONPATH=. .venv/bin/python -m model.control show --product ft
PYTHONPATH=. .venv/bin/python -m model.control run --product methanol \
  --set economics.gas_USD_per_MMBtu=6 --set active.normal=15C
PYTHONPATH=. .venv/bin/python -m model.control compare
PYTHONPATH=. .venv/bin/python -m model.control sweep --product oxo
PYTHONPATH=. .venv/bin/python -m model.control verify
PYTHONPATH=. .venv/bin/python -m model.control set active.climate middle_east
```

## Что где (V2)

| Путь | Содержание |
|---|---|
| `cases/config.json` | **единый источник истины**: продукты, нормальные условия, климаты, сырьё, утилиты, катализатор, kᵢⱼ, цены |
| `model/config.py` | загрузка, точечные переопределения (`"products.ft.knobs.O2C"`) |
| `model/products.py` | 5 вариантов, настройка (биссекция CO₂/C, O₂/C, воздуха), WGS/MDEA/PSA/метанатор, утилиты, экономика |
| `model/eos.py`, `model/steam.py` | Peng–Robinson (kᵢⱼ zero/base/high), IAPWS-IF97 + NIST-fallback |
| `model/equipment_v2.py` | 1-D профиль трубы, Ergun Δp, LMP-ползучесть, ATR-сосуд |
| `model/catalyst_inventory.py` | объёмы, масса, срок службы, расход Ni, ZnO |
| `model/scenarios.py`, `model/run_v2.py` | матрицы сценариев, CSV/JSON/PNG, генерация отчётов |
| `model/verify_v2.py` | пять контуров проверки V2 |
| `model/control.py`, `web/app.py` | CLI и живая панель |
| `data/v2_claims.json`, `docs/v2_claims_register.md` | реестр 33 утверждений V2 |
| `docs/12_v2_product_variants.md` | 5 продуктов, маршруты, оба нормальных м³, kᵢⱼ |
| `docs/13_v2_accuracy_verification.md` | максимум точности: PR, IF97, LMP, 5 контуров |
| `docs/14_v2_catalyst_nickel.md` | Ni/MgAl₂O₄: объёмы, срок, расход, никель |
| `docs/15_v2_site_cases.md` | Россия / Ближний Восток, утилиты |
| `docs/16_v2_config_control_guide.md` | как регулировать, HYSYS-эквивалент |
| `docs/17_v2_final_report.md` | итоговый отчёт V2 |
| `results_v2/` | `summary_v2.json`, `verification_v2.json`, `design_*.json`, 7 CSV, 7 PNG |

V1 (метанольный базовый кейс) сохранён без изменений: `docs/00`–`docs/11`,
`results/`, `model/run.py`, `model/flowsheet.py`, `model/validation.py`.

## Ключевые числа V2 (Россия, 0 °C/101325 Па)

| Продукт | Метрика | Достигнуто | Ni, т | Стоимость |
|---|---|---|---|---|
| метанол | SN 2,05 | 2,0500 | 9,05 | 225 USD/1000 нм³ сухого СГ |
| Фишер–Тропш | H₂/CO 2,10 | 2,1000 | 6,79 | 214 USD/1000 нм³ |
| оксо | H₂/CO 1,05 | 1,0500 | 3,30 | 249 USD/1000 нм³ |
| водород | 99,97 % H₂ (ISO 14687) | 0,99970 | 11,86 | 365 USD/1000 нм³ H₂ |
| аммиак | H₂/N₂ 3,00 | 3,0012 | 10,18 | 600 USD/т NH₃ |

Небаланс по элементам ≤ 2·10⁻¹² %, по арифметике ≤ 2·10⁻¹⁶ (отн.),
Q·Kφ/K = 1 с погрешностью ≤ 10⁻¹¹ %. Переход 0 °C → 15 °C меняет все
объёмные потоки на +5,49 % при том же молярном заводе.

## Важно

* Все числа прослеживаются к открытым источникам или помечены
  [ДОПУЩЕНИЕ] / [ЧАСТИЧНО] / [НЕ ПОДТВЕРЖДЕНО].
* Коммерческий даташит именно **Ni/MgAl₂O₄** не найден; плотность/срок/NiO
  взяты из открытой брошюры JM KATALCO как ЯВНЫЙ ПРОКСИ (там носитель
  α-Al₂O₃ / Ca-алюминат). Химия 15 мас.% Ni/MgAl₂O₄ — из открытой статьи
  Catalysts 2019, 9, 801.
* Нет вывода о патентной свободе, нет сертификации API 530/ASME, нет
  экспериментальной валидации кинетики Xu–Froment.
* Полный список непроверенного — `docs/13_v2_accuracy_verification.md` §13.6.
