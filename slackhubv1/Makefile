.PHONY: install run test lint clean

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
SLACKHUB := $(VENV)/bin/slack-hub

install: $(VENV)
	@echo "✅ Installed. Run 'slack-hub init' to configure your credentials."

$(VENV): pyproject.toml
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	$(SLACKHUB) db init
	@if [ ! -f config/config.yaml ]; then \
		cp config/config.example.yaml config/config.yaml; \
		echo "📄 Created config/config.yaml from template."; \
	fi
	@touch $(VENV)

run:
	$(SLACKHUB) digest

watch:
	$(SLACKHUB) watch

test:
	$(PYTHON) -m pytest tests/ -v

lint:
	$(PYTHON) -m ruff check src/ tests/

clean:
	rm -rf $(VENV) *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	@echo "🧹 Cleaned."
