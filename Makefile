# homebase — common dev commands.
#
# Run `make help` (or just `make`) for the menu. The dev stack stands up
# three containers via docker-compose.dev.yml:
#   - backend  (uvicorn --reload on :8000)
#   - frontend (vite dev server on :3000)
#   - postgres (reserved for future chat-history persistence work)

COMPOSE := docker compose -f docker-compose.dev.yml

.PHONY: help dev dev-build dev-up dev-down dev-logs dev-restart dev-shell dev-seed dev-clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

dev: dev-up ## Alias for `dev-up`

dev-up: ## Build (if needed) and start the dev stack in the foreground
	$(COMPOSE) up --build

dev-build: ## Rebuild dev images without starting
	$(COMPOSE) build

dev-down: ## Stop the dev stack and remove containers
	$(COMPOSE) down

dev-logs: ## Tail logs from all dev containers
	$(COMPOSE) logs -f

dev-restart: ## Restart just the backend (frontend hot-reloads on its own)
	$(COMPOSE) restart backend

dev-shell: ## Open a shell inside the backend container
	$(COMPOSE) exec backend bash

dev-seed: ## Rewrite mock calendar/today.json with today's date
	./dev/seed-mock-data.sh

dev-clean: ## Stop the stack AND wipe the postgres + node_modules volumes
	$(COMPOSE) down -v

.DEFAULT_GOAL := help
