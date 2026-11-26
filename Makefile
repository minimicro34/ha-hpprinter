PYTHON ?= python
NODE ?= node
COMPONENT := custom_components/hpprinter

.PHONY: install-dev lint format-check syntax json test coverage test-js check

install-dev:
	$(PYTHON) -m pip install -r requirements.txt

lint:
	$(PYTHON) -m ruff check $(COMPONENT)

format-check:
	$(PYTHON) -m ruff format --check $(COMPONENT)

syntax:
	$(PYTHON) -m compileall -q $(COMPONENT)
	$(NODE) --check $(COMPONENT)/www/hpprinter-card.js

json:
	$(PYTHON) -c 'import json; from pathlib import Path; [json.loads(p.read_text(encoding="utf-8")) for p in Path("$(COMPONENT)").rglob("*.json")]'

test:
	$(PYTHON) -m pytest tests -q

coverage:
	$(PYTHON) -m pytest tests -q --cov=$(subst /,.,$(COMPONENT)) --cov-report=term-missing --cov-report=xml:coverage.xml --cov-fail-under=80

test-js:
	$(NODE) --test tests/test_lovelace_card.mjs

check: lint format-check syntax json coverage test-js
