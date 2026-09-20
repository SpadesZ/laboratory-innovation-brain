# Laboratory Innovation Brain — development tasks.
#
# On Windows the same tasks are available as .\scripts\dev.ps1 <task>.

PY := .venv/bin/python
ifeq ($(OS),Windows_NT)
	PY := .venv/Scripts/python.exe
endif

.DEFAULT_GOAL := help
.PHONY: help install hooks spec test test-all coverage-gate commit-hygiene lint typecheck fmt check db-up db-down migrate clean

help:  ## Show available tasks
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

install:  ## Create the venv and install the project with dev extras
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev,postgres]"

hooks:  ## Install the tracked git hooks (commit-msg: no AI authorship attribution)
	git config core.hooksPath .githooks
	@echo "core.hooksPath -> .githooks (fast local feedback; CI commit-hygiene is the gate)"

spec:  ## Spec conformance only (T-SPEC-001 / T-SPEC-002) — blocks every slice
	$(PY) -m pytest tests/spec -q
	$(PY) scripts/check_requirement_coverage.py

test:  ## Default suite: no Postgres, no Lumerical seat, no network (AGT-007)
	$(PY) -m pytest
	$(PY) scripts/check_requirement_coverage.py

test-all:  ## Full suite including backend-dependent tests
	LAB_BRAIN_TEST_POSTGRES=1 $(PY) -m pytest
	$(PY) scripts/check_requirement_coverage.py

coverage-gate:  ## Executed-coverage gate alone (reads the last pytest run's outcomes)
	$(PY) scripts/check_requirement_coverage.py

commit-hygiene:  ## No AI authorship attribution in any enforced commit message
	$(PY) scripts/check_commit_messages.py

lint:  ## Ruff lint
	$(PY) -m ruff check src tests

fmt:  ## Ruff format
	$(PY) -m ruff format src tests

typecheck:  ## mypy strict
	$(PY) -m mypy

check: spec lint typecheck test  ## Everything CI runs

db-up:  ## Start PostgreSQL + pgvector
	docker compose up -d

db-down:  ## Stop PostgreSQL
	docker compose down

migrate:  ## Apply versioned migrations
	$(PY) scripts/migrate.py

clean:  ## Remove caches
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
