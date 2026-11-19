.PHONY: install lint test check demo docker-build docker-check

install:
	pip install -e ".[dev]"

lint:
	ruff check auditgym tests

test:
	pytest -q

# Единая команда проверки (будет расширена: генерация эпизодов + sha256, прогон 4 политик, приёмка)
check: lint test

demo:
	python -m auditgym.runner.demo

docker-build:
	docker build -t audit-rl-env .

docker-check: docker-build
	docker run --rm --network none --cpus 2 --memory 4g audit-rl-env make check
