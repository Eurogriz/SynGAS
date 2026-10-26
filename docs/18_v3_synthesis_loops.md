# 18. Downstream synthesis loops (V3 continuation)

Stoichiometric + recycle balances, **NOT** a kinetic reactor simulation.
All conversions/selectivities are adjustable in `cases/config.json -> synthesis`.

| product | p bar | T C | saleable t/h | heat MW | compression MW | status |
|---|---|---|---|---|---|---|
| methanol | 75 | 250 | 40.24 | 28.7 | 5.47 | [PARTIAL] loop stoichiometry + opened ranges, not a licensor |
| ft | 20 | 230 | 12.90 | 45.9 | n/a | [PARTIAL] ASF ideal distribution, no detailed product slate |
| oxo | 20 | 100 | 65.99 | n/a | n/a | [PARTIAL] stoichiometric aldehyde yield, heat of reaction NO |
| hydrogen | n/a | n/a | 8.99 | n/a | 12.29 | [PARTIAL] ideal multistage compression, no intercooling mode |
| ammonia | 200 | 450 | 47.39 | 35.6 | 14.04 | [PARTIAL] loop stoichiometry + opened ranges, not a converte |

## 18.1 Chemistry and opened sources

- **Methanol**: CO + 2H₂ → CH₃OH (−90,7 кДж/моль), CO₂ + 3H₂ → CH₃OH + H₂O
  (−49,7 кДж/моль), 50–100 бар, 200–300 °C, Cu/ZnO/Al₂O₃.
  Applied Sciences 2017, 7, 1213 (opened): 4–8 мол.% CO₂ в подпиточном газе,
  S-модуль чуть выше 2. OSTI 2424604 (opened): конверсия за проход 25–30 %,
  поэтому нужен рецикл 2:1–5:1 (opened review). Итоговая конверсия углерода 0,97.
- **FT**: CO + 2H₂ → –CH₂– + H₂O. ACS Catalysis 2017 (opened): в промышленности
  0,85 < α < 0,95; Hywax (opened): конверсия CO за проход 60–80 %;
  распределение Андерсона–Шульца–Флори Wₙ = n(1−α)²αⁿ⁻¹, доля C₅₊ = α⁴(5−4α).
- **Оксо**: C₃H₆ + CO + H₂ → C₄H₈O (масляный альдегид). US7582802B2 (opened):
  материальный баланс пропилена; MDPI Catalysts 2020 10,510 (opened): селективность
  ~99 % в мягких условиях; JM LP Oxo (opened): n:iso ≈ 7:1. **Внешний пропилен
  не включён в OPEX** — это открытый пункт.
- **Водород**: сжатие до 200 бар. Processes 2026 14(2),319 (opened): 9,2 МВт
  на 2966 кмоль/ч. Мощность показана отдельно от базового баланса утилит.
- **Аммиак**: N₂ + 3H₂ → 2NH₃, ΔH = −46 кДж/моль NH₃ (C-THRU brief, opened),
  150–250 бар, 400–450 °C, 15–25 % за проход (RSC EES 2020, opened),
  97 % суммарно с рециклом (Haber process, opened).

## 18.2 Результаты

| product | saleable t/h | saleable t/y | heat MW | compression MW |
|---|---|---|---|---|
| methanol | 40.24 | 321950 | 28.69 | 5.47 |
| ft | 12.90 | 103195 | 45.89 | n/a |
| oxo | 65.99 | 527888 | n/a | n/a |
| hydrogen | 8.99 | n/a | n/a | 12.29 |
| ammonia | 47.39 | 379094 | 35.55 | 14.04 |

Внимание: тоннажи разных продуктов **нельзя сравнивать напрямую** — это разные
химические продукты. Метанол 321950 т/год,
FT C₅₊ 103195 т/год,
альдегид 527888 т/год,
H₂ 71951 т/год,
NH₃ 1137 т/сут.

## 18.3 Не проверено

Кинетика синтеза, катализаторы синтеза, ректификация метанола-сырца,
гидроформилирование с рециклом родия, сепарация FT-восков, стоимость пропилена,
дополнительная мощность компрессоров в OPEX. [НЕ ПОДТВЕРЖДЕНО]
