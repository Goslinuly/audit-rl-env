# artifacts/

Закоммиченные результаты прогона четырёх базовых политик (Oracle, FlagAll,
RandomExplorer с seed 7, Reconciler) на всех 20 эпизодах `episodes/train/*` и
`episodes/dev/*`, режим `train` (агент получает reward). Пересобрать:

```bash
make artifacts          # runner + summary.md
make failure-analysis   # failure_analysis.md / .json
```

| Файл | Что внутри |
|---|---|
| `trajectories.jsonl` | 663 строки, по строке на шаг: `episode_id`, `step`, `action`, `observation`, `reward`, `terminated`, `truncated`, а также `policy`, `env_version`, `config_version`, `info`; в первой строке эпизода — `initial_observation` и `reset_info` |
| `results.csv` | 80 строк (эпизод × политика): версии среды, конфигурации, грейдера и генератора, P/R/F1, TP/FP/FN, reward, return, шаги, время, seed политики |
| `leak_report.json` | результат сканера утечек по `trajectories.jsonl`, перечитанному с диска (`status: passed`) |
| `summary.md` | средние по политикам из `results.csv` (`tools/summarize_results.py`) |
| `failure_analysis.md`, `failure_analysis.json` | абляции Reconciler через настоящие AuditEnv + Grader, разбор FP/FN по типам, причинам и отвлекающим случаям (DESIGN.md §7.2) |

**Траектории Oracle (`"policy": "Oracle"`) содержат правильный ответ в действии
`submit`.** Oracle — привилегированный эталон, которому runner передаёт
`truth.json`; его строки нельзя использовать как наблюдения или данные для обучения
других политик. Отфильтровать: `grep -v '"policy": "Oracle"' trajectories.jsonl`.
Траектории остальных политик построены только из публичных наблюдений.

`trajectories.jsonl` детерминирован (повторный `make artifacts` даёт тот же файл);
в `results.csv` меняется только `time_s`. Размер `trajectories.jsonl` около 6,7 МБ,
из них около 5,2 МБ — Reconciler, который читает все таблицы постранично
(страница до 50 записей попадает в наблюдение целиком); Oracle занимает около 0,1 МБ.
