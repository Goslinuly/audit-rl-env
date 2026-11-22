# Подключение для проверок жюри (`judge_adapter.py`)

Документ описывает, как запустить среду по «Genesis FinTech: определения проверок» (20 ноября 2026).
Адаптер — один файл в корне репозитория. Он переводит названия и оболочки, не выбирает действия и
не меняет суммы, типы и валюты.

## Запуск

Рабочая директория — корень репозитория (в контейнере `/app`). Отдельной установки не нужно.

```bash
docker build -t audit-rl-env .
docker run --rm -it --network none --cpus 2 --memory 4g audit-rl-env python   # интерпретатор в /app
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env python -m pytest -q tests/judge
```

```python
import judge_adapter as j
j.generate_episode(101, {"error_counts": {"duplicate_invoice": 1}}, "/tmp/ep")
env = j.make_env()
obs, info = env.reset(101, {"mode": "closed", "episode_dir": "/tmp/ep", "team_config": {}})
obs, reward, terminated, truncated, info = env.step(
    {"name": "list_records", "args": {"table": "ledger", "cursor": None, "limit": 50}})
j.score_episode("/tmp/ep", {"episode_id": info["episode_id"], "findings": []}, inspection_steps=1)
env.close()
```

`judge_adapter`, каталог эпизода и `score_episode` — сторона жюри. Политике передаются только
`observation`, `reward`, флаги и `info`; объект среды ей не передаётся, она работает в отдельном
процессе, который запускает жюри.

## Точки входа

| Функция | Что делает |
|---|---|
| `generate_episode(seed, config, output_dir)` | пишет в каталог `manifest.json`, `policy.json`, `ledger.csv`, `invoices.jsonl`, `payments.jsonl`, `fx.csv` и закрытые `truth.json`, `provenance.json`. `config` — частичный конфиг генератора (`docs/generator.md`) |
| `make_env()` | объект с `reset(seed, config)`, `step(action)`, `close()` |
| `score_episode(episode_dir, findings, inspection_steps)` | `{tp, fp, fn, precision, recall, f1, return}`. Неверная структура: `return = -1`, остальное `null`, причина — в файл `AUDITGYM_GRADER_LOG`, а если он не задан, в stderr |

`reset`: `mode` — `"closed"` или `"train"`. С `episode_dir` загружается именно этот каталог (плоский, как
выше, или с подкаталогами `public/` и `private/`), ID не меняются, seed не используется. Без
`episode_dir` эпизод создаётся генератором из seed и `team_config`. Повторный `reset` начинает заново.

В `closed` эталон загружает и оценивает отдельный процесс; `reward` политике всегда `0`. В `train`
терминальная награда приходит на `submit`. Лимиты: 100 действий, 60 с от начала `reset`, время
политики входит. Лимит времени проверяется в начале и в конце каждого `step`; зависшую политику
останавливает жюри.

## Наблюдения

| Что | Форма |
|---|---|
| первое | `{task, manifest, policy, remaining_steps: 100}` |
| остальные | `{result, error, remaining_steps}`; `error` — `null` или `{code, message}` |
| `info` | `{episode_id, env_version}` |
| `list_records` | `{records: [...], next_cursor: string\|null}` |
| `get_record`, `get_document` | объект записи или документа |
| `calculator` | десятичная строка, `0.1+0.2` → `"0.3"` |
| `submit` | `{accepted: true}`; при неверной структуре `error.code = invalid_submission`, эпизод всё равно завершён |

Коды ошибок: `unknown_action`, `bad_args`, `not_found`, `episode_over`, `time_limit`, `invalid_submission`.

Таблицы: `ledger` (ключ `row_id`), `invoices` (`invoice_id`), `payments` (`payment_id`), `fx`
(`date:source_currency:target_currency`). Поля записей — `docs/generator.md`.

## ID

Канонический вид: `ledger:<row_id>`, `invoices:<invoice_id>`, `payments:<payment_id>`,
`fx:<date>/<source>/<target>`. Оценщик сравнивает ID точно и ничего не исправляет.

Политика организаторов видит записи без нашего префикса, поэтому адаптер **до оценщика** заменяет
`row_id`, `invoice_id`, `payment_id`, `doc_id` и ключ курса (`date:src:tgt` или `date/src/tgt`) на
канонический ID, если строка посимвольно совпадает с ID ровно одной записи. Пробелы и регистр не
меняются. Неизвестный или неоднозначный ID передаётся как есть и не сопоставляется. То же правило
применяется к `truth.json` в `score_episode`, поэтому фикстура может использовать любой из двух видов.

## Типы ошибок

| Тип | Смысл | `affected_ids` | Сумма и валюта | Допуск τ |
|---|---|---|---|---:|
| `duplicate_invoice` | повторное отражение одного обязательства | `[счёт-дубль]` | сумма дубля, валюта счёта | 0 |
| `payment_allocation` | пропущенное или частичное распределение | `[платёж, счёт]` | нераспределённый остаток, валюта платежа | 0 |
| `fx_conversion` | курс не той даты | `[документ]` | \|проведено − верно\|, базовая валюта | 1 |
| `period_cutoff` | документ не того периода | `[документ]` | сумма проводки, базовая валюта | 0 |

τ = 1 у `fx_conversion` из-за округления строки по policy (до 1 минимальной единицы). τ опубликован
здесь и в `auditgym/grader/constants.py` и записан в `truth.json` (`tolerance_minor`); если поля нет, τ = 0.

## Как включить сценарии D01–D20

Готовые `team_config` — в [`configs/judge/scenarios.json`](../configs/judge/scenarios.json), ключи `D01`…`D20`.
Коротко: чистая компания — `clean: true`; тип ошибки — `error_counts`; вид ошибки распределения —
`allocation_mode: "missing" | "partial"` (без ключа выбирает seed); взаимодействия — `interactions: {"A": 1}`
или `{"B": 1}`; отвлекающие случаи — `distractors`. Чтобы получить только один тип, остальные счётчики
нужно явно поставить в 0: по умолчанию каждый тип ошибки — 0 или 1.

* **A:** платёж после конца периода, проведённый в периоде, распределён частично и пересчитан по курсу не той даты.
* **B:** дубль счёта в иностранной валюте, оплаченный по курсу не той даты.

## Соответствие тестам

`tests/judge/test_judge_definitions.py` вызывает только адаптер. Преобразования файлов, фикстуры и
бухгалтерские проверки в нём написаны отдельно от генератора, эталонного аудитора и `transforms.py`.

| Блок | Тесты |
|---|---|
| C01–C20 | `test_C01_…` – `test_C20_…`, плюс запуск из обычного скрипта и неизменность при повторном `reset` |
| D01–D20 | `test_D_block` на двух seed: проводки, курсы, период, распределение и дубли пересчитаны по публичным файлам |
| Matcher 1–20, M01–M12 | `test_matcher_vectors`, `test_invalid_structure`, `test_matcher_examples`, `test_M10_M11_M12_matching`, сверка tie-break полным перебором |
| P01–P20 | `test_P_block` на двух seed |

Чего тесты не доказывают: отсутствие любых скрытых каналов (C20 проверяет каналы среды, код просматривается
отдельно) и изоляцию процесса политики, который запускает жюри.
