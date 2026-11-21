.PHONY: install install-locked lint test check episodes episodes-check grader-selfcheck ui demo \
	docker-build docker-check artifacts failure-analysis lock

PYTHON ?= python
ARTIFACT_EPISODES = $(sort $(wildcard episodes/train/train_*) $(wildcard episodes/dev/dev_*))

install:
	pip install -e ".[dev]"

# Точные версии всех зависимостей (как в Docker-образе)
install-locked:
	pip install -r requirements.lock
	pip install --no-deps -e .

lint:
	$(PYTHON) -m ruff check auditgym tests

test:
	$(PYTHON) -m pytest -q

# Единая команда проверки: lint, тесты + приёмка, sha256 эпизодов, selfcheck грейдера,
# прогон 4 политик. Отчёт: runs/check-*/validation.json
check:
	$(PYTHON) -m auditgym.runner.validate

# Закоммиченные артефакты: 4 политики x (train + dev), режим train.
# trajectories.jsonl детерминирован; time_s в results.csv — нет.
artifacts:
	rm -rf artifacts/.run
	$(PYTHON) -m auditgym.runner --episodes $(ARTIFACT_EPISODES) --out artifacts/.run
	mv artifacts/.run/trajectories.jsonl artifacts/.run/results.csv artifacts/.run/leak_report.json artifacts/
	rmdir artifacts/.run
	$(PYTHON) tools/summarize_results.py artifacts/results.csv > artifacts/summary.md

# Пересобрать requirements.lock из чистого venv (результат проверить на Python 3.11)
lock:
	rm -rf .lock-venv
	$(PYTHON) -m venv .lock-venv
	.lock-venv/bin/pip install -q -e ".[dev]"
	head -4 requirements.lock > requirements.lock.new
	.lock-venv/bin/pip freeze --exclude-editable >> requirements.lock.new
	mv requirements.lock.new requirements.lock
	rm -rf .lock-venv

# Абляции Reconciler через настоящие AuditEnv + Grader (DESIGN.md §7)
failure-analysis:
	$(PYTHON) tools/failure_analysis.py --json artifacts/failure_analysis.json > artifacts/failure_analysis.md

episodes:
	$(PYTHON) -m auditgym.generator build

episodes-check:
	$(PYTHON) -m auditgym.generator build --check

# oracle = 1.0, молчание, flag-all < 0, перестановка и смена ID на каждом эпизоде
grader-selfcheck:
	$(PYTHON) -m auditgym.grader selfcheck episodes

ui:
	$(PYTHON) ui/server.py

demo:
	$(PYTHON) -m auditgym.runner.demo

docker-build:
	docker build -t audit-rl-env .

docker-check: docker-build
	docker run --rm --network none --cpus 2 --memory 4g audit-rl-env make check
