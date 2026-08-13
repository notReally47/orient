SHELL       := C:/Program Files/Git/bin/bash.exe
.SHELLFLAGS := -ec

COMPOSE ?= podman compose
PKG     := orient
RUN     := uv run --package $(PKG)

.PHONY: help bootstrap up down reset logs migrate probe shapes test test-integration lint format typecheck check clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

bootstrap: ## Sync the shared workspace venv with orient's dev and gui extras
	uv sync --package $(PKG) --extra dev --extra gui

up: ## Start the container stack
	$(COMPOSE) up -d
	@echo "waiting for the proxy to accept requests..."
	@for i in $$(seq 1 60); do \
		curl -sf http://localhost:4000/health/liveliness >/dev/null 2>&1 && break || sleep 2; \
	done

down: ## Stop the stack, keeping the database volume
	$(COMPOSE) down

reset: ## Stop the stack and DESTROY the database volume, forcing a clean bootstrap
	$(COMPOSE) down -v

logs: ## Follow proxy logs
	$(COMPOSE) logs -f litellm

migrate: ## Start the stack if needed, then apply db/migrations/*.sql in order. Safe to re-run.
	@for f in db/migrations/*.sql; do \
		echo "  applying $$(basename $$f)"; \
		$(COMPOSE) exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -q -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < "$$f" || exit 1; \
	done

probe: ## Verify every external dependency. Nothing is built on top until this is green.
	$(RUN) python -m orient.probe


shapes: ## Print what each Yahoo surface actually returns. Re-run when a provider starts failing.
	$(RUN) python -m orient.providers.shapes

test: ## Run the offline test suite
	$(RUN) pytest

test-integration: ## Run the store tests against the live Postgres from `make up`
	$(RUN) pytest -m integration --no-cov

lint: ## Read-only lint and format check, identical to CI
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format: ## Apply formatting and safe fixes
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

typecheck: ## Static type check
	$(RUN) basedpyright

check: lint typecheck test ## Everything CI runs

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +