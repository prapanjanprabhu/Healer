\
COMPOSE_FILE := deploy/docker-compose.yml
ENV_FILE := .env

.PHONY: help setup setup-dashboard setup-control-plane setup-worker setup-gateway-manager setup-agent \
	format format-dashboard format-python format-agent \
	lint lint-dashboard lint-python lint-agent \
	test test-control-plane test-worker test-agent test-all \
	up down restart logs ps build build-agent agent-version migrate

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

## --- agent --------------------------------------------------------------------

build-agent:
	cd agent && go build -o bin/healer-agent ./cmd/healer-agent

agent-version: build-agent
	./agent/bin/healer-agent -version
