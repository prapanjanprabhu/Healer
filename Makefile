\
# The root docker-compose.yml (which just includes deploy/docker-compose.yml)
# is used here — and should be used for any manual `docker compose ...` too —
# so Compose's .env auto-discovery finds the real .env at the repo root
# instead of silently defaulting every ${VAR:-fallback} in the compose file.
COMPOSE_FILE := docker-compose.yml
ENV_FILE := .env

.PHONY: help setup setup-dashboard setup-control-plane setup-worker setup-gateway-manager setup-agent \
	format format-dashboard format-python format-agent \
	lint lint-dashboard lint-python lint-agent \
	test test-control-plane test-worker test-agent test-all \
	up down restart logs ps build build-agent agent-version migrate \
	backup restore release-agent

help:
	@echo "Healer V1 — common tasks"
	@echo "  make setup            Install dependencies for every service"
	@echo "  make format           Format all code (dashboard, python services, agent)"
	@echo "  make lint             Lint all code"
	@echo "  make test             Run all test suites"
	@echo "  make up               Start the local dev stack (docker compose)"
	@echo "  make down             Stop the local dev stack"
	@echo "  make logs             Tail logs for the dev stack"
	@echo "  make build-agent      Compile the Go agent binary"
	@echo "  make agent-version    Print the compiled agent's version"
	@echo "  make migrate          Run control-plane database migrations"
	@echo "  make bootstrap-admin  Create the first Administrator account"

## --- setup ---------------------------------------------------------------

setup: setup-dashboard setup-control-plane setup-worker setup-gateway-manager setup-agent

setup-dashboard:
	cd apps/dashboard && npm install

setup-control-plane:
	cd services/control-plane && pip install -r requirements.txt -r requirements-dev.txt

setup-worker:
	cd services/worker && pip install -r requirements.txt -r requirements-dev.txt

setup-gateway-manager:
	cd services/gateway-manager && pip install -r requirements.txt -r requirements-dev.txt

setup-agent:
	cd agent && go mod download

## --- format ---------------------------------------------------------------

format: format-dashboard format-python format-agent

format-dashboard:
	cd apps/dashboard && npm run format

format-python:
	cd services/control-plane && black . && ruff check --fix .
	cd services/worker && black . && ruff check --fix .
	cd services/gateway-manager && black . && ruff check --fix .

format-agent:
	cd agent && gofmt -l -w .

## --- lint -------------------------------------------------------------------

lint: lint-dashboard lint-python lint-agent

lint-dashboard:
	cd apps/dashboard && npm run lint

lint-python:
	cd services/control-plane && ruff check . && black --check .
	cd services/worker && ruff check . && black --check .
	cd services/gateway-manager && ruff check . && black --check .

lint-agent:
	cd agent && go vet ./...

## --- test -------------------------------------------------------------------

test: test-all

test-all: test-control-plane test-worker test-agent

test-control-plane:
	cd services/control-plane && pytest -q

test-worker:
	cd services/worker && pytest -q

test-agent:
	cd agent && go test ./...

## --- local stack ------------------------------------------------------------

up:
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) up -d --build

down:
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) down

restart: down up

logs:
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) logs -f

ps:
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) ps

build:
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) build

migrate:
	cd services/control-plane && alembic upgrade head

bootstrap-admin:
	cd services/control-plane && python -m app.cli.bootstrap_admin

## --- agent --------------------------------------------------------------------

build-agent:
	cd agent && go build -o bin/healer-agent ./cmd/healer-agent

agent-version: build-agent
	./agent/bin/healer-agent -version

# Cross-compiles the Agent for both V1 target platforms, injecting the real
# release version from ./VERSION (see internal/version/version.go), and
# writes a SHA-256 checksum file alongside each binary — the "signed/
# checksummed" release artifact docs/release.md describes. Real code
# signing (Authenticode/GPG) needs a certificate/key this repo doesn't
# have; the checksum is what an operator verifies a download against.
release-agent:
	@mkdir -p agent/dist
	$(eval VERSION := $(shell cat VERSION))
	cd agent && GOOS=windows GOARCH=amd64 go build -ldflags "-X github.com/healer-platform/agent/internal/version.Version=$(VERSION)" -o dist/healer-agent-windows-amd64.exe ./cmd/healer-agent
	cd agent && GOOS=linux GOARCH=amd64 go build -ldflags "-X github.com/healer-platform/agent/internal/version.Version=$(VERSION)" -o dist/healer-agent-linux-amd64 ./cmd/healer-agent
	cd agent/dist && shasum -a 256 healer-agent-windows-amd64.exe > healer-agent-windows-amd64.exe.sha256 2>/dev/null || sha256sum healer-agent-windows-amd64.exe > healer-agent-windows-amd64.exe.sha256
	cd agent/dist && shasum -a 256 healer-agent-linux-amd64 > healer-agent-linux-amd64.sha256 2>/dev/null || sha256sum healer-agent-linux-amd64 > healer-agent-linux-amd64.sha256
	@echo "release $(VERSION) built in agent/dist/"

## --- database backup/restore (docs/backup-and-restore.md) -------------------

backup:
	@mkdir -p backups
	$(eval STAMP := $(shell date +%Y%m%d%H%M%S))
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) exec -T postgres \
		pg_dump -U $${POSTGRES_USER:-healer} -d $${POSTGRES_DB:-healer} -F c \
		-f /tmp/healer_backup_$(STAMP).dump
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) cp \
		postgres:/tmp/healer_backup_$(STAMP).dump backups/healer_backup_$(STAMP).dump
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) exec -T postgres \
		rm -f /tmp/healer_backup_$(STAMP).dump
	@echo "backup written to backups/healer_backup_$(STAMP).dump"

# Restores FILE into a NEW database named healer_restore_<timestamp> —
# never over the live `healer` database — so a restore rehearsal can be run
# safely at any time without risking the running system. Promoting a
# restored copy to be the live database is a deliberate, separate,
# documented step (docs/backup-and-restore.md), not something this target
# does for you.
restore:
	@test -n "$(FILE)" || (echo "usage: make restore FILE=backups/healer_backup_<timestamp>.dump" && exit 1)
	$(eval STAMP := $(shell date +%Y%m%d%H%M%S))
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) cp \
		$(FILE) postgres:/tmp/healer_restore_$(STAMP).dump
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) exec -T postgres \
		createdb -U $${POSTGRES_USER:-healer} healer_restore_$(STAMP)
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) exec -T postgres \
		pg_restore -U $${POSTGRES_USER:-healer} -d healer_restore_$(STAMP) /tmp/healer_restore_$(STAMP).dump
	docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) exec -T postgres \
		rm -f /tmp/healer_restore_$(STAMP).dump
	@echo "restored into database healer_restore_$(STAMP) — inspect it, then drop it when done:"
	@echo "  docker compose exec postgres dropdb -U healer healer_restore_$(STAMP)"
