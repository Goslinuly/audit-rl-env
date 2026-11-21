# Участник 4: интеграция с командной средой и оценщиком

База: main с реализациями участников 1–3 (PR #1 и #2). Генератор, env, grader и
корневые схемы сохранены; параллельных реализаций этих компонентов нет.

Добавлены Oracle, FlagAll, RandomExplorer(seed) и Reconciler; runner и терминальное
демо; сканер утечек; 320 приёмочных проверок; установка wheel вне исходников;
переносимая команда полной проверки и контейнерный CI-job. Контракты владельцев
описаны в docs/env.md и docs/grader.md.

Native API: эпизод передаётся в `env.reset(episode_dir=...)`, записи читаются из
`observation.result.items[*].record`, одиночная запись — из `result.record`.
Итоговые метрики runner читает из нового элемента `env.grade_log`; приватная
диагностика остаётся вне агентских журналов. Оценка повторно не вычисляется.

```sh
python -m auditgym.runner.validate --out runs/check --deadline 600
python -m auditgym.runner --episodes episodes/sample/sample_00 --out runs/sample
python -m auditgym.runner --mode eval --episodes episodes/sample/sample_00 --out runs/eval
python -m auditgym.runner.demo
```

`make check` вызывает тот же полный прогон. `make grader-selfcheck` сохранён.
Текущие версии компонентов задаются константами `auditgym.ENV_VERSION`,
`auditgym.generator.GENERATOR_VERSION`, `auditgym.generator.CONFIG_VERSION` и
`auditgym.grader.GRADER_VERSION` (на момент релиза 1.0.0: env/generator 0.1.0, grader 1.0.0,
config 1.0). Их значения отражаются в `results.csv`; версии владельцев компонентов не
подменяются.

Документация приёмки: docs/acceptance.md; упаковки: docs/package.md;
готовности к релизу: docs/release.md. Веб-интерфейс подключён к настоящему API
команды и служит просмотрщиком; на оценку среды не влияет.
