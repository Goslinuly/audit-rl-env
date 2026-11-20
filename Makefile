.PHONY: install lint test check episodes episodes-check grader-selfcheck ui demo docker-build docker-check

install:
	pip install -e ".[dev]"

lint:
	ruff check auditgym tests

test:
	pytest -q

# Единая команда проверки (будет расширена: генерация эпизодов + sha256, прогон 4 политик, приёмка)
check:
	python -m auditgym.runner.validate

episodes:
	python -m auditgym.generator build

episodes-check:
	python -m auditgym.generator build --check

# oracle = 1.0, молчание, flag-all < 0, перестановка и смена ID на каждом эпизоде
grader-selfcheck:
	python -m auditgym.grader selfcheck episodes

ui:
	python ui/server.py

demo:
	python -m auditgym.runner.demo

docker-build:
	docker build -t audit-rl-env .

docker-check: docker-build
	docker run --rm --network none --cpus 2 --memory 4g audit-rl-env make check
