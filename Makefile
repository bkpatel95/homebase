# homebase — common dev commands.
#
# Run `make help` (or just `make`) for the menu. The dev stack stands up
# three containers via docker-compose.dev.yml:
#   - backend  (uvicorn --reload on :8000)
#   - frontend (vite dev server on :3000)
#   - postgres (reserved for future chat-history persistence work)
#
# Container runtime is auto-detected: `docker compose` if available, else
# `podman-compose`. Override with `make dev COMPOSE_BIN="..."` if you need
# a specific one.

# Auto-detect the compose CLI. `docker compose` (v2 plugin) wins when
# present; otherwise fall back to `podman-compose`. The detection runs
# once per make invocation via `:=`.
COMPOSE_BIN ?= $(shell \
	if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then \
		echo "docker compose"; \
	elif command -v podman-compose >/dev/null 2>&1; then \
		echo "podman-compose"; \
	else \
		echo "MISSING"; \
	fi)

COMPOSE := $(COMPOSE_BIN) -f docker-compose.dev.yml

.PHONY: help setup check-runtime dev dev-build dev-up dev-down dev-logs dev-restart dev-shell dev-seed dev-clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  compose runtime: $(COMPOSE_BIN)"

check-runtime: ## Verify a compose CLI is available
	@if [ "$(COMPOSE_BIN)" = "MISSING" ]; then \
		echo "ERROR: neither 'docker compose' nor 'podman-compose' is on PATH."; \
		echo "Install one of:"; \
		echo "  - Docker Desktop:        https://www.docker.com/products/docker-desktop/"; \
		echo "  - Podman + podman-compose: brew install podman podman-compose && podman machine init && podman machine start"; \
		exit 1; \
	fi

setup: ## Create .env from .env.example if missing (no secrets required for dev)
	@if [ -f .env ]; then \
		echo ".env already exists — leaving it alone."; \
	else \
		cp .env.example .env; \
		echo ".env created from .env.example."; \
		echo ""; \
		echo "Dev mode is permissive: missing API keys will not crash the app."; \
		echo "  - Chat: paste an ANTHROPIC_API_KEY into .env to enable POST /api/chat."; \
		echo "  - Gmail, Oura, Plex, Overseerr: render 'not configured' until keys are added."; \
		echo "  - Weather: works out of the box (Open-Meteo, no key needed)."; \
		echo ""; \
		echo "Next: make dev"; \
	fi

dev: check-runtime setup dev-up ## One-shot: ensure runtime + .env, then start the dev stack

dev-up: check-runtime ## Build (if needed) and start the dev stack in the foreground
	$(COMPOSE) up --build

dev-build: check-runtime ## Rebuild dev images without starting
	$(COMPOSE) build

dev-down: check-runtime ## Stop the dev stack and remove containers
	$(COMPOSE) down

dev-logs: check-runtime ## Tail logs from all dev containers
	$(COMPOSE) logs -f

dev-restart: check-runtime ## Restart just the backend (frontend hot-reloads on its own)
	$(COMPOSE) restart backend

dev-shell: check-runtime ## Open a shell inside the backend container
	$(COMPOSE) exec backend bash

dev-seed: ## Rewrite mock calendar/today.json with today's date
	./dev/seed-mock-data.sh

dev-clean: check-runtime ## Stop the stack AND wipe the postgres + node_modules volumes
	$(COMPOSE) down -v

.DEFAULT_GOAL := help
