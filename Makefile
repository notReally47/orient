SHELL       := C:/Program Files/Git/bin/bash.exe
.SHELLFLAGS := -ec

DOCKER  ?= podman
MACHINE ?= $(DOCKER) machine
COMPOSE ?= $(DOCKER) compose
PKG     := orient
RUN     := uv run --package $(PKG)

.PHONY: help bootstrap start stop reset rebuild status logs ui migrate probe dump test test-integration lint format typecheck check clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

bootstrap: ## Sync the shared workspace venv with orient's dev and gui extras
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. See https://docs.astral.sh/uv/"; exit 1; }
	uv sync --package $(PKG) --extra dev --extra gui

start: migrate ## Start the container stack and checks if the containers are ready
	@echo "waiting for mcp to be ready..."
	@for i in $$(seq 1 60); do \
		curl -sf http://localhost:9000/mcp >/dev/null 2>&1 && break || sleep 2; \
	done
	@echo "stack started. run 'make probe' next."

stop: ## Stop the stack, keeping the database volume
	$(COMPOSE) down

reset: ## Stop the stack and DESTROY the database volume, forcing a clean bootstrap
	@if [ -t 0 ]; then \
		read -p "This will permanently delete all data in the 'pgdata' volume. Continue? [y/N] " confirm; \
		if [ "$$confirm" != "y" ] && [ "$$confirm" != "Y" ]; then echo "Aborted."; exit 1; fi; \
	fi
	$(COMPOSE) down -v

rebuild: ## Rebuilds the docker image without cache
	@if [ -t 0 ]; then \
		read -p "This should only be called if there's changes to the image. Continue? [y/N] " confirm; \
		if [ "$$confirm" != "y" ] && [ "$$confirm" != "Y" ]; then echo "Aborted."; exit 1; fi; \
	fi
	$(COMPOSE) build --no-cache

status: ## Check health status of docker images
	$(DOCKER) ps -a

logs: ## Follow proxy logs
	$(COMPOSE) logs -f litellm

ui: ## Open the LiteLLM admin UI in your default browser
	powershell.exe -Command "Start-Process 'http://localhost:4000/ui'"

migrate: ## Start the stack if needed, then apply db/migrations/*.sql in order. Safe to re-run.
	$(COMPOSE) up -d db litellm headroom jaeger
	@echo "waiting for litellm to be ready..."
	@for i in $$(seq 1 60); do \
		curl -sf http://localhost:4000/health/liveliness >/dev/null 2>&1 && break || sleep 2; \
	done
	@for f in db/migrations/*.sql; do \
		echo "  applying $$(basename $$f)"; \
		$(COMPOSE) exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -q -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < "$$f" || exit 1; \
	done
	$(COMPOSE) up -d mcp

probe: ## Verify every external dependency. Nothing is built on top until this is green.
	$(RUN) python -m orient.probe

dump: ## Print what each Yahoo surface actually returns. Re-run when a provider starts failing.
	$(RUN) python -m orient.providers.shapes

test: ## Run the offline test suite
	$(RUN) pytest

test-integration: ## Run the store tests against the live Postgres from `make start`
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