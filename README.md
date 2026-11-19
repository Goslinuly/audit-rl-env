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
