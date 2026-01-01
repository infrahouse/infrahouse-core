# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

InfraHouse Core is a lightweight Python library providing AWS and general-purpose utility classes. It's published on PyPI as `infrahouse-core`.

## Development Commands

```bash
# Create virtual environment and bootstrap
make venv
source .venv/bin/activate
make bootstrap         # Installs dev dependencies, sets up pre-commit hooks

# Run tests with coverage
make test              # Runs pytest with coverage report

# Run a single test
pytest -xvvs tests/path/to/test_file.py::test_function_name

# Linting and formatting
make lint              # All linting checks (yaml, black, isort, mdformat, pylint)
make black             # Reformat code
make isort             # Reformat imports

# Build documentation
make docs
```

## Code Style

- Line length: 120 characters (configured in pyproject.toml for black)
- Import sorting: isort with black profile
- Pre-commit hook runs `make lint` before commits

## Architecture

The library is organized into two main areas under `src/infrahouse_core/`:

### AWS Module (`aws/`)
- `__init__.py` - AWS session management, SSO login, role assumption, credential handling
- `asg.py` / `asg_instance.py` - AutoScaling Group and instance lifecycle management
- `ec2_instance.py` - EC2 instance wrapper with SSM command execution support
- `dynamodb.py` - DynamoDB table wrapper with distributed lock support
- `route53/zone.py` - Route53 zone and DNS record management
- `config.py` - AWS config file parsing

### General Utilities
- `github.py` - GitHub Actions self-hosted runner management via GitHub API, integrates with AWS Secrets Manager for token storage
- `logging.py` - Logging setup with stdout/stderr splitting by log level
- `timeout.py` - Timeout context manager
- `fs.py` - Filesystem utilities

### Key Patterns
- Classes accept optional `role_arn` parameter to assume IAM roles for cross-account access
- AWS clients are lazily created using `get_client()` helper with optional role assumption
- Properties use `cached_property_with_ttl` for time-limited caching of API responses
- Tests use `unittest.mock` to patch AWS API calls