.PHONY: install uninstall test lint

VENV := .venv
PYTHON := $(VENV)/bin/python
PYTEST := $(VENV)/bin/pytest

install:
	@bash install.sh

uninstall:
	@bash uninstall.sh

# Create venv + dev deps without placing the shim (useful for CI / local dev)
dev:
	@if [ ! -d "$(VENV)" ]; then python3 -m venv $(VENV); fi
	@$(VENV)/bin/pip install --quiet --upgrade pip
	@$(VENV)/bin/pip install --quiet -e ".[dev]"
	@echo "Dev environment ready. Activate with: source $(VENV)/bin/activate"

test:
	@if [ ! -f "$(PYTEST)" ]; then $(MAKE) dev; fi
	$(PYTEST)

lint:
	@if [ ! -f "$(VENV)/bin/ruff" ]; then $(VENV)/bin/pip install --quiet ruff; fi
	$(VENV)/bin/ruff check src/ tests/
