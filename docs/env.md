# Среда (`auditgym.env`)

Владелец: участник 2. Контракт для участников 3–4 (оценщик, политики, runner) и жюри: как запускать эпизод, какие действия есть, что видит агент и как устроена изоляция эталона.

## Быстрый старт

```python
from auditgym.env import AuditEnv

with AuditEnv(mode="train") as env:                    # "train" | "eval"
    obs, info = env.reset(seed=7, config={})            # или env.reset(episode_dir="episodes/train/train_00")
    obs, reward, terminated, truncated, info = env.step(
        {"name": "list_records", "args": {"table": "ledger", "limit": 50}})
    ...
    env.grade_log[-1]   # результат оценщика для runner/диагностики — агенту не передаётся
```

`AuditEnv(mode="train", grader=None, max_steps=100, time_limit_s=60, isolation=None, grader_log_path=None)`:

| Параметр | Значение |
| --- | --- |
| `mode` | `train` — терминальная награда возвращается агенту; `eval` — награда всегда 0, результат только в `grade_log` |
| `grader` | класс оценщика (или фабрика без аргументов). По умолчанию — `auditgym.grader.Grader`, пока его нет — временный `auditgym.env.stub_grader.StubGrader` |
| `isolation` | `process` (по умолчанию в `eval`) или `inline` (по умолчанию в `train`) — см. «Изоляция» |
| `max_steps`, `time_limit_s` | 100 шагов и 60 с на эпизод |
| `grader_log_path` | файл (JSONL), куда сторона оценщика дописывает полную оценку каждого эпизода; по умолчанию — переменная окружения `AUDITGYM_GRADER_LOG`, иначе журнала нет. См. «`grade_log` и диагностика оценщика» |

Всё, что возвращают `reset` и `step`, — обычные JSON-данные. Наследования от `gymnasium.Env` нет (не нужно по условиям); сигнатуры совпадают с Gymnasium.

> Windows: в режиме `eval` оценщик запускается в отдельном процессе (`spawn`), поэтому скрипт, который создаёт `AuditEnv(mode="eval")`, должен иметь `if __name__ == "__main__":`.

## Наблюдения

**Первое (`reset`)**: `task` (текст задания), `episode_id`, `manifest`, `policy`, `tables` (число строк в каждой таблице), `actions` (список действий с аргументами), `step = 0`, `steps_remaining = 100`.
`info` всегда ровно `{episode_id, env_version, config_version}`. Seed и config агенту не передаются.

**Каждый шаг**: `{step, steps_remaining, action, result}` или `{step, steps_remaining, action, error}`; при обрыве добавляется `truncated_reason` (`step_limit` | `time_limit`). Схемы: `schemas/observation.schema.json`, `schemas/action.schema.json`.

## Действия

Действие — `{"name": ..., "args": {...}}`, не больше 64 КБ в JSON.

| Действие | Аргументы | Результат |
| --- | --- | --- |
| `list_records` | `table` ∈ {ledger, invoices, payments, fx}, `cursor` (необяз.), `limit` 1..50 (по умолчанию 50) | `{table, items: [{ref, record}], next_cursor, total}` — строки в порядке файла |
| `get_record` | `table`, `id` (`L0042` или `ledger:L0042`) | `{ref, record}` или `not_found` |
| `get_document` | `doc_id` — `DOC-…`, `INV-…`, `PAY-…` или `invoices:INV-…` | `{doc_id, kind: invoice\|payment, ref, document}` |
| `calculator` | `expression` — числа, `+ - * / ( )` | `{expression, value}`, `value` — десятичная строка |
| `submit` | `findings` — объект findings.json | `{submitted: true, count}`; эпизод завершён |

ID записей везде в одной форме `"<table>:<id>"`: `ledger:<row_id>`, `invoices:<invoice_id>`, `payments:<payment_id>`, `fx:<date>/<source>/<target>` — та же форма, что в `truth.json` (см. `docs/generator.md`).

**Курсоры** — непрозрачные токены `c_<hex>`, вычисленные из (episode_id, таблица, позиция): одна и та же позиция в одном эпизоде всегда даёт один и тот же токен; курсор другой таблицы, другого эпизода или никогда не выданный — `bad_args`.

**Калькулятор** (`auditgym/env/calculator.py`) — собственный разборщик выражений на `decimal.Decimal` (точность 50 знаков, `ROUND_HALF_EVEN`), без `eval`/`exec`/`ast`. Запрещено всё, кроме цифр, точки, `+ - * / ( )` и пробелов: имена, вызовы, `**`, `%`, `//`, экспонента `1e9`, `_`. Лимиты: 256 символов, 128 токенов, 32 знака в числе, вложенность 32, |результат| < 10^61; деление на 0 и переполнение — ошибка.

## Правила шага

* Каждое действие — верное, ошибочное или `submit` — расходует 1 шаг; максимум 100.
* Ошибки: `{"code": ..., "message": ...}`, код ∈ `unknown_action`, `bad_args`, `not_found`, `episode_over`, `time_limit`; сообщение — фиксированный текст ≤ 200 символов, без ввода агента, без существующих ID, без путей и stack trace.
* Награда за исследование — 0. `submit` → `terminated = true`; в `train` награда = терминальная награда оценщика, в `eval` = 0.
* `inspection_steps`, передаваемый оценщику, = число шагов до `submit`, не считая сам `submit`.
* `submit` с неверной структурой findings тоже завершает эпизод; оценщик даёт −1.
* 100-й шаг без `submit` или 60 с → `truncated = true`, ответ оценивается как `findings: []` (`inspection_steps` = число сделанных шагов). `submit` сотым шагом — это `terminated`, а не `truncated`.
* Лимит 60 с проверяется **на границах шагов**: в начале каждого `step` (до выполнения действия) и после него. Первый `step` после дедлайна — в том числе `submit` — не выполняется: эпизод обрывается (`truncated = true`, ошибка `time_limit`, `truncated_reason = "time_limit"`), присланный ответ отбрасывается и оценивается пустой ответ. Награда при этом — награда оценщика за `findings: []` (а не фиксированные −1: на эпизоде без ошибок пустой ответ верен), в `eval` агенту — 0. Пока агент не вызывает `step`, среда сама эпизод не завершает — runner должен ограничивать время вызова политики снаружи.
* Шаг после завершения → `episode_over`, состояние не меняется, награда 0; повторный `submit` не оценивается заново.
* `reset` полностью пересоздаёт состояние: счётчик, таймер, курсоры, признак отправки.

## Изоляция и защита от утечек

* Среда хранит только публичную часть эпизода (`PublicStore`, `auditgym/env/store.py`): manifest, policy, ledger, invoices, payments, fx. Конструктор отказывается принимать что-либо ещё.
* Генерацию/загрузку эпизода и оценку выполняет *backend* (`auditgym/env/grading.py`), а не среда:
  * `ProcessBackend` (режим `eval`) — эпизод генерируется **в отдельном процессе**; в процесс среды приходят только публичные данные и `{episode_id, config_version}`, туда уходят только findings, обратно — только оценка. `truth`, `provenance` и seed в процессе среды не существуют. Ошибки генерации передаются только как имя типа исключения (текст мог бы содержать seed).
  * `InlineBackend` (режим `train`) — закрытая часть в отдельном объекте того же процесса; через действия агента к нему пути нет.
* Все данные отдаются глубокими копиями: изменение полученного объекта не меняет записи.
* Действий для shell, SQL, файлов и сети нет; аргументы-пути (`../private/truth.json`) — просто несуществующий ID.
* Leak-scan (`auditgym/env/leakscan.py`, `leak_scan(payload, private, seed=..., where=...)`) проверяет наблюдения, `info` и строки траекторий: запрещённые ключи (`seed`, `issue_id`, `expected_amount_minor`, `evidence_sets`, `truth`, `provenance`, …), запрещённые слова (`truth`, `provenance`, `seed`, `private/`), любые `issue_id` эталона, а в `info` и объектах ошибок — числа, равные seed или `expected_amount_minor`. Внутри самих записей суммы не проверяются: публичный счёт-дубль законно содержит ту же сумму, что и эталон. Runner (участник 4) может вызывать его для `trajectories.jsonl`.

## `grade_log` и диагностика оценщика

`env.grade_log` — список результатов оценки для runner; агенту (в наблюдения и `info`) он не попадает никогда. Его содержимое зависит от режима:

* **`train`** — полная оценка: `episode_id, mode, reason, steps, inspection_steps` + все поля оценщика (`reward, precision, recall, f1, tp, fp, fn, valid, n_findings, n_issues, matches, finding_reasons, missed_issue_ids, by_type, errors, grader_version`).
* **`eval`** — только скаляры: `episode_id, mode, reason, steps, inspection_steps, reward, precision, recall, f1, tp, fp, fn, valid, n_findings, grader_version` и `error` — код `null` | `"invalid_submission"` | `"grader_exception"` (без текстов сообщений). Список — `auditgym.env.grading.SUMMARY_KEYS`. Всё, что выведено из эталона и указывает на конкретные нарушения (`matches`, `missed_issue_ids`, `finding_reasons`, `by_type`, `n_issues`, тексты `errors`), **не покидает процесс оценщика**: сокращение делает сам рабочий процесс `ProcessBackend`, по каналу в процесс агента идут только скаляры. Это требование закрытого прогона: оценщик работает вне процесса агента, ни эталон, ни диагностика оценщика агенту не доступны.

Полная диагностика в `eval` пишется только стороной оценщика (рабочим процессом) в `grader_log_path` / `AUDITGYM_GRADER_LOG`: одна JSON-строка на оцененный эпизод — `{episode_id, mode, reason, steps, inspection_steps, ...вся оценка}`. В памяти объекта среды она не хранится. Файл должен лежать вне области, доступной агенту (среда не даёт агенту действий для чтения файлов, но политика исполняется в том же процессе, что и среда). В `train` журнал тоже пишется, если путь задан.

Ключи, которые читает runner (`auditgym/runner/core.py`): `precision, recall, f1, reward, tp, fp, fn, inspection_steps, grader_version` — во всех режимах на месте и того же типа.

## Тесты (`tests/env/`)

| Файл | Что проверяет |
| --- | --- |
| `test_env_contract.py` | форма `reset`/`info`, детерминизм `reset` и переходов, изоляция `reset`, каждое действие = 1 шаг, все коды ошибок без утечек, `limit > 50`, пагинация и стабильность курсоров, копии, `submit` → `terminated`, 100-й шаг → `truncated`, `submit` сотым шагом, тайм-аут, шаг после конца, повторный `submit`, режим `eval`, стоимость шагов 10 vs 90 = 0.16 |
| `test_env_calculator.py` | арифметика на Decimal; отказ для `__import__`, имён, `**`, `2**99999999`, `%`, `//`, `1e9`, переполнения, глубины, длины |
| `test_env_leaks.py` | leak-scan на 50 сгенерированных эпизодах (в т.ч. в `eval`) с атакующими действиями и на всех 21 опубликованных; в `eval` в объекте среды нет закрытых данных |
| `test_env_stress.py` | эпизод на 2000 строк/200 документов: все таблицы читаются меньше чем за 100 шагов, < 20 с, < 300 МБ |
| `test_env_eval_isolation.py` | в `eval` после `submit` / обрыва по времени рекурсивный обход `vars(env)` не находит ни `issue_id` эталона, ни ключей диагностики, ни списков `affected_ids`/`evidence_sets` эталона; `grade_log` в `eval` — ровно скалярные ключи; файл диагностики (`grader_log_path` и `AUDITGYM_GRADER_LOG`) содержит полные `matches`/`missed_issue_ids`; `submit` после дедлайна → `truncated` и пустой ответ |
| `test_env_schemas.py` | все наблюдения и действия соответствуют JSON Schema; схема и среда одинаково отвергают неверные действия |

## Ограничения

* Таймаут проверяется на границах шагов, а не прерывает действие на середине и не срабатывает сам, пока агент «думает» между шагами; все действия ограничены по размеру и выполняются за миллисекунды. Действие после дедлайна (включая `submit`) отбрасывается, эпизод оценивается как пустой ответ.
* В `eval` с `isolation="inline"` эталон находится в объекте backend того же процесса (как в `train`); `grade_log` всё равно сокращается до скаляров. Для закрытого прогона используйте `isolation="process"` (по умолчанию в `eval`).
* `StubGrader` — временный: жадное сопоставление и минимальная нормализация. Его заменит `auditgym.grader.Grader` участника 3 с контрактом `score(findings, *, truth, public, inspection_steps) -> dict | dataclass` с полем `reward` (остальные поля — `precision, recall, f1, tp, fp, fn, errors` — попадают в `grade_log`).
