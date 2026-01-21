.DEFAULT_GOAL := help

define BROWSER_PYSCRIPT
import os, webbrowser, sys

from urllib.request import pathname2url

webbrowser.open("docs/_build/html/index.html")
endef
export BROWSER_PYSCRIPT

define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("%-20s %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT

BROWSER := python -c "$$BROWSER_PYSCRIPT"
OS_VERSION ?= jammy

PWD := $(shell pwd)
ARCH := $(shell uname -m)

help:
	@python -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)


.PHONY: pip
pip:
	pip install -U "pip ~= 25.0"

.PHONY: hooks
hooks:
	mkdir -p .git/hooks
	test -f .git/hooks/pre-commit || cp hooks/pre-commit .git/hooks/pre-commit
	chmod 755 .git/hooks/pre-commit

.PHONY: bootstrap
bootstrap: hooks pip  ## bootstrap the development environment
	pip install -e .[dev,doc]


.PHONY: clean
clean: clean-build clean-pyc clean-test ## remove all build, test, coverage and Python artifacts

.PHONY: clean-build
clean-build:
	rm -fr build/
	rm -fr dist/
	rm -fr .eggs/
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -f {} +

.PHONY: clean-pyc
clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

.PHONY: clean-test
clean-test:
	rm -fr .tox/
	rm -f .coverage
	rm -fr htmlcov/
	rm -fr .pytest_cache

.PHONY: black
black: ## reformat code with black
	black src tests

.PHONY: isort
isort: ## reformat imports
	isort src tests

.PHONY: mdformat
mdformat: ## format markdown files
	mdformat .github

.PHONY: lint
lint: lint/yaml lint/black lint/isort lint/mdformat lint/pylint ## check style

.PHONY: lint/yaml
lint/yaml: ## check style with yamllint
	yamllint .github .readthedocs.yaml

.PHONY: lint/black
lint/black: ## check style with black
	black --check --diff src

.PHONY: lint/isort
lint/isort: ## check imports formatting
	isort --check-only src tests

.PHONY: lint/mdformat
lint/mdformat:
	mdformat --check .github

.PHONY: lint/pylint
lint/pylint: ## check style with pylint
	pylint src


.PHONY: test
test: ## run tests quickly with the default Python
	pytest --cov \
		--cov-report=term-missing --cov-report=xml  \
		-xvvs tests

.PHONY: docs
docs: ## generate Sphinx HTML documentation, including API docs
	sphinx-apidoc -o docs/ src/infrahouse_core
	$(MAKE) -C docs clean
	$(MAKE) -C docs html
	open docs/_build/html/index.html

.PHONY: release-patch
release-patch: ## Release a patch version (0.19.0 -> 0.19.1)
	bump2version patch
	git push origin main --tags

.PHONY: release-minor
release-minor: ## Release a minor version (0.19.0 -> 0.20.0)
	bump2version minor
	git push origin main --tags

.PHONY: release-major
release-major: ## Release a major version (0.19.0 -> 1.0.0)
	bump2version major
	git push origin main --tags

.PHONY: package
package:
	docker run \
	-v ${PWD}:/infrahouse-toolkit \
	--name infrahouse-toolkit-builder \
	--rm \
	"twindb/omnibus-ubuntu:${OS_VERSION}-${ARCH}" \
	bash -l /infrahouse-toolkit/omnibus-infrahouse-toolkit/omnibus_build.sh

.PHONY: dist
dist: clean ## builds source and wheel package
	python setup.py sdist
	python setup.py bdist_wheel
	ls -l dist

.PHONY: docker
docker:  ## Run a docker container with Ubuntu for local development.
	docker run -it --rm \
	-v $(PWD):/infrahouse-toolkit \
	-w /infrahouse-toolkit \
	python:3.11 bash -l

.PHONY: venv
venv: ## Create local python virtual environment
	python3 -m venv .venv
	@echo "To activate run"
	@echo ""
	@echo ". .venv/bin/activate"
