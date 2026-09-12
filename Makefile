# Laboratory Innovation Brain — development tasks.
#
# On Windows the same tasks are available as .\scripts\dev.ps1 <task>.

PY := .venv/bin/python
ifeq ($(OS),Windows_NT)
	PY := .venv/Scripts/python.exe
endif

.DEFAULT_GOAL := help
.PHONY: help install spec test test-all lint typecheck fmt check db-up db-down migrate clean

help:  ## Show available tasks
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

install:  ## Create the venv and install the project with dev extras
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev,postgres]"

spec:  ## Spec conformance only (T-SPEC-001 / T-SPEC-002) — blocks every slice
	$(PY) -m pytest tests/spec -q

test:  ## Default suite: no Postgres, no Lumerical seat, no network (AGT-007)
	$(PY) -m pytest

test-all:  ## Full suite including backend-dependent tests
	LAB_BRAIN_TEST_POSTGRES=1 $(PY) -m pytest

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
