# audit-rl-env (`auditgym`)

Воспроизводимая RL-среда для ИИ-аудитора: синтетические документы компании, инструменты расследования,
скрытые финансовые ошибки и функция награды. FinTech-трек хакатона, 19–22 ноября 2026.

Сайт: https://explorer-production-573177ce.up.railway.app ·
[видео-демо](https://explorer-production-573177ce.up.railway.app/video) ·
[презентация](https://explorer-production-573177ce.up.railway.app/presentation)

ТЗ команды — [`docs/TZ.md`](docs/TZ.md), проектная записка — [`DESIGN.md`](DESIGN.md).

## Единая команда проверки

В контейнере (нужен только Docker, сеть во время проверки не используется):

```bash
docker build -t audit-rl-env .
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env
```

Контейнер по умолчанию выполняет `make check`. На ноутбуке проверка занимает
около 45 секунд. В CI (GitHub Actions, `--network none --cpus 2 --memory 4g`)
сборка образа занимает около 20 секунд, проверка в контейнере — около 2¼ минут
(1272 теста за 129 с на v2.0.0), при лимите 10 минут. Код выхода 0 —
всё прошло. Ход проверки печатается в терминал, итоговый отчёт пишется в
`runs/check-<id>/validation.json` внутри контейнера (там же `acceptance.json` и
`junit.xml`). Чтобы сохранить отчёт на хосте, подключите папку:

```bash
docker run --rm --network none --cpus 2 --memory 4g -v "$PWD/runs:/app/runs" audit-rl-env
```

Без Docker (Python 3.11+, на Linux, macOS или Windows с `make`):

```bash
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
make check          # = python -m auditgym.runner.validate
```

`make check` по порядку запускает: ruff, все тесты и 320 приёмочных проверок,
сверку SHA256 эпизодов с генератором, selfcheck грейдера на всех эпизодах и
четыре политики на dev. Если `make` нет, используйте
`python -m auditgym.runner.validate --out runs/check --deadline 600`.

Другие команды:

```bash
make test           # python -m pytest -q
make artifacts      # пересобрать artifacts/ (4 политики на train + dev)
make failure-analysis   # абляции Reconciler, таблица из DESIGN.md §7
make docker-check   # docker build + make check с теми же ограничениями
python -m auditgym.runner --episodes episodes/sample/sample_00 --out runs/sample
python -m auditgym.runner --mode eval --episodes episodes/sample/sample_00 --out runs/eval
python -m auditgym.runner.demo
```

Для каждого прогона runner и validate нужна новая папка вывода.

## Проверки жюри

Адаптер — [`judge_adapter.py`](judge_adapter.py) в корне (в контейнере рабочая директория `/app`):
`generate_episode(seed, config, output_dir)`, `make_env()`, `score_episode(episode_dir, findings, inspection_steps)`.
Схемы наблюдений, правила ID, типы ошибок с допусками и настройки сценариев D01–D20 —
в [`docs/judge.md`](docs/judge.md). Проверить подключение:

```bash
docker run --rm --network none --cpus 2 --memory 4g audit-rl-env python -m pytest -q tests/judge
```

| Тип | Что значит | `affected_ids` | Допуск |
| --- | --- | --- | ---: |
| `duplicate_invoice` | повторное отражение счёта | `[счёт-дубль]` | 0 |
| `payment_allocation` | платёж не распределён или распределён частично | `[платёж, счёт]` | 0 |
| `fx_conversion` | курс не той даты | `[документ]` | 1 |
| `period_cutoff` | документ не того периода | `[документ]` | 0 |

## Версии и зависимости

- Все зависимости, включая транзитивные, закреплены точными версиями в
  [`requirements.lock`](requirements.lock) (собран для Python 3.11 на Linux);
  Docker-образ ставит именно их. Прямые зависимости также закреплены в `pyproject.toml`.
- Версии компонентов задаются константами в коде и пишутся в каждую строку
  `results.csv` и траекторий: `auditgym.ENV_VERSION`,
  `auditgym.generator.GENERATOR_VERSION`, `auditgym.generator.CONFIG_VERSION`,
  `auditgym.grader.GRADER_VERSION`. `make check` проверяет, что опубликованные
  эпизоды побайтно совпадают с текущим генератором.

## Политики и результаты

Runner использует настоящие `AuditEnv` и `Grader`. Политики читают
`result.items[*].record`; метрики берутся из `env.grade_log`. Диагностика grader с
закрытыми ID не попадает в траектории агента. Oracle получает эталон от runner;
остальные политики получают только наблюдения. В eval среда использует отдельный
процесс, а награды в траектории равны нулю.

Измерено на 20 эпизодах train + dev (`make artifacts`, файлы в [`artifacts/`](artifacts/)),
режим train. P, R, F1, reward, шаги — среднее по эпизодам:

| Политика | P | R | F1 | reward | шаги (мин–макс) | P micro | R micro |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Oracle (эталон, видит ответ) | 0,750 | 0,750 | 1,000 | 1,000 | 1 | 1,000 | 1,000 |
| Reconciler (скриптовый эксперт) | 0,750 | 0,750 | 1,000 | 0,960 | 21,1 (10–45) | 1,000 | 1,000 |
| RandomExplorer, seed 7 | 0,000 | 0,000 | 0,250 | −0,504 | 9 | — (0 выводов) | 0,000 |
| FlagAll | 0,000 | 0,000 | 0,000 | −1,000 | 2 | 0,000 | 0,000 |

- Средние P и R у Oracle и Reconciler равны 0,75, потому что в 5 из 20 эпизодов
  ошибок нет: грейдер ставит в таком эпизоде P = R = 0 даже за верный пустой ответ
  (F1 = 1). Колонки micro посчитаны по суммам TP/FP/FN (95 ошибок всего).
- RandomExplorer в этой таблице запущен с seed 7 — это значение по умолчанию в CLI
  (`--seed 7`). С seed 7 он ни разу не делает вывод, поэтому получает F1 = 1 на
  пустых эпизодах. Терминальное демо использует seed 42: там он всегда делает один
  случайный вывод, и на train + dev получает F1 = 0, reward = −1.
- Reconciler закодирован по тем же правилам обнаружения, что эталонный аудитор
  генератора (`auditgym/generator/audit.py`). Его F1 = 1 — верхняя граница для
  скриптового эксперта, а не признак того, что задача простая для обучаемого агента.
  Что будет, если убрать из него отдельные знания (часовой пояс, правило курса на
  выходные, сравнение строк счёта, правило частичной оплаты), измерено в
  [DESIGN.md §7](DESIGN.md#7-измеренный-разбор-сбоев-базовых-политик): F1 падает до 0,42–0,75 от
  каждого пункта и до 0,24 от всех вместе.

Файлы runner: `trajectories.jsonl` (поля `episode_id`, `step`, `action`,
`observation`, `reward`, `terminated`, `truncated` и служебные), `results.csv`
(версии, P/R/F1, TP/FP/FN, награда, возврат, шаги, время), `leak_report.json`.
`--dry-run` оставлен для диагностики транспорта без оценок. Приёмка —
[`docs/acceptance.md`](docs/acceptance.md), упаковка — [`docs/package.md`](docs/package.md),
устройство среды — [`DESIGN.md`](DESIGN.md).

Запись терминального демо на 135 секунд: `docs/demo/participant4.cast`
(`asciinema play docs/demo/participant4.cast`), метрики того же прогона —
`docs/demo/participant4.json`. Это результаты реального прогона на `sample_00`
с паузами для чтения, а не имитация времени агента. Для новой записи:
`python -m auditgym.runner.demo --record runs/demo/demo.cast --duration 135`.

## Ограничения

- Данные синтетические; проверялись только скриптовые политики, обучение не проводилось.
  Качество на этих эпизодах не доказывает применимость к реальному аудиту.
- Reconciler повторяет правила генератора, поэтому его результат — потолок, а не
  оценка сложности задачи для обучаемого агента.
- Базовый образ закреплён по digest (`python:3.11-slim@sha256:07d48240…`), но
  системные пакеты (`apt-get install make`) ставятся из репозитория Debian на
  момент сборки. Зависимости Python закреплены точно, но без хешей
  (`--require-hashes` не используется).
- `requirements.lock` проверен на наличие колёс для CPython 3.11 Linux x86_64/aarch64;
  на других версиях Python набор может отличаться.
- Проверка утечек ищет известные маркеры и не доказывает отсутствие любых скрытых
  каналов; API не является песочницей для недоверенного кода.
- Траектории Oracle в `artifacts/` содержат правильные ответы (см. `artifacts/README.md`).

## Веб-обозреватель

Открыть через GitHub без локальной установки:
**[Запустить в GitHub Codespaces](https://codespaces.new/Goslinuly/audit-rl-env?quickstart=1)**.
Создайте codespace из `main`; конфигурация установит зависимости и запустит
интерфейс на порту 8000. Если вкладка не открылась, выберите **Ports → 8000 → Open in Browser**.
Нужны доступ к репозиторию и доступные ресурсы Codespaces в аккаунте GitHub.

![Cyberpunk-интерфейс auditgym на реальном эпизоде команды](docs/screenshots/workspace.png)

Скачайте репозиторий через **Code → Download ZIP**, распакуйте и откройте терминал
в его папке. Требуется Python 3.11 или новее (интерфейс только просматривает
эпизоды и прогоны, на оценку среды не влияет):

```bash
python -m pip install -e ".[dev]"
python ui/server.py
```

Откройте **http://localhost:8000**. Cyberpunk-интерфейс содержит страницы
«Обзор», «Компании», «Эпизоды», «Расследование», «Сравнение агентов» и «Отчёты».
Документы и генерация по всем пресетам/seed работают через API команды.
Запуск агента и сравнение используют настоящие AuditEnv, runner и grader.
Oracle помечен как привилегированный эталон. Отчёт скачивается документом Word (.docx: реквизиты проверки, итоговые метрики, таблица расхождений с доказательствами), а также в CSV и JSON.

Названия компаний, состав рабочего каталога и ручные подтверждения сохраняются
в этом браузере. Удаление из каталога не удаляет опубликованные эпизоды команды.
Результаты и траектории прогонов хранятся в памяти до обновления страницы;
скачайте отчёт для сохранения результатов. Ручное подтверждение не меняет оценку grader.

GitHub показывает исходники, но не выполняет Python API: открывать `index.html`
двойным кликом вместо запуска сервера не нужно. `/prototype.html` открывает тот же
подключённый интерфейс. Старый обозреватель доступен по `/explorer.html`; его
«Режим проверяющего» показывает эталон для опубликованных открытых эпизодов.
Архив исходного демонстрационного дизайна — `ui/design/auditgym-prototype.html`.

HTTP-тесты входят в `make check`; отдельный job `web-ui` проверяет все страницы
в браузере. Локальный запуск браузерного набора описан в [docs/web-ui.md](docs/web-ui.md).
Опубликованная версия: https://explorer-production-573177ce.up.railway.app
(деплой вручную: `railway up --service explorer`).

## Структура

| Путь | Что там |
| --- | --- |
| `auditgym/generator/` | скрытая история компании, документы, инъекция ошибок, отвлекающие случаи |
| `auditgym/env/` | `AuditEnv.reset/step`, инструменты, калькулятор |
| `auditgym/grader/` | валидация findings, matcher, метрики, награда |
| `auditgym/policies/` | RandomExplorer, Reconciler, FlagAll, Oracle; абляции Reconciler |
| `auditgym/runner/` | прогон эпизодов, `trajectories.jsonl`, отчёт |
| `schemas/` | JSON Schema всех форматов |
| `configs/`, `episodes/` | train/dev конфиги и эпизоды |
| `judge_adapter.py` | подключение для проверок жюри (`docs/judge.md`) |
| `tests/` | тесты модулей, приёмочный набор и определения жюри (`tests/judge/`) |
| `artifacts/` | закоммиченные траектории, результаты и разбор сбоев |
| `tools/` | `failure_analysis.py`, `summarize_results.py`, проверки UI и wheel |

Все данные вымышлены. Это программная задача, а не аудиторское заключение.

Лицензия: MIT.
