.PHONY: test test-unit test-integration test-e2e test-cov lint format format-check lock-check audit pre-commit security doctor check frontend-install frontend-dev frontend-build frontend-typecheck frontend-lint frontend-test frontend-audit frontend-check

TEST_APP_ENV ?= test
PYTEST = APP_ENV=$(TEST_APP_ENV) poetry run pytest
FRONTEND_DIR ?= frontend
FRONTEND_PACKAGE = $(FRONTEND_DIR)/package.json
FRONTEND_NPM = npm --prefix $(FRONTEND_DIR)

test:
	$(PYTEST) tests/ -v

test-unit:
	$(PYTEST) tests/ -v -m unit

test-integration:
	$(PYTEST) tests/ -v -m integration

test-e2e:
	$(PYTEST) tests/ -v -m e2e

test-cov:
	$(PYTEST) tests/ -v --cov --cov-report=term-missing --cov-report=html --cov-fail-under=85

lint:
	poetry run ruff check .

format:
	poetry run ruff format .

format-check:
	poetry run ruff format --check .

lock-check:
	poetry check --lock

audit:
	poetry run pip-audit --progress-spinner off

pre-commit:
	poetry run pre-commit run --all-files --show-diff-on-failure

frontend-install:
	@if [ -f "$(FRONTEND_PACKAGE)" ]; then $(FRONTEND_NPM) ci; else echo "No frontend package found; skipping"; fi

frontend-dev:
	@if [ -f "$(FRONTEND_PACKAGE)" ]; then $(FRONTEND_NPM) run dev; else echo "No frontend package found; skipping"; fi

frontend-build:
	@if [ -f "$(FRONTEND_PACKAGE)" ]; then $(FRONTEND_NPM) run build; else echo "No frontend package found; skipping"; fi

frontend-typecheck:
	@if [ -f "$(FRONTEND_PACKAGE)" ]; then $(FRONTEND_NPM) run typecheck; else echo "No frontend package found; skipping"; fi

frontend-lint:
	@if [ -f "$(FRONTEND_PACKAGE)" ]; then $(FRONTEND_NPM) run lint; else echo "No frontend package found; skipping"; fi

frontend-test:
	@if [ -f "$(FRONTEND_PACKAGE)" ]; then $(FRONTEND_NPM) run test; else echo "No frontend package found; skipping"; fi

frontend-audit:
	@if [ -f "$(FRONTEND_PACKAGE)" ]; then $(FRONTEND_NPM) run audit; else echo "No frontend package found; skipping"; fi

frontend-check:
	@if [ -f "$(FRONTEND_PACKAGE)" ]; then $(FRONTEND_NPM) run check; else echo "No frontend package found; skipping"; fi

security: lock-check audit frontend-audit pre-commit

doctor:
	poetry run python -m scripts.doctor

check: lock-check lint format-check test frontend-check
