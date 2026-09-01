SHELL       := C:/Program Files/Git/bin/bash.exe
.SHELLFLAGS := -ec

DOCKER  ?= podman
MACHINE ?= $(DOCKER) machine
COMPOSE ?= $(DOCKER) compose
PKG     := orient
RUN     := uv run --package $(PKG)

.PHONY: help bootstrap image start reload-proxy stop reset rebuild status logs ui gui jaeger migrate probe dump test test-integration test-run lint format typecheck check clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

bootstrap: ## Sync the shared workspace venv with orient's dev and gui extras
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. See https://docs.astral.sh/uv/"; exit 1; }
	uv sync --package $(PKG) --extra dev --extra gui

image: ## Build the app image from the working tree. Cached, so a no-op when src/ is unchanged.
	$(COMPOSE) build

start: image migrate reload-proxy ## Build, start the container stack and check the containers are ready
	@echo "stack started. run 'make probe' next."

# The proxy reads its config from a bind mount, so editing the yaml changes nothing compose can
# see: same image, same service definition, so the container keeps the config it parsed at boot.
reload-proxy: ## Recreate the proxy so a changed proxy/*.yaml is actually picked up
	$(COMPOSE) up -d --force-recreate litellm

stop: ## Stop the stack, keeping the database volume
	$(COMPOSE) down

reset: ## Stop the stack and DESTROY the database volume, forcing a clean bootstrap
	@if [ -t 0 ]; then \
		read -p "This will permanently delete all data in the 'pgdata' volume. Continue? [y/N] " confirm; \
		if [ "$$confirm" != "y" ] && [ "$$confirm" != "Y" ]; then echo "Aborted."; exit 1; fi; \
	fi
	$(COMPOSE) down -v

rebuild: ## Rebuild the image from scratch. Only for when a cached layer is itself wrong.
	@if [ -t 0 ]; then \
		read -p "This discards the layer cache and takes minutes. Continue? [y/N] " confirm; \
		if [ "$$confirm" != "y" ] && [ "$$confirm" != "Y" ]; then echo "Aborted."; exit 1; fi; \
	fi
	$(COMPOSE) build --no-cache

status: ## Check health status of docker images
	$(DOCKER) ps -a

logs: ## Follow proxy logs
	$(COMPOSE) logs -f litellm

ui: ## Open the LiteLLM admin UI in your default browser
	powershell.exe -Command "Start-Process 'http://localhost:4000/ui'"

gui: ## Open the app in your default browser
	powershell.exe -Command "Start-Process 'http://localhost:8501'"

jaeger: ## Open the Jaeger trace UI in your default browser
	powershell.exe -Command "Start-Process 'http://localhost:16686'"

migrate: ## Start the stack if needed, then apply db/migrations/*.sql in order. Safe to re-run.
	$(COMPOSE) up -d db headroom jaeger
	@echo "waiting for db to accept connections..."
	@for i in $$(seq 1 60); do \
		$(COMPOSE) exec -T db pg_isready -U "$${POSTGRES_USER:-market}" >/dev/null 2>&1 && break || sleep 2; \
	done
	@for f in db/migrations/*.sql; do \
		echo "  applying $$(basename $$f)"; \
		$(COMPOSE) exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -q -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < "$$f" || exit 1; \
	done
	$(COMPOSE) up -d mcp
	@echo "waiting for mcp to be ready..."
	@for i in $$(seq 1 60); do \
		curl -sf http://localhost:9000/mcp >/dev/null 2>&1 && break || sleep 2; \
	done
	$(COMPOSE) up -d litellm orchestrator gui
	@echo "waiting for litellm to be ready..."
	@for i in $$(seq 1 60); do \
		curl -sf http://localhost:4000/health/liveliness >/dev/null 2>&1 && break || sleep 2; \
	done

probe: ## Verify every external dependency. Nothing is built on top until this is green.
	$(RUN) python -m orient.probe

dump: ## Print what each Yahoo surface actually returns. Re-run when a provider starts failing.
	$(RUN) python -m orient.providers.shapes

test: ## Run the offline test suite
	$(RUN) pytest

test-integration: ## Run the store tests against the live Postgres from `make start`
	$(RUN) pytest -m integration --no-cov

test-run: ## Post one run to a running orchestrator, bypassing the GUI
	curl.exe -N -X POST http://localhost:8000/runs -H 'content-type: application/json' -d '{"symbol":"^GSPC","session_date":"2026-08-13","level":"beginner"}'

lint: ## Read-only lint and format check, identical to CI
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format: ## Apply formatting and safe fixes
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

typecheck: ## Static type check
	$(RUN) basedpyright

check: lint typecheck test ## Everything CI runs

clean: ## Remove local caches and coverage output. Leaves the stack and the database alone.
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
	find . -name __pycache__ -type d -prune -exec rm -rf {} +