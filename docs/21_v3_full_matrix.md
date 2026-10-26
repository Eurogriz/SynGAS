# 21. Complete product × normal × climate matrix (V3 continuation)

15 расчётных случаев: 5 продуктов × (0 °C/Россия, 15 °C/Россия, 0 °C/Ближний Восток).
Используются настроенные параметры базового случая, пересчёт без повторной настройки.

| продукт | случай | метрика | значение | CO2 мол.% | Ni т | стоимость | ед. |
|---|---|---|---|---|---|---|---|
| methanol | 0C_russia | SN | 2.0500 | 6.00 | 10.59 | 261.60 | USD/1000 Nm3 dry syngas |
| methanol | 15C_russia | SN | 2.0500 | 6.00 | 10.59 | 254.21 | USD/1000 Nm3 dry syngas |
| methanol | 0C_middle_east | SN | 2.0500 | 6.00 | 10.59 | 261.51 | USD/1000 Nm3 dry syngas |
| ft | 0C_russia | H2_CO | 2.1000 | 0.26 | 6.79 | 214.39 | USD/1000 Nm3 dry syngas |
| ft | 15C_russia | H2_CO | 2.1000 | 0.26 | 6.79 | 207.53 | USD/1000 Nm3 dry syngas |
| ft | 0C_middle_east | H2_CO | 2.1000 | 0.26 | 6.79 | 214.32 | USD/1000 Nm3 dry syngas |
| oxo | 0C_russia | H2_CO | 1.0500 | 1.24 | 4.95 | 253.97 | USD/1000 Nm3 dry syngas |
| oxo | 15C_russia | H2_CO | 1.0500 | 1.24 | 4.95 | 246.74 | USD/1000 Nm3 dry syngas |
| oxo | 0C_middle_east | H2_CO | 1.0500 | 1.24 | 4.95 | 253.88 | USD/1000 Nm3 dry syngas |
| hydrogen | 0C_russia | H2_purity | 0.9997 | 0.00 | 11.86 | 364.98 | USD/1000 Nm3 H2 |
| hydrogen | 15C_russia | H2_purity | 0.9997 | 0.00 | 11.86 | 353.27 | USD/1000 Nm3 H2 |
| hydrogen | 0C_middle_east | H2_purity | 0.9997 | 0.00 | 11.86 | 364.87 | USD/1000 Nm3 H2 |
| ammonia | 0C_russia | H2_N2 | 3.0012 | 0.00 | 10.18 | 600.09 | USD/t NH3 |
| ammonia | 15C_russia | H2_N2 | 3.0012 | 0.00 | 10.74 | 610.73 | USD/t NH3 |
| ammonia | 0C_middle_east | H2_N2 | 3.0012 | 0.00 | 10.18 | 599.84 | USD/t NH3 |

Переход 0 °C → 15 °C меняет объёмные потоки на +5,49 % при неизменном молярном
заводе. Ближний Восток поднимает температуру продукта с 40 до 55 °C, меняет
конденсацию и требует осушителя (регенерация [НЕ ПОДТВЕРЖДЕНО]).

Сводка синтеза: `results_v2/synthesis_summary.csv`; безопасность:
`results_v2/safety_summary.csv`; полная матрица: `results_v2/full_matrix.csv`.
