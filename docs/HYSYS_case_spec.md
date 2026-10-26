# Переносимое описание кейса (эквивалент HYSYS)

**Важно:** Aspen HYSYS в среде не установлен (проверено: `command -v HYSYS/hysys/dwsim/Aspen`
→ not found). Файла `.hsc` НЕ существует. Названия объектов ниже — **целевая структура**,
которую надо сверить с документацией **установленной версии** HYSYS перед созданием.
Это описание, а не утверждение о выполненном расчёте в HYSYS.

## 1. Среда и версии (фактические, `results/summary.json`)

Python 3.11.2; NumPy 2.4.6; SciPy 1.17.1; pandas 3.1.0; matplotlib 3.11.2;
pint 0.25.3; Cantera 3.2.0; PyYAML; pytest 9.1.1. Ядро модели — только stdlib.
Термоданные: `data/nist_shomate.json` + `data/gri30_nasa7.json` (Cantera 3.2.0).

## 2. Пакет свойств

- Основной: **Peng–Robinson** (или SRK) для смеси H₂/CO/CO₂/CH₄/H₂O/N₂/C₂H₆.
  Бинарные параметры k_ij зафиксировать и выписать (по умолчанию 0 — [ДОПУЩЕНИЕ]).
  Наш PR-тест: Z = 1,0029, K_φ(R1) = +1,73 % при 1123 K/25 бар(а).
- Вода/пар: **ASME Steam / NBS Steam**; проверить точку росы (наш расчёт 443,7 K при 25 бар).
- Аминовая очистка, если будет добавлена: **Acid Gas / Amines** пакет.
- Стандартное состояние: 1 бар; нормальные условия 273,15 K / 101 325 Па [ДОПУЩЕНИЕ].

## 3. Компоненты

CH₄, C₂H₆ (C₃₊ сведены в C₂H₆), H₂O, CO, CO₂, H₂, O₂, N₂, C(graphite, solid).
Опционально: H₂S, COS, ZnS, Ni, NiO — для блока очистки和安全.

## 4. Потоки (нормальный режим, из `results/base_case_streams.csv`)

| Имя | T, K | p, бар(а) | кмоль/ч | Ключевые y |
|---|---|---|---|---|
| S-101 | 298,2 | 30 | 1150,5 | CH₄ 0,9356, C₂H₆ 0,0445, CO₂ 0,005, N₂ 0,005, H₂ 0,0099 |
| S-102 | 623,2 | 30 | 3537,0 | H₂O 1 |
| S-103 | 298,2 | 30 | 290,9 | CO₂ 1 |
| S-104 | 603,3 | 25 | 4978,4 | см. CSV |
| S-105 | 597,2 | 25 | 5032,2 | см. CSV |
| S-106 | 1123,2 | 25 | 6837,9 | H₂ 0,4358, CO 0,1022, CO₂ 0,0771, CH₄ 0,0364, H₂O 0,3475 |
| S-107 | 623,2 | 25 | 6837,9 | как S-106 |
| S-108 | 313,2 | 24 | 4475,3 | H₂ 0,6659, CO 0,1562, CO₂ 0,1179, CH₄ 0,0557, H₂O 0,0031 |
| S-109 | 313,2 | 24 | 2362,6 | жидкая вода |

## 5. Наборы реакций

**Gibbs reactor (L0/L1)** — 9 веществ, ограничения по C/H/O/N, графит как отдельная
твёрдая фаза. Альтернатива — Equilibrium Reactor с тремя реакциями:

| ID | Реакция | K(T) |
|---|---|---|
| R1 | CH₄ + H₂O ⇌ CO + 3H₂ | `thermo.equilibrium_constant` (NIST) |
| R2 | CO + H₂O ⇌ CO₂ + H₂ | то же |
| R3 | CH₄ + 2H₂O ⇌ CO₂ + 4H₂ | K₃ = K₁K₂ |
| R4 | C₂H₆ + H₂ ⇌ 2CH₄ | NASA7 GRI30 |
| R5 | 2H₂ + O₂ ⇌ 2H₂O | NIST |

Для L2 — **Heterogeneous Catalytic / LHHW** с базисом скорости на массу катализатора.
Параметры из `model/kinetics.py` — **[НЕ ПОДТВЕРЖДЕНО]**, подключать только после B-01.
Насыпная плотность, порозность и фактор эффективности — [ДОПУЩЕНИЕ].

## 6. Объекты и порядок решения

```
Feed(S-101) → HDS/ZnO (conversion reactor, ТОЛЬКО вспомогательная стадия)
  → Mixer(+S-102,+S-103) → Heater(E-101, +4 695,5 кВт)
  → Gibbs/Equilibrium R-101 (adiabatic, ΔT = −6,1 K)
  → Heater/Cooler R-201 (Q = +88 844,1 кВт, T_out = 1123,2 K, approach 10 K)
  → Cooler E-201 (Q = −34 737,4 кВт, T_out = 623,2 K, NO condensation)
  → Cooler E-202 (Q = −47 850,6 кВт, T_out = 313,2 K, WITH condensation)
  → Separator V-201 → S-108 + S-109
```

Logical operations: `Adjust` для CO₂/C → SN = 2,0; `Set` для p; `Spreadsheet` для
SN = (H₂−CO₂)/(CO+CO₂); `Recycle` — **отсутствует** в базовой схеме (не «закрыт руками»).
`Case Study` для T/p/S/C/CO₂/C/O₂/C; оптимизатор — после валидации кинетики.

## 7. Дисциплина сходимости

Начальные приближения: составы из `results/base_case_streams.csv`; T из потоков;
допуск по материальному балансу 0,1 %, энергетическому 0,5 %. Поэтапно:
сырьё → реактор → охлаждение → сепарация. Все предупреждения разобрать.
Проверить Q/K = 1, отсутствие пересечения T, точку росы, физичность ρ/μ/cp.

## 8. Воспроизведение без HYSYS

`python3 -m model.run` (или `.venv/bin/python -m model.run`). Журнал, версии и время —
`results/summary.json`; проверки — `results/verification.json`; тесты — `pytest -q`.

## 9. Дополнение V3 (что добавить в HYSYS-кейс)

Разделы 1–8 описывают **V1** метанольный базовый кейс. Для эквивалента V2/V3
(`results_v2/`) добавьте следующие блоки; номера потоков — целевые, их надо
сверить с установленной версией HYSYS. **Расчёт в HYSYS по-прежнему не
выполнялся.**

```
Feed (Russian H-gas, C4+ -> C3H8 carbon-equivalent)
  -> HDS/ZnO lead-lag
  -> MIX S-102 (+ steam S/C, + imported CO2 CO2/C, + H2 recycle)
  -> E-100 preheater (623 K)
  -> R-100 adiabatic pre-reformer (Gibbs, 500-800 K bracket, C2+ conversion > 0.99)
  -> R-101 fired tubular reformer (1123 K, 25 bar, approach 10 K, PR EOS)
  -> E-101 WHB -> steam (IF97, 30 bar / 673 K)
  -> A-302 partial MDEA CO2 TRIM (target 6 mol% CO2 in make-up gas)
  -> E-601 final cooler (climate T: 40 C Russia / 55 C Middle East, IF97 psat)
  -> V-601 knockout + A-701 dryer
  -> K-801 compression to 75 bar
  -> R-801 methanol loop (RStoic/RGibbs, 25-30% per pass, recycle 3:1,
     purge for CH4/N2 inerts) -> crude methanol -> distillation
```

Варианты продуктов (заменить хвостовую часть):
- **FT** — `R-100` пропущен (ATR с O₂), `R-101` = adiabatic ATR (O₂/C ≈ 0,656,
  S/C = 0,6, T_ad ≈ 1509 K), `A-301` = полное MDEA, затем FT-синтез
  (CO + 2H₂ → –CH₂– + H₂O, α = 0,90, ASF-распределение).
- **Оксо** — ATR + CO₂ (O₂/C ≈ 0,702, CO₂/C = 0,9, T_ad ≈ 1325 K), MDEA,
  затем гидроформилирование пропилена (внешний C₃H₆, конверсия 0,90,
  селективность 0,95 по C₄H₈O).
- **Водород** — SMR + HTS/LTS WGS + MDEA + PSA ( recovery 0,88,
  ISO 14687:2025 grade D: H₂ ≥ 99,97 %, CO ≤ 0,2 ppm, CO₂ ≤ 2 ppm ),
  затем дожатие H₂ до 200 бар.
- **Аммиак** — первичный риформинг + воздушный вторичный (air ratio ≈ 1,28),
  WGS + MDEA + метанатор (CO+CO₂ < 10 ppm) + осушка + дожатие до 200 бар +
  конвертер NH₃ (18 % за проход, 97 % суммарно с рециклом).

Свойства: **Peng–Robinson** с kᵢⱼ из `model/eos.py` (наборы zero/base/high)
для углеводородных/синтез-газовых потоков; **IAPWS-IF97** (или Steam Tables)
для воды/пара; NASA7/Shomate для энтальпий реакций. Для R-100/R-101/A-302
проверять Q·Kφ/K = 1, баланс элементов ≤ 1e-8 %, баланс энергии ≤ 1e-8 %.

`Adjust`:
1. `CO2C` → SN = 2,05 **при включённом A-302** (V3: CO₂/C ≈ 0,7615);
2. `O2C` → H₂/CO = 2,10 (FT) или 1,05 (оксо);
3. `air_ratio` → H₂/N₂ = 3,00 (аммиак);
4. число труб → Δp Эргуна ≤ 3 бар **одновременно** с q = 80 кВт/м²;
5. `MDEA recovery` → CO₂ make-up = 6 мол.% (метанол).

Безопасность: добавить `Spreadsheet` для log₁₀K = 7430/T − 21,90 (Ni(CO)₄) и
проверку продувки CO < 10 ppm до охлаждения ниже 200 °C; PSV по choked flow —
только скрининг, **не** сертификация API 520/521.

Воспроизведение без HYSYS: `PYTHONPATH=. .venv/bin/python -m model.run_v2`
→ `results_v2/summary_v2.json`, `verification_v2.json`, `full_matrix.csv`.
