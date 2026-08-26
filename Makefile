VENV ?= .venv
PYTHON ?= $(VENV)/bin/python

.PHONY: setup test test-api test-web lint dev-api dev-web migrate

## 一次性初始化：Python venv + 前端依赖
setup:
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install -U pip
	$(PYTHON) -m pip install -e ".[dev]"
	cd apps/web && npm install

## 全量测试（验收命令）
test: test-api test-web

test-api:
	$(PYTHON) -m pytest

test-web:
	cd apps/web && npm test

lint:
	$(PYTHON) -m ruff check .
	cd apps/web && npx tsc --noEmit

## 数据库迁移到最新（真实运行用；测试不依赖它）
migrate:
	$(PYTHON) -m alembic upgrade head

dev-api:
	$(PYTHON) -m uvicorn meeting_api.main:app --reload --port 8000

dev-web:
	cd apps/web && npm run dev
