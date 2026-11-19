# audit-rl-env (`auditgym`)

Воспроизводимая RL-среда для ИИ-аудитора: синтетические документы компании, инструменты расследования,
скрытые финансовые ошибки и функция награды. FinTech-трек хакатона, 19–22 ноября 2026.

> Статус: скелет. ТЗ команды — [`docs/TZ.md`](docs/TZ.md).

## Быстрый старт

```bash
make install
make check          # единая команда проверки
make docker-check   # то же в контейнере: --network none --cpus 2 --memory 4g
```

## Веб-обозреватель

**https://explorer-production-573177ce.up.railway.app** — эпизоды train/dev/sample и генерация новой компании по пресету и seed.
Переключатель «Режим проверяющего» (или `?review=1`) показывает закрытый эталон: ошибки, доказательства, проводки до/после.
Локально: `python ui/server.py` → http://localhost:8000. Деплой: Railway, `ui/Dockerfile` (переменная сервиса `RAILWAY_DOCKERFILE_PATH=ui/Dockerfile`).
UI не входит в официальную проверку и не нужен для `make check`.

## Структура

| Путь | Что там |
| --- | --- |
| `auditgym/generator/` | скрытая история компании, документы, инъекция ошибок, отвлекающие случаи |
| `auditgym/env/` | `AuditEnv.reset/step`, инструменты, калькулятор |
| `auditgym/grader/` | валидация findings, matcher, метрики, награда |
| `auditgym/policies/` | RandomExplorer, Reconciler, FlagAll, Oracle |
| `auditgym/runner/` | прогон эпизодов, `trajectories.jsonl`, отчёт |
| `schemas/` | JSON Schema всех форматов |
| `configs/`, `episodes/` | train/dev конфиги и эпизоды |
| `tests/` | тесты модулей и приёмочный набор |

Все данные вымышлены. Это программная задача, а не аудиторское заключение.

Лицензия: MIT.
